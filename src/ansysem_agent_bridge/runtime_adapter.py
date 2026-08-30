"""Durable-job adapter between EDA Runtime and Ansys Electronics Desktop."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .capabilities import capability_map
from .config import agent_home
from .discovery import select_installation
from .docs_backend import docs_status, get_doc, query_docs
from .layout_build import execute_layout_build_plan
from .layout_solve import execute_layout_solve_plan
from .live_probe import live_hfss3dlayout_probe
from .operations import export_layout_image
from .project_bundle import inspect_project_bundle
from .project_create import create_hfss3dlayout_project
from .runtime import runtime_snapshot
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
    "capabilities",
    "docs.status",
    "docs.query",
    "docs.get",
    "project.create",
    "project.inspect",
    "runtime.snapshot",
    "layout.export_image",
    "layout.build",
    "layout.solve",
    "model.apply",
    "workspace.begin",
    "workspace.status",
    "workspace.reconcile",
    "workspace.rollback",
    "workspace.abort",
    "workspace.promote",
}


class _AnsysAdapterBase:
    name = "ansysem-agent-bridge"
    version = __version__

    def capabilities(self, target: dict[str, Any] | None = None) -> dict[str, Any]:
        target = target or {}
        descriptors = [
            {
                "id": operation,
                "mutates": operation
                not in {
                    "capabilities",
                    "layout.export_image",
                    "project.inspect",
                    "runtime.snapshot",
                    "workspace.status",
                    "docs.status",
                    "docs.query",
                    "docs.get",
                },
                "requires_context": False,
            }
            for operation in sorted(_OPERATIONS)
            if operation != "capabilities"
        ]
        for descriptor in descriptors:
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
            if descriptor["id"] == "docs.status":
                descriptor["input_schema"] = {
                    "required": [],
                    "optional": ["instance", "docs_root"],
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
        from eda_bridge_runtime import stable_origin_id

        return {
            "eda": "ansys-electronics-desktop",
            "origin_id": stable_origin_id("ansys-electronics-desktop"),
            "execution_host_role": "eda-worker",
            "run_model": "durable",
            "session_model": "durable-job",
            "operations": descriptors,
            "escape_lanes": ["typed", "verified-native", "bounded-script"],
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
        result = self._dispatch(request)
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
            if result.get("status") in {"ready", "passed", "preserved", "removed"}
            else "failed"
        )
        if status == "failed":
            raise RuntimeError(
                str(result.get("error") or result.get("status") or "operation failed")
            )
        return AdapterResult(
            status="passed",
            result={"bridge": result, "timing": {"adapter_total_ms": elapsed_ms}},
        )

    @staticmethod
    def _value(request, name: str, *, required: bool = False, default: Any = None) -> Any:
        value = request.payload.get(name, request.target.get(name, default))
        if required and (value is None or value == ""):
            raise ValueError(f"AnsysEM Runtime field is required: {name}")
        return value

    def _dispatch(self, request) -> dict[str, Any]:
        operation = request.operation
        redact = bool(request.payload.get("redact_paths", True))
        if operation == "capabilities":
            return {
                "status": "ready",
                "capabilities": capability_map(
                    project=self._value(request, "project"),
                    docs_root=self._value(request, "docs_root"),
                    display=self._value(request, "display"),
                ),
            }
        if operation.startswith("docs."):
            if request.is_mutating:
                raise ValueError("AnsysEM documentation operations require payload.mutating=false")
            explicit_root = self._value(request, "docs_root")
            if explicit_root:
                root = Path(str(explicit_root)).expanduser().resolve()
            else:
                configured = os.environ.get("ANSYSEM_DOC_ROOT")
                if configured:
                    root = Path(configured).expanduser().resolve()
                else:
                    installation = select_installation(self._value(request, "instance"))
                    if not installation.docs_root:
                        raise ValueError("No AnsysEM documentation root is configured")
                    root = Path(installation.docs_root).expanduser().resolve()
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
                    ),
                }
            return {
                "status": "ready",
                **get_doc(
                    root,
                    str(request.payload.get("source_ref") or ""),
                    focus=request.payload.get("focus"),
                    max_chars=int(request.payload.get("max_chars", 4000)),
                ),
            }
        if operation == "project.inspect":
            result = inspect_project_bundle(
                self._value(request, "project", required=True), redact_paths=redact
            )
            return {"status": "ready" if result["bundle_complete"] else "blocked", "result": result}
        if operation == "project.create":
            return create_hfss3dlayout_project(
                project=self._value(request, "project", required=True),
                design=str(self._value(request, "design", required=True)),
                version=str(self._value(request, "version", required=True)),
                connection_id=self._value(request, "connection_id"),
                profile=self._value(request, "profile"),
                expected_display=self._value(request, "display"),
                redact_paths=redact,
            )
        if operation == "runtime.snapshot":
            if request.payload.get("live"):
                return live_hfss3dlayout_probe(
                    project=self._value(request, "project", required=True),
                    version=self._value(request, "version", required=True),
                    design=self._value(request, "design"),
                    port=int(request.payload.get("port", 0)),
                    new_desktop=not bool(request.payload.get("reuse_existing")),
                    close_desktop=not bool(request.payload.get("leave_open")),
                    validate=bool(request.payload.get("validate")),
                    redact_paths=redact,
                    since_revision=request.payload.get("since_revision"),
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
        if operation == "layout.export_image":
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
        if operation == "layout.build":
            plan = request.payload.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("layout.build requires a structured plan object")
            return execute_layout_build_plan(plan, redact_paths=redact)
        if operation == "layout.solve":
            plan = request.payload.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("layout.solve requires a structured plan object")
            return execute_layout_solve_plan(plan, redact_paths=redact)
        if operation == "model.apply":
            plan = request.payload.get("plan")
            if not isinstance(plan, dict):
                raise ValueError("model.apply requires a structured plan object")
            plan = dict(plan)
            plan["redact_paths"] = redact
            return execute_operation_plan(plan)
        if operation == "workspace.begin":
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
        workspace = self._value(request, "workspace", required=True)
        if operation == "workspace.status":
            return workspace_status(workspace, redact_paths=redact)
        if operation == "workspace.reconcile":
            patch = request.payload.get("patch")
            if not isinstance(patch, dict):
                raise ValueError("workspace.reconcile requires a structured patch object")
            patch = dict(patch)
            patch["redact_paths"] = redact
            return reconcile_workspace(workspace, patch, redact_paths=redact)
        revision = request.payload.get("expected_workspace_revision")
        if not revision:
            raise ValueError(f"{operation} requires expected_workspace_revision")
        if operation == "workspace.rollback":
            return rollback_workspace(
                workspace,
                expected_workspace_revision=revision,
                redact_paths=redact,
            )
        if operation == "workspace.abort":
            return abort_workspace(
                workspace,
                expected_workspace_revision=revision,
                redact_paths=redact,
            )
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


class DurableAnsysService:
    def __init__(
        self,
        jobs_path: str | Path,
        ledger_path: str | Path,
        *,
        profile_id: str | None = None,
    ):
        imports = _runtime_imports()
        self.store = imports["JobStore"](jobs_path)
        self.jobs_path = Path(jobs_path).resolve()
        self.ledger_path = Path(ledger_path).resolve()
        self.ResponseEnvelope = imports["ResponseEnvelope"]
        self.spawn = imports["spawn_detached_worker"]
        self.profile_id = profile_id

    def handle(self, request):
        if request.operation == "runtime.job_status":
            return self._job_status(request)
        if request.operation == "runtime.job_events":
            return self._job_events(request)
        if request.operation == "runtime.capabilities" or request.operation.startswith("docs."):
            return build_runtime(self.ledger_path).execute(request)
        request = self._with_default_profile(self._resolve_context(request))
        if request.target.get("eda") != "ansys-electronics-desktop":
            raise ValueError("request target is not Ansys Electronics Desktop")
        job = self.store.submit(request)
        events = self.store.events(job["job_id"])
        worker_spawned = any(event["detail"].get("event") == "worker.spawned" for event in events)
        if job["state"] == "queued" and not worker_spawned:
            profile = request.target.get("profile")
            command = [sys.executable, "-m", "ansysem_agent_bridge.cli"]
            if profile:
                command.extend(["--profile", str(profile)])
            command.extend(
                [
                    "runtime",
                    "worker",
                    "--jobs",
                    str(self.jobs_path),
                    "--ledger",
                    str(self.ledger_path),
                    "--job-id",
                    job["job_id"],
                ]
            )
            log_path = runtime_state_dir() / "job-logs" / f"{job['job_id']}.log"
            self.spawn(command, job_id=job["job_id"], log_path=log_path, store=self.store)
            job = self.store.get(job["job_id"])
        if job["state"] == "orphaned":
            return self.ResponseEnvelope(
                request_id=request.request_id,
                run_id=request.run_id,
                status="failed",
                result={"job": self._public_job(job)},
                error={
                    "code": "job_orphaned",
                    "message": (
                        "The detached worker ended without a terminal result; "
                        "inspect before resume."
                    ),
                },
            )
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="accepted" if job["state"] in {"queued", "running"} else job["state"],
            result={"job": self._public_job(job)},
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
        data = request.to_dict()
        data["target"] = {
            **record["target"],
            **{key: value for key, value in request.target.items() if key != "context"},
            "eda": "ansys-electronics-desktop",
            "context_id": context_id,
        }
        return RequestEnvelope.from_dict(data)

    def _job_status(self, request):
        self.store.recover_orphans()
        job = self.store.get(str(request.payload["job_id"]))
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="passed",
            result={"job": self._public_job(job)},
        )

    def _job_events(self, request):
        job_id = str(request.payload["job_id"])
        self.store.recover_orphans()
        job = self.store.get(job_id)
        events = self.store.events(job_id, int(request.payload.get("after_cursor", 0)))
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="passed",
            result={"job_id": job_id, "job": self._public_job(job), "events": events},
        )

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: job[key]
            for key in (
                "job_id",
                "request_id",
                "run_id",
                "state",
                "result",
                "created_at",
                "updated_at",
            )
        }


def serve(
    jobs_path: str | Path,
    ledger_path: str | Path,
    input_stream,
    output_stream,
    *,
    profile_id: str | None = None,
) -> None:
    imports = _runtime_imports()
    service = DurableAnsysService(jobs_path, ledger_path, profile_id=profile_id)
    imports["serve_json_lines"](input_stream, output_stream, service.handle)


def run_worker(jobs_path: str | Path, ledger_path: str | Path, job_id: str):
    imports = _runtime_imports()
    store = imports["JobStore"](jobs_path)
    runtime = build_runtime(ledger_path)
    return imports["run_job_worker"](store, job_id, runtime.execute)
