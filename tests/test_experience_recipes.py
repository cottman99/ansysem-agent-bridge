from __future__ import annotations

import zipfile
from pathlib import Path

from ansysem_agent_bridge.experience_recipes import (
    audit_odb_archive,
    compile_bondwire_plan,
    compile_gap_port_plan,
    compile_solution_observe_plan,
)
from ansysem_agent_bridge.hfss3dlayout_pyedb_adapter import (
    Hfss3dLayoutPyedbNativeAdapter,
)


def _identity(tmp_path: Path) -> dict:
    return {
        "operation_id": "synthetic-experience-recipe",
        "source_project": str(tmp_path / "source.aedt"),
        "output_project": str(tmp_path / "output.aedt"),
        "version": "2026.1",
        "design": "Layout1",
    }


def test_odb_audit_separates_present_data_from_missing_stackup(tmp_path: Path) -> None:
    archive = tmp_path / "board.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "job/matrix/matrix",
            "LAYER {\nNAME=top\nTYPE=SIGNAL\n}\nLAYER {\nNAME=bottom\nTYPE=SIGNAL\n}\n",
        )
        output.writestr(
            "job/steps/pcb/layers/comp_+_top/components",
            "CMP 0 1 2 0 N U1 DEVICE\nTOP 1 2 3\n",
        )
        output.writestr("job/steps/pcb/eda/data", "NET GND\nNET RF\n")
        output.writestr("job/steps/pcb/netlists/cadnet/netlist", "$1 GND\n$2 RF\n")
        output.writestr("job/steps/pcb/layers/drill_pth_through/features", "P 1 2 3\n")

    result = audit_odb_archive(archive)

    assert result["status"] == "passed"
    assert result["layers"]["signal"] == 2
    assert result["layers"]["dielectric"] == 0
    assert result["components"]["top"]["references"] == ["U1"]
    assert result["nets"]["name_lists_match"] is True
    assert result["through_drill_feature_count"] == 1
    assert "dielectric_stackup" in result["missing_or_unproven"]


def test_gap_port_recipe_requires_explicit_settings_and_reference_tokens(tmp_path: Path) -> None:
    contract = {
        **_identity(tmp_path),
        "expected_total_port_count": 1,
        "ports": [
            {
                "name": "P1",
                "positive_object": "SIG1",
                "selected_side": "B",
                "reference_patch": {"layer": "GND", "net": "GND", "depth_um": 100.0},
                "reference_tokens": ["GND"],
                "settings": {
                    "HFSS Type": "Gap",
                    "Renormalize": True,
                    "Renormalize Impedance": "50ohm + 0i ohm",
                    "DeembedParasiticPortInductance": False,
                },
            }
        ],
    }

    plan = compile_gap_port_plan(contract)

    assert plan["adapter"] == "hfss3dlayout.native/v1"
    assert plan["operations"][0]["type"] == "create_gap_port"
    assert {item["type"] for item in plan["assertions"]} >= {
        "port_count",
        "required_ports",
        "port_property_equals",
        "port_property_contains",
    }


def test_bondwire_recipe_keeps_endpoint_order_and_physical_apex_assertion(
    tmp_path: Path,
) -> None:
    profile = {
        "name": "REV",
        "direction": "reverse",
        "diameter_um": 25.0,
        "material": "Gold",
        "segments": [
            {
                "horizontal_mode": "absolute_um",
                "horizontal_value": 0.0,
                "vertical_mode": "absolute_um",
                "vertical_value": 150.0,
            },
            {
                "horizontal_mode": "fraction",
                "horizontal_value": 0.5,
                "vertical_mode": "absolute_um",
                "vertical_value": 0.0,
            },
        ],
    }
    contract = {
        **_identity(tmp_path),
        "profiles": [profile],
        "wires": [
            {
                "name": "BW1",
                "expected_before": {"bondwire_type": "jedec4"},
                "desired": {
                    "start_xy_um": [0.0, 0.0],
                    "end_xy_um": [300.0, 0.0],
                    "bondwire_type": "apd",
                    "profile": "REV",
                    "diameter_um": 25.0,
                    "material": "Gold",
                },
                "checks": {
                    "projected_length_um": 300.0,
                    "apex_endpoint": "end",
                },
            }
        ],
    }

    plan = compile_bondwire_plan(contract)

    apex = next(item for item in plan["assertions"] if item["type"] == "bondwire_apex_endpoint")
    assert apex == {"type": "bondwire_apex_endpoint", "name": "BW1", "value": "end"}


def test_apex_assertion_uses_realised_polyline_not_wire_name() -> None:
    assertion = {"type": "bondwire_apex_endpoint", "name": "ordinary_name", "value": "end"}
    result = Hfss3dLayoutPyedbNativeAdapter._assert(
        None,
        {},
        {"ordinary_name": [(0, 0, 0), (80, 0, 100), (100, 0, 100), (100, 0, 0)]},
        {},
        {},
        assertion,
    )

    assert result["passed"] is True
    assert result["actual"] == "end"


def test_solution_observe_recipe_never_starts_solver_and_is_pure_json(tmp_path: Path) -> None:
    source = str((tmp_path / "solved.aedt").resolve())
    plan = compile_solution_observe_plan(
        {
            "source_project": source,
            "version": "2026.1",
            "design": "Layout1",
            "solution": "Setup1 : Sweep1",
            "expressions": {
                "s11_db": "dB(S(P1,P1))",
                "s11_re": "re(S(P1,P1))",
                "s11_im": "im(S(P1,P1))",
            },
            "expected_frequency": [1.0, 2.0],
            "magnitude_pairs": [
                {"real_label": "s11_re", "imag_label": "s11_im", "maximum": 1.0001}
            ],
        }
    )

    assert plan["effect"] == "observe"
    assert plan["scope"]["selectors"]["include_results"] is True
    assert plan["scope"]["write_paths"] == []
    assert "analyze(" not in plan["program"]["source"]
    assert '"solver_started": False' in plan["program"]["source"]
