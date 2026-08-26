from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_project_bundle(project: str | Path, *, redact_paths: bool = False) -> dict[str, Any]:
    path = Path(project).expanduser().resolve()
    if path.suffix.casefold() != ".aedt":
        raise ValueError(f"Expected an .aedt project: {path}")
    aedb = path.with_suffix(".aedb")
    edb_def = aedb / "edb.def"
    project_exists = path.is_file()
    aedb_exists = aedb.is_dir()
    payload = {
        "schema_version": 1,
        "project": path.name if redact_paths else str(path),
        "project_name": path.stem,
        "project_exists": project_exists,
        "project_size": path.stat().st_size if project_exists else None,
        "project_sha256": sha256_file(path) if project_exists else None,
        "aedb": aedb.name if redact_paths else str(aedb),
        "aedb_exists": aedb_exists,
        "edb_definition_exists": edb_def.is_file(),
        "bundle_complete": project_exists and aedb_exists and edb_def.is_file(),
    }
    if not project_exists:
        payload["reason"] = "project_missing"
    elif not aedb_exists:
        payload["reason"] = "aedb_missing"
    elif not edb_def.is_file():
        payload["reason"] = "edb_definition_missing"
    else:
        payload["reason"] = None
    return payload
