from __future__ import annotations

import argparse
import json
from pathlib import Path

from .env_config import load_llm_config
from .llm_client import OpenAICompatibleClient
from .state_store import StateStore
from .workflow import PROJECT_ROOT, run


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoRecon agentic workflow CLI")
    parser.add_argument("request", help="Natural-language request")
    parser.add_argument("--execution-mode", choices=["plan_only", "import_existing", "run_pipeline"], default="plan_only")
    parser.add_argument("--subject-dir")
    parser.add_argument("--work-root")
    parser.add_argument("--existing-run-dir")
    parser.add_argument("--ga", dest="gestational_age", type=float)
    parser.add_argument("--atlas")
    parser.add_argument("--reconstruction-tool", choices=["frost", "nesvor", "autosvrtk", "niftymic"], default="frost")
    parser.add_argument("--roi-mode", choices=["warp", "segresnet", "skip"])
    parser.add_argument("--surface", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-root", default=str(PROJECT_ROOT / "agentic_runs"))
    args = parser.parse_args()

    overrides = {key: value for key, value in vars(args).items() if key not in {"request", "run_root"} and value is not None}
    llm = OpenAICompatibleClient(load_llm_config(PROJECT_ROOT))
    saved = run(args.request, overrides, llm, StateStore(Path(args.run_root)))
    print(json.dumps(saved, indent=2, ensure_ascii=False))
    return 0 if saved.get("status") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
