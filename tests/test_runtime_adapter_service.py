import io
import json
import subprocess
import sys

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
    assert len(spawned) == 1


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
