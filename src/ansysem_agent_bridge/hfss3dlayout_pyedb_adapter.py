from __future__ import annotations

import math
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from .hfss3dlayout_adapter import Hfss3dLayoutNativeAdapter, _all_ports

_MODE_CODE = {"absolute_um": 0, "fraction": 1, "angle_deg": 2, "switch": 3}
_NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def compile_apd_parameter_block(operation: dict[str, Any]) -> str:
    """Compile a typed APD profile without accepting executable or raw APD text."""
    segments = []
    for item in operation["segments"]:
        horizontal = float(item["horizontal_value"])
        vertical = float(item["vertical_value"])
        if item["horizontal_mode"] == "absolute_um":
            horizontal *= 1e-6
        if item["vertical_mode"] == "absolute_um":
            vertical *= 1e-6
        segments.append(
            "seg(ht={ht}, hv={hv:.12g}, vt={vt}, vv={vv:.12g})".format(
                ht=_MODE_CODE[item["horizontal_mode"]],
                hv=horizontal,
                vt=_MODE_CODE[item["vertical_mode"]],
                vv=vertical,
            )
        )
    diameter = f"{float(operation['diameter_um']):.12g}um"
    material = str(operation["material"]).replace("'", "").upper()
    name = str(operation["name"]).replace("'", "")
    forward = operation["direction"] == "forward"
    return (
        f"bwd(nm='{name}', ven=false, for={'true' if forward else 'false'}, "
        f"dia='{diameter}', mat='{material}', col=0, vis=true, dih=0, "
        f"nfc={len(segments)}, {', '.join(segments)})"
    )


def _number(value: Any) -> float:
    if hasattr(value, "value"):
        return float(value.value)
    return float(value)


def _wire_state(wire: Any) -> dict[str, Any]:
    trajectory = [_number(item) * 1e6 for item in wire.core.get_traj()]
    return {
        "start_xy_um": trajectory[:2],
        "end_xy_um": trajectory[2:],
        "bondwire_type": str(wire.type).casefold(),
        "profile": str(wire.get_definition_name()),
        "diameter_um": _number(wire.width) * 1e6,
        "material": str(wire.material),
    }


def _close(actual: Any, expected: Any, tolerance: float = 1e-3) -> bool:
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                abs(float(left) - float(right)) <= tolerance
                for left, right in zip(actual, expected, strict=True)
            )
        )
    if isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= tolerance
    return str(actual).casefold() == str(expected).casefold()


def _assert_expected_before(wire: Any, expected: dict[str, Any]) -> None:
    actual = _wire_state(wire)
    failures = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if not _close(actual.get(key), value)
    }
    if failures:
        raise RuntimeError(f"Bondwire precondition failed for {wire.aedt_name}: {failures}")


def _bondwires(edb: Any) -> dict[str, Any]:
    return {
        str(item.aedt_name): item
        for item in edb.layout.primitives
        if str(item.primitive_type).casefold() == "bondwire"
    }


def _ensure_profile(edb: Any, operation: dict[str, Any]) -> dict[str, Any]:
    from pyedb.grpc.database.definition.wirebond_def import ApdBondwireDef

    name = str(operation["name"])
    definitions = dict(edb.definitions.apd_bondwires)
    parameter_block = compile_apd_parameter_block(operation)
    definition = definitions.get(name)
    created = definition is None
    if definition is None:
        definition = ApdBondwireDef.create(edb, name)
    definition.parameter_block = parameter_block
    actual_block = str(definition.parameter_block)
    required_tokens = (
        f"nm='{name}'",
        f"for={'true' if operation['direction'] == 'forward' else 'false'}",
        f"mat='{str(operation['material']).replace(chr(39), '').upper()}'",
        f"nfc={len(operation['segments'])}",
    )
    if not all(token in actual_block for token in required_tokens):
        raise RuntimeError(f"APD profile readback failed for {name}: {actual_block}")
    return {"type": operation["type"], "name": name, "created": created}


