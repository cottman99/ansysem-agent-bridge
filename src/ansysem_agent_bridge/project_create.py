"""Create and freshly verify one isolated HFSS 3D Layout project."""

from __future__ import annotations

import os
import re
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

from .aedt_context_tool import store_context
from .live_probe import live_hfss3dlayout_probe

_DESIGN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_ -]{0,127}")


def _remove_owned_partial_bundle(project_path: Path) -> None:
    for path in (
        project_path,
        project_path.with_suffix(".aedb"),
        Path(str(project_path) + "results"),
    ):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def create_hfss3dlayout_project(
    *,
    project: str | Path,
    design: str,
    version: str,
    connection_id: str | None = None,
    profile: str | None = None,
    expected_display: str | None = None,
    redact_paths: bool = True,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve()
    if project_path.suffix.casefold() != ".aedt":
        raise ValueError("project.create requires an output path ending in .aedt")
    if not _DESIGN_NAME.fullmatch(design):
        raise ValueError("design must be a simple AEDT design name")
    actual_display = os.environ.get("DISPLAY")
    if expected_display and actual_display != expected_display:
        raise RuntimeError(
            f"Configured DISPLAY mismatch: expected {expected_display}, got {actual_display}"
        )
    bundle_path = project_path.with_suffix(".aedb")
    if project_path.exists() or bundle_path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing AEDT bundle: {project_path}")
    project_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from ansys.aedt.core import Hfss3dLayout
    except ImportError as exc:
        raise RuntimeError("PyAEDT is not available in this Python environment.") from exc

    try:
        app = None
        try:
            app = Hfss3dLayout(
                project=str(project_path),
                design=design,
                version=version,
                non_graphical=False,
                new_desktop=True,
                close_on_exit=True,
            )
            if app.design_name != design:
                raise RuntimeError(f"AEDT created an unexpected design: {app.design_name}")
            if not app.save_project():
                raise RuntimeError("AEDT project save returned failure")
        finally:
            if app is not None:
                with suppress(Exception):
                    app.release_desktop(close_projects=True, close_desktop=True)

        if not project_path.is_file() or not (bundle_path / "edb.def").is_file():
            raise RuntimeError("AEDT did not persist a complete HFSS 3D Layout bundle")
        observed = live_hfss3dlayout_probe(
            project=project_path,
            version=version,
            design=design,
            new_desktop=True,
            close_desktop=True,
            redact_paths=redact_paths,
        )
        if observed.get("status") != "ready":
            raise RuntimeError("Fresh AEDT reopen did not return a ready project")
        identity = {
            "connection_id": connection_id,
            "profile": profile,
            "project": str(project_path),
            "project_name": project_path.stem,
            "design": design,
            "version": version,
            "display": actual_display,
        }
        token = store_context(identity, connection_id=connection_id)
        return {
            "status": "passed",
            "created": True,
            "project": project_path.name if redact_paths else str(project_path),
            "design": design,
            "display": actual_display,
            "fresh_reopen": observed,
            "eda_context": token,
        }
    except Exception:  # noqa: BLE001 - cleanup must cover vendor API failures
        with suppress(OSError):
            _remove_owned_partial_bundle(project_path)
        raise
