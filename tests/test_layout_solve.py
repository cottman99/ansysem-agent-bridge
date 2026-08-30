from pathlib import Path

import pytest

from ansysem_agent_bridge.layout_solve import validate_layout_solve_plan


def _plan(tmp_path: Path) -> dict:
    return {
        "schema_version": "ansysem.hfss3dlayout-solve/v1",
        "operation_id": "solve_microstrip",
        "source_project": str(tmp_path / "candidate.aedt"),
        "output_project": str(tmp_path / "solved.aedt"),
        "version": "2026.1",
        "design": "MicrostripDemo",
        "setup": "Setup1",
        "sweep": {"name": "Sweep1", "start": "1GHz", "stop": "5GHz", "step": "1GHz"},
        "expressions": ["dB(S(P1,P1))", "dB(S(P2,P1))"],
        "report_name": "S Parameters",
        "minimum_points": 5,
        "cores": 1,
    }


def test_layout_solve_plan_accepts_bounded_result_contract(tmp_path: Path):
    plan = validate_layout_solve_plan(_plan(tmp_path))
    assert plan["minimum_points"] == 5
    assert plan["expressions"] == ["dB(S(P1,P1))", "dB(S(P2,P1))"]


def test_layout_solve_plan_rejects_raw_script(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["python"] = "escape()"
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_layout_solve_plan(plan)


def test_layout_solve_plan_rejects_unbounded_core_count(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["cores"] = 128
    with pytest.raises(ValueError, match="cores must be between"):
        validate_layout_solve_plan(plan)


def test_layout_solve_plan_rejects_reversed_sweep(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["sweep"].update(start="5GHz", stop="1GHz")
    with pytest.raises(ValueError, match="stop must be greater"):
        validate_layout_solve_plan(plan)
