from __future__ import annotations

import math

from ansysem_agent_bridge.hfss3dlayout_pyedb_adapter import (
    _segment_box_distance,
    compile_apd_parameter_block,
    point_in_polygon,
    polyline_distance,
)


def _profile() -> dict:
    return {
        "name": "SYNTHETIC_LH9_RUN55",
        "direction": "forward",
        "diameter_um": 25.4,
        "material": "Gold",
        "segments": [
            {
                "horizontal_mode": "absolute_um",
                "horizontal_value": 0,
                "vertical_mode": "absolute_um",
                "vertical_value": 228.6,
            },
            {
                "horizontal_mode": "fraction",
                "horizontal_value": 0.55,
                "vertical_mode": "absolute_um",
                "vertical_value": 0,
            },
        ],
    }


def test_apd_compiler_uses_units_and_typed_segments() -> None:
    block = compile_apd_parameter_block(_profile())
    assert "dia='25.4um'" in block
    assert "for=true" in block
    assert "nfc=6" in block
    assert "vt=0, vv=0.0002286" in block
    assert "ht=1, hv=0.55" in block
    assert block.count("seg(") == 1
    assert "), seg(" not in block


def test_endpoint_polygon_and_pair_clearance_geometry() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_polygon((5.0, 5.0), square)
    assert not point_in_polygon((20.0, 5.0), square)
    first = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    second = [(0.0, 4.0, 0.0), (10.0, 4.0, 0.0)]
    assert math.isclose(polyline_distance(first, second), 4.0)


def test_segment_obstacle_distance_detects_collision_and_clearance() -> None:
    box = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
    assert _segment_box_distance((-5.0, 5.0, 5.0), (15.0, 5.0, 5.0), box) < 1e-6
    assert math.isclose(
        _segment_box_distance((-5.0, 15.0, 5.0), (15.0, 15.0, 5.0), box),
        5.0,
        abs_tol=1e-6,
    )
