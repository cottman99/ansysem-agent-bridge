import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_schemas_are_valid_json_and_versioned() -> None:
    paths = sorted((REPO_ROOT / "docs" / "schemas").glob("*.schema.json"))
    assert len(paths) == 4
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["$schema"].endswith("2020-12/schema")
        assert data["$id"].startswith("https://github.com/cottman99/ansysem-agent-bridge/")
