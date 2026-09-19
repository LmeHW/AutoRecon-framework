from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,32}$")
PBKDF2_ROUNDS = 200_000


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not USERNAME_RE.fullmatch(name) or name in {".", ".."}:
        raise ValueError("invalid username")
    return name


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if not isinstance(password, str) or len(password) < 10 or len(password) > 200:
        raise ValueError("password must be 10-200 characters")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(digest, expected)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str, secret: bytes) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def load_or_create_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    secret = os.urandom(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(secret)
    return secret


@dataclass
class LoginLimiter:
    max_attempts: int
    window_seconds: int

    def __post_init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        bucket = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window_seconds]
        if len(bucket) >= self.max_attempts:
            self._hits[key] = bucket
            return False
        bucket.append(now)
        self._hits[key] = bucket
        return True
