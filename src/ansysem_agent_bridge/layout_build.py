"""Typed transactional HFSS 3D Layout stackup and geometry construction."""

from __future__ import annotations

import math
import re
import shutil
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from .live_probe import live_hfss3dlayout_probe
from .project_bundle import (
    bundle_content_sha256,
    commit_staged_project_bundle,
    copy_project_bundle,
)

_SCHEMA = "ansysem.hfss3dlayout-build/v1"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_ -]{0,127}")
_LENGTH = re.compile(
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(?P<unit>um|mm|cm|m|mil)",
    re.IGNORECASE,
)
_FREQUENCY = re.compile(
    r"(?P<value>[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(?P<unit>Hz|kHz|MHz|GHz|THz)",
    re.IGNORECASE,
)
_LENGTH_TO_METERS = {"um": 1e-6, "mm": 1e-3, "cm": 1e-2, "m": 1.0, "mil": 2.54e-5}
_FREQUENCY_TO_HZ = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}


def _identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a simple identifier")
    return text


def _length(value: Any, field: str, *, positive: bool) -> str:
    text = str(value or "")
    match = _LENGTH.fullmatch(text)
    if not match or not math.isfinite(float(match.group("value"))):
        raise ValueError(f"{field} must be a finite length with supported units")
    if positive and float(match.group("value")) <= 0:
        raise ValueError(f"{field} must be a positive length")
    return text


