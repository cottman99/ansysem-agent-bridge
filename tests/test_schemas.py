import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_schemas_are_valid_json_and_versioned() -> None:
    paths = sorted((REPO_ROOT / "docs" / "schemas").glob("*.schema.json"))
    assert len(paths) == 8
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


def test_operation_plan_schema_accepts_typed_bondwire_and_rejects_raw_block() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-operation-plan-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    profile = {
        "type": "ensure_apd_bondwire_profile",
        "name": "SYNTHETIC_PROFILE",
        "direction": "forward",
        "diameter_um": 25.4,
        "material": "Gold",
        "segments": [
            {
                "horizontal_mode": "fraction",
                "horizontal_value": 0.5,
                "vertical_mode": "absolute_um",
                "vertical_value": 200.0,
            }
        ],
    }
    plan = {
        "schema_version": 1,
        "operation_id": "synthetic-bondwire",
        "adapter": "hfss3dlayout.pyedb-native/v1",
        "source_project": "source.aedt",
        "output_project": "output.aedt",
        "version": "2026.1",
        "design": "Layout1",
        "source_fingerprint": {
            "aedt_sha256": "0" * 64,
            "edb_definition_sha256": "1" * 64,
        },
        "operations": [
            profile,
            {
                "type": "set_bondwire",
                "name": "BW_SYNTHETIC",
                "expected_before": {"bondwire_type": "jedec4"},
                "bondwire_type": "apd",
                "profile": "SYNTHETIC_PROFILE",
            },
        ],
        "assertions": [{"type": "bondwire_count", "value": 1}],
    }
    jsonschema.validate(plan, schema)
    profile["parameter_block"] = "bwd(raw=true)"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)


def test_workspace_patch_schema_requires_revision_and_stable_assertion_ids() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "schemas" / "ansysem-workspace-patch-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    patch = {
        "schema_version": 1,
        "patch_id": "synthetic-patch",
        "expected_workspace_revision": "0" * 64,
        "adapter": "hfss3dlayout.native/v1",
        "version": "2026.1",
        "design": "Layout1",
        "operations": [
            {"type": "set_property", "server": "trace", "property": "Net", "value": "SIG"}
        ],
        "assertions": [
            {
                "id": "trace.net",
                "type": "property_equals",
                "server": "trace",
                "property": "Net",
                "value": "SIG",
            }
        ],
    }
    jsonschema.validate(patch, schema)
    patch["operations"] = [{"type": "run_python", "code": "print('no')"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(patch, schema)


def test_hfss3dlayout_build_schema_accepts_typed_plan_and_rejects_python() -> None:
    schema = json.loads(
        (
            REPO_ROOT
            / "docs"
            / "schemas"
            / "ansysem-hfss3dlayout-build-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    plan = {
        "schema_version": "ansysem.hfss3dlayout-build/v1",
        "operation_id": "build_demo",
        "source_project": "source.aedt",
        "output_project": "candidate.aedt",
        "version": "2026.1",
        "design": "Layout1",
        "materials": [
            {"name": "Copper", "kind": "conductor", "conductivity": 58000000},
            {
                "name": "Substrate",
                "kind": "dielectric",
                "permittivity": 4.2,
                "loss_tangent": 0.02,
            },
        ],
        "layers": [
            {"name": "GND", "kind": "signal", "material": "Copper", "thickness": "35um"},
            {
                "name": "SUB",
                "kind": "dielectric",
                "material": "Substrate",
                "thickness": "0.8mm",
            },
            {"name": "TOP", "kind": "signal", "material": "Copper", "thickness": "35um"},
        ],
        "rectangles": [
            {
                "name": "GroundPlane",
                "layer": "GND",
                "net": "GND_NET",
                "lower_left": ["0mm", "0mm"],
                "upper_right": ["20mm", "10mm"],
            }
        ],
        "traces": [
            {
                "name": "SignalTrace",
                "layer": "TOP",
                "net": "SIG",
                "width": "1.5mm",
                "path": [["0mm", "5mm"], ["20mm", "5mm"]],
            }
        ],
        "ports": [
            {"name": "P1", "trace": "SignalTrace", "position": "Start", "type": "Wave"},
            {"name": "P2", "trace": "SignalTrace", "position": "End", "type": "Wave"},
        ],
        "setup": {"name": "Setup1", "start": "1GHz", "stop": "5GHz", "step": "1GHz"},
    }
    jsonschema.validate(plan, schema)
    plan["python"] = "not allowed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)


def test_hfss3dlayout_solve_schema_accepts_bounded_sweep_and_report() -> None:
    schema = json.loads(
        (
            REPO_ROOT
            / "docs"
            / "schemas"
            / "ansysem-hfss3dlayout-solve-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    plan = {
        "schema_version": "ansysem.hfss3dlayout-solve/v1",
        "operation_id": "solve_demo",
        "source_project": "candidate.aedt",
        "output_project": "solved.aedt",
        "version": "2026.1",
        "design": "Layout1",
        "setup": "Setup1",
        "sweep": {"name": "Sweep1", "start": "1GHz", "stop": "5GHz", "step": "1GHz"},
        "expressions": ["dB(S(P1,P1))", "dB(S(P2,P1))"],
        "report_name": "S Parameters",
        "minimum_points": 5,
        "cores": 1,
    }
    jsonschema.validate(plan, schema)
    plan["cores"] = 128
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, schema)
