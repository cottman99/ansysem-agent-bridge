"""Install and reconcile AEDT context menus and Automation-tab actions."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PANEL = "Panel_PyAEDT_Installer"
LEGACY_PANEL = "Panel_EDA_Agent"
LEGACY_SHARED_PANEL = "Panel_PyAEDT_Extensions"
TOOLS = {
    "Use Current Design with Agent": "use_current_design.py",
    "Copy Agent Context": "copy_agent_context.py",
    "Agent Connection Status": "agent_connection_status.py",
}
MANIFEST = ".ansysem-agent-context.json"
TOOL_DIRECTORIES = {name: name.replace(" ", "") for name in TOOLS}
OWNED_DIRECTORIES = (*TOOL_DIRECTORIES.values(), *TOOLS, "EDA Agent Menus")


def _configured_personal_lib(profile_id: str | None = None) -> Path:
    from .config import load_config

    config = load_config()
    profile_id = profile_id or config.get("default_profile")
    roots = {
        Path(record["personal_lib"]).expanduser().resolve()
        for record in config.get("context_addins", [])
        if not profile_id or record.get("profile") in (None, profile_id)
    }
    if len(roots) == 1:
        return roots.pop()
    raise ValueError(
        "Select the actual AEDT PersonalLib with --personal-lib, or provide "
        "--version, --port and --process-id from the exact live session."
    )


def _signature() -> dict[str, Any]:
    from . import __version__

    sources = [
        Path(__file__),
        Path(__file__).with_name("aedt_context_tool.py"),
        Path(__file__).with_name("clipboard_owner.py"),
        Path(__file__).with_name("profiles.py"),
        Path(__file__).with_name("context_menu.py"),
    ]
    sources.extend(sorted(_assets_root().glob("*.py")))
    return {
        "bridge_version": __version__,
        "runtime_version": importlib.metadata.version("eda-bridge-runtime"),
        "python": os.path.abspath(sys.executable),
        "source_sha256": hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest(),
    }


def _backup(root: Path) -> Path:
    from .config import agent_home

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    destination = agent_home(ensure=True) / "addin-backups" / stamp
    destination.mkdir(parents=True)
    project = root / "Toolkits" / "Project"
    for name in ("TabConfig.xml", MANIFEST, *OWNED_DIRECTORIES):
        path = project / name
        if path.is_dir():
            shutil.copytree(path, destination / name)
        elif path.is_file():
            shutil.copy2(path, destination / name)
    return destination


def _remember(root: Path, profile_id: str | None) -> None:
    from .config import load_config, save_config

    config = load_config()
    records = [r for r in config.get("context_addins", []) if r["personal_lib"] != str(root)]
    records.append(
        {"personal_lib": str(root), "profile": profile_id or config.get("default_profile")}
    )
    config["context_addins"] = records
    save_config(config)


def _connect_desktop(*, version: str, port: int, process_id: int):
    import ansys.aedt.core

    return ansys.aedt.core.Desktop(
        new_desktop=False,
        version=version,
        port=port,
        aedt_process_id=process_id,
        close_on_exit=False,
    )


def _live_personal_lib(desktop: Any) -> Path:
    value = getattr(desktop, "personallib", None)
    if not value:
        raise RuntimeError("The live AEDT session did not report its PersonalLib path")
    return Path(value).expanduser().resolve()


def _assets_root() -> Path:
    return Path(__file__).parent / "aedt_addin_assets"


def _pyaedt_icon() -> Path:
    import ansys.aedt.core.extensions

    icon = Path(ansys.aedt.core.extensions.__file__).parent / "images" / "large" / "pyansys.png"
    if not icon.is_file():
        raise RuntimeError(f"PyAEDT Automation icon is missing: {icon}")
    return icon


def install(
    personal_lib: str | Path | None = None,
    *,
    version: str | None = None,
    port: int | None = None,
    process_id: int | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    live_args = (version, port, process_id)
    if any(value is not None for value in live_args) and not all(
        value is not None for value in live_args
    ):
        raise ValueError("version, port, and process_id must be provided together")
    try:
        import eda_bridge_runtime  # noqa: F401
        from ansys.aedt.core.extensions.customize_automation_tab import add_script_to_menu
    except ImportError as exc:
        raise RuntimeError(
            "PyAEDT and eda-bridge-runtime are required for the Context Add-in"
        ) from exc
    desktop = None
    if all(value is not None for value in live_args):
        desktop = _connect_desktop(version=str(version), port=int(port), process_id=int(process_id))
    root = (
        Path(personal_lib).expanduser().resolve()
        if personal_lib
        else _live_personal_lib(desktop)
        if desktop
        else _configured_personal_lib(profile_id)
    )
    if desktop and personal_lib and root != _live_personal_lib(desktop):
        raise ValueError(
            f"Explicit PersonalLib {root} does not match live AEDT PersonalLib "
            f"{_live_personal_lib(desktop)}"
        )
    backup = _backup(root)
    project = root / "Toolkits" / "Project"
    previous_manifest = {}
    with suppress(OSError, ValueError):
        previous_manifest = json.loads((project / MANIFEST).read_text(encoding="utf-8"))
    _remove_owned_buttons(root, panels=(PANEL, LEGACY_PANEL, LEGACY_SHARED_PANEL))
    installed = []
    for name, asset in TOOLS.items():
        ok = add_script_to_menu(
            TOOL_DIRECTORIES[name],
            script_file=str(_assets_root() / asset),
            icon_file=str(_pyaedt_icon()),
            product="Project",
            copy_to_personal_lib=True,
            panel=PANEL,
            personal_lib=str(root),
            odesktop=desktop.odesktop if desktop else None,
        )
        if not ok:
            raise RuntimeError(f"PyAEDT did not install Context Add-in action: {name}")
        installed.append(name)
    # Linux AEDT treats spaces in toolkit script paths as argument separators:
    # those actions disappear from the ribbon and do not launch from Toolkit.
    # Keep readable labels separate from the stable, whitespace-free paths.
    tab_config = project / "TabConfig.xml"
    tree = ET.parse(tab_config)
    for button in tree.iter("button"):
        for label, directory in TOOL_DIRECTORIES.items():
            if button.get("label") == directory:
                button.set("label", label)
    tree.write(tab_config, encoding="utf-8", xml_declaration=True)
    shutil.copy2(
        _assets_root() / "native_selection.py",
        project / TOOL_DIRECTORIES["Copy Agent Context"] / "Lib" / "native_selection.py",
    )
    from . import context_menu

    menu = context_menu.install(
        root, desktop=desktop, registration=previous_manifest.get("right_click"), backup=backup
    )
    for legacy in (*TOOLS, "EDA Agent Menus"):
        old = project / legacy
        if old.is_dir():
            shutil.rmtree(old)
    if desktop:
        desktop.odesktop.RefreshToolkitUI()
    checksums = {
        str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
        for name in OWNED_DIRECTORIES
        for path in sorted((project / name).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    manifest = {"schema_version": 1, **_signature(), "files": checksums, "right_click": menu}
    (project / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _remember(root, profile_id)
    verified = status(root)
    if verified["automation_status"] != "ready":
        raise RuntimeError(
            f"Context Add-in registration failed verification: {verified['actions']}"
        )
    return {
        "status": verified["status"],
        "personal_lib": str(root),
        "installed": installed,
        "refresh_required": desktop is None,
        "live_session": bool(desktop),
        "backup": str(backup),
        "verification": verified,
        "right_click": verified["right_click"],
    }


def status(personal_lib: str | Path | None = None) -> dict[str, Any]:
    if personal_lib is None:
        try:
            personal_lib = _configured_personal_lib()
        except ValueError:
            return {"status": "not_configured", "personal_lib": None, "actions": {}}
    root = Path(personal_lib).expanduser().resolve()
    project_root = root / "Toolkits" / "Project"
    tab_config = project_root / "TabConfig.xml"
    buttons: list[ET.Element] = []
    with suppress(OSError, ET.ParseError):
        buttons = list(ET.parse(tab_config).iter("button"))
    actions = {
        name: {
            "directory_present": (project_root / TOOL_DIRECTORIES[name]).is_dir(),
            "menu_registered": sum(node.get("label") == name for node in buttons) == 1
            and any(
                node.get("label") == name
                and node.get("script") == f"{TOOL_DIRECTORIES[name]}/run_pyaedt_toolkit_script"
                for node in buttons
            ),
            "script_present": (project_root / TOOL_DIRECTORIES[name] / "Lib" / asset).is_file(),
            "launcher_present": (
                project_root / TOOL_DIRECTORIES[name] / "run_pyaedt_toolkit_script.py"
            ).is_file(),
        }
        for name, asset in TOOLS.items()
    }
    manifest = {}
    with suppress(OSError, ValueError):
        manifest = json.loads((project_root / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        manifest = {}
    current = bool(manifest) and all(manifest.get(k) == v for k, v in _signature().items())
    intact = _files_intact(project_root, manifest.get("files"))
    ready = all(all(checks.values()) for checks in actions.values()) and current and intact
    from . import context_menu

    menu = context_menu.status(manifest.get("right_click"))
    automation_status = "ready" if ready else "repair_required" if manifest else "not_installed"
    return {
        "status": automation_status
        if not ready or menu["status"] == "ready"
        else "attention_required",
        "automation_status": automation_status,
        "verification_scope": "installation_files",
        "ui_visibility": "not_checked",
        "right_click": menu,
        "personal_lib": str(root),
        "tab_config_present": tab_config.is_file(),
        "actions": actions,
        "runtime_current": current,
        "files_intact": intact,
    }


def _files_intact(project: Path, files: Any) -> bool:
    if not isinstance(files, dict) or not files:
        return False
    for name, digest in files.items():
        if not isinstance(name, str) or not name:
            return False
        relative = Path(name)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or relative.parts[0] not in OWNED_DIRECTORIES
        ):
            return False
        path = project / relative
        try:
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return False
        except OSError:
            return False
    return True


def configured_status(profile_id: str | None = None) -> dict[str, Any]:
    from .config import load_config

    records = [
        r
        for r in load_config().get("context_addins", [])
        if not profile_id or r.get("profile") in (None, profile_id)
    ]
    installations = [status(r["personal_lib"]) for r in records]
    return {
        "status": "ready"
        if installations and all(i["status"] == "ready" for i in installations)
        else "attention_required",
        "installations": installations,
        "repair_command": (
            "ansysem-agent --profile <profile> doctor --repair --personal-lib <PersonalLib>"
        ),
    }


def reconcile_configured(profile_id: str | None = None) -> dict[str, Any]:
    """Refresh only previously configured add-ins after a package/environment upgrade."""
    from .config import load_config

    results = []
    for record in load_config().get("context_addins", []):
        if profile_id and record.get("profile") not in (None, profile_id):
            continue
        observed = status(record["personal_lib"])
        if (
            observed.get("automation_status") != "ready"
            or observed.get("right_click", {}).get("status") == "repair_required"
        ):
            observed = install(record["personal_lib"], profile_id=record.get("profile"))
        results.append(observed)
    return {
        "status": "ready"
        if results and all(r["status"] == "ready" for r in results)
        else "attention_required"
        if results
        else "not_configured",
        "installations": results,
    }


def refresh(*, version: str, port: int, process_id: int) -> dict[str, Any]:
    desktop = _connect_desktop(version=version, port=port, process_id=process_id)
    desktop.odesktop.RefreshToolkitUI()
    root = _live_personal_lib(desktop)
    manifest_path = root / "Toolkits" / "Project" / MANIFEST
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        menu = manifest.get("right_click", {})
        if menu.get("name"):
            desktop.odesktop.SetCustomMenuSet("Default")
            desktop.odesktop.SetCustomMenuSet(menu["name"])
            if str(desktop.odesktop.GetCustomMenuSet()) != menu["name"]:
                raise RuntimeError("AEDT did not reload the Agent context menu")
            menu["activation_required"] = False
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "status": "ready",
        "version": version,
        "port": port,
        "process_id": process_id,
        "personal_lib": str(root),
        "refreshed": True,
    }


def uninstall(personal_lib: str | Path | None = None) -> dict[str, Any]:
    from ansys.aedt.core.extensions.customize_automation_tab import tab_map

    from .config import load_config, save_config

    root = Path(personal_lib).expanduser().resolve() if personal_lib else _configured_personal_lib()
    backup = _backup(root)
    project_root = root / "Toolkits" / tab_map("Project")
    from . import context_menu

    with suppress(FileNotFoundError):
        manifest = json.loads((project_root / MANIFEST).read_text(encoding="utf-8"))
        context_menu.uninstall(manifest.get("right_click"), backup=backup)
    removed = []
    _remove_owned_buttons(root, panels=(PANEL, LEGACY_PANEL, LEGACY_SHARED_PANEL))
    for name in OWNED_DIRECTORIES:
        owned = project_root / name
        if owned.is_dir():
            shutil.rmtree(owned)
            removed.append(name)
    (project_root / MANIFEST).unlink(missing_ok=True)
    config = load_config()
    config["context_addins"] = [
        record
        for record in config.get("context_addins", [])
        if Path(record["personal_lib"]).expanduser().resolve() != root
    ]
    save_config(config)
    return {
        "status": "removed",
        "personal_lib": str(root),
        "removed": removed,
        "backup": str(backup),
    }


def _remove_owned_buttons(root: Path, *, panels: tuple[str, ...]) -> None:
    tab_config = root / "Toolkits" / "Project" / "TabConfig.xml"
    if not tab_config.is_file():
        return
    from ansys.aedt.core.extensions.tabconfig_parser import TabConfigParser

    parser = TabConfigParser(tab_config)
    for panel in panels:
        for name in (*TOOLS, *TOOL_DIRECTORIES.values()):
            parser.remove_button(panel, name)
    parser.save(tab_config)