def _set_bondwire(edb: Any, operation: dict[str, Any]) -> dict[str, Any]:
    wires = _bondwires(edb)
    name = str(operation["name"])
    if name not in wires:
        raise RuntimeError(f"Bondwire not found: {name}")
    wire = wires[name]
    _assert_expected_before(wire, operation["expected_before"])
    before = _wire_state(wire)
    start = operation.get("start_xy_um", before["start_xy_um"])
    end = operation.get("end_xy_um", before["end_xy_um"])
    wire.core.set_traj(*(float(item) * 1e-6 for item in [*start, *end]))
    if "bondwire_type" in operation:
        wire.type = str(operation["bondwire_type"])
    if "profile" in operation:
        wire.set_definition_name(str(operation["profile"]))
    if "diameter_um" in operation:
        wire.width = float(operation["diameter_um"]) * 1e-6
        with suppress(Exception):
            wire.cross_section_height = float(operation["diameter_um"]) * 1e-6
    if "material" in operation:
        wire.material = str(operation["material"])
    after = _wire_state(wire)
    for key in (
        "start_xy_um",
        "end_xy_um",
        "bondwire_type",
        "profile",
        "diameter_um",
        "material",
    ):
        if key in operation and not _close(after[key], operation[key]):
            raise RuntimeError(f"Bondwire readback failed for {name}.{key}: {after[key]!r}")
    return {"type": operation["type"], "name": name, "before": before, "after": after}


def _parse_length_um(value: str) -> float:
    match = re.fullmatch(r"\s*([+-]?[0-9.eE]+)\s*(mm|um|mil)\s*", value)
    if not match:
        raise ValueError(f"Unsupported profile length: {value!r}")
    return float(match.group(1)) * {"mm": 1000.0, "um": 1.0, "mil": 25.4}[match.group(2)]


