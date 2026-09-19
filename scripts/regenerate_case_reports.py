#!/usr/bin/env python3
"""Regenerate curated case reports in Chinese, optionally using configured GLM."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentic.capability_catalog import explanations_for
from agentic.coordinator import coordinate
from agentic.env_config import load_llm_config
from agentic.llm_client import OpenAICompatibleClient
from agentic.models import task_plan_from_dict
from agentic.reporter import build_report


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def regenerate_case(
    batch_root: Path,
    spec: dict[str, Any],
    llm: OpenAICompatibleClient | None,
) -> dict[str, Any]:
    case_id = str(spec["case_id"])
    case_dir = batch_root / "cases" / case_id
    state_path = case_dir / "state.json"
    state = _json(state_path)
    task_plan = task_plan_from_dict(state["plan"])
    task_plan.report_language = "zh"
    task_plan.report_steps = list(spec.get("report_steps") or [])
    inferred = coordinate(str((state.get("request") or {}).get("raw_text") or task_plan.goal))
    task_plan.unfulfilled_requests = list(dict.fromkeys(
        list(spec.get("unfulfilled_requests") or []) + list(inferred.unfulfilled_requests)
    ))
    task_plan.refusal_explanations = explanations_for(
        task_plan.unfulfilled_requests,
        list(task_plan.missing or []),
    )
    markdown, report_json = build_report(
        task_plan,
        list(state.get("step_results") or []),
        state.get("dashboard") or {},
        llm=llm,
        llm_events=[{
            "stage": "report_regeneration",
            "used": bool(llm and llm.available),
            "model": llm.config.model if llm else None,
        }],
    )
    state["plan"] = task_plan.to_dict()
    state.setdefault("request", {})["report_language"] = "zh"
    state["request"]["unfulfilled_requests"] = list(task_plan.unfulfilled_requests)
    state["request"]["refusal_explanations"] = list(task_plan.refusal_explanations)
    state["report_markdown"] = markdown
    state["report_json"] = report_json
    (case_dir / "report.md").write_text(markdown, encoding="utf-8")
    (case_dir / "report.json").write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reporting = (report_json.get("llm") or {}).get("reporting") or {}
    return {
        "case_id": case_id,
        "language": report_json.get("language"),
        "llm_used": bool(reporting.get("used")),
        "model": reporting.get("model"),
        "fallback": reporting.get("status") == "fallback",
        "error": reporting.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate seven-case reports in Chinese.")
    parser.add_argument(
        "--batch-root",
        default=str(ROOT / "validation_runs" / "case_acceptance_20260904T0819Z"),
    )
    parser.add_argument("--config", default=str(ROOT / "config" / "glm.env"))
    parser.add_argument("--cases", default="", help="Comma-separated case ids; default is all.")
    parser.add_argument("--no-llm", action="store_true", help="Generate deterministic Chinese reports only.")
    args = parser.parse_args()

    batch_root = Path(args.batch_root).expanduser().resolve()
    manifest = _json(batch_root / "cases.json")
    selected = {item.strip() for item in args.cases.split(",") if item.strip()}
    specs = [item for item in manifest.get("cases") or [] if not selected or item.get("case_id") in selected]
    if not specs:
        raise SystemExit("No matching cases.")

    llm = None
    if not args.no_llm:
        os.environ["AUTORECON_CONFIG_FILE"] = args.config
        config = load_llm_config(ROOT)
        if not config.available or not config.model.lower().startswith("glm-"):
            raise SystemExit("GLM reporting is not available through the selected configuration.")
        llm = OpenAICompatibleClient(config)

    results = [regenerate_case(batch_root, spec, llm) for spec in specs]
    print(json.dumps({"batch_root": str(batch_root), "reports": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
