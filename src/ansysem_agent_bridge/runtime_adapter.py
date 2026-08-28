"""Durable-job adapter between EDA Runtime and Ansys Electronics Desktop."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .capabilities import capability_map
from .config import agent_home
from .live_probe import live_hfss3dlayout_probe
from .operations import export_layout_image
from .project_bundle import inspect_project_bundle
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
    "project.inspect",
    "runtime.snapshot",
    "layout.export_image",
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

    def capabilities(self) -> dict[str, Any]:
        return {
            "eda": "ansys-electronics-desktop",
            "session_model": "durable-job",
            "operations": sorted(_OPERATIONS),
            "escape_lanes": ["typed", "verified-native", "bounded-script"],
        }

    def execute(self, request, context):
        AdapterResult = _runtime_imports()["AdapterResult"]
        if request.operation not in _OPERATIONS:
            raise ValueError(f"unsupported AnsysEM Runtime operation: {request.operation}")
        started = time.monotonic()
        context.emit(
            "ansysem.operation.started",
            {"operation": request.operation, "profile": request.target.get("profile")},
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
        if operation == "project.inspect":
            result = inspect_project_bundle(
                self._value(request, "project", required=True), redact_paths=redact
            )
            return {"status": "ready" if result["bundle_complete"] else "blocked", "result": result}
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
            return rollback_workspace(workspace, revision, redact_paths=redact)
        if operation == "workspace.abort":
            return abort_workspace(workspace, revision, redact_paths=redact)
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
    def __init__(self, jobs_path: str | Path, ledger_path: str | Path):
        imports = _runtime_imports()
        self.store = imports["JobStore"](jobs_path)
        self.jobs_path = Path(jobs_path).resolve()
        self.ledger_path = Path(ledger_path).resolve()
        self.ResponseEnvelope = imports["ResponseEnvelope"]
        self.spawn = imports["spawn_detached_worker"]

    def handle(self, request):
        if request.operation == "runtime.job_status":
            return self._job_status(request)
        if request.operation == "runtime.job_events":
            return self._job_events(request)
        request = self._resolve_context(request)
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
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="accepted" if job["state"] in {"queued", "running"} else job["state"],
            result={"job": self._public_job(job)},
        )

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
        job = self.store.get(str(request.payload["job_id"]))
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="passed",
            result={"job": self._public_job(job)},
        )

    def _job_events(self, request):
        job_id = str(request.payload["job_id"])
        events = self.store.events(job_id, int(request.payload.get("after_cursor", 0)))
        return self.ResponseEnvelope(
            request_id=request.request_id,
            run_id=request.run_id,
            status="passed",
            result={"job_id": job_id, "events": events},
        )

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: job[key]
            for key in (
                "job_id",
                "request_id",
                "state",
                "result",
                "created_at",
                "updated_at",
            )
        }


def serve(jobs_path: str | Path, ledger_path: str | Path, input_stream, output_stream) -> None:
    imports = _runtime_imports()
    service = DurableAnsysService(jobs_path, ledger_path)
    imports["serve_json_lines"](input_stream, output_stream, service.handle)


def run_worker(jobs_path: str | Path, ledger_path: str | Path, job_id: str):
    imports = _runtime_imports()
    store = imports["JobStore"](jobs_path)
    runtime = build_runtime(ledger_path)
    return imports["run_job_worker"](store, job_id, runtime.execute)
