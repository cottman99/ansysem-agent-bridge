import json
from pathlib import Path

import jsonschema

from ansysem_agent_bridge import operations

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_export_layout_image_returns_compact_operation_result(monkeypatch) -> None:
    def fake_probe(**kwargs):
        return {
            "status": "ready",
            "state_revision": "a" * 64,
            "identity": {
                "project_name": "synthetic",
                "design_name": "Layout1",
                "pid": 123,
            },
            "state": {
                "native_aedt_version": "2026.1.0",
                "designs": ["Layout1"],
                "setups": ["Setup1"],
                "ports": ["P1", "P2"],
            },
            "artifact": {"path": "view.png", "size": 42, "sha256": "b" * 64},
            "evidence_boundary": "presentation only",
        }

    monkeypatch.setattr(operations, "live_hfss3dlayout_probe", fake_probe)
    result = operations.export_layout_image(
        project="synthetic.aedt", output="view.png", version="2026.1"
    )
    assert result["status"] == "passed"
    assert result["readback"]["port_count"] == 2
    assert "ports" not in result["readback"]
    assert result["artifacts"][0]["sha256"] == "b" * 64
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-operation-result-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(result, schema)
