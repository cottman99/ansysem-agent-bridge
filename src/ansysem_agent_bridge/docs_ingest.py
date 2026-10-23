"""Private, version-scoped ingestion of official documentation and SDK sources."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from eda_bridge_runtime.build_lock import build_lock

from .config import agent_home

_EXTENSIONS = {".html", ".htm", ".md", ".rst", ".py", ".pyi"}


def discover_docs_root(installation_root: str | Path) -> Path | None:
    root = Path(installation_root)
    for candidate in (
        root / "Help",
        root / "help",
        root / "doc",
        root / "common" / "help",
        root.parent / "common" / "help",
    ):
        if candidate.is_dir() and source_files(candidate):
            return candidate
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        candidate = Path(distribution("pyaedt").locate_file("ansys/aedt/core"))
        if candidate.is_dir():
            return candidate
    except PackageNotFoundError:
        pass
    return None


def source_files(root: Path):
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in _EXTENSIONS
        and "__pycache__" not in path.parts
        and ".git" not in path.parts
    )


def source_fingerprint(paths):
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(f"{path}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def clean_source(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        import html2text
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        body = (
            soup.select_one('main, article, [role="main"], #mc-main-content') or soup.body or soup
        )
        for node in list(body.select("script, style, nav, header, footer")):
            node.decompose()
        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.ignore_images = True
        return converter.handle(str(body)), "official_document"
    if suffix in {".py", ".pyi"}:
        tree = ast.parse(raw)
        parts = []
        if ast.get_docstring(tree):
            parts.append(ast.get_docstring(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                signature = (
                    f"class {node.name}"
                    if isinstance(node, ast.ClassDef)
                    else f"def {node.name}({ast.unparse(node.args)})"
                )
                parts.append(
                    f"## {signature}\n\nSource line: {node.lineno}\n\n"
                    f"{ast.get_docstring(node) or ''}"
                )
        return "\n\n".join(parts), "sdk_source"
    return raw, "official_document"


def ensure_docs(
    root: str | Path, *, version: str | None = None, batch_size: int = 200, background: bool = True
):
    source = Path(root).expanduser().resolve()
    if not source.is_dir():
        return {"status": "source_missing", "source_root": str(source), "execution_available": True}
    paths = source_files(source)
    if not paths:
        return {
            "status": "source_missing",
            "source_root": str(source),
            "reason": "No supported HTML, Markdown, RST or SDK source files",
            "execution_available": True,
        }
    fingerprint = source_fingerprint(paths)
    # Preserve established corpora and MD-only roots. Mixed raw sources are
    # derived into a private generation; their originals remain untouched.
    if (source / "markdown").is_dir() or all(path.suffix.lower() == ".md" for path in paths):
        return {
            "status": "ready",
            "root": str(source),
            "source_root": str(source),
            "version": version,
            "origin": "existing_markdown",
            "fingerprint": fingerprint,
            "execution_available": True,
        }
    partition = hashlib.sha256(f"{source}\0{version or 'unknown'}".encode()).hexdigest()[:24]
    cache = agent_home(ensure=True) / "docs" / partition
    pointer = cache / "current.json"
    with build_lock(cache / ".build.lock"):
        previous = json.loads(pointer.read_text(encoding="utf-8")) if pointer.is_file() else {}
        continuing = (
            previous.get("fingerprint") == fingerprint and Path(previous.get("root", "")).is_dir()
        )
        if continuing and previous.get("build_complete", True):
            return previous
        generation = (
            Path(previous["root"]) if continuing else cache / "generations" / uuid.uuid4().hex
        )
        markdown = generation / "markdown"
        indexes = generation / "retrieval" / "indexes"
        markdown.mkdir(parents=True, exist_ok=True)
        indexes.mkdir(parents=True, exist_ok=True)
        records = json.loads((indexes / "document_index.json").read_text()) if continuing else []
        errors = list(previous.get("errors", [])) if continuing else []
        start = int(previous.get("next_file_index", 0)) if continuing else 0
        processed = start
        deadline = time.monotonic() + 3
        for path in paths[start : start + max(1, batch_size)]:
            if processed > start and time.monotonic() >= deadline:
                break
            processed += 1
            try:
                content, kind = clean_source(path)
                relative = path.relative_to(source)
                output = markdown / (relative.as_posix() + ".md")
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary_output = output.with_suffix(".tmp")
                temporary_output.write_text(
                    f"# {path.stem}\n\nSource: `{path}`\n\n{content}\n", encoding="utf-8"
                )
                os.replace(temporary_output, output)
                records.append(
                    {
                        "title": path.stem,
                        "relative_path": output.relative_to(markdown).as_posix(),
                        "source_path": str(path),
                        "source_kind": kind,
                        "source_version": version,
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "runtime_verified": False,
                    }
                )
            except (OSError, ValueError, SyntaxError) as exc:
                errors.append({"source": str(path), "error": str(exc)})
        state = {
            "status": "ready" if not errors and processed == len(paths) else "partial",
            "root": str(generation),
            "source_root": str(source),
            "version": version,
            "fingerprint": fingerprint,
            "document_count": len(records),
            "source_count": len(paths),
            "next_file_index": processed,
            "build_complete": processed == len(paths),
            "errors": errors[:20],
            "execution_available": True,
        }
        index_temporary = indexes / "document_index.tmp"
        index_temporary.write_text(json.dumps(records), encoding="utf-8")
        os.replace(index_temporary, indexes / "document_index.json")
        (indexes / "manifest.json").write_text(json.dumps(state), encoding="utf-8")
        temporary = pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, pointer)
        if background and not state["build_complete"]:
            from eda_bridge_runtime.jobs import _pid_is_alive

            pid_file = cache / "builder.pid"
            try:
                active = _pid_is_alive(int(pid_file.read_text()))
            except (OSError, ValueError):
                active = False
            if not active:
                command = [sys.executable, "-m", "ansysem_agent_bridge.docs_ingest", str(source)]
                if version:
                    command += ["--version", version]
                options = (
                    {
                        "creationflags": subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                    }
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                with (cache / "builder.log").open("ab") as log:
                    process = subprocess.Popen(
                        command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options
                    )
                pid_file.write_text(str(process.pid))
        return state


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare private official documentation in bounded batches"
    )
    parser.add_argument("root")
    parser.add_argument("--version")
    args = parser.parse_args()
    while True:
        state = ensure_docs(args.root, version=args.version, background=False)
        if state.get("build_complete", True):
            break
