from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ansysem_agent_bridge.project_bundle import sha256_file
from ansysem_agent_bridge.transaction import execute_operation_plan, validate_operation_plan


def _bundle(root: Path, name: str = "source") -> Path:
    project = root / f"{name}.aedt"
    project.write_text("source", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("definition", encoding="utf-8")
    return project


def _plan(source: Path, output: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation_id": "synthetic-transaction",
        "adapter": "hfss3dlayout.native/v1",
        "source_project": str(source),
        "output_project": str(output),
        "version": "2026.1",
        "design": "Layout1",
        "solve_requested": False,
        "operations": [
            {"type": "set_property", "server": "trace", "property": "Net", "value": "SIG"}
        ],
        "assertions": [
            {
                "type": "property_equals",
                "server": "trace",
                "property": "Net",
                "value": "SIG",
            }
        ],
    }


class FakeAdapter:
    adapter_id = "hfss3dlayout.native/v1"

    def __init__(self, *, passes: bool = True) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.passes = passes

    def apply(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("apply", project))
        project.write_text("modified", encoding="utf-8")
        return {"operation_count": 1}

    def verify(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("verify", project))
        assert project.read_text(encoding="utf-8") == "modified"
        return {
            "readback": {"port_count": 2},
            "validation": [{"id": "fresh", "passed": self.passes}],
        }


def test_transaction_commits_only_after_fresh_verify(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    output = tmp_path / "output.aedt"
    source_hash = sha256_file(source)
    adapter = FakeAdapter()
    result = execute_operation_plan(_plan(source, output), adapter=adapter)
    assert result["status"] == "passed"
    assert [call[0] for call in adapter.calls] == ["apply", "verify"]
    assert output.read_text(encoding="utf-8") == "modified"
    assert (output.with_suffix(".aedb") / "edb.def").is_file()
    assert sha256_file(source) == source_hash
    assert result["readback"]["solve_run"] is False
    assert not list(tmp_path.glob(".ansysem-stage-*"))


def test_failed_assertion_leaves_no_output(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    output = tmp_path / "output.aedt"
    result = execute_operation_plan(_plan(source, output), adapter=FakeAdapter(passes=False))
    assert result["status"] == "failed"
    assert not output.exists()
    assert not output.with_suffix(".aedb").exists()
    assert result["readback"]["source_unchanged"] is True
    assert not list(tmp_path.glob(".ansysem-stage-*"))


def test_transaction_refuses_overwrite_and_arbitrary_operation(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    output = _bundle(tmp_path, "output")
    with pytest.raises(ValueError, match="overwrite is refused"):
        execute_operation_plan(_plan(source, output), adapter=FakeAdapter())
    plan = _plan(source, tmp_path / "new.aedt")
    plan["operations"] = [{"type": "run_python", "code": "print('no')"}]
    with pytest.raises(ValueError, match="Unsupported typed operation"):
        validate_operation_plan(plan)

    plan = _plan(source, tmp_path / "new.aedt")
    plan["operations"][0]["code"] = "print('still no')"
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_operation_plan(plan)


def test_transaction_refuses_solve_request(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    plan = _plan(source, tmp_path / "new.aedt")
    plan["solve_requested"] = True
    with pytest.raises(ValueError, match="do not run solves"):
        validate_operation_plan(plan)


def _bondwire_plan(source: Path, output: Path) -> dict[str, Any]:
    plan = _plan(source, output)
    plan["adapter"] = "hfss3dlayout.pyedb-native/v1"
    plan["operations"] = [
        {
            "type": "ensure_apd_bondwire_profile",
            "name": "SYNTHETIC_LH8_RUN50",
            "direction": "forward",
            "diameter_um": 25.4,
            "material": "Gold",
            "segments": [
                {
                    "horizontal_mode": "absolute_um",
                    "horizontal_value": 0,
                    "vertical_mode": "absolute_um",
                    "vertical_value": 203.2,
                },
                {
                    "horizontal_mode": "fraction",
                    "horizontal_value": 0.5,
                    "vertical_mode": "absolute_um",
                    "vertical_value": 0,
                },
            ],
        },
        {
            "type": "set_bondwire",
            "name": "BW_SYNTHETIC",
            "expected_before": {"bondwire_type": "jedec4"},
            "end_xy_um": [300.0, 0.0],
            "bondwire_type": "apd",
            "profile": "SYNTHETIC_LH8_RUN50",
        },
    ]
    plan["assertions"] = [
        {"type": "bondwire_count", "value": 1},
        {
            "type": "bondwire_projected_length",
            "name": "BW_SYNTHETIC",
            "value_um": 300.0,
            "tolerance_um": 2.0,
        },
        {"type": "geometry_check_clean"},
    ]
    return plan


def test_bondwire_plan_is_typed_and_rejects_raw_apd(tmp_path: Path) -> None:
    plan = _bondwire_plan(_bundle(tmp_path), tmp_path / "new.aedt")
    validate_operation_plan(plan)
    plan["operations"][0]["parameter_block"] = "bwd(arbitrary=true)"
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_operation_plan(plan)


def test_bondwire_plan_requires_exact_before_state(tmp_path: Path) -> None:
    plan = _bondwire_plan(_bundle(tmp_path), tmp_path / "new.aedt")
    plan["operations"][1]["expected_before"] = {}
    with pytest.raises(ValueError, match="non-empty"):
        validate_operation_plan(plan)


def test_source_fingerprint_mismatch_fails_before_staging(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    output = tmp_path / "new.aedt"
    plan = _plan(source, output)
    plan["source_fingerprint"] = {
        "aedt_sha256": "0" * 64,
        "edb_definition_sha256": "1" * 64,
    }
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        execute_operation_plan(plan, adapter=FakeAdapter())
    assert not output.exists()
    assert not list(tmp_path.glob(".ansysem-stage-*"))
