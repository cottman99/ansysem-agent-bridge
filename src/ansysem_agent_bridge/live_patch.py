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
_PATCH_JOURNAL: OrderedDict[tuple[int, int, str, str, str, str], dict[str, Any]] = OrderedDict()
_PATCH_JOURNAL_LIMIT = 64


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
    operation: dict[str, Any] | None = None,
    operations: list[dict[str, Any]] | None = None,
    patch_id: str | None = None,
) -> dict[str, Any]:
    """Apply one bounded patch without launching another AEDT process."""

    if operations is None:
        operations = [operation] if operation is not None else []
    if not isinstance(operations, list) or not operations or len(operations) > 32:
        raise ValueError("design.live_patch requires 1..32 typed operations")
    normalized = [_normalize_operation(item) for item in operations]

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

    journal_key = (
        int(session["pid"]),
        int(session["port"]),
        str(Path(project).expanduser().resolve()),
        str(version),
        str(design),
        str(patch_id or ""),
    )
    prior = _PATCH_JOURNAL.get(journal_key) if patch_id else None
    if prior is not None:
        _PATCH_JOURNAL.move_to_end(journal_key)
        return {**prior["result"], "status": "preserved"}

    inverse: list[dict[str, Any]] = []
    readback: list[dict[str, Any]] = []
    try:
        for item in normalized:
            observed, rollback = _apply_operation(app, item)
            readback.append(observed)
            inverse.append(rollback)
    except Exception:
        for rollback in reversed(inverse):
            _rollback_operation(app, rollback)
        raise

    result = {
        "status": "passed",
        "project": str(Path(project).expanduser().resolve()),
        "design": design,
        "patch_id": str(patch_id) if patch_id else None,
        "process_id": observed_pid,
        "session_ownership": session.get("ownership", "runtime-owned"),
        "connection_reused": connection_reused,
        "readback": (
            readback[0] if operation is not None and operations == [operation] else readback
        ),
        "reversible": True,
    }
    if patch_id:
        _PATCH_JOURNAL[journal_key] = {"inverse": inverse, "result": result}
        _PATCH_JOURNAL.move_to_end(journal_key)
        while len(_PATCH_JOURNAL) > _PATCH_JOURNAL_LIMIT:
            _PATCH_JOURNAL.popitem(last=False)
    return result


def _normalize_operation(operation: Any) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise TypeError("design.live_patch operation must be an object")
    action = str(operation.get("op") or "")
    if action in {"set_design_variable", "delete_design_variable"}:
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
        return dict(operation)
    if action == "create_layout_rectangle":
        name = str(operation.get("name") or "")
        layer = str(operation.get("layer") or "")
        origin = operation.get("origin")
        sizes = operation.get("sizes")
        net = operation.get("net")
        if not _VARIABLE_NAME.fullmatch(name) or not layer:
            raise ValueError("create_layout_rectangle requires a simple name and layer")
        for field_name, value in (("origin", origin), ("sizes", sizes)):
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(
                    not isinstance(part, (str, int, float)) or isinstance(part, bool)
                    for part in value
                )
            ):
                raise ValueError(f"create_layout_rectangle {field_name} is invalid")
        if net is not None and (not isinstance(net, str) or not net):
            raise ValueError("create_layout_rectangle net is invalid")
        return {
            "op": action,
            "name": name,
            "layer": layer,
            "origin": list(origin),
            "sizes": list(sizes),
            "net": net,
        }
    raise ValueError(f"unsupported AnsysEM live design operation: {action or '<missing>'}")


def _layout_fingerprint(modeler: Any, name: str) -> dict[str, Any] | None:
    editor = getattr(modeler, "oeditor", None)
    if editor is not None:
        try:
            properties = editor.GetProperties("BaseElementTab", name)
        except Exception:
            properties = []
        if properties:
            layer = editor.GetPropertyValue("BaseElementTab", name, "PlacementLayer")
            net = editor.GetPropertyValue("BaseElementTab", name, "Net")
            return {
                "name": name,
                "layer": str(layer or ""),
                "net": str(net or "") or None,
            }
    geometries = getattr(modeler, "geometries", None)
    if isinstance(geometries, dict):
        value = geometries.get(name)
        if value is not None:
            return {
                "name": str(getattr(value, "name", "") or ""),
                "layer": str(getattr(value, "placement_layer", "") or ""),
                "net": str(getattr(value, "net_name", "") or "") or None,
            }
    objects = getattr(modeler, "objects_by_name", None)
    if isinstance(objects, dict):
        value = objects.get(name)
        if value is not None:
            return {
                "name": str(getattr(value, "name", "") or ""),
                "layer": str(getattr(value, "placement_layer", "") or ""),
                "net": str(getattr(value, "net_name", "") or "") or None,
            }
    return None


