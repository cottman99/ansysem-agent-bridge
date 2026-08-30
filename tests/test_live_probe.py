import sys
from types import ModuleType, SimpleNamespace

import pytest

from ansysem_agent_bridge import live_probe
from ansysem_agent_bridge.live_probe import _validation_result


def test_validation_result_accepts_boolean() -> None:
    assert _validation_result(True)["passed"] is True


def test_validation_result_uses_boolean_from_release_specific_tuple() -> None:
    result = _validation_result((["validation message"], False))
    assert result["supported"] is True
    assert result["passed"] is False


def test_validation_result_does_not_treat_nonempty_unknown_value_as_success() -> None:
    assert _validation_result("unknown release shape")["passed"] is False


def test_unregistered_long_lived_desktop_is_closed_immediately(tmp_path, monkeypatch):
    project = tmp_path / "demo.aedt"
    project.write_text("synthetic", encoding="utf-8")
    released = []

    class FakeLayout:
        def __init__(self, **_kwargs):
            self.desktop_class = SimpleNamespace(aedt_process_id=123, port=50051)
            self.odesktop = SimpleNamespace(GetProcessID=lambda: 123, GetVersion=lambda: "2026.1")
            self.project_name = "demo"
            self.design_name = "Layout1"
            self.design_type = "HFSS 3D Layout"
            self.design_list = ["Layout1"]
            self.setup_names = []
            self.port_list = []

        def release_desktop(self, **kwargs):
            released.append(kwargs)

    core = ModuleType("ansys.aedt.core")
    core.Hfss3dLayout = FakeLayout
    monkeypatch.setitem(sys.modules, "ansys", ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt", ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core)
    monkeypatch.setattr(
        live_probe.OwnedSessionStore,
        "register",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("registry unavailable")),
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        live_probe.live_hfss3dlayout_probe(
            project=project,
            version="2026.1",
            new_desktop=True,
            close_desktop=False,
        )
    assert released == [{"close_projects": True, "close_desktop": True}]
