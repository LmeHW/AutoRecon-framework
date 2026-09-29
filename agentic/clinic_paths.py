from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_ROOT = Path(
    "/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2/nii"
)
DEFAULT_WORK_ROOT = PROJECT_ROOT / "agentic_runs" / "clinic"
DEFAULT_ATLAS_DIR = PROJECT_ROOT / "pipeline" / "data" / "FBA_Chinese_Atlas" / "img"
DEFAULT_UPLOAD_ROOT = PROJECT_ROOT / "agentic_runs" / "clinic_uploads"
_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar("clinic_scope", default=None)
STEP_ARTIFACTS = (
    ("extraction", "staging"),
    ("reconstruction", "outputs/recon"),
    ("registration", "outputs/registered_input"),
    ("tissue", "outputs/Tissue"),
    ("roi", "outputs/ROI"),
    ("surface", "outputs/surface_subjects"),
)
STEP_PREREQS = {
    "reconstruction": ["extraction"],
    "registration": ["reconstruction"],
    "tissue": ["registration"],
    "roi": ["registration"],
    "surface": ["tissue", "roi"],
}


@contextmanager
def user_clinic_scope(uploads: Path, work: Path) -> Iterator[None]:
    uploads.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    token = _SCOPE.set({"uploads": uploads.resolve(), "work": work.resolve()})
    try:
        yield
    finally:
        _SCOPE.reset(token)


CASE_ID_RE = re.compile(r"^(?:Upload_\d{8}_\d{6}_[0-9a-f]{8}|[A-Za-z][A-Za-z0-9_-]{0,47})$")


def sanitize_case_label(raw: object) -> str:
    text = " ".join(str(raw or "").split())
    return text[:40]


def is_case_id(value: str) -> bool:
    return bool(CASE_ID_RE.fullmatch(value))


def slug_case_id(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(label or "").strip())
    slug = re.sub(r"_+", "_", slug).strip("_-")
    if slug and slug[0].isdigit():
        slug = "Case_" + slug
    return slug[:48]


def allocate_case_id(label: str, existing: set[str]) -> str:
    taken = {name.casefold() for name in existing}
    slug = slug_case_id(label)
    if is_case_id(slug) and slug.casefold() not in taken:
        return slug
    if is_case_id(slug):
        for index in range(2, 50):
            candidate = f"{slug[:44]}_{index}"
            if is_case_id(candidate) and candidate.casefold() not in taken:
                return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_")
    return "Upload_" + stamp + uuid.uuid4().hex[:8]


def _manifest_label(directory: Path) -> str:
    manifest = directory / ".upload.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return sanitize_case_label(data.get("label") or "")


