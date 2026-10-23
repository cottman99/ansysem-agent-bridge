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
from .project_bundle import bundle_content_summary, bundle_state_revision


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


def _desktop_identity(*, scope: str = "auto") -> dict[str, Any]:
    if not all(
        os.environ.get(name)
        for name in ("PYAEDT_DESKTOP_VERSION", "PYAEDT_PROCESS_ID", "PYAEDT_DESKTOP_PORT")
    ):
        raise RuntimeError("Run this action from the exact AEDT session's menu or Automation tab.")
    import ansys.aedt.core
    from ansys.aedt.core.extensions.misc import get_aedt_version, get_port, get_process_id

    version = get_aedt_version()
    port = get_port()
    process_id = get_process_id()
    snapshot = os.environ.pop("ANSYSEM_CONTEXT_CAPTURE", None)
    if snapshot:
        identity = json.loads(snapshot)
        if (identity.get("process_id"), identity.get("port"), identity.get("version")) != (
            process_id,
            port,
            version,
        ):
            raise RuntimeError("The menu selection belongs to a different AEDT session.")
    else:
        from .aedt_addin_assets.native_selection import capture

        desktop = ansys.aedt.core.Desktop(
            new_desktop=False,
            version=version,
            port=port,
            aedt_process_id=process_id,
            close_on_exit=False,
        )
        try:
            identity = capture(desktop.odesktop, scope)
        finally:
            desktop.release_desktop(close_projects=False, close_on_exit=False)
    identity["profile"] = os.environ.get("ANSYSEM_CONTEXT_PROFILE") or load_config().get(
        "default_profile"
    )
    return identity


def _choose_tree_item(identity: dict[str, Any]) -> dict[str, Any] | None:
    choices = identity.pop("pending_tree_choices", None)
    if choices is None:
        return identity
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Copy Agent Context")
    root.geometry("620x360")
    root.minsize(440, 240)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    branch = " / ".join(identity["selection"]["path"])
    ttk.Label(frame, text=branch, wraplength=570).pack(anchor="w")
    ttk.Label(frame, text="Choose the item to copy:").pack(anchor="w", pady=(12, 6))
    items = tk.Listbox(frame, exportselection=False, activestyle="dotbox")
    for choice in choices:
        base_depth = len(identity["selection"]["path"])
        items.insert("end", " / ".join(choice["path"][base_depth:]))
    items.pack(fill="both", expand=True)
    selected = []

    def accept(_event=None):
        indexes = items.curselection()
        if indexes:
            selected.append(choices[indexes[0]])
            root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
    ttk.Button(buttons, text="Copy", command=accept).pack(side="right", padx=8)
    items.bind("<Double-Button-1>", accept)
    root.bind("<Return>", accept)
    root.bind("<Escape>", lambda _event: root.destroy())
    root.mainloop()
    if not selected:
        return None
    choice = selected[0]
    _verify_tree_item(identity, choice["path"])
    identity["selection"]["path"] = choice["path"]
    identity["selection"]["name"] = choice["name"]
    identity["selection"]["chosen_by"] = "user"
    return identity


def _verify_tree_item(identity: dict[str, Any], path: list[str]) -> None:
    """Recheck the chosen path; do not rely on focus after the picker was opened."""
    import ansys.aedt.core

    desktop = ansys.aedt.core.Desktop(
        new_desktop=False,
        version=identity["version"],
        port=identity["port"],
        aedt_process_id=identity["process_id"],
        close_on_exit=False,
    )
    try:
        project = next(
            p
            for p in desktop.odesktop.GetProjects()
            if str(p.GetName()) == identity["project_name"]
        )
        actual_path = Path(str(project.GetPath())) / f"{identity['project_name']}.aedt"
        if actual_path.resolve() != Path(identity["project"]).resolve():
            raise ValueError("The selected project path has changed; copy its context again.")
        owner = project
        if identity.get("design"):
            owner = next(
                d
                for d in project.GetDesigns()
                if str(d.GetName()).split(";")[-1] == identity["design"]
            )
        for name in path[2:]:
            if name not in list(owner.GetChildNames()):
                raise ValueError("The selected item has changed; copy its context again.")
            owner = owner.GetChildObject(name)
    finally:
        desktop.release_desktop(close_projects=False, close_on_exit=False)


