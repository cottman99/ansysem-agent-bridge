from __future__ import annotations

from pathlib import Path
from typing import Any

from .live_probe import live_hfss3dlayout_probe


def export_layout_image(
    *,
    project: str | Path,
    output: str | Path,
    version: str,
    design: str | None = None,
    port: int = 0,
    width: int = 1600,
    height: int = 1000,
    redact_paths: bool = False,
) -> dict[str, Any]:
    snapshot = live_hfss3dlayout_probe(
        project=project,
        version=version,
        design=design,
        port=port,
        export_image=output,
        image_width=width,
        image_height=height,
        redact_paths=redact_paths,
    )
    artifact = snapshot.get("artifact")
    identity = snapshot.get("identity", {})
    state = snapshot.get("state", {})
    passed = snapshot.get("status") == "ready" and bool(artifact)
    return {
        "schema_version": 1,
        "operation": "layout.export_image",
        "status": "passed" if passed else "failed",
        "identity": identity,
        "readback": {
            "state_revision": snapshot.get("state_revision"),
            "native_aedt_version": state.get("native_aedt_version"),
            "design_count": len(state.get("designs", [])),
            "setup_count": len(state.get("setups", [])),
            "port_count": len(state.get("ports", [])),
        },
        "artifacts": [artifact] if artifact else [],
        "validation": [
            {
                "id": "artifact.nonempty",
                "passed": bool(artifact and artifact.get("size", 0) > 0 and artifact.get("sha256")),
            },
            {
                "id": "target.identity",
                "passed": bool(
                    identity.get("project_name")
                    and identity.get("design_name")
                    and identity.get("pid")
                ),
            },
        ],
        "warnings": [snapshot.get("evidence_boundary")],
        "failure": None if passed else {"reason": "image_export_did_not_produce_verified_artifact"},
        "safe_next_actions": [
            "Use the artifact only as presentation evidence; request solver evidence separately "
            "when required."
        ],
    }
