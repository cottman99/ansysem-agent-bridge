from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_directory(path: str | Path) -> None:
    """Best-effort fsync for directory-entry durability on POSIX hosts."""

    if os.name != "posix":
        return
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _bundle_files(project: Path) -> list[tuple[str, Path]]:
    aedb = project.with_suffix(".aedb")
    files = [(project.name, project)]
    files.extend(
        (f"{aedb.name}/{path.relative_to(aedb).as_posix()}", path)
        for path in sorted(item for item in aedb.rglob("*") if item.is_file())
    )
    return files


def _require_complete_bundle(project: Path) -> None:
    if project.suffix.casefold() != ".aedt":
        raise ValueError(f"Expected an .aedt project: {project}")
    if not project.is_file():
        raise ValueError(f"Project file is missing: {project}")
    aedb = project.with_suffix(".aedb")
    if not aedb.is_dir():
        raise ValueError(f"EDB directory is missing: {aedb}")
    if not (aedb / "edb.def").is_file():
        raise ValueError(f"EDB definition is missing: {aedb / 'edb.def'}")


def bundle_content_summary(project: str | Path) -> dict[str, str]:
    """Hash every file once and return compact bundle plus anchor digests."""

    path = Path(project).expanduser().resolve()
    _require_complete_bundle(path)
    digest = hashlib.sha256()
    aedt_sha256 = ""
    edb_definition_sha256 = ""
    for relative, item in _bundle_files(path):
        item_sha256 = sha256_file(item)
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(bytes.fromhex(item_sha256))
        if item == path:
            aedt_sha256 = item_sha256
        elif item == path.with_suffix(".aedb") / "edb.def":
            edb_definition_sha256 = item_sha256
    return {
        "bundle_sha256": digest.hexdigest(),
        "aedt_sha256": aedt_sha256,
        "edb_definition_sha256": edb_definition_sha256,
    }


def bundle_content_sha256(project: str | Path) -> str:
    """Return one compact digest for every file in an AEDT/EDB bundle."""

    return bundle_content_summary(project)["bundle_sha256"]


def bundle_state_revision(project: str | Path) -> str:
    """Return a cheap continuity token from paths, sizes, and timestamps.

    Mutable candidate workspaces use this token between edits. A promoted output
    still receives a full content digest, so checkpoint speed does not weaken the
    final delivery gate.
    """

    path = Path(project).expanduser().resolve()
    _require_complete_bundle(path)
    payload = [
        [relative, item.stat().st_size, item.stat().st_mtime_ns]
        for relative, item in _bundle_files(path)
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _copy_file_best_effort(
    source: str | os.PathLike[str], destination: str | os.PathLike[str]
) -> tuple[Path, bool]:
    source_path = Path(source)
    destination_path = Path(destination)
    if sys.platform.startswith("linux"):
        try:
            import fcntl

            with (
                source_path.open("rb") as source_stream,
                destination_path.open("wb") as destination_stream,
            ):
                # Linux FICLONE. Unsupported filesystems fail cleanly and fall back.
                fcntl.ioctl(destination_stream.fileno(), 0x40049409, source_stream.fileno())
            shutil.copystat(source_path, destination_path)
            return destination_path, True
        except OSError:
            destination_path.unlink(missing_ok=True)
    shutil.copy2(source_path, destination_path)
    return destination_path, False


def copy_project_bundle(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Copy a complete bundle, using copy-on-write when the host supports it."""

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    _require_complete_bundle(source_path)
    if destination_path.exists() or destination_path.with_suffix(".aedb").exists():
        raise ValueError("Destination project bundle already exists.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"reflink": 0, "copy": 0, "logical_bytes": 0}

    def copy_file(src: str, dst: str) -> str:
        copied, reflinked = _copy_file_best_effort(src, dst)
        counts["reflink" if reflinked else "copy"] += 1
        counts["logical_bytes"] += Path(src).stat().st_size
        return str(copied)

    copy_file(str(source_path), str(destination_path))
    shutil.copytree(
        source_path.with_suffix(".aedb"),
        destination_path.with_suffix(".aedb"),
        copy_function=copy_file,
    )
    if counts["reflink"] and not counts["copy"]:
        strategy = "reflink"
    elif counts["reflink"]:
        strategy = "mixed"
    else:
        strategy = "copy"
    return {
        "strategy": strategy,
        "file_count": counts["reflink"] + counts["copy"],
        "logical_bytes": counts["logical_bytes"],
    }


def commit_staged_project_bundle(
    staged_project: str | Path,
    output_project: str | Path,
    *,
    extra_moves: list[tuple[str | Path, str | Path]] | None = None,
) -> None:
    """Commit a staged bundle with the AEDT file as the final visible marker.

    A project bundle spans multiple filesystem entries and therefore cannot be
    renamed atomically as one object. Move the EDB and any result artifacts
    first, move the `.aedt` file last, and restore already-moved entries if a
    later rename fails.
    """

    staged = Path(staged_project)
    output = Path(output_project)
    moves = [(staged.with_suffix(".aedb"), output.with_suffix(".aedb"))]
    moves.extend((Path(source), Path(destination)) for source, destination in extra_moves or [])
    moves.append((staged, output))
    for source, destination in moves:
        if not source.exists():
            raise FileNotFoundError(f"staged commit source is missing: {source}")
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite commit destination: {destination}")

    moved: list[tuple[Path, Path]] = []
    try:
        for source, destination in moves:
            os.replace(source, destination)
            moved.append((source, destination))
        sync_directory(output.parent)
    except Exception as original_error:
        rollback_failures = []
        for source, destination in reversed(moved):
            try:
                os.replace(destination, source)
            except OSError as exc:
                rollback_failures.append(f"{destination}: {exc}")
        if rollback_failures:
            raise RuntimeError(
                "bundle commit failed and rollback was incomplete: " + "; ".join(rollback_failures)
            ) from original_error
        raise


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
