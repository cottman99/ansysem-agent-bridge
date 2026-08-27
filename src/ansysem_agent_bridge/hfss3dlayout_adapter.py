from __future__ import annotations

import math
import os
from contextlib import suppress
from pathlib import Path
from typing import Any


def native_polygon_edges(editor: Any, primitive_name: str) -> list[list[list[float]]]:
    info = list(editor.GetPolygonInfo(primitive_name))
    if "Poly:=" not in info:
        raise RuntimeError(f"No polygon data for {primitive_name}")
    source = list(info[info.index("Poly:=") + 1])
    values = list(source[source.index("pt:=") + 1])[2:]
    x_values = [float(value) for value in values[1::4]]
    y_values = [float(value) for value in values[3::4]]
    points = list(zip(x_values, y_values, strict=True))
    edges = [[list(points[index]), list(points[index + 1])] for index in range(len(points) - 1)]
    if points and points[-1] != points[0]:
        edges.append([list(points[-1]), list(points[0])])
    if not edges:
        raise RuntimeError(f"No polygon edges for {primitive_name}")
    return edges


def outer_edge_index(edges: list[list[list[float]]], side: str) -> int:
    if side in {"L", "R"}:
        candidates = [
            index for index, edge in enumerate(edges) if abs(edge[0][0] - edge[1][0]) <= 1e-9
        ]
        if not candidates:
            raise RuntimeError(f"No {side} edge candidate")
        return (min if side == "L" else max)(
            candidates, key=lambda index: (edges[index][0][0] + edges[index][1][0]) / 2
        )
    if side in {"T", "B"}:
        candidates = [
            index for index, edge in enumerate(edges) if abs(edge[0][1] - edge[1][1]) <= 1e-9
        ]
        if not candidates:
            raise RuntimeError(f"No {side} edge candidate")
        return (max if side == "T" else min)(
            candidates, key=lambda index: (edges[index][0][1] + edges[index][1][1]) / 2
        )
    raise ValueError(f"selected_side must be one of L/R/T/B, got {side!r}")


def _base_properties(editor: Any, server: str, tab: str = "BaseElementTab") -> dict[str, Any]:
    names = [str(item) for item in editor.GetProperties(tab, server)]
    return {name: editor.GetPropertyValue(tab, server, name) for name in names}


def _set_property(editor: Any, operation: dict[str, Any]) -> dict[str, Any]:
    tab = str(operation.get("tab", "BaseElementTab"))
    server = str(operation["server"])
    prop = str(operation["property"])
    value = operation["value"]
    before = _base_properties(editor, server, tab).get(prop)
    if before == value:
        return {
            "type": "set_property",
            "server": server,
            "property": prop,
            "value": before,
            "skipped": True,
        }
    if "expected_before" in operation and before != operation["expected_before"]:
        raise RuntimeError(
            f"Precondition failed for {server}.{prop}: expected "
            f"{operation['expected_before']!r}, found {before!r}"
        )
    editor.ChangeProperty(
        [
            "NAME:AllTabs",
            [
                f"NAME:{tab}",
                ["NAME:PropServers", server],
                ["NAME:ChangedProps", [f"NAME:{prop}", "Value:=", value]],
            ],
        ]
    )
    after = _base_properties(editor, server, tab).get(prop)
    if after != value:
        raise RuntimeError(f"Property readback failed for {server}.{prop}: {after!r}")
    return {
        "type": "set_property",
        "server": server,
        "property": prop,
        "value": after,
        "skipped": False,
    }


def _all_ports(editor: Any, excitations: Any) -> list[str]:
    names = [str(item) for item in excitations.GetAllPortsList()]
    for object_type in ("Port", "Edge Port"):
        with suppress(Exception):
            names.extend(str(item) for item in editor.FindObjects("Type", object_type))
    return sorted(set(names))


def _edge_descriptor(primitive: str, edge_index: int) -> list[Any]:
    return ["et:=", "pe", "prim:=", primitive, "edge:=", edge_index]