def cases_root() -> Path:
    raw = os.environ.get("AUTORECON_CASES_ROOT", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_CASES_ROOT


def work_root() -> Path:
    scoped = _SCOPE.get()
    if scoped:
        return Path(scoped["work"])
    raw = os.environ.get("AUTORECON_CLINIC_WORK_ROOT", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_WORK_ROOT


def atlas_dir() -> Path:
    raw = os.environ.get("AUTORECON_ATLAS_DIR", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_ATLAS_DIR


def upload_root() -> Path:
    scoped = _SCOPE.get()
    if scoped:
        return Path(scoped["uploads"])
    raw = os.environ.get("AUTORECON_CLINIC_UPLOAD_ROOT", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_UPLOAD_ROOT


def discard_upload_dir(directory: Path) -> None:
    path = Path(directory)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def purge_incomplete_uploads(root: Path | None = None, *, keep: str | None = None) -> list[str]:
    base = Path(root) if root is not None else upload_root()
    removed: list[str] = []
    if not base.is_dir():
        return removed
    for child in base.iterdir():
        if not child.is_dir() or child.name == keep:
            continue
        manifest = child / ".upload.json"
        status = ""
        if manifest.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                status = str(payload.get("status") or "")
        if status == "complete":
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(child.name)
    return removed


def _case_rows(base: Path, source: str) -> list[dict[str, str]]:
    if not base.is_dir():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(base.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if source == "upload":
            manifest = path / ".upload.json"
            try:
                if not manifest.is_file() or '"status": "complete"' not in manifest.read_text(encoding="utf-8"):
                    continue
            except OSError:
                continue
        stacks = sorted(item for item in path.glob("*.nii.gz") if "crop" not in item.name.lower())
        if not stacks:
            continue
        items.append({
            "id": path.name,
            "label": _manifest_label(path) or path.name,
            "subject_dir": str(path),
            "stack_count": str(len(stacks)),
            "source": source,
        })
    return items


def list_cases(root: Path | None = None) -> list[dict[str, str]]:
    if root is not None:
        return _case_rows(root, "library")
    uploaded = _case_rows(upload_root(), "upload")
    if _SCOPE.get() is not None:
        return uploaded
    library = _case_rows(cases_root(), "library")
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for item in uploaded + library:
        if item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    return items


def resolve_case_dir(case_id: str) -> Path:
    uploaded = upload_root() / case_id
    if uploaded.is_dir() or _SCOPE.get() is not None:
        return uploaded
    return cases_root() / case_id


def choose_atlas(ga: float | None) -> tuple[str | None, int | None, str | None]:
    if ga is None:
        return None, None, None
    week = int(round(float(ga)))
    atlases: dict[int, Path] = {}
    for path in atlas_dir().glob("*w.nii.gz"):
        match = re.fullmatch(r"(\d+)w\.nii.gz", path.name)
        if match:
            atlases[int(match.group(1))] = path
    if not atlases:
        return None, None, None
    chosen = min(atlases, key=lambda value: (abs(value - week), value))
    rule = "exact" if chosen == week else f"nearest_from_{week}w"
    return str(atlases[chosen]), chosen, rule


def choose_default_atlas() -> tuple[str | None, int | None, str | None]:
    """Pick the upper median week from the installed atlas set."""
    atlases: list[tuple[int, Path]] = []
    for path in atlas_dir().glob("*w.nii.gz"):
        match = re.fullmatch(r"(\d+)w\.nii.gz", path.name)
        if match:
            atlases.append((int(match.group(1)), path))
    if not atlases:
        return None, None, None
    atlases.sort(key=lambda item: item[0])
    week, path = atlases[len(atlases) // 2]
    return str(path), week, "default_middle"


def _subject_name(run_dir: Path, fallback: str = "") -> str:
    state = run_dir / "dashboard" / "run_state.json"
    if state.is_file():
        try:
            import json
            data = json.loads(state.read_text(encoding="utf-8"))
            name = (data.get("run") or {}).get("subject_name")
            if name:
                return str(name)
        except (OSError, ValueError):
            pass
    return fallback or run_dir.name


def inventory_run(run_dir: Path, subject: str = "") -> dict[str, Any]:
    root = Path(run_dir).expanduser()
    name = _subject_name(root, subject)
    completed: list[str] = []
    if (root / "staging" / name / "seg").is_dir() and any((root / "staging" / name / "seg").glob("*.nii.gz")):
        completed.append("extraction")
    if (root / "outputs" / "recon" / f"{name}.nii.gz").is_file():
        completed.append("reconstruction")
    registered = root / "outputs" / "registered_input" / f"{name}.nii.gz"
    summary = root / "outputs" / "registration" / "summary.csv"
    if registered.is_file() or summary.is_file():
        completed.append("registration")
    if (root / "outputs" / "Tissue" / f"{name}.nii.gz").is_file():
        completed.append("tissue")
    if (root / "outputs" / "ROI" / f"{name}.nii.gz").is_file():
        completed.append("roi")
    surf = root / "outputs" / "surface_subjects" / name / "surf"
    if surf.is_dir() and len(list(surf.glob("*"))) >= 6:
        completed.append("surface")
    usable = root.is_dir() and (root / "dashboard" / "run_state.json").is_file()
    return {
        "run_dir": str(root),
        "subject": name,
        "usable": usable,
        "completed_steps": completed,
    }


def find_latest_run(case_id: str, root: Path | None = None) -> Path | None:
    base = (root or work_root()) / case_id
    if not base.is_dir():
        return None
    candidates = [path for path in base.iterdir() if path.is_dir() and (path / "dashboard" / "run_state.json").is_file()]
    if not candidates:
        direct = inventory_run(base, case_id)
        return base if direct["usable"] else None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def missing_for_scope(wanted: list[str], completed: list[str]) -> list[str]:
    have = set(completed)
    missing: list[str] = []
    for step in wanted:
        for prereq in STEP_PREREQS.get(step, []):
            if prereq not in have and prereq not in wanted:
                artifact = f"{prereq}_artifact"
                if artifact not in missing:
                    missing.append(artifact)
            if prereq in wanted and prereq not in have and step not in {"extraction"}:
                continue
        if step in {"registration", "tissue", "roi", "surface"} and "reconstruction" not in have and "reconstruction" not in wanted:
            if "reconstruction_artifact" not in missing:
                missing.append("reconstruction_artifact")
        if step in {"tissue", "roi", "surface"} and "registration" not in have and "registration" not in wanted:
            if "registration_artifact" not in missing:
                missing.append("registration_artifact")
    return missing


def reused_steps(wanted: list[str], completed: list[str]) -> list[str]:
    have = set(completed)
    selected = set(wanted)
    changed = True
    while changed:
        changed = False
        for step in list(selected):
            for prereq in STEP_PREREQS.get(step, []):
                if prereq not in selected:
                    selected.add(prereq)
                    changed = True
    return [step for step in ("extraction", "reconstruction", "registration", "tissue", "roi", "surface") if step in selected and step in have]


CLINICAL_STATUSES = ("none", "present", "unknown")
CLINICAL_STATUS_ALIASES = {
    "none": "none",
    "normal": "none",
    "未见异常": "none",
    "无": "none",
    "没有": "none",
    "present": "present",
    "abnormal": "present",
    "有": "present",
    "有病": "present",
    "有异常": "present",
    "存在异常": "present",
    "unknown": "unknown",
    "不确定": "unknown",
    "不详": "unknown",
}
CLINICAL_STATUS_LABEL_ZH = {"none": "未见异常", "present": "存在异常", "unknown": "不确定"}


def parse_gestational_age(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_GA_IN_TEXT = re.compile(
    r"(?:GA|孕周|胎龄|gestational age)\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)|(\d{1,2}(?:\.\d+)?)\s*(?:周|(?:weeks?|wk|w)\b)",
    re.I,
)


def parse_ga_from_text(text: str) -> float | None:
    match = _GA_IN_TEXT.search(text or "")
    if not match:
        return None
    value = parse_gestational_age(match.group(1) or match.group(2))
    if value is None or not 15 <= value <= 45:
        return None
    return value


def normalize_clinical_status(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return CLINICAL_STATUS_ALIASES.get(text) or CLINICAL_STATUS_ALIASES.get(text.lower())


def clinic_intake_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ga = parse_gestational_age(payload.get("gestational_age"))
    if ga is None:
        errors.append("请填写胎龄（周）。")
    elif not 15 <= ga <= 45:
        errors.append("胎龄须在 15–45 周。")
    if not str(payload.get("fetal_description") or "").strip():
        errors.append("请填写胎儿描述。")
    status = normalize_clinical_status(payload.get("clinical_status"))
    if status not in CLINICAL_STATUSES:
        errors.append("请选择临床所见。")
    if status == "present" and not str(payload.get("clinical_condition") or "").strip():
        errors.append("请填写疾病名称。")
    return errors


def normalized_clinical_intake(payload: dict[str, Any]) -> dict[str, Any]:
    errors = clinic_intake_errors(payload)
    if errors:
        raise ValueError(errors[0])
    status = normalize_clinical_status(payload.get("clinical_status"))
    condition = str(payload.get("clinical_condition") or "").strip()
    if status == "none":
        condition = ""
    return {
        "gestational_age": parse_gestational_age(payload.get("gestational_age")),
        "fetal_description": str(payload.get("fetal_description") or "").strip(),
        "clinical_status": status,
        "clinical_condition": condition or None,
        "clinical_notes": str(payload.get("clinical_notes") or "").strip() or None,
    }


def apply_clinic_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    case_id = str(data.get("case_id") or "").strip()
    explicit = {str(item) for item in data.get("explicit_fields") or []}
    if case_id and "subject_dir" not in explicit:
        data["subject_dir"] = str(resolve_case_dir(case_id))
        explicit.add("subject_dir")
    if case_id:
        label = _manifest_label(resolve_case_dir(case_id)) or sanitize_case_label(data.get("case_label")) or case_id
        data["case_label"] = label
        explicit.add("case_label")
    subject = Path(str(data.get("subject_dir") or "")).name
    ga_value = parse_gestational_age(data.get("gestational_age"))
    if ga_value is None:
        ga_value = parse_ga_from_text(str(data.get("raw_text") or ""))
    if ga_value is not None:
        data["gestational_age"] = ga_value
        explicit.add("gestational_age")
    description = str(data.get("fetal_description") or "").strip()
    if description:
        data["fetal_description"] = description
        explicit.add("fetal_description")
    status = normalize_clinical_status(data.get("clinical_status"))
    if status:
        data["clinical_status"] = status
        explicit.add("clinical_status")
    condition = str(data.get("clinical_condition") or "").strip()
    if status == "none":
        condition = ""
    data["clinical_condition"] = condition
    if condition:
        explicit.add("clinical_condition")
    notes = str(data.get("clinical_notes") or "").strip()
    if notes:
        data["clinical_notes"] = notes
        explicit.add("clinical_notes")
    if "reconstruction_tool" not in explicit:
        data["reconstruction_tool"] = "frost"
        explicit.add("reconstruction_tool")
    if "atlas" not in explicit:
        atlas, week, rule = choose_atlas(ga_value) if ga_value is not None else choose_default_atlas()
        if atlas:
            data["atlas"] = atlas
            data["atlas_week"] = week
            data["atlas_rule"] = rule
            explicit.update({"atlas", "atlas_week", "atlas_rule"})
    if "roi_mode" not in explicit:
        data["roi_mode"] = "warp" if (ga_value is not None or data.get("atlas_week") is not None) else "skip"
        explicit.add("roi_mode")
    if "surface" not in explicit:
        data["surface"] = "on"
        explicit.add("surface")
    if "report_language" not in explicit:
        data["report_language"] = "zh"
        explicit.add("report_language")
    text = str(data.get("raw_text") or "")
    fresh = bool(re.search(r"从原始|重新开始|完整重跑|from scratch|rerun", text, re.I))
    latest = find_latest_run(case_id or subject) if (case_id or subject) else None
    import_only = bool(re.search(r"导入|已有(?:结果|run)|只看|只展示|import existing", text, re.I)) and not fresh
    if latest and not fresh and "work_root" not in explicit:
        data["existing_run_dir"] = str(latest)
        data["work_root"] = str(latest)
        data["resume"] = True
        explicit.update({"existing_run_dir", "work_root", "resume"})
        if import_only:
            data["execution_mode"] = "import_existing"
        else:
            data["execution_mode"] = "continue_from_run"
        explicit.add("execution_mode")
    elif "work_root" not in explicit and (case_id or subject):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        data["work_root"] = str(work_root() / (case_id or subject) / stamp)
        explicit.add("work_root")
        if "execution_mode" not in explicit and not import_only:
            data["execution_mode"] = "run_pipeline"
            explicit.add("execution_mode")
    data["explicit_fields"] = sorted(explicit)
    data["clinic"] = True
    return data
