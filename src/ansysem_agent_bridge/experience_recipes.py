"""Experience-owned helpers that are intentionally absent from operation discovery.

These functions compile already-decided engineering data into existing Bridge
contracts.  They do not infer connectivity, materials, port intent, loop class,
or solver strategy.
"""

from __future__ import annotations

import hashlib
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from eda_bridge_runtime import validate_native_program

from .transaction import validate_operation_plan

_MAX_ODB_MEMBER_BYTES = 64 * 1024 * 1024


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    return value


def _required_text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return result


class _ArchiveReader:
    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
        self.tar = None if self.zip else tarfile.open(path, "r:*")  # noqa: SIM115
        self.names = self.zip.namelist() if self.zip else self.tar.getnames()

    def close(self) -> None:
        if self.zip:
            self.zip.close()
        if self.tar:
            self.tar.close()

    def read_suffix(self, suffix: str, *, required: bool = False) -> str:
        wanted = suffix.replace("\\", "/").casefold()
        matches = [
            name for name in self.names if name.replace("\\", "/").casefold().endswith(wanted)
        ]
        if not matches:
            if required:
                raise FileNotFoundError(f"ODB++ member ending with {suffix!r} is missing")
            return ""
        name = sorted(matches, key=lambda item: (len(item), item.casefold()))[0]
        if self.zip:
            if self.zip.getinfo(name).file_size > _MAX_ODB_MEMBER_BYTES:
                raise ValueError(f"ODB++ member is too large for bounded intake: {name}")
            data = self.zip.read(name)
        else:
            member = self.tar.getmember(name)
            if member.size > _MAX_ODB_MEMBER_BYTES:
                raise ValueError(f"ODB++ member is too large for bounded intake: {name}")
            stream = self.tar.extractfile(member)
            if stream is None:
                raise FileNotFoundError(name)
            data = stream.read()
        return data.decode("utf-8", errors="replace")


def _matrix_layers(text: str) -> list[dict[str, str]]:
    layers = []
    for block in re.findall(r"LAYER\s*\{(.*?)\}", text, re.DOTALL):
        item = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                item[key.strip()] = value.strip()
        if item:
            layers.append(item)
    return layers


def _component_inventory(text: str) -> dict[str, Any]:
    references = []
    pin_records = 0
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == "CMP" and len(fields) >= 7:
            references.append(fields[6])
        elif fields and fields[0] in {"TOP", "BOT"}:
            pin_records += 1
    return {
        "count": len(references),
        "pin_record_count": pin_records,
        "references": sorted(set(references)),
    }


