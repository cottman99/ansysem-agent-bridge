import io
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ansysem_agent_bridge import runtime_adapter


def _request(**overrides):
    from eda_bridge_runtime import RequestEnvelope

    values = {
        "purpose": "Inspect one sanitized project",
        "target": {"eda": "ansys-electronics-desktop", "profile": "demo"},
        "operation": "project.inspect",
        "payload": {"mutating": False, "project": "demo.aedt"},
    }
    values.update(overrides)
    return RequestEnvelope(**values)


def test_runtime_adapter_requires_optional_runtime(monkeypatch):
    real_import = __import__

    def blocked(name, *args, **kwargs):
        if name.startswith("eda_bridge_runtime"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked)
    with pytest.raises(RuntimeError, match="not installed"):
        runtime_adapter._runtime_imports()


def test_capabilities_advertise_owned_aedt_resource_release():
    capabilities = runtime_adapter._AnsysAdapterBase().capabilities()
    operations = {item["id"]: item for item in capabilities["operations"]}
    assert operations["session.launch"]["resource_lifecycle"]["release_operation"] == (
        "session.release"
    )
    assert operations["runtime.snapshot"]["mutates"] is False
    assert operations["session.launch"]["mutates"] is True
    assert operations["session.release"]["mutates"] is True
    assert operations["session.release"]["input_schema"]["required"] == [
        "resource_id",
        "release_handle",
    ]


def test_runtime_snapshot_refuses_hidden_long_lived_session():
    request = SimpleNamespace(
        operation="runtime.snapshot",
        payload={"live": True, "leave_open": True},
        target={"project": "demo.aedt", "version": "2026.1"},
    )
    with pytest.raises(ValueError, match="use session.launch"):
        runtime_adapter._AnsysAdapterBase()._dispatch(request)


@pytest.mark.parametrize(
    ("operation", "function_name"),
    [
        ("workspace.rollback", "rollback_workspace"),
        ("workspace.abort", "abort_workspace"),
    ],
)
def test_workspace_revision_is_forwarded_as_keyword_only(monkeypatch, operation, function_name):
    observed = {}

    def fake_workspace_action(workspace, *, expected_workspace_revision, redact_paths):
        observed.update(
            workspace=workspace,
            expected_workspace_revision=expected_workspace_revision,
            redact_paths=redact_paths,
        )
        return {"status": "passed"}

    monkeypatch.setattr(runtime_adapter, function_name, fake_workspace_action)
    request = SimpleNamespace(
        operation=operation,
        payload={
            "workspace": "/scratch/candidate",
            "expected_workspace_revision": "revision-one",
            "redact_paths": True,
        },
        target={},
    )

    assert runtime_adapter._AnsysAdapterBase()._dispatch(request) == {"status": "passed"}
    assert observed == {
        "workspace": "/scratch/candidate",
        "expected_workspace_revision": "revision-one",
        "redact_paths": True,
    }


@pytest.mark.parametrize(
    ("operation", "function_name"),
    [
        ("layout.build", "execute_layout_build_plan"),
        ("layout.solve", "execute_layout_solve_plan"),
        ("native.batch", "execute_native_batch"),
    ],
)
def test_layout_workflow_forwards_only_typed_plan(monkeypatch, operation, function_name):
    observed = {}

    def fake_execute(plan, *, redact_paths):
        observed.update(plan=plan, redact_paths=redact_paths)
        return {"status": "passed"}

    monkeypatch.setattr(runtime_adapter, function_name, fake_execute)
    plan = {"schema_version": "synthetic/v1"}
    if operation != "native.batch":
        plan["version"] = "2026.1"
    request = SimpleNamespace(
        operation=operation,
        payload={"plan": plan, "redact_paths": True},
        target={},
    )

    result = runtime_adapter._AnsysAdapterBase()._dispatch(request)
    assert result["status"] == "passed"
    if operation != "native.batch":
        assert result["compiled_shortcut"]["implements_asset_id"]
    assert observed == {"plan": plan, "redact_paths": True}