def _point(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must contain exactly two coordinates")
    return [
        _length(item, f"{field}[{index}]", positive=False) for index, item in enumerate(value)
    ]


def _length_m(value: str) -> float:
    match = _LENGTH.fullmatch(value)
    assert match is not None
    return float(match.group("value")) * _LENGTH_TO_METERS[match.group("unit").casefold()]


def _frequency(value: Any, field: str) -> str:
    text = str(value or "")
    match = _FREQUENCY.fullmatch(text)
    if (
        not match
        or not math.isfinite(float(match.group("value")))
        or float(match.group("value")) <= 0
    ):
        raise ValueError(f"{field} must be a positive frequency with supported units")
    return text


def _frequency_hz(value: str) -> float:
    match = _FREQUENCY.fullmatch(value)
    assert match is not None
    return float(match.group("value")) * _FREQUENCY_TO_HZ[match.group("unit").casefold()]


def validate_layout_build_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("layout.build requires a structured plan object")
    plan = dict(value)
    allowed = {
        "schema_version",
        "operation_id",
        "source_project",
        "output_project",
        "version",
        "design",
        "source_fingerprint",
        "materials",
        "layers",
        "rectangles",
        "traces",
        "ports",
        "setup",
    }
    unknown = sorted(set(plan) - allowed)
    if unknown:
        raise ValueError("layout build plan contains unsupported fields: " + ", ".join(unknown))
    required = (
        "schema_version",
        "operation_id",
        "source_project",
        "output_project",
        "version",
        "design",
        "materials",
        "layers",
        "traces",
        "ports",
        "setup",
    )
    missing = [name for name in required if not plan.get(name)]
    if missing:
        raise ValueError("layout build plan is missing: " + ", ".join(missing))
    if plan["schema_version"] != _SCHEMA:
        raise ValueError(f"unsupported layout build schema: {plan['schema_version']}")
    plan["operation_id"] = _identifier(plan["operation_id"], "operation_id")
    plan["design"] = _identifier(plan["design"], "design")
    fingerprint = plan.get("source_fingerprint")
    if fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", str(fingerprint)):
        raise ValueError("source_fingerprint must be a lowercase SHA-256 digest")

    materials = plan["materials"]
    if not isinstance(materials, list) or not materials or len(materials) > 32:
        raise ValueError("materials must contain between 1 and 32 entries")
    material_names: set[str] = set()
    material_kinds: dict[str, str] = {}
    normalized_materials = []
    for index, raw in enumerate(materials):
        if not isinstance(raw, dict):
            raise TypeError(f"materials[{index}] must be an object")
        kind = raw.get("kind")
        allowed_material = (
            {"name", "kind", "conductivity"}
            if kind == "conductor"
            else {"name", "kind", "permittivity", "loss_tangent"}
        )
        if kind not in {"conductor", "dielectric"} or set(raw) != allowed_material:
            raise ValueError(f"materials[{index}] is invalid")
        name = _identifier(raw["name"], f"materials[{index}].name")
        if name in material_names:
            raise ValueError(f"duplicate material: {name}")
        numeric_fields = allowed_material - {"name", "kind"}
        if any(
            not isinstance(raw[field], int | float)
            or isinstance(raw[field], bool)
            or not math.isfinite(float(raw[field]))
            for field in numeric_fields
        ):
            raise ValueError(f"materials[{index}] contains invalid numeric properties")
        if kind == "conductor" and float(raw["conductivity"]) <= 0:
            raise ValueError(f"materials[{index}] conductivity must be positive")
        if kind == "dielectric" and (
            float(raw["permittivity"]) <= 0 or float(raw["loss_tangent"]) < 0
        ):
            raise ValueError(
                f"materials[{index}] permittivity must be positive and loss_tangent non-negative"
            )
        normalized_materials.append(dict(raw))
        material_names.add(name)
        material_kinds[name] = kind

    layers = plan["layers"]
    if not isinstance(layers, list) or len(layers) < 2 or len(layers) > 64:
        raise ValueError("layers must contain between 2 and 64 bottom-to-top entries")
    layer_names: set[str] = set()
    normalized_layers = []
    for index, raw in enumerate(layers):
        if not isinstance(raw, dict) or set(raw) != {"name", "kind", "material", "thickness"}:
            raise ValueError(f"layers[{index}] is invalid")
        name = _identifier(raw["name"], f"layers[{index}].name")
        kind = str(raw["kind"])
        material = str(raw["material"])
        if (
            name in layer_names
            or kind not in {"signal", "dielectric"}
            or material not in material_names
            or material_kinds[material]
            != ("conductor" if kind == "signal" else "dielectric")
        ):
            raise ValueError(f"layers[{index}] is invalid")
        normalized_layers.append(
            {
                **raw,
                "name": name,
                "kind": kind,
                "thickness": _length(
                    raw["thickness"], f"layers[{index}].thickness", positive=True
                ),
            }
        )
        layer_names.add(name)

    rectangles = plan.get("rectangles", [])
    traces = plan["traces"]
    if not isinstance(rectangles, list) or len(rectangles) > 128:
        raise ValueError("rectangles must be a list with at most 128 entries")
    if not isinstance(traces, list) or not traces or len(traces) > 128:
        raise ValueError("traces must contain between 1 and 128 entries")
    primitive_names: set[str] = set()
    normalized_rectangles = []
    for index, raw in enumerate(rectangles):
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "layer",
            "net",
            "lower_left",
            "upper_right",
        }:
            raise ValueError(f"rectangles[{index}] is invalid")
        name = _identifier(raw["name"], f"rectangles[{index}].name")
        if name in primitive_names or raw["layer"] not in layer_names:
            raise ValueError(f"rectangles[{index}] is invalid")
        lower_left = _point(raw["lower_left"], f"rectangles[{index}].lower_left")
        upper_right = _point(raw["upper_right"], f"rectangles[{index}].upper_right")
        if any(_length_m(upper_right[axis]) <= _length_m(lower_left[axis]) for axis in (0, 1)):
            raise ValueError(f"rectangles[{index}] upper_right must exceed lower_left")
        normalized_rectangles.append(
            {
                **raw,
                "name": name,
                "net": _identifier(raw["net"], f"rectangles[{index}].net"),
                "lower_left": lower_left,
                "upper_right": upper_right,
            }
        )
        primitive_names.add(name)
    normalized_traces = []
    trace_names: set[str] = set()
    for index, raw in enumerate(traces):
        if not isinstance(raw, dict) or set(raw) != {"name", "layer", "net", "width", "path"}:
            raise ValueError(f"traces[{index}] is invalid")
        name = _identifier(raw["name"], f"traces[{index}].name")
        path = raw["path"]
        if (
            name in primitive_names
            or raw["layer"] not in layer_names
            or not isinstance(path, list)
            or len(path) < 2
        ):
            raise ValueError(f"traces[{index}] is invalid")
        normalized_path = [_point(point, f"traces[{index}].path") for point in path]
        if any(
            all(
                math.isclose(_length_m(left[axis]), _length_m(right[axis]), abs_tol=1e-15)
                for axis in (0, 1)
            )
            for left, right in zip(normalized_path, normalized_path[1:], strict=False)
        ):
            raise ValueError(f"traces[{index}].path contains a zero-length segment")
        normalized_traces.append(
            {
                **raw,
                "name": name,
                "net": _identifier(raw["net"], f"traces[{index}].net"),
                "width": _length(raw["width"], f"traces[{index}].width", positive=True),
                "path": normalized_path,
            }
        )
        primitive_names.add(name)
        trace_names.add(name)

    ports = plan["ports"]
    if not isinstance(ports, list) or len(ports) < 2 or len(ports) > 64:
        raise ValueError("ports must contain between 2 and 64 entries")
    port_names: set[str] = set()
    normalized_ports = []
    for index, raw in enumerate(ports):
        if not isinstance(raw, dict) or set(raw) != {"name", "trace", "position", "type"}:
            raise ValueError(f"ports[{index}] is invalid")
        name = _identifier(raw["name"], f"ports[{index}].name")
        if (
            name in port_names
            or raw["trace"] not in trace_names
            or raw["position"] not in {"Start", "End"}
            or raw["type"] not in {"Wave", "Gap"}
        ):
            raise ValueError(f"ports[{index}] is invalid")
        normalized_ports.append(dict(raw))
        port_names.add(name)

    setup = plan["setup"]
    if not isinstance(setup, dict) or set(setup) != {"name", "start", "stop", "step"}:
        raise ValueError("setup is invalid")
    normalized_setup = {
        "name": _identifier(setup["name"], "setup.name"),
        "start": _frequency(setup["start"], "setup.start"),
        "stop": _frequency(setup["stop"], "setup.stop"),
        "step": _frequency(setup["step"], "setup.step"),
    }
    if _frequency_hz(normalized_setup["stop"]) < _frequency_hz(normalized_setup["start"]):
        raise ValueError("setup.stop must be greater than or equal to setup.start")
    plan.update(
        materials=normalized_materials,
        layers=normalized_layers,
        rectangles=normalized_rectangles,
        traces=normalized_traces,
        ports=normalized_ports,
        setup=normalized_setup,
    )
    return plan


