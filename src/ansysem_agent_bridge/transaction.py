from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol

from .project_bundle import inspect_project_bundle, sha256_file


class OperationAdapter(Protocol):
    adapter_id: str

    def apply(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]: ...

    def verify(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]: ...


def load_operation_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_operation_plan(plan)
    return plan


def validate_operation_plan(plan: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "operation_id",
        "adapter",
        "source_project",
        "output_project",
        "version",
        "design",
        "operations",
        "assertions",
    }
    missing = sorted(required - set(plan))
    if missing:
        raise ValueError(f"Operation plan is missing required fields: {missing}")
    if plan["schema_version"] != 1:
        raise ValueError(f"Unsupported operation plan schema: {plan['schema_version']}")
    for field in ("operation_id", "source_project", "output_project", "version", "design"):
        if not isinstance(plan[field], str) or not plan[field].strip():
            raise ValueError(f"Operation plan field {field} must be a non-empty string.")
    adapters = {"hfss3dlayout.native/v1", "hfss3dlayout.pyedb-native/v1"}
    if plan["adapter"] not in adapters:
        raise ValueError(f"Unsupported operation adapter: {plan['adapter']}")
    if plan.get("solve_requested", False) is not False:
        raise ValueError("Bridge transactions do not run solves; solve_requested must be false.")
    if not isinstance(plan["operations"], list) or not plan["operations"]:
        raise ValueError("Operation plan requires at least one typed operation.")
    if not isinstance(plan["assertions"], list) or not plan["assertions"]:
        raise ValueError("Operation plan requires fresh-reopen assertions.")
    allowed_plan_keys = required | {
        "profile",
        "runtime",
        "solve_requested",
        "redact_paths",
        "source_fingerprint",
    }
    extra = sorted(set(plan) - allowed_plan_keys)
    if extra:
        raise ValueError(f"Unsupported operation plan fields: {extra}")
    if "source_fingerprint" in plan:
        _validate_source_fingerprint(plan["source_fingerprint"])
    operation_types = {
        "set_property",
        "create_gap_port",
        "ensure_apd_bondwire_profile",
        "set_bondwire",
    }
    assertion_types = {
        "property_equals",
        "same_property",
        "object_exists",
        "port_count",
        "required_ports",
        "setup_count",
        "required_setups",
        "port_property_equals",
        "port_property_contains",
        "design_equals",
        "display_equals",
        "bondwire_matches",
        "bondwire_projected_length",
        "bondwire_profile_height",
        "bondwire_endpoint_in_conductor",
        "bondwire_obstacle_clearance",
        "bondwire_pairwise_clearance",
        "bondwire_count",
        "geometry_check_clean",
    }
    for operation in plan["operations"]:
        if not isinstance(operation, dict) or operation.get("type") not in operation_types:
            raise ValueError(f"Unsupported typed operation: {operation!r}")
        if operation["type"] == "set_property":
            _validate_shape(
                operation,
                required={"type", "server", "property", "value"},
                allowed={"type", "tab", "server", "property", "value", "expected_before"},
                label="set_property",
            )
            if operation.get("tab", "BaseElementTab") != "BaseElementTab":
                raise ValueError("set_property supports only BaseElementTab in v1.")
        elif operation["type"] == "create_gap_port":
            _validate_shape(
                operation,
                required={
                    "type",
                    "positive_object",
                    "selected_side",
                    "port_name",
                    "reference_patch",
                },
                allowed={
                    "type",
                    "positive_object",
                    "selected_side",
                    "port_name",
                    "reference_patch",
                    "settings",
                },
                label="create_gap_port",
            )
            if operation["selected_side"] not in {"L", "R", "T", "B"}:
                raise ValueError("create_gap_port selected_side must be one of L/R/T/B.")
            reference = operation["reference_patch"]
            if not isinstance(reference, dict):
                raise ValueError("create_gap_port reference_patch must be an object.")
            _validate_shape(
                reference,
                required={"layer", "net", "depth_um"},
                allowed={"layer", "net", "depth_um"},
                label="reference_patch",
            )
            if not isinstance(reference["depth_um"], (int, float)) or reference["depth_um"] <= 0:
                raise ValueError("reference_patch depth_um must be positive.")
            settings = operation.get("settings", {})
            if not isinstance(settings, dict):
                raise ValueError("create_gap_port settings must be an object.")
            allowed_settings = {
                "HFSS Type",
                "Renormalize",
                "Renormalize Impedance",
                "DeembedParasiticPortInductance",
            }
            if set(settings) - allowed_settings:
                raise ValueError("create_gap_port contains unsupported settings.")
            if settings.get("HFSS Type", "Gap") != "Gap":
                raise ValueError("create_gap_port HFSS Type must remain Gap.")
        elif operation["type"] == "ensure_apd_bondwire_profile":
            _validate_apd_profile(operation)
        else:
            _validate_set_bondwire(operation)
    permitted_operations = {
        "hfss3dlayout.native/v1": {"set_property", "create_gap_port"},
        "hfss3dlayout.pyedb-native/v1": {
            "ensure_apd_bondwire_profile",
            "set_bondwire",
        },
    }[plan["adapter"]]
    incompatible = sorted(
        {operation["type"] for operation in plan["operations"]} - permitted_operations
    )
    if incompatible:
        raise ValueError(
            f"Operations {incompatible} are incompatible with adapter {plan['adapter']}."
        )
    for assertion in plan["assertions"]:
        if not isinstance(assertion, dict) or assertion.get("type") not in assertion_types:
            raise ValueError(f"Unsupported typed assertion: {assertion!r}")
        required_by_type = {
            "property_equals": {"server", "property", "value"},
            "same_property": {"left_server", "right_server", "property"},
            "object_exists": {"name"},
            "port_count": {"value"},
            "required_ports": {"value"},
            "setup_count": {"value"},
            "required_setups": {"value"},
            "port_property_equals": {"port", "property", "value"},
            "port_property_contains": {"port", "property", "value"},
            "design_equals": {"value"},
            "display_equals": {"value"},
            "bondwire_matches": {"name", "expected"},
            "bondwire_projected_length": {"name", "value_um", "tolerance_um"},
            "bondwire_profile_height": {"name", "value_um", "tolerance_um"},
            "bondwire_endpoint_in_conductor": {"name", "endpoint", "conductor"},
            "bondwire_obstacle_clearance": {"name", "obstacles", "minimum_um"},
            "bondwire_pairwise_clearance": {"minimum_um"},
            "bondwire_count": {"value"},
            "geometry_check_clean": set(),
        }
        allowed_assertion = {
            "type",
            "id",
            "tab",
            "server",
            "left_server",
            "right_server",
            "property",
            "name",
            "port",
            "value",
            "expected",
            "value_um",
            "tolerance_um",
            "endpoint",
            "conductor",
            "obstacles",
            "minimum_um",
            "names",
            "start_contact_exemption_um",
        }
        _validate_shape(
            assertion,
            required={"type"} | required_by_type[assertion["type"]],
            allowed=allowed_assertion,
            label=f"assertion {assertion['type']}",
        )
        if assertion.get("tab", "BaseElementTab") != "BaseElementTab":
            raise ValueError("Assertions support only BaseElementTab in v1.")
        if assertion["type"] in {
            "required_ports",
            "required_setups",
            "port_property_contains",
        } and (not isinstance(assertion["value"], list) or not assertion["value"]):
            raise ValueError(f"{assertion['type']} value must be a non-empty list.")
        if assertion["type"] in {"port_count", "setup_count"} and (
            not isinstance(assertion["value"], int) or assertion["value"] < 0
        ):
            raise ValueError(f"{assertion['type']} value must be a non-negative integer.")
        if assertion["type"] == "bondwire_count" and (
            not isinstance(assertion["value"], int) or assertion["value"] < 0
        ):
            raise ValueError("bondwire_count value must be a non-negative integer.")
        if assertion["type"] == "bondwire_endpoint_in_conductor" and assertion["endpoint"] not in {
            "start",
            "end",
        }:
            raise ValueError("bondwire endpoint must be start or end.")
        if assertion["type"] == "bondwire_obstacle_clearance" and (
            not isinstance(assertion["obstacles"], list) or not assertion["obstacles"]
        ):
            raise ValueError("bondwire_obstacle_clearance obstacles must be non-empty.")


