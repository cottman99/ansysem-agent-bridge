from __future__ import annotations

import hashlib
import os
import platform
import socket
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TargetIdentity, state_revision
from .session_lifecycle import OwnedSessionStore


def _safe_value(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
        return value() if callable(value) else value
    except Exception:
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validation_result(value: Any) -> dict[str, Any]:
    """Normalize the PyAEDT validation return without assuming one release shape."""
    if isinstance(value, bool):
        passed = value
    elif isinstance(value, tuple | list):
        boolean_values = [item for item in value if isinstance(item, bool)]
        passed = boolean_values[-1] if boolean_values else False
    else:
        passed = False
    return {"supported": True, "passed": passed, "raw": value}


def live_hfss3dlayout_probe(
    *,
    project: str | Path,
    version: str,
    design: str | None = None,
    port: int = 0,
    new_desktop: bool = True,
    close_desktop: bool = True,
    validate: bool = False,
    export_image: str | Path | None = None,
    image_width: int = 1600,
    image_height: int = 1000,
    redact_paths: bool = False,
    since_revision: str | None = None,
    expected_pid: int | None = None,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    if not project_path.is_file() or project_path.suffix.casefold() != ".aedt":
        raise ValueError(f"Expected an existing .aedt project: {project_path}")

    try:
        from ansys.aedt.core import Hfss3dLayout
    except ImportError as exc:
        raise RuntimeError("PyAEDT is not available in this Python environment.") from exc

    app = None
    output = Path(export_image).expanduser().resolve() if export_image else None
    started = time.monotonic()
    phase_timing_ms: dict[str, float] = {}
    try:
        kwargs: dict[str, Any] = {
            "project": str(project_path),
            "version": version,
            "non_graphical": False,
            "new_desktop": new_desktop,
            "close_on_exit": new_desktop and close_desktop,
        }
        if design:
            kwargs["design"] = design
        if port:
            kwargs["port"] = port
        open_started = time.monotonic()
        app = Hfss3dLayout(**kwargs)
        phase_timing_ms["desktop_connect_and_project_open"] = round(
            (time.monotonic() - open_started) * 1000, 3
        )

        readback_started = time.monotonic()
        desktop = _safe_value(app, "desktop_class")
        pid = _safe_value(desktop, "aedt_process_id") if desktop is not None else None
        if pid is None:
            try:
                pid = app.odesktop.GetProcessID()
            except Exception:
                pid = None
        if expected_pid is not None and int(pid or 0) != int(expected_pid):
            raise PermissionError("AEDT resource process identity changed")
        try:
            native_version = app.odesktop.GetVersion()
        except Exception:
            native_version = None
        identity = TargetIdentity(
            host=socket.gethostname(),
            platform=platform.system(),
            version=version,
            display=os.environ.get("DISPLAY"),
            pid=pid,
            project_path=str(project_path),
            project_name=_safe_value(app, "project_name"),
            design_name=_safe_value(app, "design_name"),
            editor=str(_safe_value(app, "design_type", "HFSS 3D Layout")),
            lane="pyaedt-live",
        ).to_dict(redact_paths=redact_paths)
        state: dict[str, Any] = {
            "native_aedt_version": native_version,
            "designs": list(_safe_value(app, "design_list", []) or []),
            "setups": list(_safe_value(app, "setup_names", []) or []),
            "ports": list(_safe_value(app, "port_list", []) or []),
            "validation": None,
        }

        artifact = None
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            editor = app.oeditor
            editor.ZoomToFit()
            editor.ExportImage(str(output), int(image_width), int(image_height))
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError(
                    "AEDT returned from ExportImage without creating a non-empty artifact."
                )
            artifact = {
                "path": output.name if redact_paths else str(output),
                "size": output.stat().st_size,
                "sha256": _sha256(output),
            }

        validation: dict[str, Any] | None = None
        if validate:
            if not hasattr(app, "validate_simple"):
                validation = {
                    "supported": False,
                    "passed": False,
                    "reason": "validate_simple unavailable",
                }
            else:
                try:
                    value = app.validate_simple()
                    validation = _validation_result(value)
                except Exception as exc:
                    validation = {
                        "supported": True,
                        "passed": False,
                        "status": "error",
                        "error": {"type": exc.__class__.__name__, "message": str(exc)},
                    }
        state["validation"] = validation
        phase_timing_ms["identity_and_state_readback"] = round(
            (time.monotonic() - readback_started) * 1000, 3
        )
        revision = state_revision({"identity": identity, "state": state})
        changed = since_revision != revision
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "attention_required"
            if validation and not validation.get("passed", False)
            else "ready",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "state_revision": revision,
            "changed": changed,
            "identity": identity,
            "artifact": artifact,
            "evidence_boundary": (
                "Live readback proves only the captured project/design state; solver completion "
                "requires separate evidence."
            ),
        }
        if changed:
            payload["detail"] = "compact"
            payload["state"] = state
            payload["recommended_safe_actions"] = [
                "Treat project, design, editor, process, and display identity as one target tuple.",
                "Use a separate solver-status or result artifact before claiming simulation "
                "completion.",
            ]
        if new_desktop and not close_desktop:
            desktop_port = _safe_value(desktop, "port") if desktop is not None else None
            if not desktop_port:
                desktop_port = _safe_value(app, "port")
            try:
                payload["resource"] = OwnedSessionStore().register(
                    pid=int(pid or 0),
                    port=int(desktop_port or port or 0),
                    version=version,
                    project=str(project_path),
                    design=str(_safe_value(app, "design_name") or design or "") or None,
                )
            except Exception:
                with suppress(Exception):
                    app.release_desktop(close_projects=True, close_desktop=True)
                raise
        payload["session_reused"] = not new_desktop
        if new_desktop and close_desktop:
            release_started = time.monotonic()
            app.release_desktop(close_projects=True, close_desktop=True)
            app = None
            phase_timing_ms["owned_session_release"] = round(
                (time.monotonic() - release_started) * 1000, 3
            )
        phase_timing_ms["total"] = round((time.monotonic() - started) * 1000, 3)
        payload["phase_timing_ms"] = phase_timing_ms
        return payload
    finally:
        if app is not None and new_desktop and close_desktop:
            with suppress(Exception):
                app.release_desktop(close_projects=True, close_desktop=True)
