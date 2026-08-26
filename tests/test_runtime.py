import json
from pathlib import Path

import jsonschema

from ansysem_agent_bridge.runtime import runtime_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_suppresses_unchanged_state(tmp_path: Path) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("synthetic", encoding="utf-8")
    aedb = tmp_path / "synthetic.aedb"
    aedb.mkdir()
    (aedb / "edb.def").write_text("synthetic", encoding="utf-8")
    first = runtime_snapshot(project=project, version="2026.1", display=":4.0", redact_paths=True)
    second = runtime_snapshot(
        project=project,
        version="2026.1",
        display=":4.0",
        redact_paths=True,
        since_revision=first["state_revision"],
    )
    assert first["changed"] is True
    assert second["changed"] is False
    assert "state" not in second
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-runtime-snapshot-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(first, schema)
    jsonschema.validate(second, schema)
