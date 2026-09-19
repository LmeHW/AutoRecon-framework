from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TYPE_MAP = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool, "null": type(None)}


def validate_schema(instance: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _validate(instance, schema, "$", errors)
    return errors


def _validate(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    types = schema.get("type")
    if types:
        names = [types] if isinstance(types, str) else types
        if not any(isinstance(value, TYPE_MAP[name]) and not (name in {"number", "integer"} and isinstance(value, bool)) for name in names):
            errors.append(f"{path}: expected {'|'.join(names)}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in enum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties: _validate(child, properties[key], f"{path}.{key}", errors)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value): _validate(child, schema["items"], f"{path}[{index}]", errors)


def validate_agentic_objects(project_root: Path, request: dict, plan: dict) -> list[str]:
    root = project_root / "agentic" / "schemas"
    return validate_schema(request, root / "user_request.schema.json") + validate_schema(plan, root / "task_plan.schema.json")
