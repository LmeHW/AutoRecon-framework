from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

try:
    from .run_backend import BACKENDS
except ImportError:  # Executed directly by run_single_case_pipeline.sh.
    from run_backend import BACKENDS


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> int:
    requested = list(dict.fromkeys(args.backends))
    if args.selected not in requested:
        requested.insert(0, args.selected)
    else:
        requested.remove(args.selected)
        requested.insert(0, args.selected)

    output_root = args.output_root.resolve()
    summary_path = output_root / "reconstruction/comparison.json"
    summary: dict[str, object] = {
        "schema_version": 1,
        "selected_backend": args.selected,
        "requested_backends": requested,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "results": {},
    }
    _write_json(summary_path, summary)
    results: dict[str, object] = {}
    for backend in requested:
        canonical = (
            Path(os.path.abspath(args.canonical_output))
            if backend == args.selected
            else output_root / "recon_candidates" / backend / f"{args.subject_dir.name}.nii.gz"
        )
        command = [
            sys.executable, str(Path(__file__).with_name("run_backend.py")),
            "--backend", backend,
            "--subject-dir", str(args.subject_dir),
            "--output-root", str(output_root),
            "--scratch-root", str(args.scratch_root),
            "--canonical-output", str(canonical),
            "--project-root", str(args.project_root),
        ]
        if args.runtime_root:
            command.extend(["--runtime-root", str(args.runtime_root)])
        result_path = output_root / "reconstruction" / backend / "result.json"
        reused = False
        if result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if existing.get("status") == "completed":
                command.append("--validate-existing")
                reused = True
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0 and reused:
            command = [item for item in command if item != "--validate-existing"]
            completed = subprocess.run(command, check=False)
        result_path = output_root / "reconstruction" / backend / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {
            "status": "failed", "error": f"missing result manifest; exit={completed.returncode}"
        }
        results[backend] = {
            "status": result.get("status"),
            "exit_code": completed.returncode,
            "result": str(result_path),
            "output": result.get("output"),
            "qc": result.get("qc"),
            "error": result.get("error"),
        }
        summary["results"] = results
        _write_json(summary_path, summary)

    selected_ok = results[args.selected]["status"] == "completed"
    all_ok = all(record["status"] == "completed" for record in results.values())
    summary.update({
        "status": "completed" if all_ok else ("partial" if selected_ok else "failed"),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json(summary_path, summary)
    return 0 if selected_ok else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multiple reconstruction backends and retain a selected canonical result.")
    parser.add_argument("--selected", choices=BACKENDS, required=True)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    parser.add_argument("--subject-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--runtime-root", type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
