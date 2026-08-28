"""Small PyAEDT toolkit actions for explicit, secret-free Agent context."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import agent_home, load_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _context_root() -> Path:
    path = agent_home() / "runtime" / "contexts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        with suppress(OSError):
            os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _desktop_identity() -> dict[str, Any]:
    import ansys.aedt.core
    from ansys.aedt.core.extensions.misc import get_aedt_version, get_port, get_process_id

    version = get_aedt_version()
    port = get_port()
    process_id = get_process_id()
    desktop = ansys.aedt.core.Desktop(
        new_desktop=False,
        version=version,
        port=port,
        aedt_process_id=process_id,
        close_on_exit=False,
    )
    project = desktop.active_project()
    design = desktop.active_design()
    if project is None or design is None:
        raise RuntimeError("Open and activate one AEDT project and design first.")
    project_name = str(project.GetName())
    design_name = str(design.GetName()).split(";")[-1]
    project_path = Path(str(project.GetPath())) / f"{project_name}.aedt"
    profile = load_config().get("default_profile")
    return {
        "profile": profile,
        "project": str(project_path),
        "project_name": project_name,
        "design": design_name,
        "version": version,
        "port": port,
        "process_id": process_id,
        "display": os.environ.get("DISPLAY"),
    }


def store_context(
    identity: dict[str, Any],
    *,
    connection_id: str | None = None,
    make_current: bool = False,
) -> str:
    from eda_bridge_runtime import EDAContext, capability_digest, stable_origin_id

    stable = json.dumps(
        {
            "process_id": identity.get("process_id"),
            "project": identity["project"],
            "design": identity["design"],
        },
        sort_keys=True,
    )
    context_id = "ctx_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]
    root = _context_root()
    path = root / f"{context_id}.json"
    generation = 1
    if path.is_file():
        try:
            generation = int(json.loads(path.read_text(encoding="utf-8"))["generation"]) + 1
        except (OSError, ValueError, KeyError, TypeError):
            generation = 1
    record = {
        "schema_version": 1,
        "context_id": context_id,
        "generation": generation,
        "captured_at": _utc_now(),
        "target": identity,
    }
    _write_private_json(path, record)
    if make_current:
        _write_private_json(root / "active.json", record)
    locator = {"context_id": context_id}
    if connection_id:
        locator["connection_id"] = connection_id
    capability_states = {name: "available" for name in ("inspect", "edit", "simulate")}
    process_id = identity.get("process_id")
    port = identity.get("port")
    live = process_id is not None
    token = EDAContext(
        eda="ansys-electronics-desktop",
        target_kind="design",
        locator=locator,
        display_name=f"{identity['project_name']}:{identity['design']}",
        generation=generation,
        capabilities_hint=tuple(capability_states),
        origin={"origin_id": stable_origin_id("ansys-electronics-desktop")},
        session={
            "session_id": f"aedt-{process_id}-{port}" if live else None,
            "display": identity.get("display"),
            "process_id": process_id,
            "port": port,
            "profile": identity.get("profile"),
            "state": "live" if live else "closed",
        },
        target={
            "project_name": identity["project_name"],
            "design": identity["design"],
            "version": identity.get("version"),
        },
        capabilities={
            "states": capability_states,
            "digest": capability_digest(capability_states),
        },
        freshness={
            "scope": "live" if live else "durable",
            "generation": generation,
            "captured_at": record["captured_at"],
            "state": "captured-live" if live else "reopenable",
            "expires_on": "session-restart" if live else None,
        },
    ).encode()
    return token


def capture_context(*, make_current: bool = False, copy_to_clipboard: bool = True) -> str:
    identity = _desktop_identity()
    token = store_context(identity, make_current=make_current)
    if copy_to_clipboard:
        _copy_text(token)
        action = "selected and copied" if make_current else "copied"
        _show_message("EDA Agent Context", f"Current AEDT design {action} for the Agent.")
    return token


def connection_status() -> dict[str, Any]:
    runtime = agent_home() / "runtime"
    active_path = runtime / "contexts" / "active.json"
    active = None
    if active_path.is_file():
        try:
            record = json.loads(active_path.read_text(encoding="utf-8"))
            active = {
                "project_name": record["target"].get("project_name"),
                "design": record["target"].get("design"),
                "captured_at": record.get("captured_at"),
            }
        except (OSError, ValueError, KeyError, TypeError):
            active = None
    counts: dict[str, int] = {}
    jobs = runtime / "jobs.sqlite3"
    if jobs.is_file():
        try:
            connection = sqlite3.connect(f"file:{jobs}?mode=ro", uri=True)
            counts = {
                state: count
                for state, count in connection.execute(
                    "SELECT state, COUNT(*) FROM jobs GROUP BY state"
                )
            }
            connection.close()
        except sqlite3.Error:
            counts = {"unavailable": 1}
    status = {"runtime_installed": _runtime_available(), "active_context": active, "jobs": counts}
    lines = [
        f"Runtime installed: {'yes' if status['runtime_installed'] else 'no'}",
        f"Current design: {active['project_name']}:{active['design']}"
        if active
        else "Current design: none",
        "Jobs: " + (", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"),
    ]
    _show_message("EDA Agent Connection Status", "\n".join(lines))
    return status


def _runtime_available() -> bool:
    try:
        import eda_bridge_runtime  # noqa: F401
    except ImportError:
        return False
    return True


def _copy_text(text: str) -> None:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()


def _show_message(title: str, message: str) -> None:
    try:
        from tkinter import messagebox

        messagebox.showinfo(title, message)
    except Exception:
        print(f"{title}: {message}")


def main(action: str) -> Any:
    if action == "copy":
        return capture_context()
    if action == "use-current":
        return capture_context(make_current=True)
    if action == "status":
        return connection_status()
    raise ValueError(f"unsupported context action: {action}")
