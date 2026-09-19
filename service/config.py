from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentic.env_config import parse_env_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PROJECT_ROOT / ".runtime" / "gateway"
DEFAULT_ATLAS_DIR = PROJECT_ROOT / "pipeline" / "data" / "FBA_Chinese_Atlas" / "img"
PIPELINE_SCRIPT = PROJECT_ROOT / "pipeline" / "run_single_case_pipeline.sh"

ALLOWED_SUFFIXES = (".nii.gz", ".nii", ".zip")
ALLOWED_STEPS = (
    "extraction",
    "reconstruction",
    "registration",
    "tissue",
    "roi",
    "surface",
)


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    return int(value)


def _path(value: str | None, default: Path) -> Path:
    if value is None or not str(value).strip():
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class GatewayConfig:
    host: str
    port: int
    data_root: Path
    project_root: Path
    atlas_dir: Path
    max_upload_bytes: int
    max_user_bytes: int
    max_chunk_bytes: int
    max_global_jobs: int
    max_user_jobs: int
    session_hours: int
    retention_days: int
    login_max_attempts: int
    login_window_seconds: int
    bootstrap_username: str
    bootstrap_password: str | None

    @property
    def db_path(self) -> Path:
        return self.data_root / "gateway.sqlite"

    @property
    def secret_path(self) -> Path:
        return self.data_root / "secret.key"

    @property
    def log_path(self) -> Path:
        return self.data_root / "gateway.log"

    @property
    def users_root(self) -> Path:
        return self.data_root / "users"


def load_gateway_config(project_root: Path | None = None) -> GatewayConfig:
    root = project_root or PROJECT_ROOT
    configured = os.environ.get("AUTORECON_GATEWAY_CONFIG", "").strip()
    file_values: dict[str, str] = {}
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = root / path
        file_values = parse_env_file(path)
    elif (root / "config" / "service.env").is_file():
        file_values = parse_env_file(root / "config" / "service.env")

    def get(name: str, default: str | None = None) -> str | None:
        if name in os.environ and os.environ[name] != "":
            return os.environ[name]
        return file_values.get(name, default)

    data_root = _path(get("AUTORECON_GATEWAY_DATA"), DEFAULT_DATA_ROOT)
    return GatewayConfig(
        host=get("AUTORECON_GATEWAY_HOST", "127.0.0.1") or "127.0.0.1",
        port=_int(get("AUTORECON_GATEWAY_PORT"), 19001),
        data_root=data_root,
        project_root=root,
        atlas_dir=_path(get("AUTORECON_GATEWAY_ATLAS_DIR"), DEFAULT_ATLAS_DIR),
        max_upload_bytes=_int(get("AUTORECON_GATEWAY_MAX_UPLOAD_BYTES"), 2 * 1024 ** 3),
        max_user_bytes=_int(get("AUTORECON_GATEWAY_MAX_USER_BYTES"), 20 * 1024 ** 3),
        max_chunk_bytes=_int(get("AUTORECON_GATEWAY_MAX_CHUNK_BYTES"), 8 * 1024 ** 2),
        max_global_jobs=_int(get("AUTORECON_GATEWAY_MAX_GLOBAL_JOBS"), 1),
        max_user_jobs=_int(get("AUTORECON_GATEWAY_MAX_USER_JOBS"), 1),
        session_hours=_int(get("AUTORECON_GATEWAY_SESSION_HOURS"), 12),
        retention_days=_int(get("AUTORECON_GATEWAY_RETENTION_DAYS"), 7),
        login_max_attempts=_int(get("AUTORECON_GATEWAY_LOGIN_MAX_ATTEMPTS"), 8),
        login_window_seconds=_int(get("AUTORECON_GATEWAY_LOGIN_WINDOW_SECONDS"), 600),
        bootstrap_username=get("AUTORECON_GATEWAY_BOOTSTRAP_USER", "admin") or "admin",
        bootstrap_password=get("AUTORECON_GATEWAY_BOOTSTRAP_PASSWORD"),
    )
