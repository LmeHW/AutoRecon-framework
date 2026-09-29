from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from service.config import ALLOWED_SUFFIXES, GatewayConfig, PIPELINE_SCRIPT
from service.storage import Store, iso


def safe_join(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escapes isolation root")
    return candidate


def sanitize_filename(name: str) -> str:
    base = Path(name).name
    if not name or base != name or base in {".", ".."}:
        raise ValueError("invalid filename")
    lowered = base.lower()
    if not any(lowered.endswith(suffix) for suffix in ALLOWED_SUFFIXES):
        raise ValueError("file type not allowed")
    if any(part.startswith(".") for part in Path(base).parts):
        raise ValueError("invalid filename")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(ch not in allowed for ch in base):
        raise ValueError("filename contains unsupported characters")
    return base


def incoming_path(upload_dir: Path, filename: str) -> Path:
    return upload_dir / sanitize_filename(filename)


def extract_subject(upload_rows: list[dict[str, Any]], job_dir: Path, store: Store) -> Path:
    subject = job_dir / "subject"
    if subject.exists():
        shutil.rmtree(subject)
    subject.mkdir(parents=True, exist_ok=True)
    for row in upload_rows:
        if row["status"] != "complete":
            raise ValueError(f"upload {row['upload_id']} is not complete")
        if row["username"] != upload_rows[0]["username"]:
            raise ValueError("upload isolation violation")
        source_dir = store.upload_dir(row["username"], row["upload_id"])
        source = incoming_path(source_dir, row["filename"])
        if not source.is_file():
            raise ValueError("uploaded file missing")
        if source.name.lower().endswith(".zip"):
            _extract_zip(source, subject)
        else:
            target = subject / source.name
            shutil.copy2(source, target)
    report = inspect_subject_stacks(subject)
    if report["errors"]:
        raise ValueError("；".join(report["errors"]))
    return subject


def inspect_subject_stacks(subject: Path) -> dict[str, Any]:
    nifti = sorted(
        path
        for path in subject.iterdir()
        if path.is_file()
        and "crop" not in path.name.lower()
        and (path.name.lower().endswith(".nii.gz") or path.name.lower().endswith(".nii"))
    )
    errors: list[str] = []
    if not nifti:
        errors.append("未找到可用于三维重建的 NIfTI 栈。请上传 DICOM 检查或同对比度多方向三维栈。")
    return {
        "btfe": [path.name for path in nifti],
        "stacks": [path.name for path in nifti],
        "other": [],
        "errors": errors,
    }


def _extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            name = Path(info.filename).name
            try:
                safe = sanitize_filename(name)
            except ValueError:
                continue
            if info.file_size > 2 * 1024 ** 3:
                raise ValueError("zip entry too large")
            target = dest / safe
            if target.exists():
                raise ValueError(f"duplicate file in zip: {safe}")
            copied = 0
            with zf.open(info, "r") as src, target.open("wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > info.file_size + 64 * 1024:
                        raise ValueError("zip entry exceeded declared size")
                    out.write(chunk)


def atlas_for_ga(atlas_dir: Path, ga: float) -> Path | None:
    week = int(round(float(ga)))
    candidate = atlas_dir / f"{week}w.nii.gz"
    return candidate if candidate.is_file() else None


def write_input_check(subject_dir: Path, work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    files = []
    warnings: list[str] = []
    for path in sorted(subject_dir.iterdir()):
        if not path.is_file():
            continue
        item = {"name": path.name, "bytes": path.stat().st_size}
        files.append(item)
        if path.name.lower().endswith(".nii.gz"):
            with path.open("rb") as handle:
                magic = handle.read(2)
            if magic != b"\x1f\x8b":
                warnings.append(f"{path.name} is not a gzip stream")
    stacks = [item["name"] for item in files if item["name"].lower().endswith(".nii.gz") or item["name"].lower().endswith(".nii")]
    stack_report = inspect_subject_stacks(subject_dir)
    warnings.extend(stack_report["errors"])
    ok = bool(stacks) and not warnings
    report = {"ok": ok, "files": files, "btfe_files": stacks, "stack_files": stacks, "warnings": warnings}
    (work_dir / "input_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def list_result_files(job_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not job_dir.exists():
        return results
    for path in sorted(job_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(job_dir).as_posix()
        results.append({"path": rel, "bytes": path.stat().st_size})
    return results


class JobManager:
    def __init__(self, config: GatewayConfig, store: Store):
        self.config = config
        self.store = store
        self._queue: list[str] = []
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="gateway-worker", daemon=True)
        self._cleaner = threading.Thread(target=self._cleanup_loop, name="gateway-cleaner", daemon=True)
        self._current_proc: subprocess.Popen[str] | None = None
        self._current_job: str | None = None

    def start(self) -> None:
        self._worker.start()
        self._cleaner.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        proc = self._current_proc
        if proc and proc.poll() is None:
            _kill_process_group(proc)

    def submit(self, job_id: str) -> None:
        with self._cv:
            self._queue.append(job_id)
            self._cv.notify()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._queue and not self._stop.is_set():
                    self._cv.wait(timeout=1)
                if self._stop.is_set():
                    return
                job_id = self._queue.pop(0)
            try:
                self._run_job(job_id)
            except Exception as exc:  # noqa: BLE001 - worker must never die
                self.store.update_job(
                    job_id,
                    status="failed",
                    error=str(exc),
                    finished_at=iso(),
                    progress={"phase": "failed", "message": str(exc)},
                )

    def _run_job(self, job_id: str) -> None:
        row = self.store.get_job(job_id)
        if row is None or row["status"] not in {"queued", "running"}:
            return
        username = row["username"]
        program = row["program"]
        params = json.loads(row["params_json"])
        upload_ids = json.loads(row["upload_ids_json"])
        job_dir = self.store.job_dir(username, job_id)
        work_dir = job_dir / "work"
        log_path = job_dir / "job.log"
        work_dir.mkdir(parents=True, exist_ok=True)
        self.store.update_job(
            job_id,
            status="running",
            started_at=iso(),
            progress={"phase": "preparing", "message": "Preparing isolated workspace"},
        )
        uploads = []
        for upload_id in upload_ids:
            item = self.store.get_upload(upload_id)
            if item is None or item["username"] != username:
                raise ValueError("upload not found")
            uploads.append(dict(item))
        subject_dir = extract_subject(uploads, job_dir, self.store)
        timeout = int(row["timeout_seconds"])
        started = time.monotonic()
        if program == "input_check":
            report = write_input_check(subject_dir, work_dir)
            status = "succeeded" if report["ok"] else "failed"
            (job_dir / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.store.update_job(
                job_id,
                status=status,
                finished_at=iso(),
                error=None if report["ok"] else "; ".join(report["warnings"]),
                progress={"phase": status, "message": "Input check finished", "report": report},
            )
            return
        if program != "run_pipeline":
            raise ValueError("unknown program")
        argv = self._pipeline_argv(subject_dir, work_dir, params)
        env = os.environ.copy()
        for key in ("API_KEY", "OPENAI_API_KEY", "AUTORECON_LLM_API_KEY"):
            env.pop(key, None)
        env["AUTORECON_DASHBOARD_HOST"] = "127.0.0.1"
        env["AUTORECON_DASHBOARD_MODE"] = "on"
        with log_path.open("w", encoding="utf-8") as log:
            log.write("argv: " + " ".join(argv) + "\n")
            log.flush()
            proc = subprocess.Popen(
                argv,
                cwd=str(self.config.project_root / "pipeline"),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        self._current_proc = proc
        self._current_job = job_id
        self.store.update_job(job_id, pid=proc.pid, progress={"phase": "running", "message": "Pipeline started"})
        returncode = self._wait(proc, timeout, started, job_id, work_dir)
        self._current_proc = None
        self._current_job = None
        if returncode is None:
            _kill_process_group(proc)
            self.store.update_job(
                job_id,
                status="timeout",
                finished_at=iso(),
                error=f"exceeded {timeout} seconds",
                pid=None,
                progress={"phase": "timeout", "message": "Job exceeded the configured timeout"},
            )
            return
        report = {
            "returncode": returncode,
            "work_root": str(work_dir),
            "files": list_result_files(job_dir),
        }
        state_path = work_dir / "dashboard" / "run_state.json"
        if state_path.is_file():
            try:
                report["pipeline_state"] = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        (job_dir / "result.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        status = "succeeded" if returncode == 0 else "failed"
        self.store.update_job(
            job_id,
            status=status,
            finished_at=iso(),
            error=None if returncode == 0 else f"pipeline exited with {returncode}",
            pid=None,
            progress={"phase": status, "message": "Pipeline finished", "returncode": returncode},
        )

    def _wait(
        self,
        proc: subprocess.Popen[str],
        timeout: int,
        started: float,
        job_id: str,
        work_dir: Path,
    ) -> int | None:
        while True:
            if self._stop.is_set():
                return None
            row = self.store.get_job(job_id)
            if row is not None and row["status"] == "cancelled":
                return None
            code = proc.poll()
            if code is not None:
                return code
            if time.monotonic() - started > timeout:
                return None
            progress = {"phase": "running", "elapsed_seconds": int(time.monotonic() - started)}
            state_path = work_dir / "dashboard" / "run_state.json"
            if state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    progress["pipeline"] = {
                        "status": (state.get("run") or {}).get("status"),
                        "steps": [
                            {"id": step.get("id"), "status": step.get("status"), "message": step.get("message")}
                            for step in state.get("steps") or []
                        ],
                    }
                except (OSError, ValueError):
                    pass
            self.store.update_job(job_id, progress=progress)
            time.sleep(2)

    def _pipeline_argv(self, subject_dir: Path, work_dir: Path, params: dict[str, Any]) -> list[str]:
        if not PIPELINE_SCRIPT.is_file():
            raise FileNotFoundError("pipeline script is not available")
        argv = [
            "bash",
            str(PIPELINE_SCRIPT),
            "--subject-dir",
            str(subject_dir),
            "--work-root",
            str(work_dir),
            "--reconstruction-tool",
            str(params["reconstruction_tool"]),
            "--roi-mode",
            str(params["roi_mode"]),
            "--surface",
            str(params["surface"]),
            "--dashboard",
            "on",
            "--dashboard-host",
            "127.0.0.1",
            "--steps",
            ",".join(params["steps"]),
            "--ga",
            str(params["ga"]),
        ]
        if params.get("resume"):
            argv.append("--resume")
        atlas = atlas_for_ga(self.config.atlas_dir, float(params["ga"]))
        if atlas is not None:
            argv.extend(["--atlas", str(atlas)])
        ants = os.environ.get("AUTORECON_ANTS_DIR", "").strip()
        if ants:
            argv.extend(["--ants-dir", ants])
        roi_env = os.environ.get("AUTORECON_ROI_WARP_ENV", "").strip()
        if roi_env:
            argv.extend(["--roi-warp-env", roi_env])
        return argv

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(3600):
            try:
                self.cleanup_once()
            except Exception:
                continue

    def cleanup_once(self) -> dict[str, int]:
        removed_jobs = 0
        removed_uploads = 0
        for row in self.store.expired_job_rows(self.config.retention_days):
            job_dir = self.store.job_dir(row["username"], row["job_id"])
            shutil.rmtree(job_dir, ignore_errors=True)
            self.store.delete_job(row["job_id"])
            removed_jobs += 1
        for row in self.store.stale_uploads(24):
            upload_dir = self.store.upload_dir(row["username"], row["upload_id"])
            shutil.rmtree(upload_dir, ignore_errors=True)
            self.store.delete_upload(row["upload_id"])
            removed_uploads += 1
        return {"removed_jobs": removed_jobs, "removed_uploads": removed_uploads}


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
