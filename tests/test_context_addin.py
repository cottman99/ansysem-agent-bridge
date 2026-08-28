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
    assert context.protocol == "eda-context/v2"
    assert context.origin["origin_id"].startswith("origin-")
    assert context.session["display"] == ":4.0"
    assert context.session["session_id"] == "aedt-99-1234"
    assert context.target == {
        "project_name": "demo",
        "design": "Layout1",
        "version": "2026.1",
    }
    assert context.capabilities["digest"].startswith("cap-")
    assert set(context.locator) == {"context_id"}
    record = json.loads(
        (tmp_path / "runtime" / "contexts" / f"{context.locator['context_id']}.json").read_text()
    )
    assert record["target"]["project"] == "/private/customer/demo.aedt"


def test_store_context_accepts_background_identity_without_process_id(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    monkeypatch.setattr(aedt_context_tool, "agent_home", lambda: tmp_path)
    token = aedt_context_tool.store_context(
        {
            "project": "/private/scratch/demo.aedt",
            "project_name": "demo",
            "design": "Layout1",
        },
        connection_id="ansys-display4",
    )
    context = EDAContext.decode(token)
    assert context.locator["connection_id"] == "ansys-display4"
    assert "project" not in context.locator
    assert context.freshness["scope"] == "durable"


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
    icon = tmp_path / "pyansys.png"
    icon.write_bytes(b"png")
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: icon)
    result = context_addin.install(tmp_path)
    assert result["status"] == "ready"
    assert [call[0] for call in calls] == list(context_addin.TOOLS)
    assert all(call[1]["panel"] == context_addin.PANEL for call in calls)
    assert all(call[1]["icon_file"] == str(icon) for call in calls)


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
        odesktop=SimpleNamespace(RefreshToolkitUI=lambda: calls.append("refresh")),
        personallib="/live/PersonalLib",
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
    assert result["personal_lib"].replace("\\", "/").endswith("live/PersonalLib")
    assert calls == ["refresh"]


def test_context_addin_install_prefers_live_personal_lib(tmp_path, monkeypatch):
    calls = []
    refreshed = []
    desktop = SimpleNamespace(
        personallib=str(tmp_path / "live" / "PersonalLib"),
        odesktop=SimpleNamespace(RefreshToolkitUI=lambda: refreshed.append(True)),
    )

    def add_script_to_menu(name, **kwargs):
        calls.append((name, kwargs))
        return True

    monkeypatch.setattr(context_addin, "_connect_desktop", lambda **kwargs: desktop)
    icon = tmp_path / "pyansys.png"
    icon.write_bytes(b"png")
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: icon)
    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=add_script_to_menu),
    )
    result = context_addin.install(version="2026.1", port=50051, process_id=123)
    assert result["live_session"] is True
    assert result["refresh_required"] is False
    assert all(call[1]["personal_lib"] == desktop.personallib for call in calls)
    assert all(call[1]["odesktop"] is desktop.odesktop for call in calls)
    assert refreshed == [True]


def test_context_addin_install_rejects_partial_live_identity(tmp_path):
    try:
        context_addin.install(tmp_path, version="2026.1")
    except ValueError as exc:
        assert "provided together" in str(exc)
    else:
        raise AssertionError("partial live identity was accepted")