def test_context_native_dispatch_returns_reusable_or_rotated_content_bound_context(monkeypatch):
    plan = {
        "effect": "observe",
        "scope": {
            "read_paths": ["synthetic.aedt"],
            "write_paths": [],
            "selectors": {"version": "2026.1", "design": "Layout1"},
        },
    }
    monkeypatch.setattr(
        runtime_adapter,
        "execute_native_batch",
        lambda _plan, *, redact_paths: {"status": "passed", "source_preserved": True},
    )
    monkeypatch.setattr(runtime_adapter, "store_context", lambda *_args, **_kwargs: "opaque-next")
    request = SimpleNamespace(
        operation="native.batch",
        payload={"plan": plan, "redact_paths": True},
        target={
            "context_id": "ctx_synthetic",
            "_continuation_context": "opaque-next",
            "profile": "synthetic",
            "display": ":4.0",
        },
    )

    result = runtime_adapter._AnsysAdapterBase()._dispatch(request)

    assert result["eda_context"] == "opaque-next"
    assert result["continuation_context"] == "opaque-next"
    assert result["continuation_state"] == {
        "content_bound": True,
        "target_kind": "design",
    }

    plan["effect"] = "staged_mutation"
    plan["scope"]["write_paths"] = ["output.aedt"]
    monkeypatch.setattr(runtime_adapter, "store_context", lambda *_args, **_kwargs: "opaque-output")
    mutated = runtime_adapter._AnsysAdapterBase()._dispatch(request)
    assert mutated["continuation_context"] == "opaque-output"


def test_service_submits_once_for_same_mutating_key(tmp_path, monkeypatch):
    pytest.importorskip("eda_bridge_runtime")
    spawned = []
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )

    def fake_spawn(command, **kwargs):
        spawned.append(command)
        kwargs["store"].record_event(kwargs["job_id"], {"event": "worker.spawned", "pid": 123})
        return 123

    monkeypatch.setattr(service, "spawn", fake_spawn)
    request = _request(
        purpose="Apply one sanitized patch",
        operation="model.apply",
        payload={"mutating": True, "plan": {"schema_version": 1}},
        idempotency_key="stable-patch",
    )
    first = service.handle(request)
    retry = _request(
        purpose=request.purpose,
        operation=request.operation,
        payload=request.payload,
        idempotency_key=request.idempotency_key,
    )
    second = service.handle(retry)
    assert first.status == second.status == "accepted"
    assert first.result["job"]["job_id"] == second.result["job"]["job_id"]
    assert first.result["job"]["run_id"] == request.run_id
    assert second.result["job"]["run_id"] == request.run_id
    assert len(spawned) == 1

    events = service.handle(
        _request(
            operation="runtime.job_events",
            payload={
                "mutating": False,
                "job_id": first.result["job"]["job_id"],
                "after_cursor": 0,
            },
        )
    )
    assert events.result["job"]["run_id"] == request.run_id
    assert events.result["events"]


def test_service_inherits_connection_profile_for_detached_worker(tmp_path, monkeypatch):
    pytest.importorskip("eda_bridge_runtime")
    spawned = []
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3",
        tmp_path / "ledger.sqlite3",
        profile_id="display4-profile",
    )

    def fake_spawn(command, **kwargs):
        spawned.append(command)
        kwargs["store"].record_event(kwargs["job_id"], {"event": "worker.spawned", "pid": 123})
        return 123

    monkeypatch.setattr(service, "spawn", fake_spawn)
    response = service.handle(
        _request(
            purpose="Create sanitized project",
            target={"eda": "ansys-electronics-desktop"},
            operation="project.create",
            payload={"mutating": True},
            idempotency_key="profile-inheritance",
        )
    )

    assert response.status == "accepted"
    assert spawned[0][3:5] == ["--profile", "display4-profile"]
    stored = service.store.get(response.result["job"]["job_id"])
    assert stored["request"]["target"]["profile"] == "display4-profile"


def test_stdio_returns_job_receipt_before_worker_completion(tmp_path, monkeypatch):
    pytest.importorskip("eda_bridge_runtime")

    def fake_spawn(command, **kwargs):
        kwargs["store"].record_event(kwargs["job_id"], {"event": "worker.spawned", "pid": 123})
        return 123

    monkeypatch.setattr("eda_bridge_runtime.spawn_detached_worker", fake_spawn)
    request = _request()
    source = io.StringIO(
        json.dumps({"protocol": "eda-runtime.handshake/v1", "versions": [1]})
        + "\n"
        + json.dumps(request.to_dict())
        + "\n"
    )
    destination = io.StringIO()
    runtime_adapter.serve(
        tmp_path / "jobs.sqlite3",
        tmp_path / "ledger.sqlite3",
        source,
        destination,
    )
    responses = [json.loads(line) for line in destination.getvalue().splitlines()]
    assert responses[0]["selected"] == 1
    assert responses[1]["status"] == "accepted"
    assert responses[1]["result"]["job"]["state"] == "queued"