def _apply_operation(app: Any, operation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    action = operation["op"]
    if action in {"set_design_variable", "delete_design_variable"}:
        name = operation["name"]
        variables = app.variable_manager.variables
        before = str(app[name]) if name in variables else None
        if before != operation.get("expected_before"):
            raise RuntimeError(
                f"AEDT live patch precondition failed for {name}: "
                f"expected {operation.get('expected_before')!r}, got {before!r}"
            )
        if action == "set_design_variable":
            changed = app.variable_manager.set_variable(
                name, expression=operation["value"], overwrite=True
            )
            expected_after = operation["value"]
        else:
            changed = app.variable_manager.delete_variable(name)
            expected_after = None
        if not changed:
            raise RuntimeError(f"AEDT rejected live patch operation for {name}")
        variables = app.variable_manager.variables
        actual = str(app[name]) if name in variables else None
        if actual != expected_after:
            if before is None:
                app.variable_manager.delete_variable(name)
            else:
                app.variable_manager.set_variable(name, expression=before, overwrite=True)
            raise RuntimeError(
                f"AEDT live patch readback failed for {name}: "
                f"expected {expected_after!r}, got {actual!r}"
            )
        return (
            {"name": name, "before": before, "actual": actual},
            {
                "op": "restore_variable",
                "name": name,
                "expected_current": actual,
                "value": before,
            },
        )

    modeler = app.modeler
    name = operation["name"]
    if _layout_fingerprint(modeler, name) is not None:
        raise RuntimeError(
            f"AEDT live patch precondition failed: layout object {name} already exists"
        )
    created = modeler.create_rectangle(
        layer=operation["layer"],
        origin=operation["origin"],
        sizes=operation["sizes"],
        name=name,
        net=operation.get("net"),
    )
    if not created:
        raise RuntimeError(f"AEDT rejected live rectangle creation for {name}")
    try:
        fingerprint = _layout_fingerprint(modeler, name) or {
            "name": str(getattr(created, "name", "") or ""),
            "layer": str(getattr(created, "placement_layer", "") or ""),
            "net": str(getattr(created, "net_name", "") or "") or None,
        }
        actual_name = fingerprint["name"]
        actual_layer = fingerprint["layer"]
        actual_net = fingerprint["net"]
        if actual_name != name or actual_layer != operation["layer"]:
            raise RuntimeError(f"AEDT live rectangle readback failed for {name}")
        if operation.get("net") is not None and actual_net != operation["net"]:
            raise RuntimeError(f"AEDT live rectangle net readback failed for {name}")
    except Exception:
        modeler.oeditor.Delete(name)
        cleanup = getattr(modeler, "cleanup_objects", None)
        if callable(cleanup):
            cleanup()
        raise
    return (
        {"op": action, **fingerprint},
        {"op": "delete_created_layout_object", **fingerprint},
    )


def _rollback_operation(app: Any, operation: dict[str, Any]) -> None:
    if operation["op"] == "restore_variable":
        name = operation["name"]
        variables = app.variable_manager.variables
        current = str(app[name]) if name in variables else None
        if current != operation["expected_current"]:
            raise RuntimeError(f"AEDT live rollback refused because variable {name} changed")
        if operation["value"] is None:
            changed = app.variable_manager.delete_variable(name)
        else:
            changed = app.variable_manager.set_variable(
                name, expression=operation["value"], overwrite=True
            )
        if not changed:
            raise RuntimeError(f"AEDT failed to restore variable {name}")
        return

    modeler = app.modeler
    fingerprint = _layout_fingerprint(modeler, operation["name"])
    if fingerprint is None:
        raise RuntimeError("AEDT live rollback target no longer exists")
    if fingerprint != {key: operation[key] for key in ("name", "layer", "net")}:
        raise RuntimeError(
            f"AEDT live rollback refused because layout object {operation['name']} changed"
        )
    modeler.oeditor.Delete(operation["name"])
    cleanup = getattr(modeler, "cleanup_objects", None)
    if callable(cleanup):
        cleanup()
    if _layout_fingerprint(modeler, operation["name"]) is not None:
        raise RuntimeError(f"AEDT layout object {operation['name']} still exists after rollback")


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

    if action not in {"keep_unsaved", "save", "discard_unsaved", "rollback_patch"}:
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
    if action == "rollback_patch":
        patch_id = str((decision or {}).get("patch_id") or "")
        if not patch_id:
            raise ValueError("rollback_patch requires decision.patch_id")
        key = (
            int(session["pid"]),
            int(session["port"]),
            str(Path(project).expanduser().resolve()),
            str(version),
            str(design),
            patch_id,
        )
        record = _PATCH_JOURNAL.get(key)
        if record is None:
            raise RuntimeError("AEDT live patch is not available for rollback")
        for rollback in reversed(record["inverse"]):
            _rollback_operation(app, rollback)
        del _PATCH_JOURNAL[key]
        return {
            "status": "passed",
            "design": design,
            "action": action,
            "patch_id": patch_id,
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
    for key in list(_PATCH_JOURNAL):
        if key[:5] == (
            int(session["pid"]),
            int(session["port"]),
            str(Path(project).expanduser().resolve()),
            str(version),
            str(design),
        ):
            del _PATCH_JOURNAL[key]
    return {
        "status": "passed",
        "project": str(Path(project).expanduser().resolve()),
        "design": design,
        "action": action,
        "session_ownership": session["ownership"],
        "connection_reused": connection_reused,
        "decision": {"authorization": authorization, "reason": reason},
    }
