from pathlib import Path

import pytest

from ansysem_agent_bridge.layout_build import validate_layout_build_plan


def _plan(tmp_path: Path) -> dict:
    return {
        "schema_version": "ansysem.hfss3dlayout-build/v1",
        "operation_id": "build_microstrip",
        "source_project": str(tmp_path / "source.aedt"),
        "output_project": str(tmp_path / "candidate.aedt"),
        "version": "2026.1",
        "design": "MicrostripDemo",
        "materials": [
            {"name": "CopperDemo", "kind": "conductor", "conductivity": 58000000},
            {
                "name": "DielectricDemo",
                "kind": "dielectric",
                "permittivity": 4.2,
                "loss_tangent": 0.02,
            },
        ],
        "layers": [
            {"name": "GND", "kind": "signal", "material": "CopperDemo", "thickness": "35um"},
            {
                "name": "SUB",
                "kind": "dielectric",
                "material": "DielectricDemo",
                "thickness": "0.8mm",
            },
            {"name": "TOP", "kind": "signal", "material": "CopperDemo", "thickness": "35um"},
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


def test_layout_build_plan_accepts_generic_stackup_geometry_and_setup(tmp_path: Path):
    plan = validate_layout_build_plan(_plan(tmp_path))
    assert [layer["name"] for layer in plan["layers"]] == ["GND", "SUB", "TOP"]
    assert [port["name"] for port in plan["ports"]] == ["P1", "P2"]


def test_layout_build_plan_rejects_raw_script(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["python"] = "escape()"
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_layout_build_plan(plan)


def test_layout_build_plan_rejects_port_on_unknown_trace(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["ports"][0]["trace"] = "Missing"
    with pytest.raises(ValueError, match=r"ports\[0\] is invalid"):
        validate_layout_build_plan(plan)


def test_layout_build_plan_supports_negative_coordinates_and_lossless_dielectric(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["materials"][1]["loss_tangent"] = 0
    plan["rectangles"][0]["lower_left"] = ["-10mm", "-5mm"]
    plan["rectangles"][0]["upper_right"] = ["10mm", "5mm"]
    validated = validate_layout_build_plan(plan)
    assert validated["rectangles"][0]["lower_left"] == ["-10mm", "-5mm"]


def test_layout_build_plan_rejects_dimension_unit_in_setup(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["setup"]["start"] = "1mm"
    with pytest.raises(ValueError, match="positive frequency"):
        validate_layout_build_plan(plan)


def test_layout_build_plan_rejects_dielectric_material_on_signal_layer(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["layers"][0]["material"] = "DielectricDemo"
    with pytest.raises(ValueError, match=r"layers\[0\] is invalid"):
        validate_layout_build_plan(plan)


def test_layout_build_plan_rejects_reversed_rectangle(tmp_path: Path):
    plan = _plan(tmp_path)
    plan["rectangles"][0]["upper_right"] = ["-1mm", "10mm"]
    with pytest.raises(ValueError, match="upper_right must exceed lower_left"):
        validate_layout_build_plan(plan)
