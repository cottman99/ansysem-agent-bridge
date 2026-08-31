"""Bounded edits inside one Runtime-owned graphical AEDT session."""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .session_lifecycle import (
    authorize_captured_aedt_session,
    authorize_owned_aedt_session,
)

_VARIABLE_NAME = re.compile(r"\$?[A-Za-z_][A-Za-z0-9_]*")
_APP_CACHE: OrderedDict[tuple[int, int, str, str, str], Any] = OrderedDict()
_APP_CACHE_LIMIT = 4


def _authorized_session(
    *,
    resource_id: str | None,
    release_handle: str | None,
    context: str | None,
    project: str | Path,
    version: str,
    design: str,
) -> dict[str, Any]:
    if bool(resource_id) != bool(release_handle):
        raise ValueError("resource_id and release_handle must be provided together")
    if resource_id:
        session = authorize_owned_aedt_session(
            resource_id=resource_id,
            release_handle=str(release_handle),
            project=project,
            version=version,
            design=design,
        )
        return {**session, "ownership": "runtime-owned"}
    if context:
        return authorize_captured_aedt_session(
            context=context,
            project=project,
            version=version,
            design=design,
        )
    raise PermissionError(
        "live design operation requires an owned session handle or a live EDA Context"
    )


def _live_app(*, session: dict[str, Any], project: str | Path, version: str, design: str):
    try:
        from ansys.aedt.core import Hfss3dLayout
    except ImportError as exc:
        raise RuntimeError("PyAEDT is not available in this Python environment") from exc

    project_path = str(Path(project).expanduser().resolve())
    key = (
        int(session["pid"]),
        int(session["port"]),
        project_path,
        str(version),
        str(design),
    )
    cached = _APP_CACHE.get(key)
    if cached is not None:
        try:
            if int(cached.odesktop.GetProcessID()) == int(session["pid"]) and str(
                cached.design_name
            ) == str(design):
                _APP_CACHE.move_to_end(key)
                return cached, True
        except Exception:
            pass
        _APP_CACHE.pop(key, None)

    app = Hfss3dLayout(
        project=project_path,
        design=design,
        version=version,
        non_graphical=False,
        new_desktop=False,
        close_on_exit=False,
        port=int(session["port"]),
    )
    _APP_CACHE[key] = app
    _APP_CACHE.move_to_end(key)
    while len(_APP_CACHE) > _APP_CACHE_LIMIT:
        _APP_CACHE.popitem(last=False)
    return app, False


def apply_live_patch(
    *,
    resource_id: str | None = None,
    release_handle: str | None = None,
    context: str | None = None,
    project: str | Path,
    version: str,
    design: str,
    operation: dict[str, Any],
) -> dict[str, Any]:
    """Apply one typed variable edit without launching another AEDT process."""

    if not isinstance(operation, dict):
        raise TypeError("design.live_patch operation must be an object")
    action = str(operation.get("op") or "")
    if action not in {"set_design_variable", "delete_design_variable"}:
        raise ValueError("design.live_patch supports only typed design-variable edits")
    name = str(operation.get("name") or "")
    if not _VARIABLE_NAME.fullmatch(name):
        raise ValueError("design.live_patch variable name is invalid")

    expected_before = operation.get("expected_before")
    if expected_before is not None and not isinstance(expected_before, str):
        raise TypeError("expected_before must be a string or null")
    value = operation.get("value")
    if action == "set_design_variable" and (not isinstance(value, str) or not value):
        raise ValueError("set_design_variable requires a non-empty string value")
    if action == "delete_design_variable" and "value" in operation:
        raise ValueError("delete_design_variable does not accept value")

    session = _authorized_session(
        resource_id=resource_id,
        release_handle=release_handle,
        context=context,
        project=project,
        version=version,
        design=design,
    )
    app, connection_reused = _live_app(
        session=session,
        project=project,
        version=version,
        design=design,
    )
    observed_pid = int(app.odesktop.GetProcessID())
    if observed_pid != int(session["pid"]):
        raise PermissionError("AEDT resource process identity changed")
    if str(app.design_name) != design:
        raise PermissionError("AEDT resource active design identity changed")

    variables = app.variable_manager.variables
    before = str(app[name]) if name in variables else None
    if before != expected_before:
        raise RuntimeError(
            f"AEDT live patch precondition failed for {name}: "
            f"expected {expected_before!r}, got {before!r}"
        )

    if action == "set_design_variable":
        changed = app.variable_manager.set_variable(name, expression=value, overwrite=True)
        expected_after = value
    else:
        changed = app.variable_manager.delete_variable(name)
        expected_after = None
    if not changed:
        raise RuntimeError(f"AEDT rejected live patch operation for {name}")

    variables = app.variable_manager.variables
    actual = str(app[name]) if name in variables else None
    if actual != expected_after:
        raise RuntimeError(
            f"AEDT live patch readback failed for {name}: "
            f"expected {expected_after!r}, got {actual!r}"
        )
    return {
        "status": "passed",
        "project": str(Path(project).expanduser().resolve()),
        "design": design,
        "process_id": observed_pid,
        "session_ownership": session.get("ownership", "runtime-owned"),
        "connection_reused": connection_reused,
        "readback": {"name": name, "before": before, "actual": actual},
    }


def finalize_live_design(
    *,
    project: str | Path,
    version: str,
    design: str,
    action: str,
    decision: dict[str, Any] | None = None,
    resource_id: str | None = None,
    release_handle: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Keep, save, or explicitly discard one live AEDT design state."""

    if action not in {"keep_unsaved", "save", "discard_unsaved"}:
        raise ValueError("Unsupported Ansys live finalize action")
    session = _authorized_session(
        resource_id=resource_id,
        release_handle=release_handle,
        context=context,
        project=project,
        version=version,
        design=design,
    )
    app, connection_reused = _live_app(
        session=session,
        project=project,
        version=version,
        design=design,
    )
    if action == "keep_unsaved":
        return {
            "status": "passed",
            "design": design,
            "action": action,
            "session_ownership": session["ownership"],
            "connection_reused": connection_reused,
        }

    if not isinstance(decision, dict):
        raise ValueError("save and discard_unsaved require a decision object")
    authorization = str(decision.get("authorization") or "")
    reason = str(decision.get("reason") or "")
    if authorization not in {"user-confirmed", "agent-owned-session"} or not reason:
        raise ValueError("finalize decision is incomplete or unsupported")
    if (
        action == "discard_unsaved"
        and authorization == "agent-owned-session"
        and session.get("ownership") != "runtime-owned"
    ):
        raise PermissionError(
            "discard_unsaved agent-owned-session policy requires a Runtime-owned AEDT session"
        )
    if action == "save":
        if not app.save_project():
            raise RuntimeError("AEDT project save returned failure")
    else:
        project_name = str(app.project_name)
        if not app.close_project(name=project_name, save=False):
            raise RuntimeError("AEDT refused to close the project without saving")
        if not app.load_project(
            str(Path(project).expanduser().resolve()),
            design=design,
            close_active=False,
            set_active=True,
        ):
            raise RuntimeError("AEDT failed to reopen the discarded project")
        if str(app.design_name) != design:
            raise RuntimeError("AEDT reopened an unexpected design after discard")
    return {
        "status": "passed",
        "project": str(Path(project).expanduser().resolve()),
        "design": design,
        "action": action,
        "session_ownership": session["ownership"],
        "connection_reused": connection_reused,
        "decision": {"authorization": authorization, "reason": reason},
    }
