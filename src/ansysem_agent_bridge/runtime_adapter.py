"""Durable-job adapter between EDA Runtime and Ansys Electronics Desktop."""

from __future__ import annotations

import os
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from eda_bridge_runtime.service import DurableService

from . import __version__
from .aedt_context_tool import store_context
from .capabilities import capability_map
from .config import agent_home
from .discovery import select_installation
from .docs_backend import docs_status, get_doc, query_docs
from .experience_shortcuts import (
    compiled_shortcut_binding,
    get_asset,
    list_assets,
    shortcut_receipt,
    shortcut_state,
    validate_shortcut,
)
from .layout_build import execute_layout_build_plan
from .layout_solve import execute_layout_solve_plan
from .live_patch import apply_live_patch, finalize_live_design
from .live_probe import live_hfss3dlayout_probe
from .native_program import execute_native_program
from .operations import export_layout_image
from .project_bundle import bundle_state_revision, inspect_project_bundle
from .project_create import create_hfss3dlayout_project
from .runtime import runtime_snapshot
from .session_lifecycle import (
    authorize_owned_aedt_session,
    release_owned_aedt_session,
)
from .transaction import execute_operation_plan
from .workspace import (
    abort_workspace,
    begin_workspace,
    promote_workspace,
    reconcile_workspace,
    rollback_workspace,
    workspace_status,
)


def _runtime_imports():
    try:
        from eda_bridge_runtime import (
            Adapter,
            AdapterResult,
            ExecutionLedger,
            JobStore,
            ResponseEnvelope,
            Runtime,
            run_job_worker,
            spawn_detached_worker,
        )
        from eda_bridge_runtime.transport import serve_json_lines
    except ImportError as exc:
        raise RuntimeError(
            "EDA Runtime support is not installed. Install ansysem-agent-bridge[runtime]."
        ) from exc
    return {
        "Adapter": Adapter,
        "AdapterResult": AdapterResult,
        "ExecutionLedger": ExecutionLedger,
        "JobStore": JobStore,
        "ResponseEnvelope": ResponseEnvelope,
        "Runtime": Runtime,
        "run_job_worker": run_job_worker,
        "serve_json_lines": serve_json_lines,
        "spawn_detached_worker": spawn_detached_worker,
    }


def runtime_state_dir() -> Path:
    path = agent_home() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_jobs_path() -> Path:
    return runtime_state_dir() / "jobs.sqlite3"


def default_ledger_path() -> Path:
    return runtime_state_dir() / "execution-ledger.sqlite3"


_OPERATIONS = {
    "capabilities": {"handler": "_execute_capabilities", "mutates": False},
    "design.live_finalize": {"handler": "_execute_design_live_finalize", "mutates": True},
    "design.live_patch": {"handler": "_execute_design_live_patch", "mutates": True},
    "docs.get": {"handler": "_execute_docs_get", "mutates": False},
    "docs.symbol": {"handler": "_execute_docs_get", "mutates": False},
    "docs.query": {"handler": "_execute_docs_get", "mutates": False},
    "docs.status": {"handler": "_execute_docs_get", "mutates": False},
    "experience.get": {"handler": "_execute_experience_get", "mutates": False},
    "experience.list": {"handler": "_execute_experience_list", "mutates": False},
    "layout.build": {"handler": "_execute_layout_build", "mutates": True},
    "layout.export_image": {"handler": "_execute_layout_export_image", "mutates": False},
    "layout.solve": {"handler": "_execute_layout_solve", "mutates": True},
    "model.apply": {"handler": "_execute_model_apply", "mutates": True},
    "native.execute": {"handler": "_execute_native_execute", "mutates": True},
    "project.create": {"handler": "_execute_project_create", "mutates": True},
    "project.inspect": {"handler": "_execute_project_inspect", "mutates": False},
    "runtime.snapshot": {"handler": "_execute_runtime_snapshot", "mutates": False},
    "session.launch": {"handler": "_execute_session_launch", "mutates": True},
    "session.release": {"handler": "_execute_session_release", "mutates": True},
    "workspace.abort": {"handler": "_execute_workspace_abort", "mutates": True},
    "workspace.begin": {"handler": "_execute_workspace_begin", "mutates": True},
    "workspace.promote": {"handler": "_execute_workspace_promote", "mutates": True},
    "workspace.reconcile": {"handler": "_execute_workspace_reconcile", "mutates": True},
    "workspace.rollback": {"handler": "_execute_workspace_rollback", "mutates": True},
    "workspace.status": {"handler": "_execute_workspace_status", "mutates": False},
}

_CERTIFIED_WORKFLOWS = {"layout.build", "layout.solve", "model.apply"}
_NATIVE_RUNTIME = "ansys.pyaedt.hfss3dlayout"
_CONTEXT_IDENTITY_FIELDS = (
    "project",
    "project_name",
    "design",
    "version",
    "profile",
    "display",
    "target_kind",
    "selection",
)


def _operation_class(operation: str) -> str:
    if operation == "native.execute":
        return "generic-native-execution"
    if operation in _CERTIFIED_WORKFLOWS:
        return "certified-workflow"
    return "bridge-infrastructure"


