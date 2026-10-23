import json
import shutil
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from ansysem_agent_bridge import aedt_context_tool, context_addin


def fake_registration(name, **kwargs):
    project = Path(kwargs["personal_lib"]) / "Toolkits" / "Project"
    folder = project / name
    (folder / "Lib").mkdir(parents=True, exist_ok=True)
    source = Path(kwargs["script_file"])
    shutil.copy2(source, folder / "Lib" / source.name)
    (folder / "run_pyaedt_toolkit_script.py").write_text("launcher")
    tab = project / "TabConfig.xml"
    root = ET.parse(tab).getroot() if tab.exists() else ET.Element("TabConfig")
    for item in list(root):
        if item.get("label") == name or item.get("script") == f"{name}/run_pyaedt_toolkit_script":
            root.remove(item)
    ET.SubElement(root, "button", label=name, script=f"{name}/run_pyaedt_toolkit_script")
    ET.ElementTree(root).write(tab)
    return True


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


def test_store_context_binds_complete_bundle_state_only_in_private_record(tmp_path, monkeypatch):
    from eda_bridge_runtime import EDAContext

    project = tmp_path / "synthetic.aedt"
    project.write_text("project", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("edb", encoding="utf-8")
    monkeypatch.setattr(aedt_context_tool, "agent_home", lambda: tmp_path)
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
    record = json.loads(
        (tmp_path / "runtime" / "contexts" / f"{context.locator['context_id']}.json").read_text()
    )
    binding = record["binding"]
    assert binding["resource_kind"] == "aedt-project"
    assert len(binding["bundle_sha256"]) == 64
    assert len(binding["state_revision"]) == 64
    assert binding["bundle_sha256"] not in token
    public_context = json.dumps(
        {
            "locator": context.locator,
            "session": context.session,
            "target": context.target,
            "freshness": context.freshness,
        },
        sort_keys=True,
    )
    assert "bundle_sha256" not in public_context
    assert "state_revision" not in public_context
    assert str(project.resolve()) not in public_context
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "schemas"
            / "ansysem-continuation-context-record-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(record, schema)


def test_context_addin_install_uses_official_pyaedt_registration(tmp_path, monkeypatch):
    calls = []

    def add_script_to_menu(name, **kwargs):
        calls.append((name, kwargs))
        return fake_registration(name, **kwargs)

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
    assert result["status"] == "attention_required"
    assert result["right_click"]["status"] == "requires_live_session"
    assert result["verification"]["automation_status"] == "ready"
    assert context_addin.status(tmp_path)["files_intact"]
    assert [call[0] for call in calls] == list(context_addin.TOOL_DIRECTORIES.values())
    assert all(" " not in call[0] for call in calls)
    assert result["verification"]["ui_visibility"] == "not_checked"
    assert all(call[1]["panel"] == context_addin.PANEL for call in calls)
    assert all(call[1]["icon_file"] == str(icon) for call in calls)


def test_context_addin_status_is_bounded_to_owned_actions(tmp_path):
    project = tmp_path / "Toolkits" / "Project"
    project.mkdir(parents=True)
    for name in context_addin.TOOLS:
        (project / name).mkdir()
    (project / "TabConfig.xml").write_text("\n".join(context_addin.TOOLS), encoding="utf-8")
    result = context_addin.status(tmp_path)
    assert result["status"] == "not_installed"
    assert not result["actions"]["Copy Agent Context"]["script_present"]


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
    menu_set = ["Default"]
    desktop = SimpleNamespace(
        personallib=str(tmp_path / "live" / "PersonalLib"),
        odesktop=SimpleNamespace(
            RefreshToolkitUI=lambda: refreshed.append(True),
            GetExeDir=lambda: str(tmp_path / "vendor"),
            GetCustomMenuSet=lambda: menu_set[0],
            GetMessages=lambda *args: [],
            SetCustomMenuSet=lambda name: menu_set.__setitem__(0, name),
        ),
    )

    def add_script_to_menu(name, **kwargs):
        calls.append((name, kwargs))
        return fake_registration(name, **kwargs)

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
    assert result["status"] == "ready"
    assert result["right_click"]["status"] == "ready"
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


def test_install_upgrade_repair_preserves_unrelated_buttons_and_tracks_python(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=fake_registration),
    )
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: tmp_path / "icon.png")
    monkeypatch.setattr(context_addin, "_remove_owned_buttons", lambda *args, **kwargs: None)
    context_addin.install(tmp_path, profile_id="test-profile")
    tab = tmp_path / "Toolkits" / "Project" / "TabConfig.xml"
    tree = ET.parse(tab)
    ET.SubElement(tree.getroot(), "button", label="User Tool")
    tree.write(tab)
    script = (
        tmp_path / "Toolkits" / "Project" / "CopyAgentContext" / "Lib" / "copy_agent_context.py"
    )
    script.write_text("stale copied file")
    assert context_addin.status(tmp_path)["status"] == "repair_required"
    context_addin.reconcile_configured("test-profile")
    assert context_addin.status(tmp_path)["automation_status"] == "ready"
    assert context_addin.status(tmp_path)["right_click"]["status"] == "requires_live_session"
    assert "User Tool" in tab.read_text()
    assert len(list(ET.parse(tab).iter("button"))) == 4
    context_addin.reconcile_configured("test-profile")
    assert len(list(ET.parse(tab).iter("button"))) == 4
    old = context_addin._signature()
    monkeypatch.setattr(context_addin, "_signature", lambda: {**old, "python": "/new/python"})
    assert context_addin.status(tmp_path)["status"] == "repair_required"


