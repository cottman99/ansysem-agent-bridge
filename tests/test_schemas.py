import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_schemas_are_valid_json_and_versioned() -> None:
    paths = sorted((REPO_ROOT / "docs" / "schemas").glob("*.schema.json"))
    assert len(paths) == 5
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["$schema"].endswith("2020-12/schema")
        assert data["$id"].startswith("https://github.com/cottman99/ansysem-agent-bridge/")


def test_operation_plan_schema_accepts_only_typed_plan() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-operation-plan-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    plan = {
        "schema_version": 1,
        "operation_id": "synthetic",
        "adapter": "hfss3dlayout.native/v1",
        "source_project": "source.aedt",
        "output_project": "output.aedt",
        "version": "2026.1",
        "design": "Layout1",
        "solve_requested": False,
        "operations": [
            {"type": "set_property", "server": "trace", "property": "Net", "value": "SIG"}
        ],
        "assertions": [
            {"type": "property_equals", "server": "trace", "property": "Net", "value": "SIG"}
        ],
    }
    jsonschema.validate(plan, schema)
    plan["run_python"] = "not allowed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)