def _native_program_available() -> bool:
    return True


def _verified_content_binding(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    target = record.get("target")
    binding = record.get("binding")
    if not isinstance(target, dict) or not isinstance(binding, dict):
        raise ValueError(
            "AnsysEM context has no content-state binding; save the complete bundle and recapture"
        )
    if binding.get("schema_version") != 1 or binding.get("resource_kind") != "aedt-project":
        raise ValueError("AnsysEM context content-state binding is unsupported")
    project = Path(str(target.get("project") or "")).expanduser().resolve()
    expected_identity = {
        "project_name": target.get("project_name"),
        "design": target.get("design"),
        "version": target.get("version"),
        "profile": target.get("profile"),
        "display": target.get("display"),
    }
    for field, expected in expected_identity.items():
        if binding.get(field) != expected:
            raise ValueError(f"AnsysEM context {field} binding is inconsistent")
    try:
        actual_revision = bundle_state_revision(project)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "AnsysEM context content state is unavailable; capture a fresh continuation"
        ) from exc
    if actual_revision != binding.get("state_revision"):
        raise ValueError("AnsysEM context content state changed; capture a fresh continuation")
    digest = binding.get("bundle_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("AnsysEM context bundle fingerprint is invalid")
    return target, binding


def _materialize_context_native_plan(
    value: Any, *, target: dict[str, Any], binding: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("native.execute requires a governed native program plan")
    plan = deepcopy(value)
    runtime = plan.get("runtime")
    if runtime is not None and runtime != "" and runtime != _NATIVE_RUNTIME:
        raise ValueError("native.execute runtime conflicts with the continuation context")
    plan["runtime"] = _NATIVE_RUNTIME

    scope = plan.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("context-driven native.execute still requires an explicit scope object")
    resource_kind = scope.get("resource_kind")
    if resource_kind is not None and resource_kind != "" and resource_kind != "aedt-project":
        raise ValueError("native.execute resource kind conflicts with the continuation context")
    scope["resource_kind"] = "aedt-project"
    selectors = scope.get("selectors")
    if not isinstance(selectors, dict):
        raise ValueError("context-driven native.execute still requires scope.selectors")
    for field in ("version", "design"):
        expected = target.get(field)
        supplied = selectors.get(field)
        if supplied is not None and supplied != "" and supplied != expected:
            raise ValueError(
                f"native.execute selector {field} conflicts with the continuation context"
            )
        if not expected:
            raise ValueError(f"AnsysEM continuation context has no bound {field}")
        selectors[field] = expected

    project = Path(str(target["project"])).expanduser().resolve()
    read_paths = scope.get("read_paths")
    if read_paths is not None and read_paths != []:
        if not isinstance(read_paths, list) or len(read_paths) != 1:
            raise ValueError("native.execute read scope conflicts with the continuation context")
        if Path(str(read_paths[0])).expanduser().resolve() != project:
            raise ValueError("native.execute read path conflicts with the continuation context")
    scope["read_paths"] = [str(project)]

    if plan.get("effect") == "mutate":
        transaction = plan.get("transaction")
        if not isinstance(transaction, dict):
            raise ValueError("context-driven mutation still requires an explicit transaction")
        expected_fingerprints = {str(project): binding["bundle_sha256"]}
        supplied_fingerprints = transaction.get("source_fingerprints")
        if supplied_fingerprints is not None and supplied_fingerprints != {}:
            if not isinstance(supplied_fingerprints, dict) or len(supplied_fingerprints) != 1:
                raise ValueError(
                    "native.execute source fingerprint conflicts with the continuation context"
                )
            supplied_path, supplied_digest = next(iter(supplied_fingerprints.items()))
            if (
                Path(str(supplied_path)).expanduser().resolve() != project
                or str(supplied_digest).casefold() != binding["bundle_sha256"]
            ):
                raise ValueError(
                    "native.execute source fingerprint conflicts with the continuation context"
                )
        transaction["source_fingerprints"] = expected_fingerprints
    return plan


class _AnsysAdapterBase:
    @staticmethod
    def resource_keys(request):
        from eda_bridge_runtime import RequestEnvelope
        from eda_bridge_runtime.resources import resource_keys

        resolved = DurableAnsysService._resolve_context(request)
        target = dict(resolved.target)
        resource = resolved.payload.get("resource_id") or target.get("resource_id")
        handle = resolved.payload.get("release_handle") or target.get("release_handle")
        if resource and handle:
            from .session_lifecycle import OwnedSessionStore

            target["project"] = OwnedSessionStore().authorize(str(resource), str(handle))["project"]
        workspace = resolved.payload.get("workspace") or target.get("workspace")
        if workspace and (Path(str(workspace)) / "workspace.json").is_file():
            from .workspace import load_workspace

            _, manifest = load_workspace(workspace)
            target["source_project"] = manifest["source_project"]
            target["project"] = str(Path(str(workspace)) / manifest["current_project"])
        data = resolved.to_dict()
        data["target"] = target
        return resource_keys(RequestEnvelope.from_dict(data))

    name = "ansysem-agent-bridge"
    version = __version__

    def capabilities(self, target: dict[str, Any] | None = None) -> dict[str, Any]:
        target = target or {}
        descriptors = [
            {
                "id": operation,
                "operation_class": _operation_class(operation),
                "mutates": _OPERATIONS[operation]["mutates"],
                "requires_context": False,
            }
            for operation in sorted(_OPERATIONS)
            if operation != "capabilities"
        ]
        for descriptor in descriptors:
            if descriptor["id"] in _CERTIFIED_WORKFLOWS:
                descriptor["compiled_shortcut"] = compiled_shortcut_binding(descriptor["id"])
                descriptor["state"] = shortcut_state(
                    descriptor["id"], version=str(target.get("version") or "2026.1")
                )
            if descriptor["id"] == "project.create":
                descriptor.update(
                    {
                        "target_kind": "hfss-3d-layout-project",
                        "returns_context": True,
                        "input_schema": {
                            "required": ["project", "design", "version"],
                            "optional": ["profile", "display", "redact_paths"],
                        },
                    }
                )
            if descriptor["id"] == "session.launch":
                descriptor["resource_lifecycle"] = {
                    "creates_when": "a new interactive AEDT desktop is launched",
                    "kind": "aedt-desktop",
                    "release_operation": "session.release",
                }
                descriptor["input_schema"] = {
                    "required": ["project", "version"],
                    "optional": ["design", "port", "validate", "redact_paths"],
                }
            if descriptor["id"] == "session.release":
                descriptor["input_schema"] = {
                    "required": ["resource_id", "release_handle"],
                    "optional": ["timeout_seconds"],
                }
            if descriptor["id"] == "runtime.snapshot":
                descriptor["input_schema"] = {
                    "required": [],
                    "optional": [
                        "project",
                        "version",
                        "design",
                        "live",
                        "validate",
                        "redact_paths",
                        "reuse_existing",
                        "resource_id",
                        "release_handle",
                    ],
                    "owned_session_reuse": {
                        "requires_together": ["resource_id", "release_handle"],
                        "identity_bound": ["project", "version", "design"],
                    },
                }
            if descriptor["id"] == "project.inspect":
                descriptor["input_schema"] = {
                    "required": ["project"],
                    "optional": ["redact_paths"],
                }
            if descriptor["id"] == "layout.export_image":
                descriptor["input_schema"] = {
                    "required": ["project", "version", "output"],
                    "optional": ["design", "port", "width", "height", "redact_paths"],
                }
            if descriptor["id"] == "design.live_patch":
                descriptor.update(
                    {
                        "operation_class": "typed-live-edit",
                        "run_model": "synchronous",
                        "input_schema": {
                            "required": [
                                "project",
                                "version",
                                "design",
                            ],
                            "optional": [
                                "operation",
                                "operations",
                                "resource_id",
                                "release_handle",
                                "schema_version",
                                "patch_id",
                                "expected_revision",
                                "conflict_policy",
                                "validation",
                            ],
                            "authorization": {
                                "requires_one_of": [
                                    ["resource_id", "release_handle"],
                                    ["EDA_CONTEXT:live-session"],
                                ]
                            },
                            "requires_one_of": ["operation", "operations"],
                            "operation_schema": (
                                "eda.live-edit/v1 + ansysem.live-design-operation/v2"
                            ),
                        },
                    }
                )
            if descriptor["id"] == "design.live_finalize":
                descriptor.update(
                    {
                        "operation_class": "typed-live-edit",
                        "run_model": "synchronous",
                        "input_schema": {
                            "required": ["project", "version", "design", "action"],
                            "optional": ["resource_id", "release_handle", "decision"],
                            "action_enum": [
                                "keep_unsaved",
                                "save",
                                "discard_unsaved",
                                "rollback_patch",
                            ],
                            "authorization": {
                                "requires_one_of": [
                                    ["resource_id", "release_handle"],
                                    ["EDA_CONTEXT:live-session"],
                                ]
                            },
                        },
                    }
                )
            if descriptor["id"] == "layout.build":
                descriptor["input_schema"] = {
                    "required": ["plan"],
                    "plan_schema": "ansysem.hfss3dlayout-build/v1",
                }
            if descriptor["id"] == "layout.solve":
                descriptor["input_schema"] = {
                    "required": ["plan"],
                    "plan_schema": "ansysem.hfss3dlayout-solve/v1",
                }
            if descriptor["id"] == "model.apply":
                descriptor["input_schema"] = {
                    "required": ["plan"],
                    "plan_schema": "ansysem.operation-plan/v1",
                }
            if descriptor["id"] == "native.execute":
                from .native_backends import BACKENDS

                native_available = _native_program_available()
                descriptor.update(
                    {
                        "accepts_context": True,
                        "returns_context": True,
                        "backends": [
                            {
                                "runtime": item.runtime,
                                "modes": list(item.modes),
                                "resource_kind": item.resource_kind,
                                "sdk_module": item.sdk_module,
                            }
                            for item in BACKENDS.values()
                        ],
                        "python_environment": "normal Python with installed SDK dependencies",
                        "authorization": "checked against the selected target at execution",
                        "state": {
                            "available": native_available,
                            "healthy": native_available,
                        },
                        "input_schema": {
                            "required": ["plan"],
                            "plan_schema": "eda.native-program/v1",
                            "agent_required": [
                                "purpose",
                                "plan.effect",
                                "plan.mode",
                                "plan.program",
                                "plan.scope.write_paths",
                                "plan.scope.artifacts",
                                "plan.transaction.strategy",
                                "plan.transaction.fresh_reopen",
                                "plan.transaction.promotion",
                                "plan.validation",
                                "plan.limits",
                            ],
                            "derived_fields": [
                                "plan.program_id",
                                "plan.program.sha256",
                                "plan.validation.program.sha256",
                                "plan.runtime",
                                "plan.scope.resource_kind",
                                "plan.scope.selectors.version",
                                "plan.scope.selectors.design",
                                "plan.scope.read_paths",
                                "plan.transaction.source_fingerprints",
                            ],
                        },
                    }
                )
            if descriptor["id"] == "docs.status":
                descriptor["input_schema"] = {
                    "required": [],
                    "optional": ["instance", "docs_root"],
                }
            if descriptor["id"] == "docs.symbol":
                descriptor["input_schema"] = {
                    "required": ["query"],
                    "optional": ["sdk", "limit"],
                    "sdk": ["pyaedt", "pyedb"],
                }
            if descriptor["id"] == "docs.query":
                descriptor["input_schema"] = {
                    "required": ["query"],
                    "optional": ["instance", "docs_root", "module", "limit"],
                }
            if descriptor["id"] == "docs.get":
                descriptor["input_schema"] = {
                    "required": ["source_ref"],
                    "optional": ["instance", "docs_root", "focus", "max_chars"],
                }
            if descriptor["id"] == "experience.list":
                descriptor["input_schema"] = {
                    "required": [],
                    "optional": [
                        "intents",
                        "tags",
                        "version",
                        "profile",
                        "capability",
                    ],
                    "filter_semantics": "exact metadata match",
                }
            if descriptor["id"] == "experience.get":
                descriptor["input_schema"] = {
                    "one_of": [
                        {"required": ["asset_id"]},
                        {"required": ["version", "profile", "capability"]},
                    ],
                    "optional": ["max_chars"],
                    "normal_use": (
                        "resolve and read one unique exact metadata match without "
                        "listing the library first"
                    ),
                }
            if descriptor["id"] == "workspace.begin":
                descriptor["input_schema"] = {
                    "required": ["source", "workspace", "adapter", "version", "design"],
                    "optional": [
                        "profile",
                        "workspace_id",
                        "source_fingerprint",
                        "redact_paths",
                    ],
                }
            if descriptor["id"] == "workspace.status":
                descriptor["input_schema"] = {
                    "required": ["workspace"],
                    "optional": ["redact_paths"],
                }
            if descriptor["id"] == "workspace.reconcile":
                descriptor["input_schema"] = {
                    "required": ["workspace", "patch"],
                    "patch_schema": "ansysem.workspace-patch/v1",
                    "optional": ["redact_paths"],
                }
            if descriptor["id"] in {"workspace.rollback", "workspace.abort"}:
                descriptor["input_schema"] = {
                    "required": ["workspace", "expected_workspace_revision"],
                    "optional": ["redact_paths"],
                }
            if descriptor["id"] == "workspace.promote":
                descriptor["input_schema"] = {
                    "required": ["workspace", "expected_workspace_revision", "output"],
                    "optional": ["promotion_id", "retain_candidate", "redact_paths"],
                }
            schema = descriptor.get("input_schema")
            if isinstance(schema, dict):
                fields = set(schema.get("required") or []) | set(schema.get("optional") or [])
                descriptions = dict(schema.get("field_descriptions") or {})
                if "instance" in fields:
                    descriptions["instance"] = (
                        "Ansys Electronics Desktop installation selector "
                        "(installation_id); never a project, design, editor, or model object"
                    )
                if "project" in fields:
                    descriptions["project"] = "Exact .aedt project filesystem path"
                if "design" in fields:
                    descriptions["design"] = "Exact AEDT design name within the selected project"
                if "workspace" in fields:
                    descriptions["workspace"] = "Exact candidate-workspace directory path"
                if descriptions:
                    schema["field_descriptions"] = descriptions
                    descriptor["input_schema"] = schema
        from eda_bridge_runtime import stable_origin_id

        return {
            "eda": "ansys-electronics-desktop",
            "origin_id": stable_origin_id("ansys-electronics-desktop"),
            "execution_host_role": "eda-worker",
            "run_model": "durable",
            "session_model": "durable-job",
            "operations": descriptors,
            "execution_routes": ["native.execute", "compiled_workflow"],
            "target": {key: target[key] for key in ("profile", "display") if key in target},
        }

    def execute(self, request, context):
        AdapterResult = _runtime_imports()["AdapterResult"]
        if request.operation not in _OPERATIONS:
            raise ValueError(f"unsupported AnsysEM Runtime operation: {request.operation}")
        started = time.monotonic()
        context.emit(
            "ansysem.operation.started",
            {
                "operation": request.operation,
                "profile": request.target.get("profile"),
                "display": os.environ.get("DISPLAY"),
            },
        )
        result = self._dispatch(request, context)
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        context.emit(
            "ansysem.operation.completed",
            {
                "operation": request.operation,
                "status": result.get("status"),
                "adapter_total_ms": elapsed_ms,
            },
        )
        status = (
            "passed"
            if request.operation.startswith("docs.")
            or result.get("status") in {"ready", "passed", "preserved", "removed"}
            else "failed"
        )
        return AdapterResult(
            status=status,
            result={"bridge": result, "timing": {"adapter_total_ms": elapsed_ms}},
            error={
                "code": "validation_failed",
                "phase": "validation",
                "message": str(result.get("error") or result.get("status")),
                "evidence": result,
            }
            if status == "failed"
            else None,
        )

    @staticmethod
    def _value(request, name: str, *, required: bool = False, default: Any = None) -> Any:
        value = request.payload.get(name, request.target.get(name, default))
        if required and (value is None or value == ""):
            raise ValueError(f"AnsysEM Runtime field is required: {name}")
        return value

    @staticmethod
    def requires_admission(request):
        return _OPERATIONS.get(request.operation, {"mutates": True})["mutates"]

    def _dispatch(self, request, context=None):
        definition = _OPERATIONS.get(request.operation)
        if definition is None:
            raise ValueError(f"Unsupported operation: {request.operation}")
        return getattr(self, definition["handler"])(request, context)

    def _execute_capabilities(self, request, context=None):
        return {
            "status": "ready",
            "capabilities": capability_map(
                project=self._value(request, "project"),
                docs_root=self._value(request, "docs_root"),
                display=self._value(request, "display"),
            ),
        }

    def _execute_docs_get(self, request, context=None):
        operation = request.operation
        if request.is_mutating:
            raise ValueError("AnsysEM documentation operations require payload.mutating=false")
        if operation == "docs.symbol":
            from .sdk_docs import describe

            return describe(
                str(request.payload.get("query") or ""),
                sdk=str(request.payload.get("sdk", "pyaedt")),
                limit=int(request.payload.get("limit", 6)),
            )
        explicit_root = self._value(request, "docs_root")
        version = self._value(request, "version")
        if explicit_root:
            root = Path(str(explicit_root)).expanduser().resolve()
        else:
            configured = os.environ.get("ANSYSEM_DOC_ROOT")
            if configured:
                root = Path(configured).expanduser().resolve()
            else:
                installation = select_installation(self._value(request, "instance"))
                version = version or installation.version
                from .docs_ingest import discover_docs_root

                discovered = installation.docs_root or discover_docs_root(installation.root)
                if not discovered:
                    return {"status": "source_missing", "results": [], "execution_available": True}
                root = Path(discovered).expanduser().resolve()
        if operation == "docs.status":
            return {"status": "ready", "docs": docs_status(root)}
        if operation == "docs.query":
            return {
                "status": "ready",
                **query_docs(
                    root,
                    str(request.payload.get("query") or ""),
                    module=request.payload.get("module"),
                    limit=int(request.payload.get("limit", 6)),
                    version=version,
                ),
            }
        return {
            "status": "ready",
            **get_doc(
                root,
                str(request.payload.get("source_ref") or ""),
                focus=request.payload.get("focus"),
                max_chars=int(request.payload.get("max_chars", 4000)),
                version=version,
            ),
        }

    def _execute_experience_list(self, request, context=None):
        return list_assets(
            intents=list(request.payload.get("intents") or []),
            tags=list(request.payload.get("tags") or []),
            version=(str(request.payload["version"]) if request.payload.get("version") else None),
            profile=(str(request.payload["profile"]) if request.payload.get("profile") else None),
            capability=(
                str(request.payload["capability"]) if request.payload.get("capability") else None
            ),
        )

    def _execute_experience_get(self, request, context=None):
        return get_asset(
            (str(request.payload["asset_id"]) if request.payload.get("asset_id") else None),
            version=(str(request.payload["version"]) if request.payload.get("version") else None),
            profile=(str(request.payload["profile"]) if request.payload.get("profile") else None),
            capability=(
                str(request.payload["capability"]) if request.payload.get("capability") else None
            ),
            max_chars=int(request.payload.get("max_chars", 8000)),
        )

    def _execute_project_inspect(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        result = inspect_project_bundle(
            self._value(request, "project", required=True), redact_paths=redact
        )
        return {"status": "ready" if result["bundle_complete"] else "blocked", "result": result}

    def _execute_project_create(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        return create_hfss3dlayout_project(
            project=self._value(request, "project", required=True),
            design=str(self._value(request, "design", required=True)),
            version=str(self._value(request, "version", required=True)),
            connection_id=self._value(request, "connection_id"),
            profile=self._value(request, "profile"),
            expected_display=self._value(request, "display"),
            redact_paths=redact,
        )

    def _execute_runtime_snapshot(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        if request.payload.get("leave_open"):
            raise ValueError(
                "runtime.snapshot cannot leave a new AEDT process open; use session.launch"
            )
        if request.payload.get("live"):
            resource_id = self._value(request, "resource_id")
            release_handle = self._value(request, "release_handle")
            if bool(resource_id) != bool(release_handle):
                raise ValueError(
                    "runtime.snapshot owned-session reuse requires resource_id and release_handle"
                )
            owned = None
            if resource_id:
                owned = authorize_owned_aedt_session(
                    resource_id=str(resource_id),
                    release_handle=str(release_handle),
                    project=self._value(request, "project", required=True),
                    version=str(self._value(request, "version", required=True)),
                    design=self._value(request, "design"),
                )
            return live_hfss3dlayout_probe(
                project=self._value(request, "project", required=True),
                version=self._value(request, "version", required=True),
                design=self._value(request, "design"),
                port=int(owned["port"] if owned else request.payload.get("port", 0)),
                new_desktop=False if owned else not bool(request.payload.get("reuse_existing")),
                close_desktop=False if owned else not bool(request.payload.get("leave_open")),
                validate=bool(request.payload.get("validate")),
                redact_paths=redact,
                since_revision=request.payload.get("since_revision"),
                expected_pid=int(owned["pid"]) if owned else None,
            )
        return runtime_snapshot(
            installation_id=self._value(request, "instance"),
            version=self._value(request, "version"),
            project=self._value(request, "project"),
            design=self._value(request, "design"),
            editor=self._value(request, "editor"),
            lane=str(request.payload.get("lane", "host")),
            display=self._value(request, "display"),
            docs_root=self._value(request, "docs_root"),
            since_revision=request.payload.get("since_revision"),
            redact_paths=redact,
        )

    def _execute_session_launch(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        result = live_hfss3dlayout_probe(
            project=self._value(request, "project", required=True),
            version=self._value(request, "version", required=True),
            design=self._value(request, "design"),
            port=int(request.payload.get("port", 0)),
            new_desktop=True,
            close_desktop=False,
            validate=bool(request.payload.get("validate")),
            redact_paths=redact,
        )
        resource = result.get("resource")
        if result.get("status") not in {"ready", "passed"} and isinstance(resource, dict):
            release_owned_aedt_session(
                resource_id=str(resource.get("resource_id") or ""),
                release_handle=str(resource.get("release_handle") or ""),
            )
        return result

    def _execute_session_release(self, request, context=None):
        return release_owned_aedt_session(
            resource_id=str(self._value(request, "resource_id", required=True)),
            release_handle=str(self._value(request, "release_handle", required=True)),
            timeout_seconds=float(request.payload.get("timeout_seconds", 15.0)),
        )

    def _execute_design_live_patch(self, request, context=None):
        import hashlib

        from eda_bridge_runtime import LIVE_EDIT_SCHEMA, validate_live_edit

        requested_operations = request.payload.get("operations")
        legacy_operation = request.payload.get("operation")
        if requested_operations is None and legacy_operation is not None:
            requested_operations = [legacy_operation]
        patch_id = str(request.payload.get("patch_id") or "")
        if not patch_id:
            material = str(
                getattr(request, "idempotency_key", None)
                or getattr(request, "request_id", "live-patch")
            )
            patch_id = "patch-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        common = validate_live_edit(
            {
                "schema_version": request.payload.get("schema_version") or LIVE_EDIT_SCHEMA,
                "patch_id": patch_id,
                "expected_revision": request.payload.get("expected_revision"),
                "operations": requested_operations,
                "conflict_policy": request.payload.get("conflict_policy") or "fail_on_change",
                "validation": request.payload.get("validation") or "readback",
            }
        )
        if common["expected_revision"] is not None:
            raise ValueError(
                "AnsysEM live edits currently require object preconditions, not a global revision"
            )
        return apply_live_patch(
            resource_id=self._value(request, "resource_id"),
            release_handle=self._value(request, "release_handle"),
            context=request.target.get("_continuation_context"),
            project=self._value(request, "project", required=True),
            version=str(self._value(request, "version", required=True)),
            design=str(self._value(request, "design", required=True)),
            operations=common["operations"],
            patch_id=common["patch_id"],
        )

    def _execute_design_live_finalize(self, request, context=None):
        return finalize_live_design(
            resource_id=self._value(request, "resource_id"),
            release_handle=self._value(request, "release_handle"),
            context=request.target.get("_continuation_context"),
            project=self._value(request, "project", required=True),
            version=str(self._value(request, "version", required=True)),
            design=str(self._value(request, "design", required=True)),
            action=str(self._value(request, "action", required=True)),
            decision=request.payload.get("decision"),
        )

    def _execute_layout_export_image(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        return export_layout_image(
            project=self._value(request, "project", required=True),
            version=self._value(request, "version", required=True),
            design=self._value(request, "design"),
            port=int(request.payload.get("port", 0)),
            output=request.payload["output"],
            width=int(request.payload.get("width", 1600)),
            height=int(request.payload.get("height", 1000)),
            redact_paths=redact,
        )

    def _execute_layout_build(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        plan = request.payload.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("layout.build requires a structured plan object")
        validate_shortcut(operation, version=str(plan.get("version") or ""))
        result = execute_layout_build_plan(plan, redact_paths=redact)
        result["compiled_shortcut"] = shortcut_receipt(
            operation,
            version=str(plan["version"]),
            plan=plan,
            validation_result=result.get("assertions") or {"status": result.get("status")},
        )
        return result

    def _execute_layout_solve(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        plan = request.payload.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("layout.solve requires a structured plan object")
        validate_shortcut(operation, version=str(plan.get("version") or ""))
        result = execute_layout_solve_plan(plan, redact_paths=redact)
        result["compiled_shortcut"] = shortcut_receipt(
            operation,
            version=str(plan["version"]),
            plan=plan,
            validation_result=result.get("validation") or {"status": result.get("status")},
        )
        return result

    def _execute_model_apply(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        plan = request.payload.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("model.apply requires a structured plan object")
        plan = dict(plan)
        plan["redact_paths"] = redact
        validate_shortcut(operation, version=str(plan.get("version") or ""))
        result = execute_operation_plan(plan)
        result["compiled_shortcut"] = shortcut_receipt(
            operation,
            version=str(plan["version"]),
            plan=plan,
            validation_result=result.get("assertions") or {"status": result.get("status")},
        )
        return result

    def _execute_native_execute(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        plan = request.payload.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("native.execute requires a governed native program plan")
        binding = None
        if plan.get("mode") == "live":
            from .live_patch import _authorized_session

            binding = _authorized_session(
                resource_id=request.payload.get("resource_id"),
                release_handle=request.payload.get("release_handle"),
                context=request.target.get("_continuation_context")
                or request.target.get("context"),
                project=plan["scope"]["read_paths"][0],
                version=plan["scope"]["selectors"]["version"],
                design=plan["scope"]["selectors"]["design"],
            )
        result = execute_native_program(
            plan,
            redact_paths=redact,
            binding=binding,
            admission=getattr(context, "admission", None),
        )
        if (
            request.target.get("context_id")
            and result.get("status") == "passed"
            and plan.get("mode") != "live"
            and plan["runtime"] == _NATIVE_RUNTIME
        ):
            project = (
                plan["scope"]["read_paths"][0]
                if plan["effect"] == "observe"
                else plan["scope"]["write_paths"][0]
            )
            continuation = request.target.get("_continuation_context")
            if plan["effect"] != "observe" or not continuation:
                continuation = store_context(
                    {
                        "connection_id": request.target.get("connection_id"),
                        "profile": request.target.get("profile"),
                        "project": str(Path(project).expanduser().resolve()),
                        "project_name": Path(project).stem,
                        "design": plan["scope"]["selectors"]["design"],
                        "version": plan["scope"]["selectors"]["version"],
                        "display": request.target.get("display") or os.environ.get("DISPLAY"),
                    },
                    connection_id=request.target.get("connection_id"),
                )
            result["eda_context"] = continuation
            result["continuation_context"] = continuation
            result["continuation_state"] = {
                "content_bound": True,
                "target_kind": "design",
            }
        return result

    def _execute_workspace_begin(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        return begin_workspace(
            source_project=self._value(request, "source", required=True),
            workspace=self._value(request, "workspace", required=True),
            adapter=self._value(request, "adapter", required=True),
            version=self._value(request, "version", required=True),
            design=self._value(request, "design", required=True),
            profile=self._value(request, "profile"),
            workspace_id=request.payload.get("workspace_id"),
            source_fingerprint=request.payload.get("source_fingerprint"),
            redact_paths=redact,
        )

    def _execute_workspace_status(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        workspace = self._value(request, "workspace", required=True)
        return workspace_status(workspace, redact_paths=redact)

    def _execute_workspace_reconcile(self, request, context=None):
        redact = bool(request.payload.get("redact_paths", True))
        workspace = self._value(request, "workspace", required=True)
        patch = request.payload.get("patch")
        if not isinstance(patch, dict):
            raise ValueError("workspace.reconcile requires a structured patch object")
        patch = dict(patch)
        patch["redact_paths"] = redact
        return reconcile_workspace(workspace, patch, redact_paths=redact)

    def _execute_workspace_rollback(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        workspace = self._value(request, "workspace", required=True)
        revision = request.payload.get("expected_workspace_revision")
        if not revision:
            raise ValueError(f"{operation} requires expected_workspace_revision")
        return rollback_workspace(
            workspace,
            expected_workspace_revision=revision,
            redact_paths=redact,
        )

    def _execute_workspace_abort(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        workspace = self._value(request, "workspace", required=True)
        revision = request.payload.get("expected_workspace_revision")
        if not revision:
            raise ValueError(f"{operation} requires expected_workspace_revision")
        return abort_workspace(
            workspace,
            expected_workspace_revision=revision,
            redact_paths=redact,
        )

    def _execute_workspace_promote(self, request, context=None):
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        workspace = self._value(request, "workspace", required=True)
        revision = request.payload.get("expected_workspace_revision")
        if not revision:
            raise ValueError(f"{operation} requires expected_workspace_revision")
        return promote_workspace(
            workspace,
            output_project=request.payload["output"],
            expected_workspace_revision=revision,
            promotion_id=request.payload.get("promotion_id"),
            redact_paths=redact,
            retain_candidate=bool(request.payload.get("retain_candidate")),
        )


def build_runtime(ledger_path: str | Path):
    imports = _runtime_imports()
    Adapter = imports["Adapter"]

    class AnsysAdapter(_AnsysAdapterBase, Adapter):
        pass

    runtime = imports["Runtime"](imports["ExecutionLedger"](ledger_path))
    runtime.register("ansys-electronics-desktop", AnsysAdapter())
    return runtime


class DurableAnsysService(DurableService):
    def __init__(self, jobs_path, ledger_path, *, profile_id=None):
        self.profile_id = profile_id
        super().__init__(
            jobs_path,
            ledger_path,
            runtime_factory=build_runtime,
            worker_command=self._worker_command,
        )

    def _worker_command(self, request, job_id):
        command = [sys.executable, "-m", "ansysem_agent_bridge.cli"]
        if request.target.get("profile"):
            command.extend(["--profile", str(request.target["profile"])])
        return command + [
            "runtime",
            "worker",
            "--jobs",
            str(self.jobs_path),
            "--ledger",
            str(self.ledger_path),
            "--job-id",
            job_id,
        ]

    def prepare_request(self, request):
        if request.target.get("eda") != "ansys-electronics-desktop":
            raise ValueError("request target is not Ansys Electronics Desktop")
        return self._with_default_profile(self._resolve_context(request))

    def should_detach(self, request):
        return not (
            request.operation
            in {
                "runtime.capabilities",
                "runtime.run_receipt",
                "design.live_patch",
                "design.live_finalize",
            }
            or request.operation.startswith(("docs.", "experience."))
        )

    def _with_default_profile(self, request):
        if not self.profile_id or request.target.get("profile"):
            return request
        from eda_bridge_runtime import RequestEnvelope

        data = request.to_dict()
        data["target"] = {**request.target, "profile": self.profile_id}
        return RequestEnvelope.from_dict(data)

    @staticmethod
    def _resolve_context(request):
        token = request.target.get("context")
        if not token:
            return request
        from eda_bridge_runtime import EDAContext, RequestEnvelope

        context = EDAContext.decode(str(token))
        if context.eda != "ansys-electronics-desktop":
            raise ValueError("EDA context does not belong to Ansys Electronics Desktop")
        context_id = str(context.locator.get("context_id") or "")
        if not context_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for char in context_id
        ):
            raise ValueError("invalid AnsysEM context id")
        path = agent_home() / "runtime" / "contexts" / f"{context_id}.json"
        if not path.is_file():
            raise ValueError("AnsysEM context is unavailable on this host")
        import json

        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("generation") != context.generation:
            raise ValueError("AnsysEM context is stale; copy it again from AEDT")
        record_target = record.get("target")
        if not isinstance(record_target, dict):
            raise ValueError("AnsysEM context target record is invalid")
        for field in _CONTEXT_IDENTITY_FIELDS:
            supplied = request.target.get(field)
            recorded = record_target.get(field)
            if supplied is not None and recorded is not None and supplied != recorded:
                raise ValueError(f"Explicit {field} conflicts with the AnsysEM context")
        data = request.to_dict()
        data["target"] = {
            **record_target,
            **{key: value for key, value in request.target.items() if key != "context"},
            "eda": "ansys-electronics-desktop",
            "context_id": context_id,
            "_continuation_context": str(token),
        }
        if (
            request.operation == "native.execute"
            and request.payload.get("plan", {}).get("mode") != "live"
        ):
            bound_target, binding = _verified_content_binding(record)
            payload = dict(data["payload"])
            payload["plan"] = _materialize_context_native_plan(
                payload.get("plan"), target=bound_target, binding=binding
            )
            data["payload"] = payload
        return RequestEnvelope.from_dict(data)


def serve(
    jobs_path: str | Path,
    ledger_path: str | Path,
    input_stream,
    output_stream,
    *,
    profile_id: str | None = None,
) -> None:
    # Upgrade the remembered, owned UI entries before serving new requests. Never
    # launch AEDT or guess a different PersonalLib from a transport connection.
    from .context_addin import reconcile_configured

    try:
        reconcile_configured(profile_id)
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        import sys

        print(f"Context Add-in needs repair: {exc}", file=sys.stderr)
    imports = _runtime_imports()
    service = DurableAnsysService(jobs_path, ledger_path, profile_id=profile_id)
    imports["serve_json_lines"](input_stream, output_stream, service.handle)


def run_worker(jobs_path: str | Path, ledger_path: str | Path, job_id: str):
    imports = _runtime_imports()
    store = imports["JobStore"](jobs_path)
    runtime = build_runtime(ledger_path)
    return imports["run_job_worker"](store, job_id, runtime.execute)
