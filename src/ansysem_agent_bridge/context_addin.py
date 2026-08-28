"""Install the lightweight AEDT Automation-tab context actions."""

from __future__ import annotations

import shutil
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


def _default_personal_lib() -> Path:
    candidates = [
        Path.home() / "Ansoft" / "PersonalLib",
        Path.home() / "Documents" / "Ansoft" / "PersonalLib",
    ]
    for path in candidates:
        if path.is_dir():
            return path.resolve()
    path = candidates[0]
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


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
        else _default_personal_lib()
    )
    if desktop and personal_lib and root != _live_personal_lib(desktop):
        raise ValueError(
            f"Explicit PersonalLib {root} does not match live AEDT PersonalLib "
            f"{_live_personal_lib(desktop)}"
        )
    _remove_owned_buttons(root, panels=(LEGACY_PANEL, LEGACY_SHARED_PANEL))
    installed = []
    for name, asset in TOOLS.items():
        ok = add_script_to_menu(
            name,
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
    if desktop:
        desktop.odesktop.RefreshToolkitUI()
    return {
        "status": "ready",
        "personal_lib": str(root),
        "installed": installed,
        "refresh_required": desktop is None,
        "live_session": bool(desktop),
    }


def status(personal_lib: str | Path | None = None) -> dict[str, Any]:
    root = Path(personal_lib).expanduser().resolve() if personal_lib else _default_personal_lib()
    project_root = root / "Toolkits" / "Project"
    tab_config = project_root / "TabConfig.xml"
    text = tab_config.read_text(encoding="utf-8") if tab_config.is_file() else ""
    actions = {
        name: {
            "directory_present": (project_root / name).is_dir(),
            "menu_registered": name in text,
        }
        for name in TOOLS
    }
    ready = all(all(checks.values()) for checks in actions.values())
    return {
        "status": "ready" if ready else "not_installed",
        "personal_lib": str(root),
        "tab_config_present": tab_config.is_file(),
        "actions": actions,
    }


def refresh(*, version: str, port: int, process_id: int) -> dict[str, Any]:
    desktop = _connect_desktop(version=version, port=port, process_id=process_id)
    desktop.odesktop.RefreshToolkitUI()
    return {
        "status": "ready",
        "version": version,
        "port": port,
        "process_id": process_id,
        "personal_lib": str(_live_personal_lib(desktop)),
        "refreshed": True,
    }


def uninstall(personal_lib: str | Path | None = None) -> dict[str, Any]:
    from ansys.aedt.core.extensions.customize_automation_tab import tab_map

    root = Path(personal_lib).expanduser().resolve() if personal_lib else _default_personal_lib()
    project_root = root / "Toolkits" / tab_map("Project")
    removed = []
    _remove_owned_buttons(root, panels=(PANEL, LEGACY_PANEL, LEGACY_SHARED_PANEL))
    for name in TOOLS:
        owned = project_root / name
        if owned.is_dir():
            shutil.rmtree(owned)
            removed.append(name)
    return {"status": "removed", "personal_lib": str(root), "removed": removed}


def _remove_owned_buttons(root: Path, *, panels: tuple[str, ...]) -> None:
    tab_config = root / "Toolkits" / "Project" / "TabConfig.xml"
    if not tab_config.is_file():
        return
    from ansys.aedt.core.extensions.tabconfig_parser import TabConfigParser

    parser = TabConfigParser(tab_config)
    for panel in panels:
        for name in TOOLS:
            parser.remove_button(panel, name)
    if LEGACY_PANEL in panels:
        parser.remove_panel(LEGACY_PANEL)
    parser.save(tab_config)
