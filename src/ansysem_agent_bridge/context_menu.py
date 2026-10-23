"""Own one additive AEDT menu set, preserving the user's previous menu set."""

from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

NS = "http://www.ansys.com/uiConfigMenu"
MARKER = ".eda-agent-menu.json"
# AEDT accepts at most 100 custom menu entries. Register the two EM editors
# covered by this add-in instead of filling the global table with unused types.
DESIGNS = ("HFSS", "HFSS 3D Layout Design")
BRANCHES = (
    "Analysis",
    "Optimetrics",
    "Boundaries",
    "Excitations",
    "Mesh",
    "Radiation",
    "Field Overlays",
    "Results",
    "Circuit Elements",
    "Sources",
    "Design Verification",
)
DEFINITIONS = ("Materials", "Surface Materials", "Components", "Symbols", "Models", "Scripts")


def contexts():
    yield "Project", "project"
    yield "Definitions", "definitions"
    for branch in DEFINITIONS:
        yield "Definitions/" + branch, "definitions:" + branch
        yield "Definitions/" + branch + "/Item", "definitions:" + branch + "/Item"
    for design in DESIGNS:
        yield design, "design"
        for branch in BRANCHES:
            yield design + "/" + branch, "tree:" + branch
            suffix = "/Report" if branch == "Results" else "/Item"
            yield design + "/" + branch + suffix, "tree:" + branch + "/Item"
            if branch == "Analysis":
                yield design + "/Analysis/Item/Item", "tree:Analysis/Item/Item"
            if branch == "Results":
                yield design + "/Results/Report/Trace", "tree:Results/Item/Item"


def _launcher(scope: str) -> str:
    # Capture inside AEDT before launching CPython: neither a changed focus nor
    # slow process startup may silently replace the user's clicked target.
    return """# Generated EDA Agent menu entry. Runs inside AEDT (IronPython).
import json
import os
_eda_base = os.path.join(
    oDesktop.GetPersonalLibDirectory(), "Toolkits", "Project", "CopyAgentContext")
_eda_source = os.path.join(_eda_base, "Lib", "native_selection.py")
_eda_ns = {"__name__": "eda_agent_native_selection"}
with open(_eda_source) as _eda_stream:
    exec(compile(_eda_stream.read(), _eda_source, "exec"), _eda_ns)
_eda_snapshot = _eda_ns["capture"](oDesktop, SCOPE_PLACEHOLDER)
_eda_json = json.dumps(_eda_snapshot, ensure_ascii=True)
if len(_eda_json) > 24000:
    raise RuntimeError("This selection is too large to copy. Select a smaller group of objects.")
_eda_old = os.environ.get("ANSYSEM_CONTEXT_CAPTURE")
os.environ["ANSYSEM_CONTEXT_CAPTURE"] = _eda_json
try:
    _eda_launcher = os.path.join(_eda_base, "run_pyaedt_toolkit_script.py")
    with open(_eda_launcher) as _eda_stream:
        exec(compile(_eda_stream.read(), _eda_launcher, "exec"), globals())
finally:
    if _eda_old is None:
        os.environ.pop("ANSYSEM_CONTEXT_CAPTURE", None)
    else:
        os.environ["ANSYSEM_CONTEXT_CAPTURE"] = _eda_old
""".replace("SCOPE_PLACEHOLDER", repr(scope))


