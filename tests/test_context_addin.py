import json
import sys
import types
from types import SimpleNamespace

from ansysem_agent_bridge import aedt_context_tool, context_addin


def test_context_capture_keeps_project_path_out_of_token(tmp_path, monkeypatch):
    monkeypatch.setattr(aedt_context_tool, "agent_home", lambda: tmp_path)
    monkeypatch.setattr(
        aedt_context_tool,
        "_desktop_identity",
        lambda: {
            "profile": "demo",
            "project": "/private/customer/demo.aedt",
            "project_name": "demo",
            "design": "Layout1",
            "version": "2026.1",
            "port": 1234,
            "process_id": 99,
            "display": ":4.0",
        },
    )
    token = aedt_context_tool.capture_context(copy_to_clipboard=False)
    assert "customer" not in token
    from eda_bridge_runtime import EDAContext

    context = EDAContext.decode(token)
    assert set(context.locator) == {"context_id"}
    record = json.loads(
        (tmp_path / "runtime" / "contexts" / f"{context.locator['context_id']}.json").read_text()
    )
    assert record["target"]["project"] == "/private/customer/demo.aedt"


def test_context_addin_install_uses_official_pyaedt_registration(tmp_path, monkeypatch):
    calls = []

    def add_script_to_menu(name, **kwargs):
        calls.append((name, kwargs))
        return True

    import sys

    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=add_script_to_menu),
    )
    result = context_addin.install(tmp_path)
    assert result["status"] == "ready"
    assert [call[0] for call in calls] == list(context_addin.TOOLS)
    assert all(call[1]["panel"] == context_addin.PANEL for call in calls)


def test_context_addin_status_is_bounded_to_owned_actions(tmp_path):
    project = tmp_path / "Toolkits" / "Project"
    project.mkdir(parents=True)
    for name in context_addin.TOOLS:
        (project / name).mkdir()
    (project / "TabConfig.xml").write_text("\n".join(context_addin.TOOLS), encoding="utf-8")
    result = context_addin.status(tmp_path)
    assert result["status"] == "ready"


def test_context_addin_refresh_uses_existing_owned_desktop(monkeypatch):
    calls = []
    desktop = SimpleNamespace(
        odesktop=SimpleNamespace(RefreshToolkitUI=lambda: calls.append("refresh"))
    )
    ansys = types.ModuleType("ansys")
    aedt = types.ModuleType("ansys.aedt")
    core = types.ModuleType("ansys.aedt.core")
    core.Desktop = lambda **kwargs: desktop
    ansys.aedt = aedt
    aedt.core = core
    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.aedt", aedt)
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core)
    result = context_addin.refresh(version="2026.1", port=50051, process_id=123)
    assert result["refreshed"] is True
    assert calls == ["refresh"]
