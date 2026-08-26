from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import load_config


def _resolve_executable(value: str | None) -> Path | None:
    return Path(os.path.abspath(Path(value).expanduser())) if value else None


def get_profile(profile_id: str | None = None) -> dict[str, Any]:
    config = load_config()
    selected = profile_id or config.get("default_profile")
    if not selected:
        raise ValueError("No runtime profile selected or configured as default.")
    matches = [item for item in config["profiles"] if item.get("profile_id") == selected]
    if len(matches) != 1:
        raise ValueError(f"Unknown runtime profile: {selected}")
    return matches[0]


def profile_status(profile_id: str | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id)
    expected_python = _resolve_executable(profile.get("python_executable"))
    active_python = Path(os.path.abspath(sys.executable))
    python_matches = expected_python == active_python
    python_exists = bool(
        expected_python
        and expected_python.is_file()
        and (os.name == "nt" or os.access(expected_python, os.X_OK))
    )
    module_paths = [Path(item).expanduser().resolve() for item in profile.get("python_paths", [])]
    missing_module_paths = [str(path) for path in module_paths if not path.is_dir()]
    checks = {
        "python_exists": python_exists,
        "python_paths_exist": not missing_module_paths,
        "display_configured": bool(profile.get("display")) or os.name == "nt",
    }
    return {
        "status": "ready" if all(checks.values()) else "blocked",
        "profile_id": profile["profile_id"],
        "checks": checks,
        "active_python_matches": python_matches,
        "active_python": str(active_python),
        "expected_python": str(expected_python) if expected_python else None,
        "display": profile.get("display"),
        "missing_python_paths": missing_module_paths,
    }


def apply_profile(profile_id: str | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id)
    status = profile_status(profile["profile_id"])
    if status["status"] != "ready":
        raise RuntimeError(
            f"Runtime profile {profile['profile_id']} is not ready: {status['checks']}"
        )
    if not status["active_python_matches"]:
        raise RuntimeError(
            f"Runtime profile {profile['profile_id']} requires Python "
            f"{status['expected_python']}; use the controlled profile launcher."
        )
    if profile.get("display"):
        os.environ["DISPLAY"] = str(profile["display"])
    for key, value in profile.get("environment", {}).items():
        os.environ[str(key)] = str(value)
    for key, value in profile.get("prepend_environment", {}).items():
        key = str(key)
        prefix = str(value)
        existing = os.environ.get(key)
        if existing != prefix and not (existing or "").startswith(prefix + os.pathsep):
            os.environ[key] = prefix + (os.pathsep + existing if existing else "")
    python_paths = [
        str(Path(item).expanduser().resolve()) for item in profile.get("python_paths", [])
    ]
    for item in reversed(python_paths):
        if item not in sys.path:
            sys.path.insert(0, item)
    if python_paths:
        existing = os.environ.get("PYTHONPATH")
        existing_items = existing.split(os.pathsep) if existing else []
        os.environ["PYTHONPATH"] = os.pathsep.join(
            python_paths + [item for item in existing_items if item not in python_paths]
        )
    return {
        **status,
        "status": "ready",
        "applied_environment_keys": sorted(profile.get("environment", {})),
        "prepended_environment_keys": sorted(profile.get("prepend_environment", {})),
        "python_path_count": len(python_paths),
    }


def _profile_fingerprint(profile: dict[str, Any]) -> str:
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ensure_profile_process(profile_id: str | None, argv: list[str]) -> dict[str, Any]:
    profile = get_profile(profile_id)
    status = profile_status(profile["profile_id"])
    if status["status"] != "ready":
        raise RuntimeError(
            f"Runtime profile {profile['profile_id']} is not launchable: {status['checks']}"
        )
    fingerprint = _profile_fingerprint(profile)
    marker = os.environ.get("ANSYSEM_ACTIVE_PROFILE")
    if marker == fingerprint and status["active_python_matches"]:
        return apply_profile(profile["profile_id"])

    expected_python = _resolve_executable(profile.get("python_executable"))
    executable = expected_python or Path(sys.executable).resolve()
    environment = os.environ.copy()
    if profile.get("display"):
        environment["DISPLAY"] = str(profile["display"])
    for key, value in profile.get("environment", {}).items():
        environment[str(key)] = str(value)
    for key, value in profile.get("prepend_environment", {}).items():
        key = str(key)
        prefix = str(value)
        existing = environment.get(key)
        if existing != prefix and not (existing or "").startswith(prefix + os.pathsep):
            environment[key] = prefix + (os.pathsep + existing if existing else "")
    python_paths = [
        str(Path(item).expanduser().resolve()) for item in profile.get("python_paths", [])
    ]
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        python_paths + ([existing_pythonpath] if existing_pythonpath else [])
    )
    environment["ANSYSEM_ACTIVE_PROFILE"] = fingerprint
    os.execve(
        str(executable),
        [str(executable), "-m", "ansysem_agent_bridge.cli", *argv],
        environment,
    )
    raise RuntimeError("Controlled runtime profile relaunch returned unexpectedly.")


def parse_assignment(value: str) -> tuple[str, str]:
    key, separator, assigned = value.partition("=")
    if not separator or not key or "\x00" in value:
        raise ValueError(f"Expected KEY=VALUE assignment: {value}")
    return key, assigned
