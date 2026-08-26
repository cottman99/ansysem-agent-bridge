from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path

from .config import load_config
from .models import Installation

ROOT_PATTERN = re.compile(r"^(?:ANSYSEM_ROOT|AWP_ROOT)(\d+)$", re.IGNORECASE)


def _version_from_key(key: str) -> str | None:
    match = ROOT_PATTERN.match(key)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        return f"20{digits[:2]}.{int(digits[2])}"
    return digits


def _executable(root: Path) -> Path | None:
    candidates = (
        root / "Win64" / "ansysedt.exe",
        root / "Linux64" / "ansysedt",
        root / "ansysedt.exe",
        root / "ansysedt",
    )
    return next((item for item in candidates if item.is_file()), None)


def _instance_id(root: Path, version: str | None) -> str:
    digest = hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()[:8]
    version_part = re.sub(r"[^0-9a-z]+", "-", (version or "unknown").casefold()).strip("-")
    return f"aedt-{version_part}-{digest}"


def _from_environment(environ: dict[str, str]) -> Iterable[Installation]:
    for key, value in sorted(environ.items()):
        if not ROOT_PATTERN.match(key) or not value:
            continue
        root = Path(value).expanduser().resolve()
        executable = _executable(root)
        version = _version_from_key(key)
        yield Installation(
            instance_id=_instance_id(root, version),
            root=str(root),
            version=version,
            executable=str(executable) if executable else None,
            source=f"environment:{key}",
            docs_root=environ.get("ANSYSEM_DOC_ROOT"),
        )


def _from_config() -> Iterable[Installation]:
    for item in load_config().get("instances", []):
        if not isinstance(item, dict) or not item.get("root") or not item.get("instance_id"):
            continue
        root = Path(str(item["root"])).expanduser().resolve()
        executable = (
            Path(str(item["executable"])).expanduser()
            if item.get("executable")
            else _executable(root)
        )
        yield Installation(
            instance_id=str(item["instance_id"]),
            root=str(root),
            version=str(item["version"]) if item.get("version") else None,
            executable=str(executable) if executable and executable.is_file() else None,
            source="config",
            docs_root=str(item["docs_root"]) if item.get("docs_root") else None,
        )


def discover_installations(environ: dict[str, str] | None = None) -> list[Installation]:
    records: dict[str, Installation] = {}
    for item in [*_from_config(), *_from_environment(dict(environ or os.environ))]:
        key = str(Path(item.root)).casefold()
        existing = records.get(key)
        if existing is None or item.source == "config":
            records[key] = item
    return sorted(records.values(), key=lambda item: (item.version or "", item.instance_id))


def select_installation(instance_id: str | None = None) -> Installation:
    records = discover_installations()
    config = load_config()
    selected_id = instance_id or config.get("default_instance")
    if selected_id:
        matches = [item for item in records if item.instance_id == selected_id]
        if len(matches) == 1:
            return matches[0]
        raise ValueError(f"Configured AEDT instance is unavailable: {selected_id}")
    if len(records) == 1:
        return records[0]
    if not records:
        raise ValueError(
            "No AEDT installations discovered; run ansysem-agent setup with an explicit root."
        )
    raise ValueError("Multiple AEDT installations discovered; pass --instance.")