def _create_reference_patch(
    editor: Any, operation: dict[str, Any], selected_edge: list[list[float]]
) -> dict[str, Any]:
    reference = operation["reference_patch"]
    first, second = selected_edge
    side = operation["selected_side"]
    depth_m = float(reference["depth_um"]) * 1e-6
    center_x_m = (first[0] + second[0]) / 2 / 1000
    center_y_m = (first[1] + second[1]) / 2 / 1000
    if side in {"L", "R"}:
        width_m = depth_m
        height_m = math.dist(tuple(first), tuple(second)) / 1000
        center_x_m += depth_m / 2 if side == "L" else -depth_m / 2
    else:
        width_m = math.dist(tuple(first), tuple(second)) / 1000
        height_m = depth_m
        center_y_m += -depth_m / 2 if side == "T" else depth_m / 2
    created = str(
        editor.CreateRectangle(
            [
                "NAME:Contents",
                "RectGeometry:=",
                [
                    "LayerName:=",
                    reference["layer"],
                    "Lw:=",
                    0,
                    "X:=",
                    center_x_m,
                    "Y:=",
                    center_y_m,
                    "W:=",
                    width_m,
                    "H:=",
                    height_m,
                    "Ang:=",
                    0,
                ],
            ]
        )
    )
    if not created:
        raise RuntimeError(f"Could not create reference patch for {operation['port_name']}")
    _set_property(
        editor,
        {"type": "set_property", "server": created, "property": "Net", "value": reference["net"]},
    )
    return {"object": created, "layer": reference["layer"], "net": reference["net"]}


def _create_gap_port(app: Any, operation: dict[str, Any]) -> dict[str, Any]:
    editor = app.oeditor
    excitations = app.odesign.GetModule("Excitations")
    positive = str(operation["positive_object"])
    port_name = str(operation["port_name"])
    settings = {
        "HFSS Type": "Gap",
        "Renormalize": True,
        "Renormalize Impedance": "50ohm + 0i ohm",
        "DeembedParasiticPortInductance": False,
        **operation.get("settings", {}),
    }
    if port_name in set(_all_ports(editor, excitations)):
        excitation = app.odesign.GetChildObject("Excitations").GetChildObject(port_name)
        available = {str(item) for item in excitation.GetPropNames(False)}
        readback_names = set(settings) | {"Reference", "Boundary Type"}
        readback = {
            prop: excitation.GetPropValue(prop) for prop in readback_names if prop in available
        }
        reference = str(readback.get("Reference", ""))
        reference_spec = operation["reference_patch"]
        reference_tokens = (str(reference_spec["layer"]), str(reference_spec["net"]))
        settings_match = all(
            prop not in available or readback.get(prop) == value for prop, value in settings.items()
        )
        if (
            settings_match
            and readback.get("HFSS Type") == "Gap"
            and all(token in reference for token in reference_tokens)
        ):
            return {
                "type": "create_gap_port",
                "port_name": port_name,
                "positive_object": positive,
                "selected_side": operation["selected_side"],
                "properties": readback,
                "skipped": True,
            }
        raise RuntimeError(
            f"Existing port {port_name} does not match the requested desired state: {readback}"
        )
    edges = native_polygon_edges(editor, positive)
    edge_index = outer_edge_index(edges, str(operation["selected_side"]))
    patch = _create_reference_patch(editor, operation, edges[edge_index])
    before = set(_all_ports(editor, excitations))
    editor.CreateEdgePort(
        ["NAME:Contents", "edge:=", _edge_descriptor(positive, edge_index), "external:=", True]
    )
    created = sorted(set(_all_ports(editor, excitations)) - before)
    if len(created) != 1:
        raise RuntimeError(f"Expected one new port, found {created}")
    excitations.Rename(created[0], port_name)
    excitation = app.odesign.GetChildObject("Excitations").GetChildObject(port_name)
    available = {str(item) for item in excitation.GetPropNames(False)}
    for prop, value in settings.items():
        if prop in available:
            excitation.SetPropValue(prop, value)
    readback_names = set(settings) | {"Reference", "Boundary Type"}
    readback = {prop: excitation.GetPropValue(prop) for prop in readback_names if prop in available}
    if readback.get("HFSS Type") != "Gap":
        raise RuntimeError(f"Gap-port readback failed for {port_name}: {readback}")
    reference = str(readback.get("Reference", ""))
    reference_tokens = (str(patch["layer"]), str(patch["net"]))
    if not all(token in reference for token in reference_tokens):
        raise RuntimeError(f"Gap-port reference readback failed for {port_name}: {reference!r}")
    return {
        "type": "create_gap_port",
        "port_name": port_name,
        "positive_object": positive,
        "selected_side": operation["selected_side"],
        "edge_index": edge_index,
        "reference_patch": patch,
        "properties": readback,
        "skipped": False,
    }


