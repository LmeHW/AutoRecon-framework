from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path


SECRET_KEYS = {"AUTORECON_LLM_API_KEY", "OPENAI_API_KEY", "API_KEY"}


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a simple dotenv file. Environment variables always take precedence."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    max_retries: int
    temperature: float
    max_output_tokens: int
    use_for_request_parsing: bool
    use_for_planning: bool
    use_for_result_analysis: bool
    use_for_error_analysis: bool
    use_for_reporting: bool
    fallback_to_rules: bool
    save_request: bool
    save_response: bool
    ants_dir: str
    roi_warp_env: str

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key and self.base_url and self.model)

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("api_key", None)
        data["api_key_configured"] = bool(self.api_key)
        data["available"] = self.available
        return data


def load_llm_config(project_root: Path) -> LLMConfig:
    configured_file = os.environ.get("AUTORECON_CONFIG_FILE", "").strip()
    config_path = Path(configured_file).expanduser() if configured_file else project_root / ".env"
    if not config_path.is_absolute():
        config_path = project_root / config_path
    file_values = parse_env_file(config_path)
    secret_file = os.environ.get("AUTORECON_SECRET_FILE", "").strip()
    secret_path = Path(secret_file).expanduser() if secret_file else project_root / ".secrets/glm.env"
    if not secret_path.is_absolute():
        secret_path = project_root / secret_path
    secret_values = parse_env_file(secret_path)

    def get(name: str, default: str = "") -> str:
        # A selected AUTORECON_CONFIG_FILE must beat ambient/.env values that
        # serve() may have copied into os.environ. Secrets stay on the
        # environment / secret-file path below.
        if configured_file:
            file_value = str(file_values.get(name, "")).strip()
            if file_value:
                return file_value
        return os.environ.get(name, file_values.get(name, default)).strip()

    # Only recognized key names are read from the private secret file. Public
    # status and serialized configs never expose the value.
    api_key = (
        os.environ.get("AUTORECON_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or secret_values.get("AUTORECON_LLM_API_KEY")
        or secret_values.get("OPENAI_API_KEY")
    )
    base_url = get("AUTORECON_LLM_BASE_URL", get("OPENAI_BASE_URL", "https://airouter.aibotplatform.com/v1"))
    return LLMConfig(
        enabled=_bool(get("AUTORECON_LLM_ENABLED", "false")),
        provider=get("AUTORECON_LLM_PROVIDER", "auto"),
        base_url=base_url.rstrip("/"),
        model=get("AUTORECON_LLM_MODEL", "anthropic/claude-sonnet-4-6"),
        api_key=api_key,
        timeout_seconds=float(get("AUTORECON_LLM_TIMEOUT_SECONDS", "300")),
        max_retries=int(get("AUTORECON_LLM_MAX_RETRIES", "2")),
        temperature=float(get("AUTORECON_LLM_TEMPERATURE", "0")),
        max_output_tokens=int(get("AUTORECON_LLM_MAX_OUTPUT_TOKENS", "4096")),
        use_for_request_parsing=_bool(get("AUTORECON_LLM_USE_FOR_REQUEST_PARSING", "true"), True),
        use_for_planning=_bool(get("AUTORECON_LLM_USE_FOR_PLANNING", "true"), True),
        use_for_result_analysis=_bool(get("AUTORECON_LLM_USE_FOR_RESULT_ANALYSIS", "true"), True),
        use_for_error_analysis=_bool(get("AUTORECON_LLM_USE_FOR_ERROR_ANALYSIS", "true"), True),
        use_for_reporting=_bool(get("AUTORECON_LLM_USE_FOR_REPORTING", "true"), True),
        fallback_to_rules=_bool(get("AUTORECON_LLM_FALLBACK_TO_RULES", "true"), True),
        save_request=_bool(get("AUTORECON_LLM_SAVE_REQUEST", "false")),
        save_response=_bool(get("AUTORECON_LLM_SAVE_RESPONSE", "true"), True),
        ants_dir=get("AUTORECON_ANTS_DIR", "/home/huangwei/.conda/envs/ants/bin"),
        roi_warp_env=get("AUTORECON_ROI_WARP_ENV", "/home/zhaojunyang/.conda/envs/zjy"),
    )


def load_api_key(project_root: Path) -> str | None:
    return load_llm_config(project_root).api_key


def redacted_config_status(project_root: Path) -> dict[str, object]:
    config = load_llm_config(project_root)
    configured_file = os.environ.get("AUTORECON_CONFIG_FILE", "").strip()
    config_path = Path(configured_file).expanduser() if configured_file else project_root / ".env"
    if not config_path.is_absolute():
        config_path = project_root / config_path
    return {"env_file_exists": config_path.exists(), "config_file": str(config_path), **config.public_dict()}
