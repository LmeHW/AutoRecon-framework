from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_COMPLETE_LOCK = threading.Lock()

from .env_config import LLMConfig


class LLMError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, provider: str = "", request_id: str = ""):
        super().__init__(message)
        self.status = status
        self.provider = provider
        self.request_id = request_id

    def public_dict(self) -> dict[str, object]:
        return {"message": str(self), "status": self.status, "provider": self.provider, "request_id": self.request_id}


class OpenAICompatibleClient:
    """OpenAI-compatible and Anthropic-native client with protocol auto-detection."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._detected_provider: str | None = None

    @property
    def available(self) -> bool:
        return self.config.available

    @property
    def active_provider(self) -> str:
        return self._detected_provider or self.config.provider

    def complete(self, system: str, user: str, *, json_output: bool = False) -> str:
        if not self.available:
            raise LLMError("LLM is disabled or AUTORECON_LLM_API_KEY is not exported.")
        configured = self.config.provider.lower()
        providers = [configured] if configured in {"openai_compatible", "anthropic"} else ["openai_compatible", "anthropic"]
        if self._detected_provider:
            providers = [self._detected_provider]
        first_error: LLMError | None = None
        with _COMPLETE_LOCK:
            for provider in providers:
                try:
                    text = self._complete_provider(provider, system, user, json_output=json_output)
                    self._detected_provider = provider
                    return text
                except LLMError as exc:
                    first_error = first_error or exc
                    if configured != "auto" or exc.status not in {404, 405}:
                        raise
        raise first_error or LLMError("No configured LLM protocol succeeded.")

    def _complete_provider(self, provider: str, system: str, user: str, *, json_output: bool) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1"):
            root = base[:-3]
        else:
            root = base
        if provider == "anthropic":
            url = root + "/v1/messages"
            payload: dict[str, Any] = {
                "model": self.config.model, "system": system,
                "max_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
                "messages": [{"role": "user", "content": user}],
            }
            headers = {
                "x-api-key": str(self.config.api_key), "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        else:
            # OpenAI-compatible providers expose chat/completions below their
            # configured API version prefix (for example /v1 or GLM's /v4).
            url = base + "/chat/completions"
            payload = {
                "model": self.config.model, "temperature": self.config.temperature,
                "max_tokens": self.config.max_output_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            if json_output:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}

        body = json.dumps(payload, ensure_ascii=False).encode()
        last_error: LLMError | None = None
        for attempt in range(self.config.max_retries + 1):
            data: dict[str, Any] | None = None
            try:
                # urllib.Request mutates headers and consumes data; rebuild a fresh POST each try.
                request = Request(url, data=bytes(body), headers=dict(headers), method="POST")
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    request_id = response.headers.get("request-id") or response.headers.get("x-request-id") or ""
                    data = json.loads(response.read().decode("utf-8"))
                if provider == "anthropic":
                    blocks = data.get("content") or []
                    text = "".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
                    if not text.strip():
                        raise ValueError("empty Anthropic content")
                    return text
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices:
                    err = data.get("error") if isinstance(data, dict) else None
                    raise ValueError(f"empty choices: {err or list((data or {}).keys())[:8]}")
                message = (choices[0] or {}).get("message") or {}
                content = message.get("content")
                if content is None or str(content).strip() == "":
                    raise ValueError("empty message content")
                return str(content)
            except HTTPError as exc:
                request_id = exc.headers.get("request-id") or exc.headers.get("x-request-id") or ""
                last_error = LLMError(f"LLM HTTP {exc.code}", status=exc.code, provider=provider, request_id=request_id)
                if exc.code in {404, 405}:
                    break
            except (URLError, TimeoutError, KeyError, ValueError) as exc:
                snippet = ""
                if isinstance(data, dict):
                    snippet = json.dumps(
                        {key: data.get(key) for key in list(data)[:6]},
                        ensure_ascii=False,
                    )[:300]
                last_error = LLMError(
                    f"LLM request failed: {type(exc).__name__}: {exc}" + (f" ({snippet})" if snippet else ""),
                    provider=provider,
                )
            if attempt < self.config.max_retries:
                time.sleep(min(2 ** attempt, 8))
        raise last_error or LLMError("LLM request failed", provider=provider)

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        text = self.complete(system, user, json_output=True).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model did not return valid JSON: {exc.msg}", provider=self.active_provider) from exc
        if not isinstance(value, dict):
            raise LLMError("Model JSON response must be an object.", provider=self.active_provider)
        return value


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
