from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

OWNER = "ansysem-agent-bridge"
MARKER_NAME = ".ansysem-agent-bridge.json"
SKILL_ALIASES = {
    "bridge": "ansysem-agent-bridge",
    "docs": "ansysem-kb-docs",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%fZ")


def default_skill_root(target: str = "codex") -> Path:
    if target == "codex":
        codex_home = os.environ.get("CODEX_HOME")
        return (Path(codex_home).expanduser() if codex_home else Path.home() / ".codex") / "skills"
    if target == "agents":
        return Path.home() / ".agents" / "skills"
    raise ValueError(f"Unknown skill target: {target}")


def _selected(selection: str) -> tuple[str, ...]:
    if selection == "all":
        return tuple(SKILL_ALIASES.values())
    if selection not in SKILL_ALIASES:
        raise ValueError(f"Unknown skill selection: {selection}")
    return (SKILL_ALIASES[selection],)


def _source(skill_name: str) -> dict[str, bytes]:
    root = files("ansysem_agent_bridge").joinpath("skill_assets", skill_name)
    payload: dict[str, bytes] = {}
    for relative in ("SKILL.md", "agents/openai.yaml"):
        payload[relative] = root.joinpath(*relative.split("/")).read_bytes()
    return payload


def _installed(path: Path) -> dict[str, bytes] | None:
    payload: dict[str, bytes] = {}
    for relative in ("SKILL.md", "agents/openai.yaml"):
        candidate = path / relative
        if not candidate.is_file():
            return None
        payload[relative] = candidate.read_bytes()
    return payload


def _digest(payload: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(payload.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _declares_name(path: Path, expected: str) -> bool:
    try:
        lines = (path / "SKILL.md").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator and key.strip() == "name":
            return value.strip().strip("\"'") == expected
    return False


def _status_one(skill_name: str, *, target: str, root: Path | None) -> dict[str, Any]:
    destination = (root or default_skill_root(target)).expanduser().resolve() / skill_name
    expected = _source(skill_name)
    actual = _installed(destination) if destination.is_dir() else None
    marker_path = destination / MARKER_NAME
    marker = None
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker = None
    managed = bool(marker and marker.get("owner") == OWNER and marker.get("skill") == skill_name)
    if actual is None:
        status = "missing" if not destination.exists() else "conflict"
    elif _digest(actual) == _digest(expected):
        status = "ready"
    elif (
        skill_name == "ansysem-kb-docs" and not managed and _declares_name(destination, skill_name)
    ):
        status = "compatible"
    else:
        status = "stale" if managed else "conflict"
    return {
        "skill": skill_name,
        "status": status,
        "target": target,
        "path": str(destination),
        "managed": managed,
        "expected_digest": _digest(expected),
        "installed_digest": _digest(actual) if actual is not None else None,
    }


def _aggregate(items: list[dict[str, Any]]) -> str:
    states = {str(item["status"]) for item in items}
    if states <= {"ready", "compatible", "preserved"}:
        return "ready"
    if "conflict" in states:
        return "conflict"
    if "stale" in states:
        return "stale"
    if states == {"missing"}:
        return "missing"
    if states == {"removed"}:
        return "removed"
    return "partial"


def skill_status(
    selection: str = "all", *, target: str = "codex", root: Path | None = None
) -> dict[str, Any]:
    items = [_status_one(name, target=target, root=root) for name in _selected(selection)]
    if len(items) == 1:
        return items[0]
    return {"selection": selection, "target": target, "status": _aggregate(items), "skills": items}


def _install_one(
    skill_name: str,
    *,
    target: str,
    root: Path | None,
    force: bool,
    preserve_complete_unmanaged: bool,
) -> dict[str, Any]:
    state = _status_one(skill_name, target=target, root=root)
    destination = Path(state["path"])
    if state["status"] == "ready":
        return {**state, "reused": True}
    if destination.exists() and not force:
        if (
            preserve_complete_unmanaged
            and _installed(destination) is not None
            and _declares_name(destination, skill_name)
        ):
            return {
                **state,
                "status": "preserved",
                "reused": True,
                "satisfied_by_existing": True,
                "reason": "A complete unmanaged documentation Skill was preserved.",
            }
        return {
            **state,
            "status": "conflict",
            "reused": False,
            "remediation": (
                "Review the existing Skill, then rerun with --force to back it up and replace it."
            ),
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if destination.exists():
        backup_root = destination.parent / ".ansysem-agent-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / f"{skill_name}-{_stamp()}"
        shutil.move(str(destination), str(backup))

    temporary = Path(tempfile.mkdtemp(prefix=f".{skill_name}.", dir=destination.parent))
    try:
        for relative, content in _source(skill_name).items():
            output = temporary / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
        marker = {
            "schema_version": 1,
            "owner": OWNER,
            "skill": skill_name,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "digest": state["expected_digest"],
        }
        (temporary / MARKER_NAME).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        **_status_one(skill_name, target=target, root=root),
        "reused": False,
        "backup": str(backup) if backup else None,
    }


def install_skills(
    selection: str = "all",
    *,
    target: str = "codex",
    root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    items = [
        _install_one(
            name,
            target=target,
            root=root,
            force=force,
            preserve_complete_unmanaged=selection == "all" and name == "ansysem-kb-docs",
        )
        for name in _selected(selection)
    ]
    if len(items) == 1:
        return items[0]
    return {"selection": selection, "target": target, "status": _aggregate(items), "skills": items}


def uninstall_skills(
    selection: str = "all", *, target: str = "codex", root: Path | None = None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for name in _selected(selection):
        state = _status_one(name, target=target, root=root)
        destination = Path(state["path"])
        if not destination.exists():
            items.append({**state, "removed": False})
            continue
        if not state["managed"]:
            items.append(
                {
                    **state,
                    "status": "preserved",
                    "removed": False,
                    "reason": "Unmanaged Skill content was preserved.",
                }
            )
            continue
        backup_root = destination.parent / ".ansysem-agent-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / f"{name}-removed-{_stamp()}"
        shutil.move(str(destination), str(backup))
        items.append({**state, "status": "removed", "removed": True, "backup": str(backup)})
    if len(items) == 1:
        return items[0]
    return {"selection": selection, "target": target, "status": _aggregate(items), "skills": items}