def _profile_specs(edb: Any, plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for operation in plan["operations"]:
        if operation["type"] == "ensure_apd_bondwire_profile":
            absolute_vertical = [
                float(item["vertical_value"])
                for item in operation["segments"]
                if item["vertical_mode"] == "absolute_um"
            ]
            fractions = [
                float(item["horizontal_value"])
                for item in operation["segments"]
                if item["horizontal_mode"] == "fraction"
            ]
            specs[str(operation["name"])] = {
                "height_um": max(absolute_vertical, default=0.0),
                "run_fraction": max(fractions, default=0.0),
                "diameter_um": float(operation["diameter_um"]),
                "direction": operation["direction"],
            }
    for key, definition in edb.definitions.apd_bondwires.items():
        block = str(definition.parameter_block)
        absolute_vertical = [
            float(value) * 1e6 for value in re.findall(rf"vt=0,\s*vv=({_NUMBER_PATTERN})", block)
        ]
        fractions = [
            float(value) for value in re.findall(rf"ht=1,\s*hv=({_NUMBER_PATTERN})", block)
        ]
        diameter = re.search(r"dia='([^']+)'", block)
        spec = {
            "height_um": max(absolute_vertical, default=0.0),
            "run_fraction": max(fractions, default=0.0),
            "diameter_um": _parse_length_um(diameter.group(1)) if diameter else 0.0,
            "direction": "forward" if "for=true" in block else "reverse",
        }
        names = {str(key), str(key).split(":")[-1]}
        embedded_name = re.search(r"nm='([^']+)'", block)
        if embedded_name:
            names |= {embedded_name.group(1), embedded_name.group(1).split(":")[-1]}
        for name in names:
            specs.setdefault(name, spec)
    return specs


def _wire_polyline(
    edb: Any, wire: Any, profile: dict[str, Any]
) -> list[tuple[float, float, float]]:
    state = _wire_state(wire)
    start_context, start_layer = wire.core.get_start_elevation()
    end_context, end_layer = wire.core.get_end_elevation()
    del start_context, end_context
    start_z = _number(edb.stackup.layers[start_layer.name].upper_elevation) * 1e6
    end_z = _number(edb.stackup.layers[end_layer.name].upper_elevation) * 1e6
    start_x, start_y = state["start_xy_um"]
    end_x, end_y = state["end_xy_um"]
    height = float(profile["height_um"])
    fraction = float(profile.get("run_fraction", 0.0))
    if profile.get("direction") == "reverse":
        peak_z = end_z + height
        return [
            (start_x, start_y, start_z),
            (
                end_x + fraction * (start_x - end_x),
                end_y + fraction * (start_y - end_y),
                peak_z,
            ),
            (end_x, end_y, peak_z),
            (end_x, end_y, end_z),
        ]
    peak_z = start_z + height
    return [
        (start_x, start_y, start_z),
        (start_x, start_y, peak_z),
        (
            start_x + fraction * (end_x - start_x),
            start_y + fraction * (end_y - start_y),
            peak_z,
        ),
        (end_x, end_y, end_z),
    ]


def _dot(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


def segment_distance(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    q0: tuple[float, float, float],
    q1: tuple[float, float, float],
) -> float:
    """Shortest distance between two closed 3-D segments."""
    epsilon = 1e-12
    u = tuple(b - a for a, b in zip(p0, p1, strict=True))
    v = tuple(b - a for a, b in zip(q0, q1, strict=True))
    w = tuple(a - b for a, b in zip(p0, q0, strict=True))
    a, b, c, d, e = _dot(u, u), _dot(u, v), _dot(v, v), _dot(u, w), _dot(v, w)
    denominator = a * c - b * b
    sn, sd, tn, td = denominator, denominator, denominator, denominator
    if denominator < epsilon:
        sn, sd, tn, td = 0.0, 1.0, e, c
    else:
        sn, tn = b * e - c * d, a * e - b * d
        if sn < 0:
            sn, tn, td = 0.0, e, c
        elif sn > sd:
            sn, tn, td = sd, e + b, c
    if tn < 0:
        tn = 0.0
        if -d < 0:
            sn = 0.0
        elif -d > a:
            sn = sd
        else:
            sn, sd = -d, a
    elif tn > td:
        tn = td
        if -d + b < 0:
            sn = 0.0
        elif -d + b > a:
            sn = sd
        else:
            sn, sd = -d + b, a
    sc = 0.0 if abs(sn) < epsilon else sn / sd
    tc = 0.0 if abs(tn) < epsilon else tn / td
    delta = tuple(wi + sc * ui - tc * vi for wi, ui, vi in zip(w, u, v, strict=True))
    return math.sqrt(_dot(delta, delta))


def polyline_distance(
    first: list[tuple[float, float, float]], second: list[tuple[float, float, float]]
) -> float:
    return min(
        segment_distance(p0, p1, q0, q1)
        for p0, p1 in zip(first, first[1:], strict=False)
        for q0, q1 in zip(second, second[1:], strict=False)
    )


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, polygon[1:] + polygon[:1], strict=False):
        x1, y1 = first
        x2, y2 = second
        cross = (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1
        inside ^= bool(cross)
    return inside


def _primitive_polygon_um(primitive: Any) -> list[tuple[float, float]]:
    with suppress(Exception):
        points = [
            (_number(point[0]) * 1e6, _number(point[1]) * 1e6)
            for point in primitive.polygon_data.points
        ]
        if len(points) >= 3:
            return points
    bbox = [_number(value) * 1e6 for value in primitive.bbox]
    return [(bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[2], bbox[3]), (bbox[0], bbox[3])]


def _point_box_distance(point: tuple[float, float, float], box: tuple[float, ...]) -> float:
    return math.sqrt(
        sum(
            (low - value) ** 2 if value < low else (value - high) ** 2 if value > high else 0.0
            for value, low, high in zip(point, box[:3], box[3:], strict=True)
        )
    )


def _segment_box_distance(
    start: tuple[float, float, float], end: tuple[float, float, float], box: tuple[float, ...]
) -> float:
    # Distance-to-box along a segment is convex; ternary minimization is stable and bounded.
    low, high = 0.0, 1.0
    direction = tuple(b - a for a, b in zip(start, end, strict=True))
    for _ in range(80):
        one = low + (high - low) / 3
        two = high - (high - low) / 3
        p1 = tuple(a + one * delta for a, delta in zip(start, direction, strict=True))
        p2 = tuple(a + two * delta for a, delta in zip(start, direction, strict=True))
        if _point_box_distance(p1, box) <= _point_box_distance(p2, box):
            high = two
        else:
            low = one
    point = tuple(a + (low + high) / 2 * delta for a, delta in zip(start, direction, strict=True))
    return _point_box_distance(point, box)


def _obstacle_box_um(edb: Any, primitive: Any) -> tuple[float, ...]:
    bbox = [_number(item) * 1e6 for item in primitive.bbox]
    layer = edb.stackup.layers[primitive.layer_name]
    low_z = _number(layer.lower_elevation) * 1e6
    high_z = _number(layer.upper_elevation) * 1e6
    return (bbox[0], bbox[1], min(low_z, high_z), bbox[2], bbox[3], max(low_z, high_z))


def _trim_polyline(
    points: list[tuple[float, float, float]], distance_um: float
) -> list[tuple[float, float, float]]:
    remaining = distance_um
    result = list(points)
    while len(result) > 1 and remaining > 0:
        length = math.dist(result[0], result[1])
        if remaining >= length:
            remaining -= length
            result.pop(0)
        else:
            ratio = remaining / length
            result[0] = tuple(
                left + ratio * (right - left)
                for left, right in zip(result[0], result[1], strict=True)
            )
            remaining = 0
    return result


def _geometry_check(app: Any) -> dict[str, Any]:
    checks = [
        "Self-Intersecting Polygons",
        "Disjoint Nets (Floating Nodes)",
        "DC-Short Errors",
        "Identical/Overlapping Vias",
        "Misaligments",
    ]
    result = app.oeditor.GeometryCheckAndAutofix(
        ["NAME:checks", *checks], "minimum_area_meters_squared:=", 0.0, ["NAME:fixes"]
    )
    passed = result in (None, True, 0, "", "0", "true", "True")
    return {"passed": passed, "checks": checks, "autofix": False, "raw_result": str(result)}


class Hfss3dLayoutPyedbNativeAdapter:
    adapter_id = "hfss3dlayout.pyedb-native/v1"

    @staticmethod
    def _open_edb(project: Path, plan: dict[str, Any]) -> Any:
        from pyedb import Edb

        return Edb(str(project.with_suffix(".aedb")), version=str(plan["version"]), grpc=True)

    def apply(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        edb = self._open_edb(project, plan)
        records = []
        try:
            for operation in plan["operations"]:
                if operation["type"] == "ensure_apd_bondwire_profile":
                    records.append(_ensure_profile(edb, operation))
                elif operation["type"] == "set_bondwire":
                    records.append(_set_bondwire(edb, operation))
                else:
                    raise ValueError(f"Unsupported PyEDB typed operation: {operation['type']}")
            if edb.save() is False:
                raise RuntimeError("PyEDB save returned failure")
        finally:
            edb.close()
        app = Hfss3dLayoutNativeAdapter._open(project, plan)
        try:
            if not app.save_project():
                raise RuntimeError("AEDT project save returned failure")
        finally:
            app.release_desktop(close_projects=True, close_desktop=True)
        return {"operation_count": len(records), "operations": records}

    def verify(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        native = Hfss3dLayoutNativeAdapter._open(project, plan)
        try:
            ports = _all_ports(native.oeditor, native.odesign.GetModule("Excitations"))
            setups = sorted(str(item) for item in native.setup_names)
            geometry = _geometry_check(native)
            port_properties = {}
            for assertion in plan["assertions"]:
                if assertion["type"] in {"port_property_equals", "port_property_contains"}:
                    port = str(assertion["port"])
                    prop = str(assertion["property"])
                    excitation = native.odesign.GetChildObject("Excitations").GetChildObject(port)
                    port_properties.setdefault(port, {})[prop] = excitation.GetPropValue(prop)
            native_context = {
                "design": native.design_name,
                "display": os.environ.get("DISPLAY"),
                "ports": ports,
                "setups": setups,
                "geometry": geometry,
                "port_properties": port_properties,
            }
        finally:
            native.release_desktop(close_projects=True, close_desktop=True)

        edb = self._open_edb(project, plan)
        try:
            profiles = _profile_specs(edb, plan)
            wires = _bondwires(edb)
            polylines = {
                name: _wire_polyline(edb, wire, profiles[wire.get_definition_name()])
                for name, wire in wires.items()
            }
            validations = [
                self._assert(edb, wires, polylines, profiles, native_context, assertion)
                for assertion in plan["assertions"]
            ]
            readback_wires = {name: _wire_state(wire) for name, wire in wires.items()}
        finally:
            edb.close()
        return {
            "readback": {
                "design": native_context["design"],
                "display": native_context["display"],
                "port_count": len(native_context["ports"]),
                "port_properties": native_context["port_properties"],
                "setup_count": len(native_context["setups"]),
                "bondwire_count": len(readback_wires),
                "bondwires": readback_wires,
                "geometry_check": geometry,
            },
            "validation": validations,
        }

    @staticmethod
    def _assert(
        edb: Any,
        wires: dict[str, Any],
        polylines: dict[str, list[tuple[float, float, float]]],
        profiles: dict[str, dict[str, Any]],
        native: dict[str, Any],
        assertion: dict[str, Any],
    ) -> dict[str, Any]:
        kind = assertion["type"]
        expected: Any
        actual: Any
        if kind == "bondwire_count":
            actual, expected = len(wires), assertion["value"]
        elif kind == "bondwire_matches":
            state = _wire_state(wires[assertion["name"]])
            expected = assertion["expected"]
            tolerance = float(assertion.get("tolerance_um", 1e-3))
            actual = {key: state.get(key) for key in expected}
            passed = all(_close(actual[key], value, tolerance) for key, value in expected.items())
            return _record(assertion, kind, passed, expected, actual)
        elif kind == "bondwire_projected_length":
            state = _wire_state(wires[assertion["name"]])
            actual = math.dist(state["start_xy_um"], state["end_xy_um"])
            expected = float(assertion["value_um"])
            return _record(
                assertion,
                kind,
                abs(actual - expected) <= float(assertion["tolerance_um"]),
                expected,
                actual,
            )
        elif kind == "bondwire_profile_height":
            profile = profiles[wires[assertion["name"]].get_definition_name()]
            actual, expected = profile["height_um"], float(assertion["value_um"])
            return _record(
                assertion,
                kind,
                abs(actual - expected) <= float(assertion["tolerance_um"]),
                expected,
                actual,
            )
        elif kind == "bondwire_endpoint_in_conductor":
            state = _wire_state(wires[assertion["name"]])
            point = tuple(state[f"{assertion['endpoint']}_xy_um"])
            matches = [
                item
                for item in edb.layout.primitives
                if str(item.aedt_name) == assertion["conductor"]
                or str(item.layer_name) == assertion["conductor"]
            ]
            actual = any(point_in_polygon(point, _primitive_polygon_um(item)) for item in matches)
            expected = True
        elif kind == "bondwire_pairwise_clearance":
            names = assertion.get("names", sorted(wires))
            pairs = []
            for index, first in enumerate(names):
                for second in names[index + 1 :]:
                    center = polyline_distance(polylines[first], polylines[second])
                    surface = (
                        center
                        - (
                            _wire_state(wires[first])["diameter_um"]
                            + _wire_state(wires[second])["diameter_um"]
                        )
                        / 2
                    )
                    pairs.append({"first": first, "second": second, "surface_um": surface})
            actual = min((item["surface_um"] for item in pairs), default=math.inf)
            expected = float(assertion["minimum_um"])
            return _record(
                assertion,
                kind,
                actual >= expected,
                expected,
                {"minimum_um": actual, "pairs": pairs},
            )
        elif kind == "bondwire_obstacle_clearance":
            wire = wires[assertion["name"]]
            points = _trim_polyline(
                polylines[assertion["name"]],
                float(assertion.get("start_contact_exemption_um", 0.0)),
            )
            primitives = {str(item.aedt_name): item for item in edb.layout.primitives} | {
                str(item.layer_name): item for item in edb.layout.primitives
            }
            distances = []
            for name in assertion["obstacles"]:
                box = _obstacle_box_um(edb, primitives[name])
                center = min(
                    _segment_box_distance(start, end, box)
                    for start, end in zip(points, points[1:], strict=False)
                )
                distances.append(
                    {"obstacle": name, "surface_um": center - _wire_state(wire)["diameter_um"] / 2}
                )
            actual = min(item["surface_um"] for item in distances)
            expected = float(assertion["minimum_um"])
            return _record(
                assertion,
                kind,
                actual >= expected,
                expected,
                {"minimum_um": actual, "obstacles": distances},
            )
        elif kind == "geometry_check_clean":
            actual, expected = native["geometry"]["passed"], True
        elif kind == "port_count":
            actual, expected = len(native["ports"]), assertion["value"]
        elif kind == "required_ports":
            expected = sorted(assertion["value"])
            actual = sorted(name for name in native["ports"] if name in expected)
        elif kind in {"port_property_equals", "port_property_contains"}:
            actual = native["port_properties"][assertion["port"]][assertion["property"]]
            expected = assertion["value"]
            if kind == "port_property_contains":
                return _record(
                    assertion,
                    kind,
                    all(str(token) in str(actual) for token in expected),
                    expected,
                    actual,
                )
        elif kind == "setup_count":
            actual, expected = len(native["setups"]), assertion["value"]
        elif kind == "required_setups":
            expected = sorted(assertion["value"])
            actual = sorted(name for name in native["setups"] if name in expected)
        elif kind == "design_equals":
            actual, expected = native["design"], assertion["value"]
        elif kind == "display_equals":
            actual, expected = native["display"], assertion["value"]
        else:
            raise ValueError(f"Unsupported PyEDB assertion: {kind}")
        return _record(assertion, kind, actual == expected, expected, actual)


def _record(
    assertion: dict[str, Any], kind: str, passed: bool, expected: Any, actual: Any
) -> dict[str, Any]:
    return {
        "id": str(assertion.get("id", kind)),
        "type": kind,
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
    }
