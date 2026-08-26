import json
from pathlib import Path

import jsonschema

from ansysem_agent_bridge.capabilities import capability_map

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_capability_map_does_not_claim_missing_project(tmp_path: Path) -> None:
    result = capability_map(project=tmp_path / "missing.aedt")
    assert result["project.inspect"]["state"]["declared"] is True
    assert result["project.inspect"]["state"]["available"] is False
    assert result["aedt.live_snapshot"]["state"]["available"] is False


def test_capability_map_keeps_image_export_non_mutating(tmp_path: Path) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("synthetic", encoding="utf-8")
    aedb = tmp_path / "synthetic.aedb"
    aedb.mkdir()
    (aedb / "edb.def").write_text("synthetic", encoding="utf-8")
    result = capability_map(project=project, display=":4.0")
    assert result["aedt.layout_export_image"]["mutates"] is False
    assert "exported image hash" in result["aedt.layout_export_image"]["evidence"]


def test_live_capability_requires_complete_layout_bundle(tmp_path: Path) -> None:
    project = tmp_path / "incomplete.aedt"
    project.write_text("synthetic", encoding="utf-8")
    result = capability_map(project=project, display=":4.0")
    assert result["project.inspect"]["state"]["available"] is True
    assert result["aedt.live_snapshot"]["state"]["available"] is False


def test_capability_descriptors_match_public_schema(tmp_path: Path) -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-capability-descriptor-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    for descriptor in capability_map(project=tmp_path / "missing.aedt").values():
        jsonschema.validate(descriptor, schema)
