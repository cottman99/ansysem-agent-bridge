import json
from types import SimpleNamespace

import pytest
from eda_bridge_runtime import EDAContext

from ansysem_agent_bridge import aedt_context_tool, context_menu, session_lifecycle
from ansysem_agent_bridge.aedt_addin_assets.native_selection import capture


class Node:
    def __init__(self, children=None):
        self.children = children or {}

    def GetChildNames(self):
        return list(self.children)

    def GetChildObject(self, name):
        return self.children[name]


@pytest.fixture
def desktop():
    editor = SimpleNamespace(
        GetSelections=lambda: ["Patch_A", "Face3"],
        GetSelectionsInHierarchy=lambda: ["sub/Patch_A", "Face3"],
        GetEditorName=lambda: "Layout",
    )
    design = Node({"Analysis": Node({"Setup_A": Node(), "Setup_B": Node()})})
    design.GetName = lambda: "0;设计"
    design.GetDesignType = lambda: "HFSS 3D Layout Design"
    design.GetActiveEditor = lambda: editor
    project = SimpleNamespace(
        GetName=lambda: "工程",
        GetPath=lambda: "/private/task",
        GetActiveDesign=lambda: design,
        GetDesigns=lambda: [design],
    )
    return SimpleNamespace(
        GetActiveProject=lambda: project,
        GetVersion=lambda: "2026.1.0",
        GetProcessID=lambda: 99,
        GetGrpcServerPort=lambda: 50051,
    )


def test_native_capture_distinguishes_canvas_and_tree_scopes(desktop):
    selection = capture(desktop, "canvas")
    assert selection["target_kind"] == "selection"
    assert selection["selection"]["objects"] == ["Patch_A", "Face3"]
    assert selection["selection"]["hierarchy"] == ["sub/Patch_A", "Face3"]
    project = capture(desktop, "project")
    assert project["design"] is None
    assert project["designs"] == ["设计"]
    assert project["selection"] == {"source": "project-tree", "path": ["工程"]}
    folder = capture(desktop, "tree:Analysis")
    assert folder["selection"]["path"] == ["工程", "设计", "Analysis"]
    assert "objects" not in folder["selection"]


def test_tree_item_requires_explicit_choice_even_with_a_canvas_selection(desktop):
    item = capture(desktop, "tree:Analysis/Item")
    assert item["pending_tree_choices"] == [
        {"name": "Setup_A", "path": ["工程", "设计", "Analysis", "Setup_A"]},
        {"name": "Setup_B", "path": ["工程", "设计", "Analysis", "Setup_B"]},
    ]
    assert "name" not in item["selection"]


def test_empty_canvas_selection_never_falls_back_to_whole_design(desktop):
    editor = desktop.GetActiveProject().GetActiveDesign().GetActiveEditor()
    editor.GetSelections = lambda: []
    editor.GetSelectionsInHierarchy = lambda: []
    with pytest.raises(RuntimeError, match="Select objects"):
        capture(desktop, "canvas")
    assert capture(desktop)["target_kind"] == "design"


def test_copy_cancel_preserves_clipboard(monkeypatch):
    monkeypatch.setattr(aedt_context_tool, "_desktop_identity", lambda: {})
    monkeypatch.setattr(aedt_context_tool, "_choose_tree_item", lambda _identity: None)
    monkeypatch.setattr(
        aedt_context_tool, "_copy_text", lambda _text: pytest.fail("clipboard changed")
    )
    assert aedt_context_tool.capture_context() is None


def test_context_keeps_distinct_selection_snapshots_and_project_scope(desktop, monkeypatch):
    first = EDAContext.decode(aedt_context_tool.store_context(capture(desktop, "canvas")))
    second = EDAContext.decode(aedt_context_tool.store_context(capture(desktop, "tree:Analysis")))
    assert first.locator != second.locator
    assert first.selection["objects"] == ["Patch_A", "Face3"]
    assert "/private/task" not in first.encode()
    project = capture(desktop, "project")
    token = aedt_context_tool.store_context(project)
    monkeypatch.setattr(session_lifecycle, "_pid_is_alive", lambda pid: pid == 99)
    args = {"context": token, "project": project["project"], "version": "2026.1"}
    assert session_lifecycle.authorize_captured_aedt_session(**args, design="设计")["pid"] == 99
    with pytest.raises(PermissionError, match="design identity"):
        session_lifecycle.authorize_captured_aedt_session(**args, design="not-captured")


def test_additive_menus_preserve_customization_and_repair_without_duplicates(tmp_path):
    current = ["UserMenu"]
    api = SimpleNamespace(
        GetExeDir=lambda: str(tmp_path / "vendor"),
        GetCustomMenuSet=lambda: current[0],
        SetCustomMenuSet=lambda name: current.__setitem__(0, name),
        GetMessages=lambda *args: [],
    )
    base = tmp_path / "vendor/config/UI/ElectronicsDesktop/UserMenu"
    base.mkdir(parents=True)
    custom = (
        '<DesignerMenu xmlns="http://www.ansys.com/uiConfigMenu" action="useDefault">'
        '<Context name="Project"><CustomMenu action="add"><MenuName>My Tool</MenuName>'
        "<ScriptPath>$PERSONALLIB/my.py</ScriptPath></CustomMenu></Context></DesignerMenu>"
    )
    (base / "RightClickMenu.xml").write_text(custom)
    root = tmp_path / "PersonalLib"
    backup = tmp_path / "backup"
    first = context_menu.install(root, desktop=SimpleNamespace(odesktop=api), backup=backup)
    assert context_menu.status(first)["status"] == "ready"
    second = context_menu.install(root, registration=first, backup=backup)
    assert context_menu.status(second)["status"] == "ready"
    assert len(second["entries"]) < 100
    for design in context_menu.DESIGNS:
        design_entries = [entry for entry in second["entries"] if entry["context"] == design]
        assert len(design_entries) == 1
        assert design_entries[0]["label"] == "Copy Agent Context"
    assert all("Canvas" not in entry["label"] for entry in second["entries"])
    assert (base / "RightClickMenu.xml").read_text() == custom
    menu_xml = base.parent / first["name"] / "RightClickMenu.xml"
    assert "My Tool" in menu_xml.read_text()
    menu_xml.write_text(menu_xml.read_text().replace("Copy Agent Context", "Wrong action"))
    assert context_menu.status(second)["status"] == "repair_required"
    repaired = context_menu.install(root, registration=second, backup=backup)
    context_menu.uninstall(repaired, backup=backup)
    assert "My Tool" in menu_xml.read_text()
    assert "Copy Agent Context" not in menu_xml.read_text()
    reinstalled = context_menu.install(root, registration=repaired, backup=backup)
    assert context_menu.status(reinstalled)["status"] == "ready"
    marker = json.loads((menu_xml.parent / context_menu.MARKER).read_text())
    assert marker["previous"] == "UserMenu"