def test_status_does_not_create_missing_personal_lib(tmp_path):
    absent = tmp_path / "not-created"
    assert context_addin.status(absent)["status"] == "not_installed"
    assert not absent.exists()


def test_uninstall_forgets_registration_so_startup_does_not_reinstall(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=fake_registration, tab_map=lambda name: name),
    )
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: tmp_path / "icon.png")
    monkeypatch.setattr(context_addin, "_remove_owned_buttons", lambda *args, **kwargs: None)
    context_addin.install(tmp_path, profile_id="demo")
    context_addin.uninstall(tmp_path)
    assert context_addin.reconcile_configured("demo")["status"] == "not_configured"
    assert not (tmp_path / "Toolkits" / "Project" / context_addin.MANIFEST).exists()


def test_install_requires_actual_personal_lib_and_reuses_registered_root(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=fake_registration),
    )
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: tmp_path / "icon.png")
    monkeypatch.setattr(context_addin, "_remove_owned_buttons", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="actual AEDT PersonalLib"):
        context_addin.install(profile_id="demo")
    context_addin.install(tmp_path, profile_id="demo")
    assert context_addin.install(profile_id="demo")["personal_lib"] == str(tmp_path.resolve())


def test_status_detects_button_retargeting(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "ansys.aedt.core.extensions.customize_automation_tab",
        SimpleNamespace(add_script_to_menu=fake_registration),
    )
    monkeypatch.setattr(context_addin, "_pyaedt_icon", lambda: tmp_path / "icon.png")
    context_addin.install(tmp_path)
    tab = tmp_path / "Toolkits" / "Project" / "TabConfig.xml"
    tree = ET.parse(tab)
    list(tree.iter("button"))[0].set("script", "wrong/launcher")
    tree.write(tab)
    assert context_addin.status(tmp_path)["status"] == "repair_required"


def test_button_bootstrap_routes_registered_profile_and_preserves_live_identity(
    tmp_path, monkeypatch
):
    from ansysem_agent_bridge import profiles

    monkeypatch.delenv("ANSYSEM_CONTEXT_BOOTSTRAPPED", raising=False)
    monkeypatch.setenv("PYAEDT_PERSONAL_LIB", str(tmp_path))
    monkeypatch.setenv("PYAEDT_PROCESS_ID", "123")
    monkeypatch.setenv("PYAEDT_DESKTOP_PORT", "456")
    monkeypatch.setattr(
        aedt_context_tool,
        "load_config",
        lambda: {
            "default_profile": "other",
            "context_addins": [{"personal_lib": str(tmp_path), "profile": "selected"}],
        },
    )
    calls = []
    monkeypatch.setattr(
        profiles, "ensure_profile_process", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    aedt_context_tool._prepare_button_process("copy")
    assert calls == [(("selected", ["copy"]), {"module": "ansysem_agent_bridge.aedt_context_tool"})]
    import os

    assert os.environ["PYAEDT_PROCESS_ID"] == "123"
    assert os.environ["PYAEDT_DESKTOP_PORT"] == "456"


def test_button_child_keeps_captured_display_over_profile_default(monkeypatch):
    import os

    monkeypatch.setenv("ANSYSEM_CONTEXT_BOOTSTRAPPED", "1")
    monkeypatch.setenv("ANSYSEM_CONTEXT_DISPLAY", ":4.0")
    monkeypatch.setenv("DISPLAY", ":3.0")
    aedt_context_tool._prepare_button_process("copy")
    assert os.environ["DISPLAY"] == ":4.0"


def test_button_requires_session_identity_before_loading_sdk(monkeypatch):
    import pytest

    monkeypatch.delenv("PYAEDT_PROCESS_ID", raising=False)
    with pytest.raises(RuntimeError, match="exact AEDT session"):
        aedt_context_tool._desktop_identity()
