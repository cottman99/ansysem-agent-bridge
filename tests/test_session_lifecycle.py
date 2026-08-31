import json
from types import SimpleNamespace

import pytest

from ansysem_agent_bridge import session_lifecycle


def test_owned_session_store_requires_exact_release_token(tmp_path):
    store = session_lifecycle.OwnedSessionStore(tmp_path / "sessions.sqlite3")
    resource = store.register(
        pid=123,
        port=50051,
        version="2026.1",
        project="/sanitized/demo.aedt",
        design="Layout1",
    )

    assert resource["ownership"] == "runtime-owned"
    assert resource["release_operation"] == "session.release"
    with pytest.raises(PermissionError, match="unauthorized"):
        store.authorize(resource["resource_id"], "wrong-token")
    record = store.authorize(resource["resource_id"], resource["release_handle"])
    assert record["pid"] == 123
    assert record["port"] == 50051


def test_release_refuses_changed_process_identity(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite3"
    store = session_lifecycle.OwnedSessionStore(database)
    resource = store.register(
        pid=123,
        port=50051,
        version="2026.1",
        project="/sanitized/demo.aedt",
        design="Layout1",
    )
    desktop = SimpleNamespace(
        odesktop=SimpleNamespace(GetProcessID=lambda: 456),
        release_desktop=lambda **_kwargs: None,
    )
    monkeypatch.setattr(session_lifecycle, "_pid_is_alive", lambda _pid: True)
    monkeypatch.setattr(session_lifecycle, "_open_existing_desktop", lambda **_kwargs: desktop)

    with pytest.raises(PermissionError, match="identity changed"):
        session_lifecycle.release_owned_aedt_session(
            resource_id=resource["resource_id"],
            release_handle=resource["release_handle"],
            database=database,
        )


def test_release_owned_session_is_verified_and_idempotent(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite3"
    store = session_lifecycle.OwnedSessionStore(database)
    resource = store.register(
        pid=123,
        port=50051,
        version="2026.1",
        project="/sanitized/demo.aedt",
        design="Layout1",
    )
    alive = {"value": True}

    def close(**_kwargs):
        alive["value"] = False

    desktop = SimpleNamespace(
        odesktop=SimpleNamespace(GetProcessID=lambda: 123),
        release_desktop=close,
    )
    monkeypatch.setattr(session_lifecycle, "_pid_is_alive", lambda _pid: alive["value"])
    monkeypatch.setattr(session_lifecycle, "_open_existing_desktop", lambda **_kwargs: desktop)

    first = session_lifecycle.release_owned_aedt_session(
        resource_id=resource["resource_id"],
        release_handle=resource["release_handle"],
        database=database,
    )
    second = session_lifecycle.release_owned_aedt_session(
        resource_id=resource["resource_id"],
        release_handle=resource["release_handle"],
        database=database,
    )
    assert first["resource"]["state"] == "released"
    assert second["idempotent"] is True


def test_authorize_owned_session_binds_exact_project_version_and_design(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite3"
    project = tmp_path / "demo.aedt"
    store = session_lifecycle.OwnedSessionStore(database)
    resource = store.register(
        pid=123,
        port=50051,
        version="2026.1",
        project=str(project),
        design="Layout1",
    )
    monkeypatch.setattr(session_lifecycle, "_pid_is_alive", lambda _pid: True)

    record = session_lifecycle.authorize_owned_aedt_session(
        resource_id=resource["resource_id"],
        release_handle=resource["release_handle"],
        project=project,
        version="2026.1",
        design="Layout1",
        database=database,
    )
    assert record["port"] == 50051
    with pytest.raises(PermissionError, match="project identity"):
        session_lifecycle.authorize_owned_aedt_session(
            resource_id=resource["resource_id"],
            release_handle=resource["release_handle"],
            project=tmp_path / "other.aedt",
            version="2026.1",
            design="Layout1",
            database=database,
        )


def test_authorize_captured_session_requires_live_exact_context(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    project = tmp_path / "demo.aedt"
    context_root = tmp_path / "runtime" / "contexts"
    context_root.mkdir(parents=True)
    monkeypatch.setattr(session_lifecycle, "agent_home", lambda: tmp_path)
    monkeypatch.setattr(session_lifecycle, "_pid_is_alive", lambda pid: pid == 123)
    token = EDAContext(
        eda="ansys-electronics-desktop",
        target_kind="design",
        locator={"context_id": "ctx_live"},
        display_name="demo:Layout1",
        generation=2,
        session={"process_id": 123, "port": 50051, "state": "live"},
        target={"project_name": "demo", "design": "Layout1", "version": "2026.1"},
        freshness={"scope": "live", "generation": 2, "state": "captured-live"},
    ).encode()
    (context_root / "ctx_live.json").write_text(
        json.dumps(
            {
                "generation": 2,
                "target": {
                    "project": str(project),
                    "design": "Layout1",
                    "version": "2026.1",
                    "process_id": 123,
                    "port": 50051,
                },
            }
        ),
        encoding="utf-8",
    )

    result = session_lifecycle.authorize_captured_aedt_session(
        context=token,
        project=project,
        version="2026.1",
        design="Layout1",
    )

    assert result["ownership"] == "user-owned-context"
    assert result["pid"] == 123
    with pytest.raises(PermissionError, match="design identity"):
        session_lifecycle.authorize_captured_aedt_session(
            context=token,
            project=project,
            version="2026.1",
            design="Other",
        )