def test_worker_records_normalized_project_inspection(tmp_path, monkeypatch):
    pytest.importorskip("eda_bridge_runtime")
    jobs_path = tmp_path / "jobs.sqlite3"
    ledger_path = tmp_path / "ledger.sqlite3"
    imports = runtime_adapter._runtime_imports()
    store = imports["JobStore"](jobs_path)
    job = store.submit(_request())
    monkeypatch.setattr(
        runtime_adapter,
        "inspect_project_bundle",
        lambda project, redact_paths: {"bundle_complete": True, "project": "redacted.aedt"},
    )
    response = runtime_adapter.run_worker(jobs_path, ledger_path, job["job_id"])
    assert response.status == "passed"
    assert store.get(job["job_id"])["state"] == "passed"


def test_service_resolves_secret_free_context_on_eda_host(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    context_id = "ctx_safe123"
    context_root = tmp_path / "runtime" / "contexts"
    context_root.mkdir(parents=True)
    (context_root / f"{context_id}.json").write_text(
        json.dumps(
            {
                "generation": 3,
                "target": {
                    "profile": "demo",
                    "project": "/private/customer/demo.aedt",
                    "design": "Layout1",
                    "version": "2026.1",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_adapter, "agent_home", lambda: tmp_path)
    token = EDAContext(
        eda="ansys-electronics-desktop",
        target_kind="design",
        locator={"context_id": context_id},
        generation=3,
    ).encode()
    request = _request(target={"eda": "ansys-electronics-desktop", "context": token})
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )

    def fake_spawn(command, **kwargs):
        kwargs["store"].record_event(kwargs["job_id"], {"event": "worker.spawned", "pid": 123})
        return 123

    monkeypatch.setattr(service, "spawn", fake_spawn)
    response = service.handle(request)
    stored = service.store.request(response.result["job"]["job_id"])
    assert stored.target["project"] == "/private/customer/demo.aedt"
    assert "context" not in stored.target


def test_service_materializes_context_bound_native_identity_before_job(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    from ansysem_agent_bridge import aedt_context_tool

    project = tmp_path / "synthetic.aedt"
    project.write_text("project", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("edb", encoding="utf-8")
    monkeypatch.setattr(aedt_context_tool, "agent_home", lambda: tmp_path)
    monkeypatch.setattr(runtime_adapter, "agent_home", lambda: tmp_path)
    token = aedt_context_tool.store_context(
        {
            "profile": "synthetic",
            "project": str(project),
            "project_name": "synthetic",
            "design": "Layout1",
            "version": "2026.1",
            "display": ":4.0",
        }
    )
    context = EDAContext.decode(token)
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    monkeypatch.setattr(
        service,
        "spawn",
        lambda command, **kwargs: kwargs["store"].record_event(
            kwargs["job_id"], {"event": "worker.spawned", "pid": 123}
        ),
    )
    plan = {
        "schema_version": "eda.native-batch/v1",
        "effect": "observe",
        "program": {
            "language": "python",
            "source": "def run(api, context):\n    return {'status': 'passed'}\n",
        },
        "scope": {"selectors": {}, "read_paths": [], "write_paths": [], "artifacts": []},
        "transaction": {
            "strategy": "none",
            "source_fingerprints": {},
            "fresh_reopen": False,
            "promotion": "none",
        },
        "validation": {"program": None, "required_artifacts": []},
        "limits": {"timeout_seconds": 60, "max_output_bytes": 65536},
    }
    response = service.handle(
        _request(
            operation="native.batch",
            target={"eda": "ansys-electronics-desktop", "context": token},
            payload={"mutating": False, "plan": plan},
        )
    )
    stored = service.store.request(response.result["job"]["job_id"])
    materialized = stored.payload["plan"]
    assert stored.target["context_id"] == context.locator["context_id"]
    assert "context" not in stored.target
    assert materialized["runtime"] == "ansys.pyaedt.hfss3dlayout"
    assert materialized["scope"]["resource_kind"] == "aedt-project"
    assert materialized["scope"]["selectors"] == {"version": "2026.1", "design": "Layout1"}
    assert materialized["scope"]["read_paths"] == [str(project.resolve())]
    assert materialized["effect"] == "observe"
    assert "write_paths" in materialized["scope"]
    assert "limits" in materialized


def test_service_rejects_changed_context_content_before_job(tmp_path, monkeypatch):
    from ansysem_agent_bridge import aedt_context_tool

    project = tmp_path / "synthetic.aedt"
    project.write_text("project", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("edb", encoding="utf-8")
    monkeypatch.setattr(aedt_context_tool, "agent_home", lambda: tmp_path)
    monkeypatch.setattr(runtime_adapter, "agent_home", lambda: tmp_path)
    token = aedt_context_tool.store_context(
        {
            "project": str(project),
            "project_name": "synthetic",
            "design": "Layout1",
            "version": "2026.1",
        }
    )
    project.write_text("changed-project-content", encoding="utf-8")
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    with pytest.raises(ValueError, match="content state changed"):
        service.handle(
            _request(
                operation="native.batch",
                target={"eda": "ansys-electronics-desktop", "context": token},
                payload={"mutating": False, "plan": {}},
            )
        )
    with sqlite3.connect(service.jobs_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_context_native_materialization_rejects_explicit_identity_and_fingerprint_conflicts(
    tmp_path,
):
    project = tmp_path / "synthetic.aedt"
    target = {"project": str(project), "design": "Layout1", "version": "2026.1"}
    binding = {"bundle_sha256": "a" * 64}
    plan = {
        "runtime": "ansys.pyaedt.hfss3dlayout",
        "effect": "staged_mutation",
        "scope": {
            "resource_kind": "aedt-project",
            "selectors": {"design": "OtherDesign"},
            "read_paths": [],
        },
        "transaction": {"source_fingerprints": {}},
    }
    with pytest.raises(ValueError, match="selector design conflicts"):
        runtime_adapter._materialize_context_native_plan(plan, target=target, binding=binding)
    plan["scope"]["selectors"]["design"] = "Layout1"
    plan["transaction"]["source_fingerprints"] = {str(project): "b" * 64}
    with pytest.raises(ValueError, match="source fingerprint conflicts"):
        runtime_adapter._materialize_context_native_plan(plan, target=target, binding=binding)
    plan["transaction"]["source_fingerprints"] = {str(project): "a" * 64}
    materialized = runtime_adapter._materialize_context_native_plan(
        plan, target=target, binding=binding
    )
    assert materialized["scope"]["read_paths"] == [str(project.resolve())]
    assert materialized["transaction"]["source_fingerprints"] == {str(project.resolve()): "a" * 64}


def test_service_rejects_stale_context_generation(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    context_root = tmp_path / "runtime" / "contexts"
    context_root.mkdir(parents=True)
    (context_root / "ctx_safe123.json").write_text(
        json.dumps({"generation": 2, "target": {"project": "demo.aedt"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_adapter, "agent_home", lambda: tmp_path)
    token = EDAContext(
        eda="ansys-electronics-desktop",
        target_kind="design",
        locator={"context_id": "ctx_safe123"},
        generation=1,
    ).encode()
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    with pytest.raises(ValueError, match="stale"):
        service.handle(_request(target={"eda": "ansys-electronics-desktop", "context": token}))


def test_service_rejects_explicit_target_conflict_with_context(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    context_root = tmp_path / "runtime" / "contexts"
    context_root.mkdir(parents=True)
    (context_root / "ctx_safe123.json").write_text(
        json.dumps(
            {
                "generation": 1,
                "target": {
                    "project": "synthetic.aedt",
                    "project_name": "synthetic",
                    "design": "Layout1",
                    "version": "2026.1",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_adapter, "agent_home", lambda: tmp_path)
    token = EDAContext(
        eda="ansys-electronics-desktop",
        target_kind="design",
        locator={"context_id": "ctx_safe123"},
        generation=1,
    ).encode()
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    with pytest.raises(ValueError, match="Explicit design conflicts"):
        service.handle(
            _request(
                target={
                    "eda": "ansys-electronics-desktop",
                    "context": token,
                    "design": "OtherDesign",
                }
            )
        )


def test_cli_serve_keeps_protocol_on_real_stdout(tmp_path):
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "ansysem_agent_bridge.cli",
            "runtime",
            "serve",
            "--jobs",
            str(tmp_path / "jobs.sqlite3"),
            "--ledger",
            str(tmp_path / "ledger.sqlite3"),
        ],
        input=json.dumps({"protocol": "eda-runtime.handshake/v1", "versions": [1]}) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    lines = process.stdout.splitlines()
    assert json.loads(lines[0]) == {"protocol": "eda-runtime.handshake/v1", "selected": 1}


def test_job_status_recovers_dead_worker_without_replay(tmp_path, monkeypatch):
    pytest.importorskip("eda_bridge_runtime")
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    submitted = service.store.submit(_request())
    service.store.transition(
        submitted["job_id"], "running", {"event": "worker.started", "pid": 99999999}
    )
    monkeypatch.setattr("eda_bridge_runtime.jobs._pid_is_alive", lambda _pid: False)
    response = service.handle(
        _request(
            operation="runtime.job_status",
            payload={"mutating": False, "job_id": submitted["job_id"]},
        )
    )
    assert response.status == "passed"
    assert response.result["job"]["state"] == "orphaned"


def test_service_returns_capabilities_without_submitting_a_job(tmp_path):
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    response = service.handle(
        _request(
            operation="runtime.capabilities",
            payload={"mutating": False},
            target={"eda": "ansys-electronics-desktop", "display": ":4.0"},
        )
    )
    assert response.status == "passed"
    capabilities = response.result["data"]["capabilities"]
    assert capabilities["execution_host_role"] == "eda-worker"
    assert capabilities["run_model"] == "durable"
    operations = capabilities["operations"]
    create = next(item for item in operations if item["id"] == "project.create")
    assert create["returns_context"] is True
    by_id = {item["id"]: item for item in operations}
    assert {item["operation_class"] for item in operations} == {
        "bridge-infrastructure",
        "certified-workflow",
        "generic-native-execution",
    }
    assert {"docs.status", "docs.query", "docs.get", "layout.build", "layout.solve"}.issubset(by_id)
    assert by_id["layout.build"]["input_schema"]["plan_schema"] == ("ansysem.hfss3dlayout-build/v1")
    assert by_id["layout.solve"]["input_schema"]["plan_schema"] == ("ansysem.hfss3dlayout-solve/v1")
    assert by_id["native.batch"]["operation_class"] == "generic-native-execution"
    assert by_id["native.batch"]["input_schema"]["plan_schema"] == "eda.native-batch/v1"
    assert by_id["native.batch"]["accepts_context"] is True
    assert by_id["native.batch"]["returns_context"] is True
    assert "plan.scope.read_paths" in by_id["native.batch"]["input_schema"]["derived_fields"]
    assert "plan.effect" in by_id["native.batch"]["input_schema"]["agent_required"]
    for operation in ("layout.build", "layout.solve", "model.apply"):
        shortcut = by_id[operation]["compiled_shortcut"]
        assert shortcut["implements_asset_id"]
        assert shortcut["fallback"] == "governed_native_execution"
    with sqlite3.connect(service.jobs_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_degraded_experience_disables_shortcuts_but_not_native_execution(monkeypatch):
    monkeypatch.setattr(
        runtime_adapter,
        "shortcut_state",
        lambda *_args, **_kwargs: {
            "available": False,
            "healthy": False,
            "reason": "asset hash mismatch",
        },
    )
    monkeypatch.setattr(runtime_adapter, "_native_batch_available", lambda: True)

    operations = {
        item["id"]: item
        for item in runtime_adapter._AnsysAdapterBase().capabilities({"version": "2026.1"})[
            "operations"
        ]
    }
    assert operations["layout.build"]["state"]["available"] is False
    assert operations["native.batch"]["state"]["available"] is True


def test_service_queries_docs_synchronously_without_creating_job(tmp_path):
    docs_root = tmp_path / "docs"
    markdown = docs_root / "sources" / "markdown" / "hfss"
    markdown.mkdir(parents=True)
    (markdown / "api.md").write_text(
        "# API\n\nUse set_traj to define a bondwire trajectory.\n", encoding="utf-8"
    )
    service = runtime_adapter.DurableAnsysService(
        tmp_path / "jobs.sqlite3", tmp_path / "ledger.sqlite3"
    )
    response = service.handle(
        _request(
            purpose="Find one version-matched AnsysEM API",
            target={"eda": "ansys-electronics-desktop", "docs_root": str(docs_root)},
            operation="docs.query",
            payload={"mutating": False, "query": "set_traj", "module": "hfss", "limit": 6},
        )
    )
    assert response.status == "passed"
    assert response.result["data"]["bridge"]["results"][0]["source_ref"].endswith("api.md")
    with sqlite3.connect(service.jobs_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
