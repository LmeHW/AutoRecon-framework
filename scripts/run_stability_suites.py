#!/usr/bin/env python3
"""Freeze and run the 20+20 stability suites with parallel GLM/GPU workers.

Suite A writes validation_runs/stability_expand_<stamp>/
Suite B writes validation_runs/stability_continue_<stamp>/
Neither overwrites case_acceptance_20260904T0819Z.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import os
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_case_acceptance import (
    assemble_summary_from_disk,
    execute_case,
    execute_compute_isolated,
    freeze_batch,
    glm_gate_case,
    html_report,
    load_cases,
    now,
    passed_execute_result,
    utc_stamp,
    wait_for_execute_one,
    write_json,
)
from agentic.env_config import load_llm_config
from agentic.llm_client import OpenAICompatibleClient
from validation.stability_suites import (
    GOLD_BATCH,
    build_continue_cases,
    build_expand_cases,
    case_needs_gpu,
    execution_waves,
    latest_expand_batch,
    materialize_source,
)


def detect_gpus(explicit: str) -> list[str]:
    if explicit.strip():
        return [item.strip() for item in explicit.split(",") if item.strip()]
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        ids = [line.strip() for line in completed.stdout.splitlines() if line.strip().isdigit()]
        if ids:
            return ids
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ["1", "2"]


def freeze_suite(args: argparse.Namespace) -> Path:
    validation_root = ROOT / "validation_runs"
    validation_root.mkdir(parents=True, exist_ok=True)
    if args.suite == "expand":
        batch_root = args.batch_root or (validation_root / f"stability_expand_{utc_stamp()}")
        cases = build_expand_cases(batch_root)
    else:
        batch_root = args.batch_root or (validation_root / f"stability_continue_{utc_stamp()}")
        cases = build_continue_cases(
            batch_root,
            expand_batch=args.expand_batch or latest_expand_batch(),
            gold_batch=args.gold_batch or GOLD_BATCH,
        )
    freeze_batch(batch_root, cases)
    return batch_root.resolve()


def parallel_glm_gate(cases: list[dict[str, Any]], llm: OpenAICompatibleClient, repeats: int, gate_dir: Path, workers: int) -> list[dict[str, Any]]:
    gate_dir.mkdir(parents=True, exist_ok=True)

    def _one(case: dict[str, Any]) -> dict[str, Any]:
        saved = gate_dir / f"{case['case_id']}_glm.json"
        if saved.is_file():
            payload = __import__("json").loads(saved.read_text(encoding="utf-8"))
            if payload.get("authorized"):
                return payload
        materialize_source(case)
        return glm_gate_case(case, llm, repeats, gate_dir)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_one, case): case["case_id"] for case in cases}
        by_id = {futures[future]: future.result() for future in as_completed(futures)}
    for case in cases:
        results.append(by_id[case["case_id"]])
    return results


def _execute_non_gpu(case: dict[str, Any], batch_root: Path, llm: OpenAICompatibleClient) -> dict[str, Any]:
    existing = passed_execute_result(batch_root, case["case_id"], resume=False)
    if existing is not None:
        return existing
    port = 8920 + (sum(ord(ch) for ch in case["case_id"]) % 80)
    return execute_case(case, batch_root, llm, resume=False, gpu=None, dashboard_port=port)


def execute_suite(batch_root: Path, cases: list[dict[str, Any]], llm: OpenAICompatibleClient, gpu_ids: list[str]) -> list[dict[str, Any]]:
    for case in cases:
        materialize_source(case)
    results: list[dict[str, Any]] = []
    non_gpu = [case for case in cases if not case_needs_gpu(case)]
    gpu_cases = [case for case in cases if case_needs_gpu(case)]
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(non_gpu)))) as pool:
        futures = [pool.submit(_execute_non_gpu, case, batch_root, llm) for case in non_gpu]
        for future in as_completed(futures):
            results.append(future.result())
    gpu_by_id = {case["case_id"]: case for case in gpu_cases}
    for wave in execution_waves(gpu_cases):
        pending = []
        for case in wave:
            wait_for_execute_one(case["case_id"])
            existing = passed_execute_result(batch_root, case["case_id"], resume=False)
            if existing is not None:
                results.append(existing)
                continue
            pending.append(case)
        index = 0
        workers = max(1, len(gpu_ids) or 1)
        while pending:
            batch = pending[:workers]
            pending = pending[len(batch):]
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = []
                for offset, case in enumerate(batch):
                    gpu = gpu_ids[(index + offset) % len(gpu_ids)] if gpu_ids else None
                    futures.append(pool.submit(execute_compute_isolated, batch_root, case["case_id"], gpu, False))
                for future in as_completed(futures):
                    results.append(future.result())
            index += len(batch)
        _ = gpu_by_id
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("expand", "continue"), required=True)
    parser.add_argument("--phase", choices=("freeze", "glm-gate", "execute", "report", "all"), default="freeze")
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--expand-batch", type=Path)
    parser.add_argument("--gold-batch", type=Path, default=GOLD_BATCH)
    parser.add_argument("--gpus", default="", help="Comma-separated GPU ids. Empty = detect all.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--glm-workers", type=int, default=8)
    parser.add_argument("--cases", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("AUTORECON_CONFIG_FILE", str(ROOT / "config/glm.env"))
    os.environ.setdefault("AUTORECON_SECRET_FILE", str(ROOT / ".secrets/glm.env"))
    batch_root = freeze_suite(args) if args.phase in {"freeze", "all"} else (args.batch_root.resolve() if args.batch_root else freeze_suite(args))
    selected = {item.strip() for item in args.cases.split(",") if item.strip()}
    cases = [case for case in load_cases(batch_root) if not selected or case["case_id"] in selected]
    summary: dict[str, Any] = {"generated_at": now(), "suite": args.suite, "batch_root": str(batch_root)}
    if args.phase == "freeze":
        print(str(batch_root))
        return 0
    config = load_llm_config(ROOT)
    llm = OpenAICompatibleClient(config)
    if args.phase in {"glm-gate", "all"}:
        if not config.available:
            raise SystemExit("GLM is unavailable; configure AUTORECON_SECRET_FILE")
        gates = parallel_glm_gate(cases, llm, args.repeats, batch_root / "glm_gate", args.glm_workers)
        write_json(batch_root / "glm_gate.json", gates)
        summary["glm_gate"] = gates
    if args.phase in {"execute", "all"}:
        gpu_ids = detect_gpus(args.gpus)
        authorized = {
            item["case_id"]
            for item in (summary.get("glm_gate") or __import__("json").loads((batch_root / "glm_gate.json").read_text(encoding="utf-8")) if (batch_root / "glm_gate.json").is_file() else [])
            if item.get("authorized")
        } if (batch_root / "glm_gate.json").is_file() or summary.get("glm_gate") else {case["case_id"] for case in cases}
        runnable = [case for case in cases if case["case_id"] in authorized]
        results = execute_suite(batch_root, runnable, llm, gpu_ids)
        write_json(batch_root / "execute.json", results)
        summary["execute"] = results
    if args.phase in {"report", "all"}:
        merged = assemble_summary_from_disk(batch_root, summary)
        write_json(batch_root / "summary.json", {key: value for key, value in merged.items() if key != "glm_gate"})
        html_report(batch_root, merged)
        if merged.get("stability"):
            write_json(batch_root / "stability.json", merged["stability"])
    print(str(batch_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
