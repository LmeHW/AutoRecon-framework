from __future__ import annotations

import json
import os
import subprocess
import csv
from pathlib import Path

from .models import StepResult, TaskPlan, utc_now
from .env_config import load_llm_config
from .failure_catalog import classify_failure, incomplete_run_notice
from .planner import BASH_STEPS
from .verifier import log_has_error, verify_nifti, verify_outputs
from .qc import evaluate_run


ORCHESTRATION_STEP_IDS = frozenset({"pipeline"})


def _bash_steps_finished(pipeline_state: dict, task_plan: TaskPlan) -> bool:
    requested = [step for step in (task_plan.execution_steps or []) if step in BASH_STEPS]
    if not requested:
        return False
    by_id = {str(item.get("id")): item for item in pipeline_state.get("steps") or []}
    done = {"completed", "skipped"}
    return all(str((by_id.get(step) or {}).get("status") or "") in done for step in requested)


def results_indicate_failure(results: list[dict]) -> bool:
    """Treat imaging/tool failures as run failures; ignore wrapper-only lock exits."""
    facing = [item for item in results if item.get("step_id") not in ORCHESTRATION_STEP_IDS]
    if any(item.get("status") == "failed" for item in facing):
        return True
    imaging = [item for item in facing if item.get("step_id") in BASH_STEPS]
    if imaging:
        return False
    return any(item.get("status") == "failed" for item in results)


