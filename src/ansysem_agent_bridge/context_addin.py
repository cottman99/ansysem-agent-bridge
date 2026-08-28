"""Install the lightweight AEDT Automation-tab context actions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

PANEL = "Panel_EDA_Agent"
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


def _assets_root() -> Path:
    return Path(__file__).parent / "aedt_addin_assets"


def install(personal_lib: str | Path | None = None) -> dict[str, Any]:
    try:
        import eda_bridge_runtime  # noqa: F401
        from ansys.aedt.core.extensions.customize_automation_tab import add_script_to_menu
    except ImportError as exc:
        raise RuntimeError(
            "PyAEDT and eda-bridge-runtime are required for the Context Add-in"
        ) from exc
    root = Path(personal_lib).expanduser().resolve() if personal_lib else _default_personal_lib()
    installed = []
    for name, asset in TOOLS.items():
        ok = add_script_to_menu(
            name,
            script_file=str(_assets_root() / asset),
            product="Project",
            copy_to_personal_lib=True,
            panel=PANEL,
            personal_lib=str(root),
        )
        if not ok:
            raise RuntimeError(f"PyAEDT did not install Context Add-in action: {name}")
        installed.append(name)
    return {
        "status": "ready",
        "personal_lib": str(root),
        "installed": installed,
        "refresh_required": True,
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


def uninstall(personal_lib: str | Path | None = None) -> dict[str, Any]:
    from ansys.aedt.core.extensions.customize_automation_tab import tab_map
    from ansys.aedt.core.extensions.tabconfig_parser import TabConfigParser

    root = Path(personal_lib).expanduser().resolve() if personal_lib else _default_personal_lib()
    project_root = root / "Toolkits" / tab_map("Project")
    tab_config = project_root / "TabConfig.xml"
    removed = []
    if tab_config.is_file():
        parser = TabConfigParser(tab_config)
        for name in TOOLS:
            parser.remove_button(PANEL, name)
        parser.save(tab_config)
    for name in TOOLS:
        owned = project_root / name
        if owned.is_dir():
            shutil.rmtree(owned)
            removed.append(name)
    return {"status": "removed", "personal_lib": str(root), "removed": removed}