def execute_layout_build_plan(value: Any, *, redact_paths: bool = True) -> dict[str, Any]:
    plan = validate_layout_build_plan(value)
    source = Path(str(plan["source_project"])).expanduser().resolve()
    output = Path(str(plan["output_project"])).expanduser().resolve()
    if source == output or source.parent != output.parent:
        raise ValueError("source and output projects must be distinct siblings")
    if output.exists() or output.with_suffix(".aedb").exists():
        raise FileExistsError(f"refusing to overwrite output bundle: {output}")
    source_before = bundle_content_sha256(source)
    if plan.get("source_fingerprint") and plan["source_fingerprint"] != source_before:
        raise ValueError("source project fingerprint does not match the plan")
    stage_root = output.parent / f".ansysem-layout-stage-{uuid.uuid4().hex}"
    staging = stage_root / output.name
    try:
        stage_root.mkdir()
        copy_result = copy_project_bundle(source, staging)
        from pyedb import Edb

        edb = Edb(str(staging.with_suffix(".aedb")), version=str(plan["version"]))
        try:
            for material in plan["materials"]:
                if material["kind"] == "conductor":
                    edb.materials.add_conductor_material(
                        material["name"], float(material["conductivity"])
                    )
                else:
                    edb.materials.add_dielectric_material(
                        material["name"],
                        float(material["permittivity"]),
                        float(material["loss_tangent"]),
                    )
            for layer in plan["layers"]:
                created = edb.stackup.add_layer(
                    layer["name"],
                    method="add_on_top",
                    layer_type=layer["kind"],
                    material=layer["material"],
                    filling_material=layer["material"],
                    thickness=layer["thickness"],
                )
                if not created:
                    raise RuntimeError(f"failed to create stackup layer: {layer['name']}")
            for rectangle in plan["rectangles"]:
                primitive = edb.modeler.create_rectangle(
                    rectangle["layer"],
                    rectangle["net"],
                    lower_left_point=rectangle["lower_left"],
                    upper_right_point=rectangle["upper_right"],
                )
                if not primitive:
                    raise RuntimeError(f"failed to create rectangle: {rectangle['name']}")
                primitive.aedt_name = rectangle["name"]
            traces = {}
            for trace in plan["traces"]:
                primitive = edb.modeler.create_trace(
                    trace["path"],
                    trace["layer"],
                    trace["width"],
                    trace["net"],
                    "Flat",
                    "Flat",
                    "Sharp",
                )
                if not primitive:
                    raise RuntimeError(f"failed to create trace: {trace['name']}")
                primitive.aedt_name = trace["name"]
                traces[trace["name"]] = primitive
            for port in plan["ports"]:
                created = traces[port["trace"]].create_edge_port(
                    port["name"], position=port["position"], port_type=port["type"]
                )
                if not created:
                    raise RuntimeError(f"failed to create port: {port['name']}")
            setup = plan["setup"]
            created_setup = edb.hfss.add_setup(
                name=setup["name"],
                distribution="linear",
                start_freq=setup["start"],
                stop_freq=setup["stop"],
                step_freq=setup["step"],
                discrete_sweep=True,
            )
            if not created_setup:
                raise RuntimeError(f"failed to create setup: {setup['name']}")
            if edb.save() is False:
                raise RuntimeError("PyEDB save returned failure")
        finally:
            edb.close()

        reopened_edb = Edb(str(staging.with_suffix(".aedb")), version=str(plan["version"]))
        try:
            edb_ports = sorted(str(name) for name in reopened_edb.ports)
            edb_setups = sorted(str(name) for name in reopened_edb.setups)
        finally:
            reopened_edb.close()
        expected_ports = sorted(port["name"] for port in plan["ports"])
        expected_setup = plan["setup"]["name"]
        if edb_ports != expected_ports or expected_setup not in edb_setups:
            raise RuntimeError(f"fresh PyEDB mismatch: ports={edb_ports!r}, setups={edb_setups!r}")

        staging.unlink()
        from ansys.aedt.core import Hfss3dLayout

        app = None
        try:
            app = Hfss3dLayout(
                project=str(staging.with_suffix(".aedb")),
                design=str(plan["design"]),
                version=str(plan["version"]),
                non_graphical=False,
                new_desktop=True,
                close_on_exit=True,
            )
            if not app.save_project(str(staging)):
                raise RuntimeError("AEDT project save-as returned failure")
        finally:
            if app is not None:
                with suppress(Exception):
                    app.release_desktop(close_projects=True, close_desktop=True)

        observed = live_hfss3dlayout_probe(
            project=staging,
            version=str(plan["version"]),
            design=str(plan["design"]),
            new_desktop=True,
            close_desktop=True,
            validate=False,
            redact_paths=redact_paths,
        )
        actual_ports = sorted(observed["state"]["ports"])
        actual_setups = sorted(observed["state"]["setups"])
        if actual_ports != expected_ports or expected_setup not in actual_setups:
            raise RuntimeError(
                f"fresh-reopen mismatch: ports={actual_ports!r}, setups={actual_setups!r}"
            )
        if bundle_content_sha256(source) != source_before:
            raise RuntimeError("source project changed during layout transaction")
        output_fingerprint = bundle_content_sha256(staging)
        commit_staged_project_bundle(staging, output)
        return {
            "status": "passed",
            "operation_id": plan["operation_id"],
            "source_preserved": True,
            "source_fingerprint": source_before,
            "output_fingerprint": output_fingerprint,
            "output_project": output.name if redact_paths else str(output),
            "copy": copy_result,
            "stackup_layers": [layer["name"] for layer in plan["layers"]],
            "primitive_count": len(plan["rectangles"]) + len(plan["traces"]),
            "ports": actual_ports,
            "setups": actual_setups,
            "fresh_reopen": observed,
        }
    finally:
        for path in (stage_root,):
            with suppress(OSError):
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
