"""Read native selection at the instant an AEDT menu command is invoked.

This file is also loaded by AEDT's IronPython interpreter. Keep it stdlib-only
and Python 2 compatible; execution and clipboard handling stay in the Bridge.
"""

import os
from datetime import datetime

try:
    text_type = unicode  # noqa: F821 -- AEDT IronPython 2
except NameError:
    text_type = str


def _names(values):
    return [text_type(value) for value in (values or [])]


def _descendants(node, depth, prefix):
    if depth == 0:
        return [{"name": prefix[-1], "path": prefix}]
    result = []
    for name in _names(node.GetChildNames()):
        path = prefix + [name]
        if depth == 1:
            result.append({"name": name, "path": path})
        else:
            result.extend(_descendants(node.GetChildObject(name), depth - 1, path))
    return result


def capture(odesktop, scope="auto"):
    """Return a snapshot, never infer a selected tree item from the active design."""
    project = odesktop.GetActiveProject()
    if project is None:
        raise RuntimeError("Select an AEDT project first.")
    project_name = text_type(project.GetName())
    design = project.GetActiveDesign()
    design_name = text_type(design.GetName()).split(";")[-1] if design else None
    identity = {
        "project": os.path.join(text_type(project.GetPath()), project_name + ".aedt"),
        "project_name": project_name,
        "design": design_name,
        "version": str(odesktop.GetVersion()).split()[0][:6],
        "process_id": int(odesktop.GetProcessID()),
        "port": int(odesktop.GetGrpcServerPort()),
        "display": os.environ.get("DISPLAY"),
        "captured_at": datetime.utcnow().isoformat() + "Z",
    }
    path = [project_name]
    if scope == "project" or scope.startswith("definitions"):
        identity["design"] = None
        identity["designs"] = [text_type(d.GetName()).split(";")[-1] for d in project.GetDesigns()]
    elif design is None:
        raise RuntimeError("Select an AEDT design first.")
    else:
        path.append(design_name)
        identity["design_type"] = text_type(design.GetDesignType())
    if scope in ("auto", "canvas"):
        editor = design.GetActiveEditor()
        if editor is None or "GetSelections" not in dir(editor):
            if scope == "canvas":
                raise RuntimeError("The active editor does not expose a selection API.")
        else:
            names = _names(editor.GetSelections())
            hierarchy = (
                _names(editor.GetSelectionsInHierarchy())
                if "GetSelectionsInHierarchy" in dir(editor)
                else names
            ) or names
            if names or hierarchy:
                identity["target_kind"] = "selection"
                identity["selection"] = {
                    "source": "canvas",
                    "editor": str(editor.GetEditorName())
                    if "GetEditorName" in dir(editor)
                    else str(design.GetDesignType()),
                    "objects": names,
                    "hierarchy": hierarchy,
                    "path": path,
                }
                return identity
            if scope == "canvas":
                raise RuntimeError("Select objects on the canvas before copying the selection.")
        scope = "design"
    if scope in ("project", "design"):
        identity["target_kind"] = scope
        identity["selection"] = {"source": "project-tree", "path": path}
        return identity
    if scope.startswith("tree:"):
        segments = scope[len("tree:") :].split("/")
        branch = segments[0]
        owner = design
    elif scope.startswith("definitions"):
        segments = scope.split(":", 1)[-1].split("/") if ":" in scope else []
        branch = segments[0] if segments else None
        owner = project
        path.append("Definitions")
    else:
        raise ValueError("Unknown context scope: " + scope)
    if branch:
        path.append(branch)
    identity["target_kind"] = "tree-folder"
    identity["selection"] = {"source": "project-tree", "path": path}
    depth = segments.count("Item")
    if depth:
        # AEDT reports the menu category but does not pass the selected item name
        # to the script. A branch-local picker makes this choice explicit.
        node = owner.GetChildObject(branch)
        if node is None:
            raise RuntimeError("AEDT does not expose items in this branch: " + str(branch))
        choices = _descendants(node, depth, path)
        if not choices:
            raise RuntimeError("No script-addressable items were found in this branch.")
        identity["pending_tree_choices"] = choices
        identity["target_kind"] = "tree-item"
    return identity
