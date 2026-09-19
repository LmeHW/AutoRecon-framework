from __future__ import annotations

from typing import Any

from service.config import ALLOWED_STEPS

PROGRAMS: dict[str, dict[str, Any]] = {
    "input_check": {
        "description": "检查已上传的受试者文件是否符合 BTFE NIfTI 约定，不启动 GPU 流程。",
        "timeout_seconds": 60,
        "params": {},
    },
    "run_pipeline": {
        "description": "在服务器分配的隔离目录中运行已注册的单病例确定性流水线。",
        "timeout_seconds": 12 * 60 * 60,
        "params": {
            "reconstruction_tool": {
                "enum": ["frost", "nesvor", "autosvrtk", "niftymic"],
                "default": "frost",
            },
            "roi_mode": {
                "enum": ["warp", "segresnet", "skip"],
                "default": "warp",
            },
            "surface": {
                "enum": ["auto", "on", "off"],
                "default": "auto",
            },
            "ga": {
                "type": "float",
                "min": 20.0,
                "max": 40.0,
                "default": 31.0,
            },
            "steps": {
                "type": "step_list",
                "allowed": list(ALLOWED_STEPS),
                "default": list(ALLOWED_STEPS),
            },
            "resume": {
                "type": "bool",
                "default": False,
            },
        },
    },
}


def public_programs() -> list[dict[str, Any]]:
    items = []
    for name, spec in PROGRAMS.items():
        items.append(
            {
                "name": name,
                "description": spec["description"],
                "timeout_seconds": spec["timeout_seconds"],
                "params": {
                    key: {k: v for k, v in rule.items() if k != "default"} | {"default": rule.get("default")}
                    for key, rule in spec["params"].items()
                },
            }
        )
    return items


def validate_program_params(program: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if program not in PROGRAMS:
        raise ValueError("unknown program")
    payload = raw or {}
    if not isinstance(payload, dict):
        raise ValueError("params must be an object")
    spec = PROGRAMS[program]
    unknown = sorted(set(payload) - set(spec["params"]))
    if unknown:
        raise ValueError(f"unsupported parameters: {', '.join(unknown)}")
    validated: dict[str, Any] = {}
    for name, rule in spec["params"].items():
        if name in payload:
            validated[name] = _coerce(name, payload[name], rule)
        elif "default" in rule:
            validated[name] = rule["default"]
        else:
            raise ValueError(f"missing parameter: {name}")
    return validated


def _coerce(name: str, value: Any, rule: dict[str, Any]) -> Any:
    if "enum" in rule:
        text = str(value).strip()
        if text not in rule["enum"]:
            raise ValueError(f"invalid {name}")
        return text
    kind = rule.get("type")
    if kind == "float":
        number = float(value)
        if number < float(rule["min"]) or number > float(rule["max"]):
            raise ValueError(f"{name} out of range")
        return number
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"invalid {name}")
    if kind == "step_list":
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, list):
            items = [str(item).strip() for item in value]
        else:
            raise ValueError(f"invalid {name}")
        allowed = set(rule["allowed"])
        if not items or any(item not in allowed for item in items):
            raise ValueError(f"invalid {name}")
        # Preserve canonical order, drop duplicates.
        ordered = [step for step in rule["allowed"] if step in set(items)]
        return ordered
    raise ValueError(f"invalid {name}")