class AgenticExecutor:
    def __init__(self, project_root: Path, run_root: Path):
        self.project_root = project_root.resolve()
        self.pipeline_root = self.project_root / "pipeline"
        self.run_root = run_root.resolve()

    def execute(self, task_plan: TaskPlan, run_id: str, dashboard_url: str = "") -> tuple[list[dict], dict]:
        if task_plan.execution_mode == "plan_only":
            return self._plan_only(task_plan), {}
        if task_plan.execution_mode == "import_existing":
            results = self._import_existing(task_plan, run_id)
            existing_run = Path(task_plan.existing_run_dir or "").expanduser().resolve()
            dashboard_dir = existing_run / "dashboard"
            return results, {
                "dashboard_dir": str(dashboard_dir),
                "dashboard_file": str(dashboard_dir / "index.html"),
                "dashboard_state": str(dashboard_dir / "run_state.json"),
                "url": dashboard_url,
            }
        if task_plan.execution_mode in {"run_pipeline", "continue_from_run"}:
            results = self._run_pipeline(task_plan, run_id)
            work_root = Path(task_plan.work_root or (self.run_root / run_id / "pipeline_run")).expanduser().resolve()
            return results, {
                "dashboard_dir": str(work_root / "dashboard"),
                "dashboard_file": str(work_root / "dashboard" / "index.html"),
                "dashboard_state": str(work_root / "dashboard" / "run_state.json"),
                "url": "http://127.0.0.1:8765",
            }
        raise ValueError(f"Unknown execution mode: {task_plan.execution_mode}")

    def _plan_only(self, task_plan: TaskPlan) -> list[dict]:
        results = []
        for step in task_plan.steps:
            results.append(
                StepResult(
                    step_id=step.id,
                    tool=step.tool,
                    status="skipped" if step.status == "skipped" else "pending",
                    message=step.reason or "Planned but not executed.",
                ).to_dict()
            )
        return results

    def _import_existing(self, task_plan: TaskPlan, run_id: str) -> list[dict]:
        started = utc_now()
        existing_run = Path(task_plan.existing_run_dir or "").expanduser().resolve()
        results: list[dict] = []

        input_ok = existing_run.is_dir() and (existing_run / "dashboard" / "run_state.json").is_file()
        results.append(
            StepResult(
                step_id="input_check",
                tool="input_check",
                status="completed" if input_ok else "failed",
                inputs={"existing_run_dir": str(existing_run)},
                error=None if input_ok else "Existing run must contain dashboard/run_state.json.",
                message="Existing run is readable." if input_ok else "Existing run is not usable.",
                started_at=started,
                ended_at=utc_now(),
            ).to_dict()
        )
        if not input_ok:
            return results

        dashboard_src = existing_run / "dashboard"
        run_state_path = dashboard_src / "run_state.json"
        run_state = json.loads(run_state_path.read_text(encoding="utf-8"))

        outputs = {
            "dashboard_dir": str(dashboard_src),
            "dashboard_state": str(run_state_path),
            "dashboard_file": str(dashboard_src / "index.html"),
        }
        ok, checks = verify_outputs(outputs)
        results.append(
            StepResult(
                step_id="visualization",
                tool="visualization_dashboard",
                status="completed" if ok else "failed",
                inputs={"source_dashboard": str(dashboard_src)},
                outputs=outputs,
                message="Linked existing dashboard assets without copying." if ok else "; ".join(checks),
                started_at=started,
                ended_at=utc_now(),
            ).to_dict()
        )
        results.append(self._metrics_from_existing(existing_run, run_state))
        return results

    def _metrics_from_existing(self, existing_run: Path, dashboard_state: dict) -> dict:
        subject = dashboard_state.get("run", {}).get("subject_name") or existing_run.name.replace("_run01", "")
        staging_subject = existing_run / "staging" / subject
        stats_dir = existing_run / "outputs" / "surface_subjects" / subject / "stats"
        surface_dir = existing_run / "outputs" / "surface_subjects" / subject
        surface_surf_dir = surface_dir / "surf"
        metric_files = [
            str(path)
            for path in (
                stats_dir / "roi86_basic.stats",
                stats_dir / "roi86_thicknessproxy_cortexonly.stats",
            )
            if path.exists()
        ]
        roi_file = existing_run / "outputs" / "ROI" / f"{subject}.nii.gz"
        if roi_file.exists():
            ok, message = verify_nifti(roi_file)
        else:
            ok, message = False, "ROI image not found; metrics may be unavailable."
        analysis = self._technical_analysis(existing_run, dashboard_state, subject, staging_subject, surface_dir)
        status = "completed" if metric_files or ok else "skipped"
        return StepResult(
            step_id="metrics",
            tool="roi_volume_statistics",
            status=status,
            inputs={"existing_run_dir": str(existing_run)},
            outputs={
                "metrics_files": metric_files,
                "roi_image": str(roi_file) if roi_file.exists() else None,
                "surface_subject_dir": str(surface_dir) if surface_dir.exists() else None,
                "surface_surf_dir": str(surface_surf_dir) if surface_surf_dir.exists() else None,
                "technical_analysis": analysis,
            },
            message=f"Metrics files found: {len(metric_files)}. {message}",
            started_at=utc_now(),
            ended_at=utc_now(),
        ).to_dict()

    def _technical_analysis(
        self,
        existing_run: Path,
        dashboard_state: dict,
        subject: str,
        staging_subject: Path,
        surface_dir: Path,
    ) -> dict:
        steps = dashboard_state.get("steps", [])
        step_summary = {
            "completed": [step.get("id") for step in steps if step.get("status") == "completed"],
            "failed": [step.get("id") for step in steps if step.get("status") == "failed"],
            "skipped": [step.get("id") for step in steps if step.get("status") == "skipped"],
        }
        stack_files = sorted(staging_subject.glob("*.nii.gz")) if staging_subject.exists() else []
        completed_ids = {str(step) for step in step_summary["completed"]}
        skipped_ids = {str(step) for step in step_summary["skipped"]}
        image_checks: dict[str, str] = {}
        for label, path in {
            "reconstruction": existing_run / "outputs" / "recon" / f"{subject}.nii.gz",
            "tissue": existing_run / "outputs" / "Tissue" / f"{subject}.nii.gz",
            "roi": existing_run / "outputs" / "ROI" / f"{subject}.nii.gz",
        }.items():
            if label in skipped_ids:
                continue
            if label not in completed_ids and not path.exists():
                continue
            ok, message = verify_nifti(path) if path.exists() else (False, f"missing file: {path}")
            image_checks[label] = ("PASS: " if ok else "WARN: ") + message

        expected_surface_files = [
            "lh.white",
            "rh.white",
            "lh.pial",
            "rh.pial",
            "lh.inflated",
            "rh.inflated",
        ]
        surf_dir = surface_dir / "surf"
        present_surface_files = [name for name in expected_surface_files if (surf_dir / name).exists()]
        missing_surface_files = [
            name for name in expected_surface_files
            if (surf_dir / name).exists() is False and "surface" not in skipped_ids
        ]
        stats_dir = surface_dir / "stats"
        expected_stats_files = ("roi86_basic.stats", "roi86_thicknessproxy_cortexonly.stats")
        present_stats = [name for name in expected_stats_files if (stats_dir / name).exists()]
        missing_stats = [
            name for name in expected_stats_files
            if not (stats_dir / name).exists() and "surface" not in skipped_ids and "roi" not in skipped_ids
        ]
        conversion = {}
        for candidate in (
            staging_subject / "conversion.json",
            Path(str(dashboard_state.get("run", {}).get("subject_dir") or "")) / "conversion.json",
            Path(str(dashboard_state.get("run", {}).get("subject_dir") or "")) / ".upload.json",
        ):
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            conversion = payload.get("conversion") or (payload if candidate.name == "conversion.json" else {})
            if conversion:
                break
        quantitative_summary = {
            "roi86_basic": self._read_segstats_summary(stats_dir / "roi86_basic.stats"),
            "roi86_cortexonly": self._read_segstats_summary(stats_dir / "roi86_thicknessproxy_cortexonly.stats"),
        }
        registration_summary = self._read_registration_summary(existing_run / "outputs" / "registration" / "summary.csv")

        log_findings = []
        for step in steps:
            log_relpath = step.get("log_relpath")
            if not log_relpath:
                continue
            has_error, message = log_has_error(existing_run / "dashboard" / log_relpath)
            if has_error:
                log_findings.append({"step": step.get("id"), "message": message})

        quality_flags = []
        if step_summary["failed"]:
            quality_flags.append("One or more pipeline steps failed.")
        if missing_surface_files:
            quality_flags.append("Surface reconstruction is incomplete.")
        if any(value.startswith("WARN") for value in image_checks.values()):
            quality_flags.append("One or more expected image outputs are missing or unreadable.")
        if log_findings:
            quality_flags.append("One or more step logs contain error-like patterns.")
        if not quality_flags:
            quality_flags.append("Technical completeness checks passed for imported outputs.")

        step_qc = evaluate_run(existing_run, subject)
        return {
            "case_info": {
                "subject": subject,
                "existing_run_dir": str(existing_run),
                "staging_subject_dir": str(staging_subject),
                "stack_files": [path.name for path in stack_files],
                "stack_count": len(stack_files),
                "btfe_stack_count": len(stack_files),
                "conversion": conversion,
                "dashboard_status": dashboard_state.get("run", {}).get("status"),
            },
            "step_summary": step_summary,
            "image_checks": image_checks,
            "surface_checks": {
                "surface_dir": str(surface_dir),
                "present_surface_files": present_surface_files,
                "missing_surface_files": missing_surface_files,
                "present_stats_files": present_stats,
                "missing_stats_files": missing_stats,
            },
            "registration_summary": registration_summary,
            "quantitative_summary": quantitative_summary,
            "log_findings": log_findings,
            "technical_quality_summary": quality_flags,
            "step_qc": step_qc,
        }

    def _read_registration_summary(self, path: Path) -> dict:
        if not path.exists():
            return {"available": False, "message": f"missing file: {path}"}
        try:
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except Exception as exc:
            return {"available": False, "message": f"cannot read registration summary: {exc}"}
        if not rows:
            return {"available": False, "message": "registration summary is empty"}
        row = rows[0]
        return {
            "available": True,
            "status": row.get("status") or "",
            "qc_group": row.get("qc_group") or "",
            "atlas": row.get("atlas") or "",
            "atlas_week": row.get("atlas_week") or "",
            "gestational_age": row.get("gestational_age") or "",
            "mattes_lower_is_better": row.get("mattes_lower_is_better") or "",
            "gc_lower_is_better": row.get("gc_lower_is_better") or "",
            "message": row.get("message") or "",
        }

    def _read_segstats_summary(self, path: Path) -> dict:
        if not path.exists():
            return {"available": False, "message": f"missing file: {path}"}
        headers: list[str] = []
        rows: list[dict[str, str | float | int]] = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("# ColHeaders"):
                    headers = stripped.split()[2:]
                    continue
                if stripped.startswith("#") or not headers:
                    continue
                parts = stripped.split(None, len(headers) - 1)
                if len(parts) != len(headers):
                    continue
                row: dict[str, str | float | int] = {}
                for key, value in zip(headers, parts):
                    if key in {"Index", "SegId", "NVoxels"}:
                        try:
                            row[key] = int(value)
                        except ValueError:
                            row[key] = value
                    elif key == "Volume_mm3":
                        try:
                            row[key] = float(value)
                        except ValueError:
                            row[key] = value
                    else:
                        row[key] = value
                rows.append(row)
        except Exception as exc:
            return {"available": False, "message": f"cannot read segstats: {exc}"}
        volumes = [float(row["Volume_mm3"]) for row in rows if isinstance(row.get("Volume_mm3"), float)]
        largest = sorted(
            (row for row in rows if isinstance(row.get("Volume_mm3"), float)),
            key=lambda item: float(item["Volume_mm3"]),
            reverse=True,
        )[:5]
        return {
            "available": True,
            "path": str(path),
            "roi_count": len(rows),
            "total_volume_mm3": round(sum(volumes), 1),
            "largest_regions": [
                {
                    "seg_id": row.get("SegId"),
                    "struct_name": row.get("StructName"),
                    "volume_mm3": row.get("Volume_mm3"),
                }
                for row in largest
            ],
            "labeling_note": "Only generic Seg#### labels are present in this stats file.",
        }

    def _run_pipeline(self, task_plan: TaskPlan, run_id: str) -> list[dict]:
        started = utc_now()
        work_root = Path(task_plan.work_root or (self.run_root / run_id / "pipeline_run")).expanduser().resolve()
        log_path = self.run_root / run_id / "pipeline.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        args = [
            "bash",
            str(self.pipeline_root / "run_single_case_pipeline.sh"),
            "--subject-dir",
            str(Path(task_plan.subject_dir or "").expanduser()),
            "--work-root",
            str(work_root),
            "--reconstruction-tool",
            task_plan.reconstruction_tool,
            "--roi-mode",
            task_plan.roi_mode,
            "--surface",
            task_plan.surface,
            "--dashboard",
            os.environ.get("AUTORECON_DASHBOARD_MODE", "on"),
            "--dashboard-host",
            os.environ.get("AUTORECON_DASHBOARD_HOST", "127.0.0.1"),
            "--dashboard-port",
            os.environ.get("AUTORECON_DASHBOARD_PORT", "8765"),
            "--steps",
            ",".join(step for step in task_plan.execution_steps if step in BASH_STEPS),
        ]
        if task_plan.reconstruction_compare_tools:
            args.extend(["--compare-reconstruction-tools", ",".join(task_plan.reconstruction_compare_tools)])
        config = load_llm_config(self.project_root)
        if config.ants_dir:
            args.extend(["--ants-dir", config.ants_dir])
        if config.roi_warp_env:
            args.extend(["--roi-warp-env", config.roi_warp_env])
        if task_plan.resume or task_plan.execution_mode == "continue_from_run":
            args.append("--resume")
        if task_plan.atlas:
            args.extend(["--atlas", task_plan.atlas])
        ga = task_plan.gestational_age
        if ga is None and task_plan.atlas_week is not None:
            ga = float(task_plan.atlas_week)
        if ga is not None:
            args.extend(["--ga", str(ga)])

        env = os.environ.copy()
        env.pop("API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env.pop("AUTORECON_LLM_API_KEY", None)

        pid_path = work_root / "dashboard" / "pipeline.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                args, cwd=self.pipeline_root, env=env, stdout=log, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            try:
                pid_path.write_text(str(proc.pid), encoding="utf-8")
                returncode = proc.wait()
            finally:
                try:
                    pid_path.unlink(missing_ok=True)
                except OSError:
                    pass

        err, log_msg = log_has_error(log_path)
        state_path = work_root / "dashboard" / "run_state.json"
        pipeline_state = None
        if state_path.is_file():
            try:
                pipeline_state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pipeline_state = None
        imaging_done = _bash_steps_finished(pipeline_state, task_plan) if pipeline_state else False
        lock_reuse = returncode == 75 and imaging_done
        status = "completed" if ((returncode == 0 and not err) or lock_reuse) else "failed"
        l0_message = ""
        try:
            subject = Path(task_plan.subject_dir or "").name
            qc = evaluate_run(work_root, subject, list(task_plan.execution_steps or []))
            l0_failed = [item for item in qc.get("steps") or [] if item.get("contract_status") == "fail"]
            if l0_failed:
                names = ", ".join(str(item.get("step_id")) for item in l0_failed)
                l0_message = f"L0 合同失败（{names}），下游不得继续。"
                if status == "completed":
                    status = "failed"
        except Exception:
            l0_failed = []
        log_msg = ""
        if lock_reuse:
            log_msg = "已有步骤产物仍在；工作目录锁被占用，未再次写入。按复用计。"
        elif returncode != 0:
            log_tail = ""
            try:
                log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            except OSError:
                log_tail = ""
            failure = classify_failure(returncode, log_msg, log_tail)
            notice = None
            if pipeline_state:
                notice = incomplete_run_notice(pipeline_state.get("steps", []))
            log_msg = " ".join(
                part for part in (
                    failure["cause_zh"], failure["meaning_zh"], failure["next_action_zh"], notice,
                ) if part
            )
        if l0_message:
            log_msg = f"{log_msg} {l0_message}".strip()

        outputs = {
            "work_root": str(work_root),
            "dashboard_dir": str(work_root / "dashboard"),
            "dashboard_file": str(work_root / "dashboard" / "index.html"),
            "recon_image": str(work_root / "outputs" / "recon" / f"{Path(task_plan.subject_dir or '').name}.nii.gz"),
        }
        result = StepResult(
            step_id="pipeline",
            tool="run_single_case_pipeline",
            status=status,
            inputs={"plan_file": str(self.run_root / run_id / "task_plan.json")},
            outputs=outputs,
            log=str(log_path),
            error=None if status == "completed" else log_msg,
            message=log_msg if lock_reuse else ("Pipeline finished." if status == "completed" else log_msg),
            started_at=started,
            ended_at=utc_now(),
        )
        results = [result.to_dict()]
        if pipeline_state:
            try:
                for step in pipeline_state.get("steps", []):
                    results.append(StepResult(
                        step_id=str(step.get("id", "")),
                        tool=next((item.tool for item in task_plan.steps if item.id == step.get("id")), "visualization_dashboard"),
                        status=step.get("status", "pending"),
                        outputs={"artifacts": step.get("artifacts", []), "preview_relpath": step.get("preview_relpath")},
                        message=str(step.get("message") or ""),
                        log=str(work_root / "dashboard" / step["log_relpath"]) if step.get("log_relpath") else None,
                    ).to_dict())
                results.append(self._metrics_from_existing(work_root, pipeline_state))
            except (OSError, ValueError):
                pass
        return results

    def collect_pipeline_results(self, task_plan: TaskPlan, run_id: str) -> tuple[list[dict], dict]:
        """Recover results from a pipeline dashboard after the agent server restarted."""
        work_root = Path(task_plan.work_root or "").expanduser().resolve()
        state_path = work_root / "dashboard" / "run_state.json"
        if not state_path.is_file():
            return [], {}
        pipeline_state = json.loads(state_path.read_text(encoding="utf-8"))
        run_status = str(pipeline_state.get("run", {}).get("status") or "failed")
        imaging_done = _bash_steps_finished(pipeline_state, task_plan)
        wrapper_ok = run_status == "completed" or imaging_done
        results = [StepResult(
            step_id="pipeline", tool="run_single_case_pipeline",
            status="completed" if wrapper_ok else "failed",
            inputs={"plan_file": str(self.run_root / run_id / "task_plan.json")},
            outputs={"work_root": str(work_root), "dashboard_state": str(state_path)},
            message=f"Recovered pipeline state: {run_status}.",
        ).to_dict()]
        for step in pipeline_state.get("steps", []):
            results.append(StepResult(
                step_id=str(step.get("id", "")),
                tool=next((item.tool for item in task_plan.steps if item.id == step.get("id")), "visualization_dashboard"),
                status=step.get("status", "pending"),
                outputs={"artifacts": step.get("artifacts", []), "preview_relpath": step.get("preview_relpath")},
                message=str(step.get("message") or ""),
                log=str(work_root / "dashboard" / step["log_relpath"]) if step.get("log_relpath") else None,
            ).to_dict())
        subject = pipeline_state.get("run", {}).get("subject_name") or Path(task_plan.subject_dir or "").name
        results.append(self._metrics_from_existing(work_root, pipeline_state))
        dashboard = {
            "dashboard_dir": str(work_root / "dashboard"),
            "dashboard_file": str(work_root / "dashboard" / "index.html"),
            "dashboard_state": str(state_path), "url": "http://127.0.0.1:8765",
        }
        return results, dashboard

    def _dashboard_info(self, run_id: str, dashboard_url: str) -> dict:
        visual_dir = self.run_root / run_id / "visual_dashboard"
        if visual_dir.exists():
            return {
                "dashboard_dir": str(visual_dir),
                "dashboard_file": str(visual_dir / "index.html"),
                "dashboard_state": str(visual_dir / "run_state.json"),
                "url": dashboard_url,
            }
        return {"url": dashboard_url}