def audit_odb_archive(path: str | Path) -> dict[str, Any]:
    """Return a bounded, read-only inventory of one ODB++ ZIP or TAR archive."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    archive = _ArchiveReader(source)
    try:
        matrix = _matrix_layers(archive.read_suffix("matrix/matrix", required=True))
        top_components = _component_inventory(archive.read_suffix("layers/comp_+_top/components"))
        bottom_components = _component_inventory(
            archive.read_suffix("layers/comp_+_bot/components")
        )
        eda_data = archive.read_suffix("eda/data")
        cadnet = archive.read_suffix("netlists/cadnet/netlist")
        eda_nets = re.findall(r"^NET\s+(.+)$", eda_data, re.MULTILINE)
        cad_nets = re.findall(r"^\$\d+\s+(.+)$", cadnet, re.MULTILINE)
        drill_features = archive.read_suffix("drill_pth_through/features")
        signal_layers = [item for item in matrix if item.get("TYPE") == "SIGNAL"]
        dielectric_layers = [item for item in matrix if item.get("TYPE") == "DIELECTRIC"]
        missing = []
        if not signal_layers:
            missing.append("signal_layers")
        if not dielectric_layers:
            missing.append("dielectric_stackup")
        if not eda_nets:
            missing.append("eda_nets")
        if top_components["count"] == 0 and bottom_components["count"] == 0:
            missing.append("components")
        return {
            "schema": "ansysem.odb-intake-audit/v1",
            "status": "passed",
            "source_sha256": digest.hexdigest(),
            "archive_format": "zip" if archive.zip else "tar",
            "member_count": len(archive.names),
            "layers": {
                "total": len(matrix),
                "signal": len(signal_layers),
                "dielectric": len(dielectric_layers),
                "items": matrix,
            },
            "components": {"top": top_components, "bottom": bottom_components},
            "nets": {
                "eda_count": len(eda_nets),
                "cad_count": len(cad_nets),
                "name_lists_match": bool(eda_nets) and eda_nets == cad_nets,
                "eda_names": eda_nets,
            },
            "through_drill_feature_count": len(re.findall(r"^P\s+", drill_features, re.MULTILINE)),
            "missing_or_unproven": missing,
            "evidence_boundary": (
                "Archive inventory does not prove material values, dielectric thicknesses, "
                "plating, assembly state, or electrical correctness."
            ),
        }
    finally:
        archive.close()


def _base_operation_plan(contract: dict[str, Any], *, adapter: str) -> dict[str, Any]:
    plan = {
        "schema_version": 1,
        "operation_id": _required_text(contract, "operation_id"),
        "adapter": adapter,
        "source_project": _required_text(contract, "source_project"),
        "output_project": _required_text(contract, "output_project"),
        "version": _required_text(contract, "version"),
        "design": _required_text(contract, "design"),
        "solve_requested": False,
        "operations": [],
        "assertions": [],
    }
    for key in ("profile", "runtime", "source_fingerprint", "redact_paths"):
        if key in contract:
            plan[key] = contract[key]
    return plan


def compile_gap_port_plan(contract: dict[str, Any]) -> dict[str, Any]:
    """Compile an explicit terminal map into the existing model.apply contract."""

    contract = _require_object(contract, "port contract")
    ports = _require_list(contract.get("ports"), "ports")
    plan = _base_operation_plan(contract, adapter="hfss3dlayout.native/v1")
    names = []
    for index, raw in enumerate(ports):
        port = _require_object(raw, f"ports[{index}]")
        name = _required_text(port, "name")
        if name in names:
            raise ValueError(f"duplicate port name: {name}")
        names.append(name)
        settings = _require_object(port.get("settings"), f"ports[{index}].settings")
        required_settings = {
            "HFSS Type",
            "Renormalize",
            "Renormalize Impedance",
            "DeembedParasiticPortInductance",
        }
        if set(settings) != required_settings or settings["HFSS Type"] != "Gap":
            raise ValueError(
                f"ports[{index}].settings must explicitly define the four supported "
                "Gap-port settings"
            )
        plan["operations"].append(
            {
                "type": "create_gap_port",
                "positive_object": _required_text(port, "positive_object"),
                "selected_side": _required_text(port, "selected_side"),
                "port_name": name,
                "reference_patch": _require_object(
                    port.get("reference_patch"), f"ports[{index}].reference_patch"
                ),
                "settings": settings,
            }
        )
        plan["assertions"].append(
            {"type": "port_property_equals", "port": name, "property": "HFSS Type", "value": "Gap"}
        )
        for prop, value in settings.items():
            if prop != "HFSS Type":
                plan["assertions"].append(
                    {"type": "port_property_equals", "port": name, "property": prop, "value": value}
                )
        tokens = port.get("reference_tokens")
        if tokens is not None:
            plan["assertions"].append(
                {
                    "type": "port_property_contains",
                    "port": name,
                    "property": "Reference",
                    "value": _require_list(tokens, f"ports[{index}].reference_tokens"),
                }
            )
    plan["assertions"].insert(0, {"type": "required_ports", "value": names})
    if "expected_total_port_count" in contract:
        plan["assertions"].insert(
            0, {"type": "port_count", "value": contract["expected_total_port_count"]}
        )
    validate_operation_plan(plan)
    return plan


def compile_bondwire_plan(contract: dict[str, Any]) -> dict[str, Any]:
    """Compile explicit profiles and wire states with physical-shape assertions."""

    contract = _require_object(contract, "bondwire contract")
    profiles = _require_list(contract.get("profiles"), "profiles")
    wires = _require_list(contract.get("wires"), "wires")
    plan = _base_operation_plan(contract, adapter="hfss3dlayout.pyedb-native/v1")
    profile_names = set()
    for index, raw in enumerate(profiles):
        profile = _require_object(raw, f"profiles[{index}]")
        name = _required_text(profile, "name")
        if name in profile_names:
            raise ValueError(f"duplicate profile name: {name}")
        profile_names.add(name)
        plan["operations"].append({"type": "ensure_apd_bondwire_profile", **profile})
    wire_names = []
    for index, raw in enumerate(wires):
        wire = _require_object(raw, f"wires[{index}]")
        name = _required_text(wire, "name")
        if name in wire_names:
            raise ValueError(f"duplicate wire name: {name}")
        wire_names.append(name)
        desired = _require_object(wire.get("desired"), f"wires[{index}].desired")
        expected_before = _require_object(
            wire.get("expected_before"), f"wires[{index}].expected_before"
        )
        profile_name = desired.get("profile")
        if profile_name and profile_name not in profile_names:
            raise ValueError(f"wire {name} references unknown profile {profile_name}")
        plan["operations"].append(
            {"type": "set_bondwire", "name": name, "expected_before": expected_before, **desired}
        )
        plan["assertions"].append({"type": "bondwire_matches", "name": name, "expected": desired})
        checks = _require_object(wire.get("checks", {}), f"wires[{index}].checks")
        if "projected_length_um" in checks:
            plan["assertions"].append(
                {
                    "type": "bondwire_projected_length",
                    "name": name,
                    "value_um": checks["projected_length_um"],
                    "tolerance_um": checks.get("length_tolerance_um", 1.0),
                }
            )
        if "profile_height_um" in checks:
            plan["assertions"].append(
                {
                    "type": "bondwire_profile_height",
                    "name": name,
                    "value_um": checks["profile_height_um"],
                    "tolerance_um": checks.get("height_tolerance_um", 1.0),
                }
            )
        if "apex_endpoint" in checks:
            plan["assertions"].append(
                {
                    "type": "bondwire_apex_endpoint",
                    "name": name,
                    "value": checks["apex_endpoint"],
                }
            )
        for endpoint in ("start", "end"):
            conductor = checks.get(f"{endpoint}_conductor")
            if conductor:
                plan["assertions"].append(
                    {
                        "type": "bondwire_endpoint_in_conductor",
                        "name": name,
                        "endpoint": endpoint,
                        "conductor": conductor,
                    }
                )
        obstacles = checks.get("obstacles")
        if obstacles:
            plan["assertions"].append(
                {
                    "type": "bondwire_obstacle_clearance",
                    "name": name,
                    "obstacles": obstacles,
                    "minimum_um": checks.get("minimum_obstacle_clearance_um", 0.0),
                    "start_contact_exemption_um": checks.get("start_contact_exemption_um", 0.0),
                }
            )
    if "expected_total_bondwire_count" in contract:
        plan["assertions"].insert(
            0, {"type": "bondwire_count", "value": contract["expected_total_bondwire_count"]}
        )
    if "minimum_pairwise_clearance_um" in contract:
        plan["assertions"].append(
            {
                "type": "bondwire_pairwise_clearance",
                "names": wire_names,
                "minimum_um": contract["minimum_pairwise_clearance_um"],
            }
        )
    validate_operation_plan(plan)
    return plan


def _program_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def compile_solution_observe_plan(contract: dict[str, Any]) -> dict[str, Any]:
    """Compile a no-solve native.execute plan for persisted solution readback."""

    contract = _require_object(contract, "solution observation contract")
    source = _required_text(contract, "source_project")
    solution = _required_text(contract, "solution")
    expressions = _require_object(contract.get("expressions"), "expressions")
    normalized = {}
    for label, raw in expressions.items():
        if not isinstance(label, str) or not label:
            raise ValueError("expression labels must be non-empty strings")
        if isinstance(raw, str):
            normalized[label] = {"expression": raw, "formula": "real"}
        else:
            item = _require_object(raw, f"expressions.{label}")
            normalized[label] = {
                "expression": _required_text(item, "expression"),
                "formula": str(item.get("formula", "real")),
            }
    expected_frequency = contract.get("expected_frequency")
    if expected_frequency is not None and not isinstance(expected_frequency, list):
        raise ValueError("expected_frequency must be a list")
    magnitude_pairs = contract.get("magnitude_pairs", [])
    if not isinstance(magnitude_pairs, list):
        raise ValueError("magnitude_pairs must be a list")
    program = f"""import math