def install(personal_lib: Path, *, desktop=None, registration=None, backup: Path) -> dict[str, Any]:
    registration = registration or {}
    if desktop:
        parent = Path(desktop.odesktop.GetExeDir()) / "config" / "UI" / "ElectronicsDesktop"
        current = str(desktop.odesktop.GetCustomMenuSet())
    elif registration.get("directory"):
        parent = Path(registration["directory"]).parent
        current = registration["previous"]
    else:
        return {"status": "requires_live_session"}
    name = "EDA Agent-" + hashlib.sha256(str(personal_lib).encode()).hexdigest()[:8]
    destination = parent / name
    marker = destination / MARKER
    previous = registration.get("previous", current)
    clone_base = not destination.exists() or (desktop is not None and current != name)
    if destination.exists():
        if not marker.is_file():
            raise ValueError("The Agent menu directory exists without an ownership record")
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved.get("personal_lib") != str(personal_lib):
            raise ValueError("The Agent menu directory belongs to a different PersonalLib")
        previous = saved["previous"] if current == name else current
        shutil.copytree(destination, backup / "right-click-menu", dirs_exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    # Clone the selected UI set once, then add our entries to its existing XML.
    # Never modify vendor defaults or replace other users' custom commands.
    base = parent / previous
    if clone_base and previous not in ("Default", name) and base.is_dir():
        for path in base.glob("*.xml"):
            shutil.copy2(path, destination / path.name)
    xml_path = destination / "RightClickMenu.xml"
    ET.register_namespace("", NS)
    root = (
        ET.parse(xml_path).getroot()
        if xml_path.exists()
        else ET.Element(f"{{{NS}}}DesignerMenu", action="useDefault")
    )
    if root.get("action") != "useDefault":
        raise ValueError("The existing menu set does not use additive menus; keep it unchanged")
    for parent_node in root.iter():
        for child in list(parent_node):
            script = child.find(f"{{{NS}}}ScriptPath")
            if script is not None and any(
                marker in (script.text or "")
                for marker in ("/EDA Agent Menus/", "/CopyAgentContext/Lib/menus/")
            ):
                parent_node.remove(child)
    scripts = personal_lib / "Toolkits" / "Project" / "CopyAgentContext" / "Lib" / "menus"
    scripts.mkdir(parents=True, exist_ok=True)
    owned = []
    for context_name, scope in contexts():
        context = next((c for c in root if c.get("name") == context_name), None)
        if context is None:
            context = ET.SubElement(root, f"{{{NS}}}Context", name=context_name)
        commands = [(scope, "Copy Agent Context..." if "/Item" in scope else "Copy Agent Context")]
        for command, label in commands:
            filename = hashlib.sha256(command.encode()).hexdigest()[:16] + ".py"
            (scripts / filename).write_text(_launcher(command), encoding="utf-8")
            menu = ET.SubElement(context, f"{{{NS}}}CustomMenu", action="add")
            ET.SubElement(menu, f"{{{NS}}}MenuName").text = label
            script = "$PERSONALLIB/Toolkits/Project/CopyAgentContext/Lib/menus/" + filename
            ET.SubElement(menu, f"{{{NS}}}ScriptPath").text = script
            owned.append({"context": context_name, "label": label, "script": script})
    ET.indent(root)
    custom_count = len(list(root.iter(f"{{{NS}}}CustomMenu")))
    for path in destination.glob("*.xml"):
        if path.name != "RightClickMenu.xml":
            custom_count += len(list(ET.parse(path).iter(f"{{{NS}}}CustomMenu")))
    if custom_count > 100:
        raise ValueError("The selected AEDT menu set exceeds the 100 custom-menu limit")
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    record = {
        "directory": str(destination),
        "name": name,
        "previous": previous,
        "personal_lib": str(personal_lib),
        "entries": owned,
    }
    marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    if desktop:
        before = list(desktop.odesktop.GetMessages("", "", 0))
        desktop.odesktop.SetCustomMenuSet("Default")
        desktop.odesktop.SetCustomMenuSet(name)
        if str(desktop.odesktop.GetCustomMenuSet()) != name:
            raise RuntimeError("AEDT did not activate the Agent context menu")
        messages = list(desktop.odesktop.GetMessages("", "", 0))[len(before) :]
        if any("maximum number of custom menus" in str(m).lower() for m in messages):
            desktop.odesktop.SetCustomMenuSet(previous)
            raise RuntimeError("AEDT rejected menu entries because its custom-menu table is full")
    return {"status": "ready", **record, "activation_required": desktop is None}


def status(registration: dict[str, Any] | None) -> dict[str, Any]:
    if not registration or not registration.get("directory"):
        return {"status": "requires_live_session"}
    try:
        directory = Path(registration["directory"])
        marker = json.loads((directory / MARKER).read_text(encoding="utf-8"))
        root = ET.parse(directory / "RightClickMenu.xml").getroot()
        actual = [
            (c.get("name"), m.findtext(f"{{{NS}}}MenuName"), m.findtext(f"{{{NS}}}ScriptPath"))
            for c in root
            for m in c.findall(f"{{{NS}}}CustomMenu")
            if m.get("action") == "add"
        ]
        ready = (
            root.get("action") == "useDefault"
            and marker == {k: registration[k] for k in marker}
            and all(
                actual.count((e["context"], e["label"], e["script"])) == 1
                for e in registration["entries"]
            )
        )
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        ready = False
    return {"status": "ready" if ready else "repair_required", "name": registration.get("name")}


def uninstall(registration: dict[str, Any] | None, *, backup: Path) -> None:
    if not registration or not registration.get("directory"):
        return
    directory = Path(registration["directory"]).resolve()
    marker = directory / MARKER
    if not marker.is_file():
        return
    saved = json.loads(marker.read_text(encoding="utf-8"))
    if saved.get("personal_lib") != registration.get("personal_lib"):
        raise ValueError("The menu ownership record does not match this installation")
    shutil.copytree(directory, backup / "right-click-menu", dirs_exist_ok=True)
    # Keep a valid named menu set for open AEDT sessions until their next UI
    # switch. Remove only our entries, preserving the original user's XML.
    xml_path = directory / "RightClickMenu.xml"
    root = ET.parse(xml_path).getroot()
    for context in root:
        for menu in list(context):
            script = menu.findtext(f"{{{NS}}}ScriptPath", "")
            if any(
                marker in script for marker in ("/EDA Agent Menus/", "/CopyAgentContext/Lib/menus/")
            ):
                context.remove(menu)
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    # Retain the ownership marker so a subsequent explicit install can safely
    # reuse this directory. The installer registration is removed separately.
