from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from agentic.clinic_paths import user_clinic_scope
from agentic.dashboard_server import DEFAULT_RUN_ROOT, AgenticHandler
from agentic.env_config import load_llm_config
from agentic.executor import AgenticExecutor
from agentic.llm_client import OpenAICompatibleClient
from agentic.state_store import StateStore
from service.allowlist import PROGRAMS, public_programs, validate_program_params
from service.auth import (
    LoginLimiter,
    hash_password,
    load_or_create_secret,
    new_token,
    token_hash,
    validate_username,
    verify_password,
)
from service.config import PROJECT_ROOT, GatewayConfig
from service.jobs import JobManager, incoming_path, list_result_files, safe_join, sanitize_filename
from service.storage import Store, iso
from service.ui import INDEX_HTML

JSON_LIMIT = 1 * 1024 * 1024
SESSION_COOKIE = "autorecon_session"
CLINIC_GET = {
    "/api/cases",
    "/api/config",
    "/api/runs",
    "/api/results",
    "/api/state",
    "/api/dashboard-state",
    "/api/file",
    "/api/log-tail",
}


class GatewayHandler(BaseHTTPRequestHandler):
    config: GatewayConfig
    store: Store
    jobs: JobManager
    secret: bytes
    limiter: LoginLimiter

    def log_message(self, fmt: str, *args: object) -> None:
        line = f"{iso()} {self.client_address[0]} {fmt % args}\n"
        try:
            with self.config.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: object, status: int = 200, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _session_cookie(self, token: str, *, clear: bool = False) -> str:
        if clear:
            return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        max_age = max(60, int(self.config.session_hours) * 3600)
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"

    def _request_token(self) -> str:
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            return header.removeprefix("Bearer ").strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and value:
                return value.strip()
        return ""

    def _user_clinic_root(self, username: str) -> Path:
        root = (self.config.users_root / username / "clinic").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _clinic_handler(self, username: str | None = None) -> AgenticHandler:
        clinic = AgenticHandler.__new__(AgenticHandler)
        clinic.rfile = self.rfile
        clinic.wfile = self.wfile
        clinic.headers = self.headers
        clinic.path = self.path
        clinic.command = self.command
        clinic.request_version = self.request_version
        clinic.client_address = self.client_address
        clinic.requestline = getattr(self, "requestline", "")
        clinic.connection = getattr(self, "connection", None)
        clinic.server = self.server
        clinic.close_connection = False
        if username:
            root = self._user_clinic_root(username)
            runs = root / "runs"
            clinic.store = StateStore(runs)
            clinic.executor = AgenticExecutor(PROJECT_ROOT, runs)
            clinic.allow_roots = [root]
        return clinic

    def _run_clinic(self, username: str, method: str) -> None:
        root = self._user_clinic_root(username)
        with user_clinic_scope(root / "uploads", root / "work"):
            getattr(self._clinic_handler(username), method)()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > JSON_LIMIT:
            raise ValueError("invalid json body")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json object required")
        return data

    def _auth(self) -> dict[str, Any] | None:
        token = self._request_token()
        if not token:
            self._error("authentication required", HTTPStatus.UNAUTHORIZED)
            return None
        row = self.store.lookup_token(token_hash(token, self.secret))
        if row is None:
            self._error("invalid token", HTTPStatus.UNAUTHORIZED)
            return None
        if row["disabled"]:
            self._error("account disabled", HTTPStatus.FORBIDDEN)
            return None
        if row["expires_at"] < iso():
            self._error("token expired", HTTPStatus.UNAUTHORIZED)
            return None
        return {"username": row["username"], "role": row["role"], "token": token}

    def _can_access(self, actor: dict[str, Any], owner: str) -> bool:
        return actor["username"] == owner or actor["role"] == "admin"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/", "/index.html"}:
                self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/health":
                self._json({"ok": True, "bind": f"{self.config.host}:{self.config.port}"})
                return
            if parsed.path.startswith("/brand/"):
                self._clinic_handler().do_GET()
                return
            actor = self._auth()
            if actor is None:
                return
            if parsed.path in CLINIC_GET:
                self._run_clinic(actor["username"], "do_GET")
                return
            if parsed.path == "/api/me":
                self._json({"username": actor["username"], "role": actor["role"]})
                return
            if parsed.path == "/api/programs":
                self._json({"programs": public_programs()})
                return
            if parsed.path == "/api/uploads":
                self._json({"uploads": self.store.list_uploads(actor["username"])})
                return
            if parsed.path == "/api/jobs":
                username = None if actor["role"] == "admin" else actor["username"]
                jobs = [self._public_job(row) for row in self.store.list_jobs(username)]
                if actor["role"] != "admin":
                    jobs = [job for job in jobs if job["username"] == actor["username"]]
                self._json({"jobs": jobs})
                return
            if parsed.path == "/api/admin/users":
                if actor["role"] != "admin":
                    self._error("admin only", HTTPStatus.FORBIDDEN)
                    return
                self._json({"users": self.store.list_users()})
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "jobs":
                job_id = parts[2]
                row = self.store.get_job(job_id)
                if row is None or not self._can_access(actor, row["username"]):
                    self._error("job not found", HTTPStatus.NOT_FOUND)
                    return
                if len(parts) == 3:
                    self._json(self._public_job(row))
                    return
                if parts[3] == "log":
                    log_path = self.store.job_dir(row["username"], job_id) / "job.log"
                    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
                    self._json({"text": text[-20000:]})
                    return
                if parts[3] == "files":
                    job_dir = self.store.job_dir(row["username"], job_id)
                    if len(parts) == 4:
                        self._json({"files": list_result_files(job_dir)})
                        return
                    relative = unquote("/".join(parts[4:]))
                    path = safe_join(job_dir, relative)
                    if not path.is_file():
                        self._error("file not found", HTTPStatus.NOT_FOUND)
                        return
                    data = path.read_bytes()
                    self._send(200, data, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{path.name}"'})
                    return
                if parts[3] == "archive":
                    self._send_archive(row)
                    return
            self._error("not found", HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._error(str(exc))
        except Exception:
            self._error("internal error", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/login":
                self._login()
                return
            actor = self._auth()
            if actor is None:
                return
            if parsed.path == "/api/logout":
                self.store.delete_token(token_hash(actor["token"], self.secret))
                self._json({"ok": True}, extra={"Set-Cookie": self._session_cookie("", clear=True)})
                return
            if parsed.path == "/api/uploads":
                body = self._read_json()
                filename = sanitize_filename(str(body.get("filename") or ""))
                size = int(body.get("size") or 0)
                if size <= 0 or size > self.config.max_upload_bytes:
                    self._error("upload size not allowed")
                    return
                if self.store.user_usage_bytes(actor["username"]) + size > self.config.max_user_bytes:
                    self._error("user storage quota exceeded", HTTPStatus.FORBIDDEN)
                    return
                upload_id = self.store.create_upload(actor["username"], filename, size)
                incoming_path(self.store.upload_dir(actor["username"], upload_id), filename).write_bytes(b"")
                self._json({"upload_id": upload_id, "chunk_bytes": self.config.max_chunk_bytes})
                return
            if parsed.path.startswith("/api/uploads/") and parsed.path.endswith("/complete"):
                upload_id = parsed.path.split("/")[3]
                row = self.store.get_upload(upload_id)
                if row is None or not self._can_access(actor, row["username"]):
                    self._error("upload not found", HTTPStatus.NOT_FOUND)
                    return
                if int(row["received_bytes"]) != int(row["size_bytes"]):
                    self._error("upload incomplete")
                    return
                self.store.update_upload(upload_id, status="complete")
                self._json({"ok": True, "upload_id": upload_id})
                return
            if parsed.path == "/api/jobs":
                self._create_job(actor)
                return
            if parsed.path == "/api/clinic-upload" or parsed.path in {"/api/plan", "/api/run", "/api/analyze"}:
                self._run_clinic(actor["username"], "do_POST")
                return
            if re.fullmatch(r"/api/clinic-upload/[A-Za-z0-9_-]+/(complete|rename)", parsed.path):
                self._run_clinic(actor["username"], "do_POST")
                return
            if parsed.path == "/api/admin/users":
                if actor["role"] != "admin":
                    self._error("admin only", HTTPStatus.FORBIDDEN)
                    return
                body = self._read_json()
                username = validate_username(str(body.get("username") or ""))
                salt, digest = hash_password(str(body.get("password") or ""))
                role = str(body.get("role") or "user")
                if role not in {"user", "admin"}:
                    self._error("invalid role")
                    return
                self.store.create_user(username, digest, salt, role)
                self._json({"ok": True, "username": username, "role": role})
                return
            self._error("not found", HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._error(str(exc))
        except Exception:
            self._error("internal error", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        try:
            actor = self._auth()
            if actor is None:
                return
            if re.fullmatch(r"/api/clinic-upload/[A-Za-z0-9_-]+/\d+", parsed.path):
                self._run_clinic(actor["username"], "do_PUT")
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "api" or parts[1] != "uploads":
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            upload_id = parts[2]
            row = self.store.get_upload(upload_id)
            if row is None or not self._can_access(actor, row["username"]):
                self._error("upload not found", HTTPStatus.NOT_FOUND)
                return
            if row["status"] != "pending":
                self._error("upload is not pending")
                return
            query = parse_qs(parsed.query)
            offset = int((query.get("offset") or ["0"])[0])
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > self.config.max_chunk_bytes:
                self._error("chunk size not allowed")
                return
            if offset != int(row["received_bytes"]):
                self._error("chunks must be sequential")
                return
            if offset + length > int(row["size_bytes"]):
                self._error("chunk exceeds declared size")
                return
            dest = incoming_path(self.store.upload_dir(row["username"], upload_id), row["filename"])
            with dest.open("ab") as handle:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    handle.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                self._error("incomplete chunk")
                return
            self.store.update_upload(upload_id, received_bytes=offset + length)
            self._json({"received_bytes": offset + length})
        except ValueError as exc:
            self._error(str(exc))
        except Exception:
            self._error("internal error", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            actor = self._auth()
            if actor is None:
                return
            if re.fullmatch(r"/api/clinic-upload/[A-Za-z0-9_-]+", parsed.path):
                self._run_clinic(actor["username"], "do_DELETE")
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "api" or parts[1] != "uploads":
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            row = self.store.get_upload(parts[2])
            if row is None or not self._can_access(actor, row["username"]):
                self._error("upload not found", HTTPStatus.NOT_FOUND)
                return
            shutil.rmtree(self.store.upload_dir(row["username"], row["upload_id"]), ignore_errors=True)
            self.store.delete_upload(row["upload_id"])
            self._json({"ok": True})
        except Exception:
            self._error("internal error", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _login(self) -> None:
        body = self._read_json()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        key = f"{self.client_address[0]}:{username}"
        if not self.limiter.allow(key):
            self._error("too many login attempts", HTTPStatus.TOO_MANY_REQUESTS)
            return
        try:
            username = validate_username(username)
        except ValueError:
            self._error("invalid credentials", HTTPStatus.UNAUTHORIZED)
            return
        row = self.store.get_user(username)
        if row is None or row["disabled"] or not verify_password(password, row["salt"], row["password_hash"]):
            self._error("invalid credentials", HTTPStatus.UNAUTHORIZED)
            return
        token = new_token()
        expires = self.store.save_token(token_hash(token, self.secret), username, self.config.session_hours)
        self._json(
            {"token": token, "expires_at": expires, "username": username, "role": row["role"]},
            extra={"Set-Cookie": self._session_cookie(token)},
        )

    def _create_job(self, actor: dict[str, Any]) -> None:
        body = self._read_json()
        program = str(body.get("program") or "")
        params = validate_program_params(program, body.get("params") or {})
        upload_ids = body.get("upload_ids")
        if upload_ids is None:
            upload_ids = [item["upload_id"] for item in self.store.list_uploads(actor["username"]) if item["status"] == "complete"]
        if not isinstance(upload_ids, list) or not upload_ids:
            self._error("no complete uploads selected")
            return
        cleaned: list[str] = []
        for upload_id in upload_ids:
            row = self.store.get_upload(str(upload_id))
            if row is None or row["username"] != actor["username"] or row["status"] != "complete":
                self._error("upload not found or not owned by current user", HTTPStatus.FORBIDDEN)
                return
            cleaned.append(row["upload_id"])
        if self.store.active_job_count() >= self.config.max_global_jobs:
            self._error("server is at global job capacity", HTTPStatus.TOO_MANY_REQUESTS)
            return
        if self.store.active_job_count(actor["username"]) >= self.config.max_user_jobs:
            self._error("user is at job capacity", HTTPStatus.TOO_MANY_REQUESTS)
            return
        job_id = self.store.create_job(
            actor["username"],
            program,
            params,
            cleaned,
            int(PROGRAMS[program]["timeout_seconds"]),
        )
        self.jobs.submit(job_id)
        self._json({"job_id": job_id, "status": "queued"})

    def _public_job(self, row: Any) -> dict[str, Any]:
        progress = {}
        try:
            progress = json.loads(row["progress_json"] or "{}")
        except ValueError:
            progress = {}
        return {
            "job_id": row["job_id"],
            "username": row["username"],
            "program": row["program"],
            "params": json.loads(row["params_json"]),
            "status": row["status"],
            "progress": progress,
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def _send_archive(self, row: Any) -> None:
        job_dir = self.store.job_dir(row["username"], row["job_id"])
        if not job_dir.exists():
            self._error("job files not found", HTTPStatus.NOT_FOUND)
            return
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        tmp.close()
        archive = Path(tmp.name)
        try:
            with tarfile.open(archive, "w:gz") as tar:
                for path in job_dir.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        tar.add(path, arcname=path.relative_to(job_dir).as_posix())
            data = archive.read_bytes()
        finally:
            archive.unlink(missing_ok=True)
        filename = f"{row['job_id']}.tar.gz"
        self._send(200, data, "application/gzip", {"Content-Disposition": f'attachment; filename="{filename}"'})


def bootstrap_admin(config: GatewayConfig, store: Store) -> Path | None:
    if store.count_users() > 0:
        return None
    password = config.bootstrap_password
    notice: Path | None = None
    if not password:
        import os
        import secrets

        password = secrets.token_urlsafe(16)
        notice = config.data_root / "bootstrap_admin.txt"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(notice, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"username={config.bootstrap_username}\npassword={password}\n")
            handle.write("Change this password after first login. This file is not a public credential store.\n")
    salt, digest = hash_password(password)
    store.create_user(config.bootstrap_username, digest, salt, "admin")
    return notice


def serve(config: GatewayConfig) -> ThreadingHTTPServer:
    from agentic.env_config import parse_env_file

    env_path = config.project_root / ".env"
    if env_path.is_file():
        selected_llm = os.environ.get("AUTORECON_CONFIG_FILE", "").strip()
        for key, value in parse_env_file(env_path).items():
            if selected_llm and (
                key.startswith("AUTORECON_LLM_") or key in {"OPENAI_BASE_URL", "OPENAI_API_KEY", "API_KEY"}
            ):
                continue
            os.environ.setdefault(key, value)

    store = Store(config)
    secret = load_or_create_secret(config.secret_path)
    notice = bootstrap_admin(config, store)
    jobs = JobManager(config, store)
    jobs.start()
    handler = GatewayHandler
    handler.config = config
    handler.store = store
    handler.jobs = jobs
    handler.secret = secret
    handler.limiter = LoginLimiter(config.login_max_attempts, config.login_window_seconds)
    run_root = DEFAULT_RUN_ROOT
    AgenticHandler.store = StateStore(run_root)
    AgenticHandler.executor = AgenticExecutor(PROJECT_ROOT, run_root)
    AgenticHandler.allow_roots = [PROJECT_ROOT.resolve(), run_root.resolve(), Path("/tmp").resolve()]
    AgenticHandler.llm = OpenAICompatibleClient(load_llm_config(PROJECT_ROOT))
    server = ThreadingHTTPServer((config.host, config.port), handler)
    actual_port = int(server.server_address[1])
    AgenticHandler.dashboard_url = f"http://127.0.0.1:{actual_port}"
    print(f"AutoRecon: http://{config.host}:{actual_port}", flush=True)
    if config.host in {"127.0.0.1", "localhost"}:
        print("Bound to loopback only. Campus/VPN clients cannot reach this process.", flush=True)
    else:
        print("Listening on a non-loopback address. Keep 8899 Dashboard on 127.0.0.1.", flush=True)
    if notice is not None:
        print(f"Bootstrap admin password written to {notice} (mode 600).", flush=True)
    return server