def _validate_source_fingerprint(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("source_fingerprint must be an object.")
    _validate_shape(
        value,
        required={"aedt_sha256", "edb_definition_sha256"},
        allowed={"aedt_sha256", "edb_definition_sha256"},
        label="source_fingerprint",
    )
    for key in ("aedt_sha256", "edb_definition_sha256"):
        digest = value[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in digest)
        ):
            raise ValueError(f"source_fingerprint {key} must be a SHA-256 hex digest.")


def _validate_apd_profile(operation: dict[str, Any]) -> None:
    _validate_shape(
        operation,
        required={"type", "name", "direction", "diameter_um", "material", "segments"},
        allowed={"type", "name", "direction", "diameter_um", "material", "segments"},
        label="ensure_apd_bondwire_profile",
    )
    if operation["direction"] not in {"forward", "reverse"}:
        raise ValueError("APD direction must be forward or reverse.")
    if not isinstance(operation["diameter_um"], (int, float)) or operation["diameter_um"] <= 0:
        raise ValueError("APD diameter_um must be positive.")
    if not isinstance(operation["segments"], list) or not operation["segments"]:
        raise ValueError("APD segments must be a non-empty list.")
    modes = {"absolute_um", "fraction", "angle_deg", "switch"}
    for segment in operation["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("Each APD segment must be an object.")
        _validate_shape(
            segment,
            required={"horizontal_mode", "horizontal_value", "vertical_mode", "vertical_value"},
            allowed={"horizontal_mode", "horizontal_value", "vertical_mode", "vertical_value"},
            label="APD segment",
        )
        if segment["horizontal_mode"] not in modes or segment["vertical_mode"] not in modes:
            raise ValueError("Unsupported APD segment mode.")
        if not all(
            isinstance(segment[key], (int, float)) for key in ("horizontal_value", "vertical_value")
        ):
            raise ValueError("APD segment values must be numeric.")


def _validate_xy(value: Any, label: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError(f"{label} must be a two-number list in micrometres.")


def _validate_set_bondwire(operation: dict[str, Any]) -> None:
    _validate_shape(
        operation,
        required={"type", "name", "expected_before"},
        allowed={
            "type",
            "name",
            "expected_before",
            "start_xy_um",
            "end_xy_um",
            "bondwire_type",
            "profile",
            "diameter_um",
            "material",
        },
        label="set_bondwire",
    )
    expected = operation["expected_before"]
    if not isinstance(expected, dict) or not expected:
        raise ValueError("set_bondwire expected_before must be a non-empty object.")
    allowed_state = {
        "start_xy_um",
        "end_xy_um",
        "bondwire_type",
        "profile",
        "diameter_um",
        "material",
    }
    if set(expected) - allowed_state:
        raise ValueError("set_bondwire expected_before contains unsupported fields.")
    for container in (operation, expected):
        for key in ("start_xy_um", "end_xy_um"):
            if key in container:
                _validate_xy(container[key], key)
    for container in (operation, expected):
        if "bondwire_type" in container and container["bondwire_type"] not in {
            "apd",
            "jedec4",
            "jedec5",
        }:
            raise ValueError("bondwire_type must be apd, jedec4, or jedec5.")


def _validate_shape(
    value: dict[str, Any], *, required: set[str], allowed: set[str], label: str
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ValueError(f"{label} is missing required fields: {missing}")
    if extra:
        raise ValueError(f"{label} contains unsupported fields: {extra}")


def _bundle_fingerprint(project: Path) -> dict[str, str]:
    aedb = project.with_suffix(".aedb")
    fingerprint = {project.name: sha256_file(project)}
    for path in sorted(item for item in aedb.rglob("*") if item.is_file()):
        fingerprint[f"{aedb.name}/{path.relative_to(aedb).as_posix()}"] = sha256_file(path)
    return fingerprint


def _source_unchanged(source: Path, expected: dict[str, str]) -> bool:
    try:
        return _bundle_fingerprint(source) == expected
    except OSError:
        return False


def _adapter_for(plan: dict[str, Any]) -> OperationAdapter:
    if plan["adapter"] == "hfss3dlayout.native/v1":
        from .hfss3dlayout_adapter import Hfss3dLayoutNativeAdapter

        return Hfss3dLayoutNativeAdapter()
    if plan["adapter"] == "hfss3dlayout.pyedb-native/v1":
        from .hfss3dlayout_pyedb_adapter import Hfss3dLayoutPyedbNativeAdapter

        return Hfss3dLayoutPyedbNativeAdapter()
    raise ValueError(f"Unsupported operation adapter: {plan['adapter']}")


def _display_path(path: Path, *, redact: bool) -> str:
    return path.name if redact else str(path)


def execute_operation_plan(
    plan: dict[str, Any], *, adapter: OperationAdapter | None = None
) -> dict[str, Any]:
    validate_operation_plan(plan)
    source = Path(plan["source_project"]).expanduser().resolve()
    output = Path(plan["output_project"]).expanduser().resolve()
    redact = bool(plan.get("redact_paths", False))
    if source == output:
        raise ValueError("source_project and output_project must differ.")
    source_state = inspect_project_bundle(source)
    if not source_state["bundle_complete"]:
        raise ValueError(f"Incomplete source project bundle: {source_state['reason']}")
    expected_fingerprint = plan.get("source_fingerprint")
    if expected_fingerprint:
        actual_fingerprint = {
            "aedt_sha256": sha256_file(source),
            "edb_definition_sha256": sha256_file(source.with_suffix(".aedb") / "edb.def"),
        }
        if {key: str(value).casefold() for key, value in actual_fingerprint.items()} != {
            key: str(value).casefold() for key, value in expected_fingerprint.items()
        }:
            raise ValueError(
                "Source fingerprint mismatch; transaction refused before staging. "
                f"Expected {expected_fingerprint}, found {actual_fingerprint}."
            )
    if output.exists() or output.with_suffix(".aedb").exists():
        raise ValueError("Output project or matching .aedb already exists; overwrite is refused.")
    if not output.parent.is_dir():
        raise ValueError(f"Output parent does not exist: {output.parent}")

    selected_adapter = adapter or _adapter_for(plan)
    if selected_adapter.adapter_id != plan["adapter"]:
        raise ValueError(
            "Adapter identity mismatch: "
            f"plan={plan['adapter']} runtime={selected_adapter.adapter_id}"
        )
    source_before = _bundle_fingerprint(source)
    stage_root = output.parent / f".ansysem-stage-{uuid.uuid4().hex}"
    staged_project = stage_root / output.name
    committed: list[Path] = []
    try:
        stage_root.mkdir()
        shutil.copy2(source, staged_project)
        shutil.copytree(source.with_suffix(".aedb"), staged_project.with_suffix(".aedb"))
        apply_readback = selected_adapter.apply(staged_project, plan)
        verify_readback = selected_adapter.verify(staged_project, plan)
        validations = list(verify_readback.get("validation", []))
        if not validations or not all(item.get("passed") is True for item in validations):
            raise RuntimeError("One or more fresh-reopen assertions failed.")
        source_after = _bundle_fingerprint(source)
        if source_after != source_before:
            raise RuntimeError("Source project bundle changed during the transaction.")

        os.replace(staged_project, output)
        committed.append(output)
        os.replace(staged_project.with_suffix(".aedb"), output.with_suffix(".aedb"))
        committed.append(output.with_suffix(".aedb"))
        output_state = inspect_project_bundle(output, redact_paths=redact)
        return {
            "schema_version": 1,
            "operation": "model.apply_transaction",
            "status": "passed",
            "identity": {
                "operation_id": plan["operation_id"],
                "adapter": selected_adapter.adapter_id,
                "project": _display_path(output, redact=redact),
                "design": plan["design"],
                "display": os.environ.get("DISPLAY"),
            },
            "readback": {
                "apply": apply_readback,
                "fresh_reopen": verify_readback.get("readback", {}),
                "source_unchanged": True,
                "output_bundle_complete": output_state["bundle_complete"],
                "solve_requested": False,
                "solve_run": False,
            },
            "artifacts": [
                {
                    "path": output_state["project"],
                    "sha256": output_state["project_sha256"],
                    "edb_definition_sha256": sha256_file(output.with_suffix(".aedb") / "edb.def"),
                    "bundle_complete": output_state["bundle_complete"],
                }
            ],
            "validation": validations,
            "warnings": [
                "No solve, packaging, publication, or release operation was requested or run."
            ],
            "failure": None,
            "safe_next_actions": [],
        }
    except Exception as exc:
        for path in reversed(committed):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        return {
            "schema_version": 1,
            "operation": "model.apply_transaction",
            "status": "failed",
            "identity": {
                "operation_id": plan["operation_id"],
                "adapter": selected_adapter.adapter_id,
                "project": _display_path(output, redact=redact),
                "design": plan["design"],
                "display": os.environ.get("DISPLAY"),
            },
            "readback": {
                "source_unchanged": _source_unchanged(source, source_before),
                "output_committed": False,
                "solve_requested": False,
                "solve_run": False,
            },
            "artifacts": [],
            "validation": [],
            "warnings": [],
            "failure": {"type": exc.__class__.__name__, "message": str(exc)},
            "safe_next_actions": ["Correct the typed plan or runtime prerequisite and retry."],
        }
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root)