SOLUTION = {solution!r}
EXPRESSIONS = {normalized!r}
EXPECTED_FREQUENCY = {expected_frequency!r}
FREQUENCY_TOLERANCE = {float(contract.get("frequency_tolerance", 1e-6))!r}
MAGNITUDE_PAIRS = {magnitude_pairs!r}

def run(api, context):
    available = [str(item) for item in api.existing_analysis_sweeps]
    if SOLUTION not in available:
        raise RuntimeError("Requested persisted solution is unavailable: " + SOLUTION)
    result = {{}}
    for label, item in EXPRESSIONS.items():
        data = api.post.get_solution_data(
            expressions=[item["expression"]], setup_sweep_name=SOLUTION, domain="Sweep")
        if not data:
            raise RuntimeError("No persisted data for " + item["expression"])
        frequency, values = data.get_expression_data(
            item["expression"], formula=item["formula"])
        frequency = [float(value) for value in frequency]
        values = [float(value) for value in values]
        if len(frequency) != len(values) or not all(math.isfinite(value) for value in values):
            raise RuntimeError("Non-finite or mismatched result for " + item["expression"])
        if EXPECTED_FREQUENCY is not None:
            if len(frequency) != len(EXPECTED_FREQUENCY) or any(
                abs(actual - expected) > FREQUENCY_TOLERANCE
                for actual, expected in zip(frequency, EXPECTED_FREQUENCY)
            ):
                raise RuntimeError("Unexpected frequency grid for " + item["expression"])
        result[label] = {{"frequency": frequency, "value": values}}
    for check in MAGNITUDE_PAIRS:
        real_values = result[check["real_label"]]["value"]
        imag_values = result[check["imag_label"]]["value"]
        limit = float(check.get("maximum", 1.000001))
        magnitudes = zip(real_values, imag_values)
        if any(real * real + imag * imag > limit * limit for real, imag in magnitudes):
            raise RuntimeError("Magnitude bound failed: " + str(check))
    return {{"status": "passed", "solver_started": False,
            "solution": SOLUTION, "available_solutions": available,
            "values": result}}