def _content_binding(identity: dict[str, Any]) -> dict[str, Any] | None:
    if not identity.get("design"):
        return None
    project = Path(str(identity["project"])).expanduser().resolve()
    try:
        summary = bundle_content_summary(project)
        revision = bundle_state_revision(project)
    except (OSError, ValueError):
        return None
    return {
        "schema_version": 1,
        "resource_kind": "aedt-project",
        "bundle_sha256": summary["bundle_sha256"],
        "state_revision": revision,
        "project_name": str(identity["project_name"]),
        "design": str(identity["design"]),
        "version": identity.get("version"),
        "profile": identity.get("profile"),
        "display": identity.get("display"),
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
            "port": identity.get("port"),
            "target_kind": identity.get("target_kind", "design"),
            "selection": identity.get("selection", {}),
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
        "captured_at": identity.get("captured_at") or _utc_now(),
        "target": identity,
    }
    binding = _content_binding(identity)
    if binding is not None:
        record["binding"] = binding
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
        target_kind=identity.get("target_kind", "design"),
        locator=locator,
        display_name=" / ".join(identity.get("selection", {}).get("path", []))
        or ":".join(filter(None, (identity["project_name"], identity.get("design")))),
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
        selection=identity.get("selection", {}),
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


def capture_context(*, make_current: bool = False, copy_to_clipboard: bool = True) -> str | None:
    identity = _desktop_identity(scope="design") if make_current else _desktop_identity()
    identity = _choose_tree_item(identity)
    if identity is None:
        return None
    token = store_context(identity, make_current=make_current)
    if copy_to_clipboard:
        _copy_text(token)
        action = "selected and copied" if make_current else "copied"
        label = " / ".join(identity.get("selection", {}).get("path", []))
        if identity.get("target_kind") == "selection":
            label += "\n" + ", ".join(identity["selection"]["hierarchy"])
        _show_message(
            "EDA Agent Context", f"{label or identity['project_name']}\nContext {action}."
        )
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
    if os.name != "nt":
        # X11 owns clipboard data in a live process. Destroying a Tk root here
        # loses the selection as soon as the button script exits.
        import select
        import subprocess
        import sys

        process = subprocess.Popen(
            [sys.executable, "-m", "ansysem_agent_bridge.clipboard_owner"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        try:
            process.stdin.write(text)
            process.stdin.close()
            ready, _, _ = select.select([process.stdout], [], [], 10)
            if not ready or process.stdout.readline().strip() != "ready":
                raise RuntimeError("The desktop clipboard did not accept the context")
        except Exception:
            process.terminate()
            raise
        finally:
            process.stdout.close()
        return
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()


def _show_message(title: str, message: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        try:
            messagebox.showinfo(title, message, parent=root)
        finally:
            root.destroy()
    except Exception:
        print(f"{title}: {message}")


def _prepare_button_process(action: str) -> None:
    """Use the registered Python profile before loading AEDT or desktop libraries.

    AEDT's toolkit launcher exports its bundled Tcl paths and loader paths.
    Those paths do not describe the independently installed Bridge interpreter.
    """
    import subprocess
    import sys

    if os.environ.get("ANSYSEM_CONTEXT_BOOTSTRAPPED") == "1":
        if os.environ.get("ANSYSEM_CONTEXT_DISPLAY"):
            os.environ["DISPLAY"] = os.environ["ANSYSEM_CONTEXT_DISPLAY"]
        return
    config = load_config()
    personal_lib = os.environ.get("PYAEDT_PERSONAL_LIB")
    records = [
        record
        for record in config.get("context_addins", [])
        if personal_lib and Path(record["personal_lib"]).resolve() == Path(personal_lib).resolve()
    ]
    profile = records[0].get("profile") if len(records) == 1 else config.get("default_profile")
    if os.name != "nt":
        if os.environ.get("DISPLAY"):
            os.environ["ANSYSEM_CONTEXT_DISPLAY"] = os.environ["DISPLAY"]
        for name in ("TCL_LIBRARY", "TK_LIBRARY", "TKPATH"):
            os.environ.pop(name, None)
        # Standalone Python's copied venv launcher can lose its relative loader
        # path to Tcl/Tk. Use this interpreter's own library directory.
        library = str(Path(sys.base_prefix) / "lib")
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = library + (os.pathsep + existing if existing else "")
    os.environ["ANSYSEM_CONTEXT_BOOTSTRAPPED"] = "1"
    if profile:
        from .profiles import ensure_profile_process

        os.environ["ANSYSEM_CONTEXT_PROFILE"] = profile
        # AEDT may inherit the marker, then replace its loader paths at startup.
        os.environ.pop("ANSYSEM_ACTIVE_PROFILE", None)
        ensure_profile_process(profile, [action], module="ansysem_agent_bridge.aedt_context_tool")
    else:
        arguments = [sys.executable, "-m", "ansysem_agent_bridge.aedt_context_tool", action]
        if os.name == "nt":
            raise SystemExit(subprocess.call(arguments, creationflags=subprocess.CREATE_NO_WINDOW))
        os.execve(sys.executable, arguments, os.environ.copy())


def main(action: str) -> Any:
    _prepare_button_process(action)
    if action == "copy":
        return capture_context()
    if action == "use-current":
        return capture_context(make_current=True)
    if action == "status":
        return connection_status()
    raise ValueError(f"unsupported context action: {action}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1])
