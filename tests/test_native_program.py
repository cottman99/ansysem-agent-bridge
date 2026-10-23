from pathlib import Path

import pytest
from eda_bridge_runtime.errors import ExecutionError
from eda_bridge_runtime.lease import LeaseStore

from ansysem_agent_bridge import native_program
from ansysem_agent_bridge.native_backends import backend_for


def plan(source, *, mode="offline", effect="observe", output=None):
    return {
        "schema_version": "eda.native-program/v1",
        "runtime": "ansys.pyedb",
        "mode": mode,
        "effect": effect,
        "program": {
            "language": "python",
            "source": "def run(api, context):\n    return {'path': context['project']}\n",
        },
        "scope": {
            "resource_kind": "edb-database",
            "selectors": {"version": "2026.1"},
            "read_paths": [str(source)],
            "write_paths": [str(output)] if output else [],
            "artifacts": [],
        },
        "transaction": {
            "strategy": "adapter_staging" if effect == "mutate" else "none",
            "source_fingerprints": {
                str(source): native_program._fingerprint(source, "edb-database")
            }
            if effect == "mutate"
            else {},
            "fresh_reopen": effect == "mutate",
            "promotion": "on_validation" if effect == "mutate" else "none",
        },
        "validation": {
            "program": {
                "language": "python",
                "source": "def validate(api, context):\n    return {'status': 'passed'}\n",
            }
            if effect == "mutate"
            else None,
            "required_artifacts": [],
        },
        "limits": {"timeout_seconds": 60, "max_output_bytes": 65536},
    }


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    source = tmp_path / "source.aedb"
    source.mkdir()
    (source / "edb.def").write_text("original")
    store = LeaseStore(tmp_path / "resources.sqlite3")
    lease = store.acquire(str(source), "worker")
    admission = {"store": str(tmp_path / "resources.sqlite3"), "leases": [lease.__dict__]}
    opened, closed = [], []

    class Backend:
        resource_kind = "edb-database"

        def open(self, path, selectors, **kwargs):
            opened.append(Path(path))
            return Path(path)

        def save(self, api):
            (api / "saved.txt").write_text("saved")

        def close(self, api, **kwargs):
            closed.append(api)

    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent"))
    monkeypatch.setattr(native_program, "backend_for", lambda *_: Backend())
    return source, admission, opened, closed


def test_registry_keeps_runtime_and_mode_independent():
    assert backend_for("ansys.pyedb", "offline").resource_kind == "edb-database"
    assert backend_for("ansys.pyaedt.hfss3dlayout", "live").resource_kind == "aedt-project"
    with pytest.raises(ExecutionError) as error:
        backend_for("ansys.pyedb", "live")
    assert error.value.code == "runtime_unsupported"


def test_offline_observe_protects_source_and_closes_owned_sdk(fixture):
    source, admission, opened, closed = fixture
    expected = native_program._fingerprint(source, "edb-database")
    result = native_program.execute_bound_program(
        plan(source), redact_paths=False, binding=None, admission=admission
    )
    assert result["source_fingerprint"] == expected
    assert result["source_preserved"] and result["validation"] == "not_requested"
    assert opened == closed and opened[0] != source and not opened[0].exists()
    assert (source / "edb.def").read_text() == "original"


def test_relative_source_still_checks_fingerprint(fixture, monkeypatch):
    source, admission, opened, _ = fixture
    monkeypatch.chdir(source.parent)
    value = plan(Path(source.name), effect="mutate", output=source.parent / "result.aedb")
    (source / "edb.def").write_text("changed after plan capture")
    with pytest.raises(ExecutionError, match="fingerprint"):
        native_program.execute_bound_program(
            value, redact_paths=False, binding=None, admission=admission
        )
    assert not opened


def test_offline_mutation_saves_reopens_validates_then_promotes(fixture):
    source, admission, opened, closed = fixture
    output = source.parent / "result.aedb"
    result = native_program.execute_bound_program(
        plan(source, effect="mutate", output=output),
        redact_paths=False,
        binding=None,
        admission=admission,
    )
    assert result["fresh_reopen"] and result["validation"] == "passed"
    assert len(opened) == len(closed) == 2
    assert (output / "saved.txt").read_text() == "saved"
    assert not (source / "saved.txt").exists()


def test_validation_failure_retains_stage_and_never_promotes(fixture):
    source, admission, opened, closed = fixture
    output = source.parent / "result.aedb"
    value = plan(source, effect="mutate", output=output)
    value["validation"]["program"]["source"] = (
        "def validate(api, context):\n    return {'status': 'failed', 'observed': 3}\n"
    )
    with pytest.raises(ExecutionError) as error:
        native_program.execute_bound_program(
            value, redact_paths=False, binding=None, admission=admission
        )
    assert error.value.code == "validation_failed"
    assert error.value.evidence["validation"]["observed"] == 3
    assert Path(error.value.evidence["retained_stage"]).exists()
    assert not output.exists() and len(closed) == 2


def test_worker_rejects_expired_ownership_before_opening_sdk(fixture):
    source, admission, opened, _ = fixture
    store = LeaseStore(admission["store"])
    from eda_bridge_runtime.lease import Lease

    store.mark_uncertain(Lease(**admission["leases"][0]))
    with pytest.raises(ExecutionError):
        native_program.execute_bound_program(
            plan(source), redact_paths=False, binding=None, admission=admission
        )
    assert opened == []
