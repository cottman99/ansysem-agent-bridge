from __future__ import annotations

import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capabilities import capability_map
from .models import TargetIdentity, state_revision
from .project_bundle import inspect_project_bundle


def runtime_snapshot(
    *,
    installation_id: str | None = None,
    version: str | None = None,
    project: str | Path | None = None,
    design: str | None = None,
    editor: str | None = None,
    lane: str = "host",
    display: str | None = None,
    docs_root: str | Path | None = None,
    since_revision: str | None = None,
    redact_paths: bool = False,
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve() if project else None
    identity = TargetIdentity(
        host=socket.gethostname(),
        platform=platform.system(),
        installation_id=installation_id,
        version=version,
        display=display or os.environ.get("DISPLAY"),
        project_path=str(project_path) if project_path else None,
        project_name=project_path.stem if project_path else None,
        design_name=design,
        editor=editor,
        lane=lane,
    )
    state: dict[str, Any] = {
        "project_bundle": inspect_project_bundle(project_path, redact_paths=redact_paths)
        if project_path
        else None,
        "capability_states": capability_map(
            project=project_path, docs_root=docs_root, display=identity.display
        ),
    }
    fingerprint_payload = {"identity": identity.to_dict(redact_paths=redact_paths), "state": state}
    revision = state_revision(fingerprint_payload)
    changed = since_revision != revision
    payload: dict[str, Any] = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "state_revision": revision,
        "changed": changed,
        "identity": identity.to_dict(redact_paths=redact_paths),
    }
    if changed:
        payload["detail"] = "compact"
        payload["state"] = state
        payload["recommended_safe_actions"] = [
            "Resolve one exact AEDT installation and project before live work.",
            "Use capability state instead of probing support through arbitrary code.",
            "Request solver or visual evidence only when the workflow gate requires it.",
        ]
    return payload
