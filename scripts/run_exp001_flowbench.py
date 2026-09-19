#!/usr/bin/env python3
"""Offline EXP-001 development-corpus FlowBench runner.

This is a plan-only pilot on validation/nl_corpus.py. It is not the locked
1000-utterance FetalMR-FlowBench test. Do not copy rates into CLAIM or RES.
Never starts GPU pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentic.coordinator import coordinate, coordinate_with_llm
from agentic.env_config import LLMConfig, load_llm_config
from agentic.llm_client import OpenAICompatibleClient
from agentic.planner import plan, plan_with_llm, validate_plan, validate_runtime
from validation.exp001_scoring import METRIC_VERSION, score_row, summarize
from validation.nl_corpus import CORPUS

EMAIL_SCRIPT = Path.home() / ".cursor/skills/send-qq-email/scripts/send_email.py"
VARIANTS = ("rules_only", "direct_llm", "structural_validator", "full")
LLM_VARIANTS = ("direct_llm", "structural_validator", "full")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def discover_qwen(root: Path, glm: LLMConfig) -> tuple[LLMConfig | None, str]:
    env_url = os.environ.get("AUTORECON_QWEN_BASE_URL", "").strip()
    env_model = os.environ.get("AUTORECON_QWEN_MODEL", "").strip() or "Qwen/Qwen3-32B-AWQ"
    env_key = os.environ.get("AUTORECON_QWEN_API_KEY", "").strip() or glm.api_key or "local"
    qwen_file = root / "config/qwen.env"
    if env_url:
        return replace(glm, enabled=True, provider="openai_compatible", base_url=env_url.rstrip("/"), model=env_model, api_key=env_key), "env"
    if qwen_file.is_file():
        from agentic.env_config import parse_env_file
        values = parse_env_file(qwen_file)
        url = (values.get("AUTORECON_LLM_BASE_URL") or values.get("AUTORECON_QWEN_BASE_URL") or "").strip()
        model = (values.get("AUTORECON_LLM_MODEL") or values.get("AUTORECON_QWEN_MODEL") or env_model).strip()
        key = (values.get("AUTORECON_LLM_API_KEY") or env_key).strip()
        if url:
            return replace(glm, enabled=True, provider="openai_compatible", base_url=url.rstrip("/"), model=model, api_key=key or "local"), str(qwen_file)
    return None, "no qwen env or config/qwen.env; checkpoint still unfrozen"


def run_variant(item: dict[str, Any], variant: str, llm: OpenAICompatibleClient | None, ants_dir: str, roi_warp_env: str) -> dict[str, Any]:
    text = item["natural_language"]
    overrides = deepcopy_json(item["overrides"])
    request_event: dict[str, Any] = {}
    plan_event: dict[str, Any] = {}
    if variant == "rules_only":
        request = coordinate(text, overrides)
        request_event = {"used": False, "stage": "request_parsing", "reason": "rules_only"}
        task_plan = plan(request)
        plan_event = {"used": False, "stage": "planning", "reason": "rules_only"}
        plan_errors = validate_plan(task_plan)
        runtime_errors = []
    elif variant == "direct_llm":
        request, request_event = coordinate_with_llm(text, overrides, llm)
        task_plan, plan_event = plan_with_llm(
            request, llm, force_llm=True, apply_validator=False, max_attempts=1, allow_fallback=False,
        )
        plan_errors = validate_plan(task_plan)
        runtime_errors = []
    elif variant == "structural_validator":
        request, request_event = coordinate_with_llm(text, overrides, llm)
        task_plan, plan_event = plan_with_llm(
            request, llm, force_llm=True, apply_validator=True, include_capability=False,
            max_attempts=4, allow_fallback=False,
        )
        plan_errors = validate_plan(task_plan, include_capability=False)
        runtime_errors = []
    elif variant == "full":
        request, request_event = coordinate_with_llm(text, overrides, llm)
        task_plan, plan_event = plan_with_llm(request, llm)
        plan_errors = validate_plan(task_plan)
        runtime_errors = validate_runtime(task_plan, ants_dir, roi_warp_env)
        plan_errors = list(plan_errors) + list(runtime_errors)
    else:
        raise ValueError(f"unknown variant: {variant}")
    request_data, plan_data = request.to_dict(), task_plan.to_dict()
    scored = score_row(request_data, plan_data, item["expected"], plan_errors, runtime_errors, None)
    return {
        "request": request_data,
        "plan": plan_data,
        "events": [request_event, plan_event],
        **scored,
    }


def row_key(backbone: str, variant: str, case_id: str, repeat: int) -> str:
    return f"{backbone}|{variant}|{case_id}|{repeat}"


def load_progress(path: Path) -> dict[str, dict[str, Any]]:
    saved: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return saved
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = row.get("key")
        if key:
            saved[key] = row
    return saved


def append_progress(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def send_email(output: Path, subject: str, body: str) -> dict[str, Any]:
    marker = output / "EMAIL_SENT"
    body_path = output / "email_body.txt"
    body_path.write_text(body, encoding="utf-8")
    if not EMAIL_SCRIPT.is_file():
        return {"sent": False, "reason": f"missing {EMAIL_SCRIPT}"}
    try:
        proc = subprocess.run(
            [sys.executable, str(EMAIL_SCRIPT), "--subject", subject, "--body-file", str(body_path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        marker.write_text(now() + "\n", encoding="utf-8")
        return {"sent": True, "returncode": 0}
    return {"sent": False, "returncode": proc.returncode, "stderr": (proc.stderr or "")[-400]}


def write_status(output: Path, **fields: Any) -> None:
    payload = {"updated_at": now(), "pid": os.getpid(), **fields}
    write_json(output / "STATUS.json", payload)
    (output / "HEARTBEAT").write_text(now() + f" pid={os.getpid()}\n", encoding="utf-8")


def public_config(config: LLMConfig) -> dict[str, Any]:
    data = config.public_dict()
    data.pop("api_key", None)
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", default="config/glm.env")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="If >0, only the first N corpus items.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--skip-qwen", action="store_true")
    parser.add_argument("--notify", action="store_true", help="Email when the run finishes or crashes.")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Recompute metric_version=2 from progress.jsonl without calling LLMs.",
    )
    return parser.parse_args()


def expected_by_case(corpus: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["case_id"]: item["expected"] for item in corpus}


def rescore_progress(output: Path, corpus: list[dict[str, Any]]) -> dict[str, Any]:
    progress_path = output / "progress.jsonl"
    saved = load_progress(progress_path)
    if not saved:
        raise SystemExit(f"no progress.jsonl rows in {progress_path}")
    expected = expected_by_case(corpus)
    results = []
    missing_gold = []
    for row in saved.values():
        case_id = row.get("case_id")
        if case_id not in expected:
            missing_gold.append(case_id)
            continue
        scored = score_row(
            row.get("request") or {},
            row.get("plan") or {},
            expected[case_id],
            row.get("plan_errors") or [],
            row.get("runtime_errors") or [],
            row.get("error"),
        )
        results.append({**row, **scored})
    if missing_gold:
        raise SystemExit(f"progress rows missing corpus gold: {sorted(set(missing_gold))[:12]}")
    results.sort(key=lambda row: (row["backbone"], row["variant"], row["case_id"], row["repeat"]))
    summary = summarize(results, corpus, now())
    write_json(output / "summary_v2.json", summary)
    return {"rows": len(results), "summary": str(output / "summary_v2.json"), "metric_version": METRIC_VERSION}


def main() -> int:
    args = parse_args()
    os.environ.setdefault("AUTORECON_CONFIG_FILE", args.config)
    os.environ.setdefault("AUTORECON_SECRET_FILE", str(ROOT / ".secrets/glm.env"))
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    if args.rescore:
        corpus = list(CORPUS[: args.limit] if args.limit > 0 else CORPUS)
        result = rescore_progress(output, corpus)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    notify = bool(args.notify) and not args.no_notify
    glm = load_llm_config(ROOT)
    qwen, qwen_source = (None, "skipped by flag") if args.skip_qwen else discover_qwen(ROOT, glm)
    corpus = list(CORPUS[: args.limit] if args.limit > 0 else CORPUS)
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]
    unknown = [item for item in variants if item not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variants: {unknown}")
    if any(item in LLM_VARIANTS for item in variants) and not glm.available:
        write_status(output, status="blocked", error="GLM config unavailable")
        raise SystemExit("GLM is unavailable; cannot run LLM variants")
    backbones: list[tuple[str, LLMConfig | None]] = [("glm", glm)]
    if qwen is not None:
        backbones.append(("qwen", qwen))
    jobs: list[tuple[str, LLMConfig | None, str, dict[str, Any], int]] = []
    if "rules_only" in variants:
        for item in corpus:
            jobs.append(("n/a", None, "rules_only", item, 1))
    for backbone, config in backbones:
        if config is None or not config.available:
            continue
        for variant in variants:
            if variant not in LLM_VARIANTS:
                continue
            for item in corpus:
                for repeat in range(1, max(1, args.repeats) + 1):
                    jobs.append((backbone, config, variant, item, repeat))
    manifest = {
        "schema_version": 1,
        "metric_version": METRIC_VERSION,
        "experiment": "EXP-001",
        "role": "development_pilot",
        "locked_test": False,
        "offline_plan_only": True,
        "gpu": False,
        "corpus": "validation/nl_corpus.py:CORPUS",
        "corpus_size": len(corpus),
        "note": "Old development corpus only. Not the locked 1000-item FlowBench. Do not copy rates into CLAIM or RES.",
        "variants": variants,
        "repeats_llm": args.repeats,
        "repeats_rules": 1,
        "glm": public_config(glm),
        "qwen": public_config(qwen) if qwen else {"available": False, "reason": qwen_source},
        "started_at": now(),
        "planned_rows": len(jobs),
        "pid": os.getpid(),
    }
    write_json(output / "manifest.json", manifest)
    (output / "README.txt").write_text(
        "EXP-001 development/pilot run (plan-only).\n"
        "Not a locked test. Do not treat summary rates as paper results.\n",
        encoding="utf-8",
    )
    progress_path = output / "progress.jsonl"
    saved = load_progress(progress_path)
    pending = [job for job in jobs if row_key(job[0], job[2], job[3]["case_id"], job[4]) not in saved]
    write_status(output, status="running", planned=len(jobs), completed=len(saved), pending=len(pending), qwen=qwen_source)
    print(f"EXP-001 pilot planned={len(jobs)} resume_skip={len(jobs) - len(pending)} pending={len(pending)}", flush=True)

    def run_one(backbone: str, config: LLMConfig | None, variant: str, item: dict[str, Any], repeat: int) -> dict[str, Any]:
        started = time.perf_counter()
        error = None
        payload: dict[str, Any] = {}
        try:
            llm = OpenAICompatibleClient(config) if variant in LLM_VARIANTS and config is not None else None
            payload = run_variant(item, variant, llm, glm.ants_dir, glm.roi_warp_env)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            payload = score_row({}, {}, item["expected"], [], [], error)
            payload.update({"request": {}, "plan": {}, "events": []})
        row = {
            "key": row_key(backbone, variant, item["case_id"], repeat),
            "backbone": backbone,
            "variant": variant,
            "case_id": item["case_id"],
            "category": item["category"],
            "repeat": repeat,
            "duration_seconds": time.perf_counter() - started,
            "error": error,
            "natural_language": item["natural_language"],
            **payload,
        }
        return row

    results = list(saved.values())
    exit_code = 0
    try:
        workers = 1 if not pending else max(1, min(args.workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, *job): job for job in pending}
            for future in as_completed(futures):
                row = future.result()
                results.append(row)
                append_progress(progress_path, row)
                write_status(
                    output, status="running", planned=len(jobs), completed=len(results),
                    pending=len(jobs) - len(results), last_key=row["key"],
                    last_strict=row.get("strict_plan_success"), last_error=row.get("error"),
                )
                print(
                    f"[{len(results)}/{len(jobs)}] {row['key']} "
                    f"strict={row.get('strict_plan_success')} err={row.get('error')} "
                    f"{row['duration_seconds']:.1f}s",
                    flush=True,
                )
        results.sort(key=lambda row: (row["backbone"], row["variant"], row["case_id"], row["repeat"]))
        summary = summarize(results, corpus, now())
        write_json(output / "summary.json", summary)
        manifest["finished_at"] = now()
        manifest["completed_rows"] = len(results)
        manifest["status"] = "completed"
        write_json(output / "manifest.json", manifest)
        write_status(output, status="completed", planned=len(jobs), completed=len(results), pending=0)
        print(json.dumps({"output": str(output), "status": "completed", "rows": len(results)}, ensure_ascii=False), flush=True)
    except BaseException as exc:
        exit_code = 1
        manifest["status"] = "failed"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        manifest["traceback"] = traceback.format_exc()[-4000:]
        write_json(output / "manifest.json", manifest)
        write_status(output, status="failed", error=manifest["error"], completed=len(results), planned=len(jobs))
        print(manifest["error"], file=sys.stderr, flush=True)
        if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
            traceback.print_exc()
    finally:
        if notify and not (output / "EMAIL_SENT").is_file():
            status = json.loads((output / "STATUS.json").read_text(encoding="utf-8")).get("status", "unknown") if (output / "STATUS.json").is_file() else "unknown"
            summary_path = output / "summary.json"
            summary_text = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else "(no summary yet)"
            body = (
                f"EXP-001 development/pilot 已结束\n"
                f"状态: {status}\n"
                f"目录: {output}\n"
                f"日志: {output / 'runner.log'}\n"
                f"这不是 locked test，数字不得写入 CLAIM/RES。\n\n"
                f"{summary_text[:4000]}\n"
            )
            mail = send_email(output, f"[AutoRecon] EXP-001 {status}", body)
            write_json(output / "email_result.json", mail)
    return exit_code


if __name__ == "__main__":
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise SystemExit(main())