"""
    plan = {
        "schema_version": "eda.native-program/v1",
        "mode": "background",
        "effect": "observe",
        "runtime": "ansys.pyaedt.hfss3dlayout",
        "scope": {
            "resource_kind": "aedt-project",
            "selectors": {
                "version": _required_text(contract, "version"),
                "design": _required_text(contract, "design"),
                "include_results": True,
            },
            "read_paths": [source],
            "write_paths": [],
            "artifacts": [],
        },
        "transaction": {
            "strategy": "none",
            "source_fingerprints": {},
            "fresh_reopen": False,
            "promotion": "none",
        },
        "program": {"language": "python", "source": program, "sha256": _program_hash(program)},
        "validation": {"program": None, "required_artifacts": []},
        "limits": {
            "timeout_seconds": int(contract.get("timeout_seconds", 1800)),
            "max_output_bytes": int(contract.get("max_output_bytes", 1048576)),
        },
    }
    return validate_native_program(plan)


def recipe_contracts() -> dict[str, dict[str, Any]]:
    """Return compact input boundaries for experience.get receipts and tests."""

    return {
        "ansysem.odb.intake-audit": {
            "callable": "audit_odb_archive",
            "input": "path to one ODB++ ZIP or TAR archive",
            "effect": "static_read",
        },
        "ansysem.hfss3dlayout.gap-port-reference": {
            "callable": "compile_gap_port_plan",
            "input": "explicit project identity and terminal map",
            "effect": "plan_compile",
        },
        "ansysem.hfss3dlayout.bondwire-realisation": {
            "callable": "compile_bondwire_plan",
            "input": "explicit profiles, wire states, and physical assertions",
            "effect": "plan_compile",
        },
        "ansysem.hfss3dlayout.solution-observe": {
            "callable": "compile_solution_observe_plan",
            "input": "exact persisted solution and expression map",
            "effect": "plan_compile",
        },
    }
