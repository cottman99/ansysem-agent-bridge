from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import agent_home

RESOURCE_PROTOCOL = "eda-runtime.resource/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_owned_sessions_path() -> Path:
    path = agent_home(ensure=True) / "runtime" / "owned-sessions.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class OwnedSessionStore:
    def __init__(self, database: str | Path | None = None):
        self.database = Path(database) if database else default_owned_sessions_path()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS owned_sessions (
                    resource_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    port INTEGER NOT NULL,
                    version TEXT NOT NULL,
                    project TEXT NOT NULL,
                    design TEXT,
                    created_at TEXT NOT NULL,
                    released_at TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def register(
        self,
        *,
        pid: int,
        port: int,
        version: str,
        project: str,
        design: str | None,
    ) -> dict[str, Any]:
        if pid <= 0 or port <= 0:
            raise RuntimeError("AEDT did not expose a stable process id and gRPC port")
        resource_id = f"aedt_{uuid.uuid4().hex}"
        token = secrets.token_urlsafe(24)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO owned_sessions
                (resource_id, token_sha256, state, pid, port, version, project, design, created_at)
                VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource_id,
                    _token_hash(token),
                    int(pid),
                    int(port),
                    str(version),
                    str(project),
                    design,
                    _now(),
                ),
            )
        return {
            "protocol": RESOURCE_PROTOCOL,
            "resource_id": resource_id,
            "kind": "aedt-desktop",
            "ownership": "runtime-owned",
            "state": "active",
            "release_operation": "session.release",
            "release_handle": token,
        }

    def authorize(self, resource_id: str, release_token: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM owned_sessions WHERE resource_id = ?", (resource_id,)
            ).fetchone()
        if row is None or not secrets.compare_digest(
            str(row["token_sha256"]), _token_hash(release_token)
        ):
            raise PermissionError("unknown or unauthorized AEDT resource handle")
        return dict(row)

    def mark_released(self, resource_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE owned_sessions SET state = 'released', released_at = ? "
                "WHERE resource_id = ?",
                (_now(), resource_id),
            )


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _open_existing_desktop(*, version: str, port: int):
    try:
        from ansys.aedt.core import Desktop
    except ImportError as exc:
        raise RuntimeError("PyAEDT is not available in this Python environment.") from exc
    return Desktop(
        version=version,
        non_graphical=False,
        new_desktop=False,
        close_on_exit=False,
        port=port,
    )


def authorize_owned_aedt_session(
    *,
    resource_id: str,
    release_handle: str,
    project: str | Path,
    version: str,
    design: str | None = None,
    database: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve one active Runtime-owned AEDT session without exposing its port."""
    record = OwnedSessionStore(database).authorize(resource_id, release_handle)
    if record["state"] != "active" or not _pid_is_alive(int(record["pid"])):
        raise RuntimeError("AEDT resource is not an active owned session")
    expected_project = str(Path(project).expanduser().resolve())
    if str(Path(record["project"]).expanduser().resolve()) != expected_project:
        raise PermissionError("AEDT resource project identity does not match")
    if str(record["version"]) != str(version):
        raise PermissionError("AEDT resource version identity does not match")
    if design and str(record.get("design") or "") != str(design):
        raise PermissionError("AEDT resource design identity does not match")
    return record


def authorize_captured_aedt_session(
    *,
    context: str,
    project: str | Path,
    version: str,
    design: str,
) -> dict[str, Any]:
    """Authorize exact live-session reuse from a host-local EDA Context."""

    try:
        from eda_bridge_runtime import EDAContext
    except ImportError as exc:
        raise RuntimeError("EDA Runtime support is required for live Context reuse") from exc
    decoded = EDAContext.decode(context)
    if decoded.eda != "ansys-electronics-desktop":
        raise ValueError("EDA context does not belong to Ansys Electronics Desktop")
    if decoded.freshness.get("scope") != "live":
        raise PermissionError("AnsysEM Context does not identify a live AEDT session")
    context_id = str(decoded.locator.get("context_id") or "")
    if not context_id or not context_id.replace("_", "").isalnum():
        raise ValueError("invalid AnsysEM context id")
    path = agent_home() / "runtime" / "contexts" / f"{context_id}.json"
    if not path.is_file():
        raise ValueError("AnsysEM context is unavailable on this host")
    record = json.loads(path.read_text(encoding="utf-8"))
    if int(record.get("generation") or 0) != int(decoded.generation):
        raise ValueError("AnsysEM context is stale; copy it again from AEDT")
    target = record.get("target")
    if not isinstance(target, dict):
        raise ValueError("AnsysEM context target record is invalid")
    expected_project = Path(project).expanduser().resolve()
    recorded_project = Path(str(target.get("project") or "")).expanduser().resolve()
    if recorded_project != expected_project:
        raise PermissionError("AnsysEM Context project identity does not match")
    if str(target.get("version") or "") != str(version):
        raise PermissionError("AnsysEM Context version identity does not match")
    if str(target.get("design") or "") != str(design):
        raise PermissionError("AnsysEM Context design identity does not match")
    pid = int(target.get("process_id") or 0)
    port = int(target.get("port") or 0)
    if not _pid_is_alive(pid) or port <= 0:
        raise RuntimeError("AnsysEM Context session is no longer live")
    return {
        "pid": pid,
        "port": port,
        "version": str(version),
        "project": str(expected_project),
        "design": str(design),
        "ownership": "user-owned-context",
    }


def release_owned_aedt_session(
    *,
    resource_id: str,
    release_handle: str,
    timeout_seconds: float = 15.0,
    database: str | Path | None = None,
) -> dict[str, Any]:
    store = OwnedSessionStore(database)
    record = store.authorize(resource_id, release_handle)
    if record["state"] == "released" and not _pid_is_alive(int(record["pid"])):
        return {
            "status": "passed",
            "resource": {
                "protocol": RESOURCE_PROTOCOL,
                "resource_id": resource_id,
                "kind": "aedt-desktop",
                "ownership": "runtime-owned",
                "state": "released",
                "release_operation": "session.release",
            },
            "idempotent": True,
        }
    if not _pid_is_alive(int(record["pid"])):
        store.mark_released(resource_id)
        return {
            "status": "passed",
            "resource": {
                "protocol": RESOURCE_PROTOCOL,
                "resource_id": resource_id,
                "kind": "aedt-desktop",
                "ownership": "runtime-owned",
                "state": "released",
                "release_operation": "session.release",
            },
            "observed": "process-already-exited",
        }

    desktop = _open_existing_desktop(version=str(record["version"]), port=int(record["port"]))
    try:
        observed_pid = int(desktop.odesktop.GetProcessID())
        if observed_pid != int(record["pid"]):
            raise PermissionError("AEDT resource identity changed; refusing to close it")
        desktop.release_desktop(close_projects=True, close_on_exit=True)
    finally:
        with suppress(Exception):
            desktop.close_on_exit = False

    deadline = time.monotonic() + max(0.5, min(float(timeout_seconds), 60.0))
    while _pid_is_alive(int(record["pid"])) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_is_alive(int(record["pid"])):
        raise RuntimeError("AEDT accepted the close request but the owned process is still alive")
    store.mark_released(resource_id)
    return {
        "status": "passed",
        "resource": {
            "protocol": RESOURCE_PROTOCOL,
            "resource_id": resource_id,
            "kind": "aedt-desktop",
            "ownership": "runtime-owned",
            "state": "released",
            "release_operation": "session.release",
        },
    }
