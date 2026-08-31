from types import SimpleNamespace

import pytest

from ansysem_agent_bridge import live_patch


class _Variables:
    def __init__(self):
        self.values = {}

    @property
    def variables(self):
        return self.values

    def set_variable(self, name, expression, overwrite):
        assert overwrite is True
        self.values[name] = expression
        return True

    def delete_variable(self, name):
        del self.values[name]
        return True


class _App:
    def __init__(self, *, design="Layout1", variables=None):
        self.design_name = design
        self.variable_manager = _Variables()
        self.variable_manager.values.update(variables or {})
        self.odesktop = SimpleNamespace(GetProcessID=lambda: 123)
        self.saved = False
        self.project_name = "demo"

    def __getitem__(self, name):
        return self.variable_manager.values[name]

    def save_project(self):
        self.saved = True
        return True

    def close_project(self, name, save):
        assert name == self.project_name
        assert save is False
        self.variable_manager.values.clear()
        return True

    def load_project(self, file_name, design, close_active, set_active):
        assert file_name.endswith("demo.aedt")
        assert design == self.design_name
        assert close_active is False
        assert set_active is True
        return True


def _install_fake_aedt(monkeypatch, app):
    live_patch._APP_CACHE.clear()
    monkeypatch.setattr(
        live_patch,
        "authorize_owned_aedt_session",
        lambda **_kwargs: {"pid": 123, "port": 50051},
    )
    monkeypatch.setattr(
        live_patch,
        "authorize_captured_aedt_session",
        lambda **_kwargs: {
            "pid": 123,
            "port": 50051,
            "ownership": "user-owned-context",
        },
    )
    core = SimpleNamespace(Hfss3dLayout=lambda **_kwargs: app)
    monkeypatch.setitem(__import__("sys").modules, "ansys", SimpleNamespace(aedt=core))
    monkeypatch.setitem(__import__("sys").modules, "ansys.aedt", core)
    monkeypatch.setitem(__import__("sys").modules, "ansys.aedt.core", core)


def test_live_patch_creates_and_deletes_variable_in_owned_gui_session(monkeypatch, tmp_path):
    app = _App()
    _install_fake_aedt(monkeypatch, app)
    common = {
        "resource_id": "aedt_owned",
        "release_handle": "secret",
        "project": tmp_path / "demo.aedt",
        "version": "2026.1",
        "design": "Layout1",
    }

    created = live_patch.apply_live_patch(
        **common,
        operation={
            "op": "set_design_variable",
            "name": "agent_probe",
            "expected_before": None,
            "value": "75mil",
        },
    )
    deleted = live_patch.apply_live_patch(
        **common,
        operation={
            "op": "delete_design_variable",
            "name": "agent_probe",
            "expected_before": "75mil",
        },
    )

    assert created["readback"] == {
        "name": "agent_probe",
        "before": None,
        "actual": "75mil",
    }
    assert deleted["readback"] == {
        "name": "agent_probe",
        "before": "75mil",
        "actual": None,
    }


def test_live_patch_refuses_stale_precondition_before_mutation(monkeypatch, tmp_path):
    app = _App(variables={"trace_w": "10mil"})
    _install_fake_aedt(monkeypatch, app)

    with pytest.raises(RuntimeError, match="precondition failed"):
        live_patch.apply_live_patch(
            resource_id="aedt_owned",
            release_handle="secret",
            project=tmp_path / "demo.aedt",
            version="2026.1",
            design="Layout1",
            operation={
                "op": "set_design_variable",
                "name": "trace_w",
                "expected_before": "9mil",
                "value": "12mil",
            },
        )
    assert app.variable_manager.values["trace_w"] == "10mil"


def test_live_patch_accepts_live_context_without_release_authority(monkeypatch, tmp_path):
    app = _App()
    _install_fake_aedt(monkeypatch, app)

    result = live_patch.apply_live_patch(
        context="EDA_CONTEXT:synthetic",
        project=tmp_path / "demo.aedt",
        version="2026.1",
        design="Layout1",
        operation={
            "op": "set_design_variable",
            "name": "trace_w",
            "expected_before": None,
            "value": "10mil",
        },
    )

    assert result["session_ownership"] == "user-owned-context"


def test_live_patch_reuses_exact_authorized_pyaedt_connection(monkeypatch, tmp_path):
    app = _App()
    calls = []
    _install_fake_aedt(monkeypatch, app)
    core = __import__("sys").modules["ansys.aedt.core"]
    core.Hfss3dLayout = lambda **kwargs: calls.append(kwargs) or app
    common = {
        "context": "EDA_CONTEXT:synthetic",
        "project": tmp_path / "demo.aedt",
        "version": "2026.1",
        "design": "Layout1",
    }

    first = live_patch.apply_live_patch(
        **common,
        operation={
            "op": "set_design_variable",
            "name": "trace_w",
            "expected_before": None,
            "value": "10mil",
        },
    )
    second = live_patch.apply_live_patch(
        **common,
        operation={
            "op": "delete_design_variable",
            "name": "trace_w",
            "expected_before": "10mil",
        },
    )

    assert first["connection_reused"] is False
    assert second["connection_reused"] is True
    assert len(calls) == 1


def test_live_finalize_discard_reopens_exact_project(monkeypatch, tmp_path):
    app = _App(variables={"trace_w": "12mil"})
    _install_fake_aedt(monkeypatch, app)

    result = live_patch.finalize_live_design(
        resource_id="aedt_owned",
        release_handle="secret",
        project=tmp_path / "demo.aedt",
        version="2026.1",
        design="Layout1",
        action="discard_unsaved",
        decision={
            "authorization": "agent-owned-session",
            "reason": "Discard a disposable owned design",
        },
    )

    assert result["action"] == "discard_unsaved"
    assert app.variable_manager.values == {}


def test_live_finalize_context_cannot_claim_agent_owned_discard(monkeypatch, tmp_path):
    app = _App()
    _install_fake_aedt(monkeypatch, app)

    with pytest.raises(PermissionError, match="Runtime-owned"):
        live_patch.finalize_live_design(
            context="EDA_CONTEXT:synthetic",
            project=tmp_path / "demo.aedt",
            version="2026.1",
            design="Layout1",
            action="discard_unsaved",
            decision={
                "authorization": "agent-owned-session",
                "reason": "Must not claim user session ownership",
            },
        )
