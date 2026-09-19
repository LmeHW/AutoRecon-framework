from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from service.config import GatewayConfig

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime | None = None) -> str:
    return (moment or utc_now()).astimezone(UTC).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, config: GatewayConfig):
        self.config = config
        config.data_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.config.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(username) REFERENCES users(username)
                );
                CREATE TABLE IF NOT EXISTS uploads (
                    upload_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    received_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sha256 TEXT,
                    FOREIGN KEY(username) REFERENCES users(username)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    program TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    upload_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    timeout_seconds INTEGER NOT NULL,
                    pid INTEGER,
                    FOREIGN KEY(username) REFERENCES users(username)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(username, created_at);
                CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(username, created_at);
                CREATE INDEX IF NOT EXISTS idx_tokens_exp ON tokens(expires_at);
                """
            )

    def user_root(self, username: str) -> Path:
        path = self.config.users_root / username
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_dir(self, username: str, upload_id: str) -> Path:
        path = self.user_root(username) / "uploads" / upload_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def job_dir(self, username: str, job_id: str) -> Path:
        path = self.user_root(username) / "jobs" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def user_usage_bytes(self, username: str) -> int:
        root = self.user_root(username)
        total = 0
        for item in root.rglob("*"):
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        return total

    def count_users(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])

    def create_user(self, username: str, password_hash: str, salt: str, role: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO users(username, password_hash, salt, role, created_at, disabled) VALUES (?,?,?,?,?,0)",
                (username, password_hash, salt, role, iso()),
            )

    def get_user(self, username: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT username, role, created_at, disabled FROM users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_token(self, token_hash: str, username: str, hours: int) -> str:
        now = utc_now()
        expires = now + timedelta(hours=hours)
        with self.connect() as conn:
            conn.execute("DELETE FROM tokens WHERE expires_at < ?", (iso(now),))
            conn.execute(
                "INSERT INTO tokens(token_hash, username, created_at, expires_at) VALUES (?,?,?,?)",
                (token_hash, username, iso(now), iso(expires)),
            )
        return iso(expires)

    def lookup_token(self, token_hash: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT tokens.username, tokens.expires_at, users.role, users.disabled
                FROM tokens JOIN users ON users.username = tokens.username
                WHERE token_hash=?
                """,
                (token_hash,),
            ).fetchone()

    def delete_token(self, token_hash: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM tokens WHERE token_hash=?", (token_hash,))

    def create_upload(self, username: str, filename: str, size_bytes: int) -> str:
        upload_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO uploads(upload_id, username, filename, size_bytes, received_bytes, status, created_at)
                VALUES (?,?,?,?,0,'pending',?)
                """,
                (upload_id, username, filename, size_bytes, iso()),
            )
        return upload_id

    def get_upload(self, upload_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM uploads WHERE upload_id=?", (upload_id,)).fetchone()

    def update_upload(self, upload_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = list(fields.values()) + [upload_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE uploads SET {assignments} WHERE upload_id=?", values)

    def list_uploads(self, username: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM uploads WHERE username=? ORDER BY created_at DESC",
                (username,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_upload(self, upload_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM uploads WHERE upload_id=?", (upload_id,))

    def create_job(
        self,
        username: str,
        program: str,
        params: dict[str, Any],
        upload_ids: list[str],
        timeout_seconds: int,
    ) -> str:
        job_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, username, program, params_json, upload_ids_json, status,
                    progress_json, created_at, timeout_seconds
                ) VALUES (?,?,?,?,?,'queued','{}',?,?)
                """,
                (job_id, username, program, json.dumps(params), json.dumps(upload_ids), iso(), timeout_seconds),
            )
        return job_id

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()

    def list_jobs(self, username: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if username is None:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE username=? ORDER BY created_at DESC",
                    (username,),
                ).fetchall()
        return [dict(row) for row in rows]

    def active_job_count(self, username: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')"
        args: tuple[Any, ...] = ()
        if username is not None:
            sql += " AND username=?"
            args = (username,)
        with self.connect() as conn:
            row = conn.execute(sql, args).fetchone()
        return int(row["n"])

    def update_job(self, job_id: str, **fields: Any) -> None:
        converted: dict[str, Any] = {}
        for key, value in fields.items():
            if key == "progress" and isinstance(value, dict):
                converted["progress_json"] = json.dumps(value)
            elif key == "params" and isinstance(value, dict):
                converted["params_json"] = json.dumps(value)
            else:
                converted[key] = value
        assignments = ", ".join(f"{key}=?" for key in converted)
        values = list(converted.values()) + [job_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE job_id=?", values)

    def expired_job_rows(self, retention_days: int) -> list[sqlite3.Row]:
        cutoff = iso(utc_now() - timedelta(days=retention_days))
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('succeeded','failed','timeout','cancelled')
                  AND COALESCE(finished_at, created_at) < ?
                """,
                (cutoff,),
            ).fetchall()

    def delete_job(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))

    def stale_uploads(self, hours: int = 24) -> Iterable[sqlite3.Row]:
        cutoff = iso(utc_now() - timedelta(hours=hours))
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM uploads WHERE status!='complete' AND created_at < ?",
                (cutoff,),
            ).fetchall()
