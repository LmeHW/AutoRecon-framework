from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import RunState, utc_now


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = PROJECT_ROOT / "agentic_runs"


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._acceptance_cache: dict[str, dict] | None = None

    def new_run_id(self) -> str:
        return utc_now().replace(":", "").replace("+", "Z") + "_" + uuid4().hex[:8]

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def save(self, state: RunState | dict) -> dict:
        data = state.to_dict() if isinstance(state, RunState) else dict(state)
        data["updated_at"] = utc_now()
        run_dir = self.run_dir(data["run_id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "agentic_state.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if isinstance(data.get("request"), dict):
            (run_dir / "intent_spec.json").write_text(
                json.dumps(data["request"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        if isinstance(data.get("plan"), dict):
            (run_dir / "task_plan.json").write_text(
                json.dumps(data["plan"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        medical_report = (data.get("report_json") or {}).get("medical_report")
        if isinstance(medical_report, dict):
            (run_dir / "medical_evidence.json").write_text(
                json.dumps(medical_report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        evidence_bank = (data.get("report_json") or {}).get("evidence_bank")
        if isinstance(evidence_bank, dict):
            (run_dir / "evidence_bank.json").write_text(
                json.dumps(evidence_bank, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        if data.get("report_markdown"):
            (run_dir / "report.md").write_text(str(data["report_markdown"]), encoding="utf-8")
        return data

    def load(self, run_id: str) -> dict:
        local = self.run_dir(run_id) / "agentic_state.json"
        if local.is_file():
            return json.loads(local.read_text(encoding="utf-8"))
        curated = self._acceptance_states().get(run_id)
        if curated is not None:
            return curated
        raise FileNotFoundError(f"Run not found: {run_id}")

    def latest(self) -> dict | None:
        paths = sorted(self.root.glob("*/agentic_state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not paths:
            return None
        return json.loads(paths[0].read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict]:
        runs: list[dict] = []
        seen_subjects: set[str] = set()
        for data in self._acceptance_states().values():
            subject = self._subject(data)
            if not subject:
                continue
            seen_subjects.add(subject.casefold())
            runs.append(self._run_summary(data, subject, source="validated"))
        for path in sorted(self.root.glob("*/agentic_state.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            subject = self._subject(data)
            key = self._subject_key(subject)
            if not subject or not self._visible_local_result(data) or key in seen_subjects:
                continue
            seen_subjects.add(key)
            runs.append(self._run_summary(data, subject, source="clinic"))
        return runs

    @staticmethod
    def _subject(data: dict) -> str:
        catalog_subject = str(data.get("catalog_subject") or "").strip()
        if catalog_subject:
            return catalog_subject
        request = data.get("request") or {}
        subject = Path(str(request.get("subject_dir") or "")).name
        if not subject:
            technical = ((data.get("report_json") or {}).get("technical_analysis") or {}).get("case_info") or {}
            subject = str(technical.get("subject") or "").strip()
        if not subject:
            existing = request.get("existing_run_dir")
            if existing:
                existing_path = Path(str(existing))
                subject = existing_path.name.replace("_run01", "")
                if subject.lower() in {"run", "run01", "raw", "raw_run01"}:
                    subject = existing_path.parent.name
            else:
                subject = ""
        if not subject:
            subject = str(data.get("run_id") or "").strip()
        subject = subject.strip()
        if subject.lower() in {"", ".", "unknown", "unnamed", "未命名病例"}:
            return ""
        return subject

    @staticmethod
    def _subject_key(subject: str) -> str:
        return subject.strip().casefold().removesuffix("_raw").removesuffix("-raw")

    @staticmethod
    def _visible_local_result(data: dict) -> bool:
        status = str(data.get("status") or "")
        if status in {"completed", "failed", "imported"}:
            return True
        if status not in {"running", "planned"}:
            return False
        try:
            updated = datetime.fromisoformat(str(data.get("updated_at") or "").replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - updated).total_seconds() <= 24 * 3600
        except ValueError:
            return False

    @staticmethod
    def _run_summary(data: dict, subject: str, source: str) -> dict:
        request = data.get("request") or {}
        plan = data.get("plan") or {}
        return {
            "run_id": data["run_id"],
            "case_id": data.get("case_id") or Path(str(request.get("subject_dir") or "")).name or None,
            "case_label": request.get("case_label") or data.get("case_label"),
            "status": data.get("status") or "completed",
            "task_type": request.get("task_type"),
            "goal": plan.get("goal") or request.get("intent") or request.get("raw_text") or "影像分析结果",
            "subject": subject,
            "has_report": bool(data.get("report_markdown")),
            "updated_at": data.get("updated_at"),
            "source": source,
        }

    def _acceptance_states(self) -> dict[str, dict]:
        if self._acceptance_cache is not None:
            return self._acceptance_cache
        if self.root.resolve() != DEFAULT_RUN_ROOT.resolve():
            self._acceptance_cache = {}
            return self._acceptance_cache
        validation_root = PROJECT_ROOT / "validation_runs"
        batches = sorted(
            (path for path in validation_root.glob("case_acceptance_*") if (path / "cases.json").is_file()),
            reverse=True,
        )
        for batch in batches:
            try:
                manifest = json.loads((batch / "cases.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            specs = manifest.get("cases") or []
            if len(specs) != 7 or not all((batch / "cases" / str(item.get("case_id")) / "state.json").is_file() for item in specs):
                continue
            states: dict[str, dict] = {}
            for spec in specs:
                case_id = str(spec["case_id"])
                case_dir = batch / "cases" / case_id
                try:
                    data = json.loads((case_dir / "state.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                run_id = f"validated_{batch.name.removeprefix('case_acceptance_')}_{case_id}"
                data["run_id"] = run_id
                data["case_id"] = case_id
                data["catalog_subject"] = str(spec.get("subject") or "")
                data.setdefault("request", {})["subject_dir"] = spec.get("subject_dir")
                report = case_dir / "report.md"
                if report.is_file():
                    data["report_markdown"] = report.read_text(encoding="utf-8")
                pipeline_dashboard = case_dir / "pipeline" / "dashboard" / "run_state.json"
                if pipeline_dashboard.is_file():
                    try:
                        dashboard_data = json.loads(pipeline_dashboard.read_text(encoding="utf-8"))
                        dashboard_status = (dashboard_data.get("run") or {}).get("status")
                        if dashboard_status == "completed":
                            data["status"] = "completed"
                        data["dashboard"] = {
                            "dashboard_dir": str(pipeline_dashboard.parent),
                            "dashboard_file": str(pipeline_dashboard.parent / "index.html"),
                            "dashboard_state": str(pipeline_dashboard),
                            "url": "",
                        }
                        data["updated_at"] = (dashboard_data.get("run") or {}).get("updated_at") or data.get("updated_at")
                    except (OSError, ValueError):
                        pass
                states[run_id] = data
            if len(states) == 7:
                self._acceptance_cache = states
                return self._acceptance_cache
        self._acceptance_cache = {}
        return self._acceptance_cache