class Hfss3dLayoutNativeAdapter:
    adapter_id = "hfss3dlayout.native/v1"

    @staticmethod
    def _open(project: Path, plan: dict[str, Any]) -> Any:
        from ansys.aedt.core import Hfss3dLayout

        runtime = plan.get("runtime", {})
        return Hfss3dLayout(
            project=str(project),
            version=str(plan["version"]),
            design=str(plan["design"]),
            non_graphical=False,
            new_desktop=True,
            close_on_exit=True,
            port=int(runtime.get("port", 0)),
        )

    def apply(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        app = self._open(project, plan)
        try:
            if app.design_name != plan["design"]:
                raise RuntimeError(f"Unexpected design: {app.design_name}")
            records = []
            for operation in plan["operations"]:
                if operation["type"] == "set_property":
                    records.append(_set_property(app.oeditor, operation))
                elif operation["type"] == "create_gap_port":
                    records.append(_create_gap_port(app, operation))
                else:
                    raise ValueError(f"Unsupported typed operation: {operation['type']}")
            if not app.save_project():
                raise RuntimeError("AEDT project save returned failure")
            return {
                "operation_count": len(records),
                "applied_count": sum(not item.get("skipped", False) for item in records),
                "skipped_count": sum(item.get("skipped", False) for item in records),
                "operations": records,
            }
        finally:
            app.release_desktop(close_projects=True, close_desktop=True)

    def verify(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        app = self._open(project, plan)
        try:
            editor = app.oeditor
            excitations = app.odesign.GetModule("Excitations")
            ports = _all_ports(editor, excitations)
            setups = sorted(str(item) for item in app.setup_names)
            validations = [
                self._assert(app, assertion, ports, setups) for assertion in plan["assertions"]
            ]
            return {
                "readback": {
                    "design": app.design_name,
                    "display": os.environ.get("DISPLAY"),
                    "port_count": len(ports),
                    "setup_count": len(setups),
                },
                "validation": validations,
            }
        finally:
            app.release_desktop(close_projects=True, close_desktop=True)

    @staticmethod
    def _assert(
        app: Any, assertion: dict[str, Any], ports: list[str], setups: list[str]
    ) -> dict[str, Any]:
        kind = assertion["type"]
        editor = app.oeditor
        actual: Any
        expected: Any
        if kind == "property_equals":
            actual = _base_properties(
                editor, assertion["server"], assertion.get("tab", "BaseElementTab")
            ).get(assertion["property"])
            expected = assertion["value"]
        elif kind == "same_property":
            left = _base_properties(
                editor, assertion["left_server"], assertion.get("tab", "BaseElementTab")
            ).get(assertion["property"])
            right = _base_properties(
                editor, assertion["right_server"], assertion.get("tab", "BaseElementTab")
            ).get(assertion["property"])
            actual, expected = left, right
        elif kind == "object_exists":
            actual = bool(editor.FindObjects("Name", assertion["name"]))
            expected = True
        elif kind == "port_count":
            actual, expected = len(ports), int(assertion["value"])
        elif kind == "required_ports":
            expected = sorted(str(item) for item in assertion["value"])
            actual = sorted(name for name in ports if name in expected)
        elif kind == "setup_count":
            actual, expected = len(setups), int(assertion["value"])
        elif kind == "required_setups":
            expected = sorted(str(item) for item in assertion["value"])
            actual = sorted(name for name in setups if name in expected)
        elif kind in {"port_property_equals", "port_property_contains"}:
            excitation = app.odesign.GetChildObject("Excitations").GetChildObject(assertion["port"])
            actual = excitation.GetPropValue(assertion["property"])
            expected = assertion["value"]
            if kind == "port_property_contains":
                passed = all(str(token) in str(actual) for token in expected)
                return {
                    "id": str(assertion.get("id", kind)),
                    "type": kind,
                    "passed": passed,
                    "expected": expected,
                    "actual": actual,
                }
        elif kind == "design_equals":
            actual, expected = app.design_name, assertion["value"]
        elif kind == "display_equals":
            actual, expected = os.environ.get("DISPLAY"), assertion["value"]
        else:
            raise ValueError(f"Unsupported typed assertion: {kind}")
        return {
            "id": str(assertion.get("id", kind)),
            "type": kind,
            "passed": actual == expected,
            "expected": expected,
            "actual": actual,
        }
