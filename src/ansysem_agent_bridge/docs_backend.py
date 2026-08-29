from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.:+-]+")


def _terms(query: str) -> list[str]:
    return [item.casefold() for item in TOKEN_PATTERN.findall(query) if len(item) > 1]


def _markdown_root(root: Path) -> Path:
    candidates = (root / "sources" / "markdown", root / "markdown", root)
    return next((item for item in candidates if item.is_dir()), root)


def docs_status(root: str | Path) -> dict[str, Any]:
    path = Path(root).expanduser().resolve()
    markdown = _markdown_root(path)
    manifest_candidates = (
        path / "retrieval" / "indexes" / "manifest.json",
        path / "retrieval" / "manifest.json",
    )
    manifest = next((item for item in manifest_candidates if item.is_file()), None)
    return {
        "status": "ready" if path.is_dir() and markdown.is_dir() else "missing",
        "root": str(path),
        "markdown_root": str(markdown),
        "manifest": str(manifest) if manifest else None,
        "indexed": manifest is not None,
    }


def _iter_index_records(root: Path) -> Iterable[dict[str, Any]]:
    index_root = root / "retrieval" / "indexes"
    topic = index_root / "topic_index.jsonl"
    if topic.is_file():
        with topic.open(encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield {"kind": "topic", **item}

    for filename, kind in (
        ("document_index.json", "document"),
        ("filename_index.json", "filename"),
    ):
        path = index_root / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield {"kind": kind, **item}
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    yield {"kind": kind, "index_key": key, **value}
                else:
                    yield {"kind": kind, "index_key": key, "value": value}


def _record_text(record: dict[str, Any]) -> str:
    values: list[str] = []
    for key, value in record.items():
        if key in {"content", "text"} and isinstance(value, str):
            values.append(value[:4000])
        elif isinstance(value, str | int | float):
            values.append(str(value))
        elif isinstance(value, list):
            values.extend(str(item) for item in value[:30])
    return " ".join(values)


def _candidate_path(root: Path, record: dict[str, Any]) -> Path | None:
    markdown = _markdown_root(root)
    values = [record.get(key) for key in ("relative_path", "path", "markdown_file", "filename")]
    for value in values:
        if not value or not isinstance(value, str):
            continue
        raw = Path(value)
        candidates = [raw] if raw.is_absolute() else [markdown / raw, root / raw]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            if resolved.is_file() and resolved.suffix.casefold() == ".md":
                return resolved
    module = record.get("module")
    document = record.get("document") or record.get("title") or record.get("index_key")
    if module and document:
        candidate = markdown / str(module) / f"{document}.md"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _source_ref(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(root.resolve()).as_posix()


def _content_matches(
    root: Path,
    terms: list[str],
    *,
    module: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    markdown = _markdown_root(root)
    search_root = markdown / module if module and (markdown / module).is_dir() else markdown
    matches: list[dict[str, Any]] = []
    for candidate in sorted(search_root.rglob("*.md")):
        if len(matches) >= limit:
            break
        try:
            if candidate.stat().st_size > 32 * 1024 * 1024:
                continue
            with candidate.open(encoding="utf-8", errors="replace") as stream:
                for line_number, line in enumerate(stream, 1):
                    folded = line.casefold()
                    hit_count = sum(term in folded for term in terms)
                    if hit_count == 0:
                        continue
                    relative = candidate.resolve().relative_to(root.resolve()).as_posix()
                    module_name = (
                        candidate.relative_to(markdown).parts[0] if candidate != markdown else None
                    )
                    matches.append(
                        {
                            "score": 20 + 8 * hit_count,
                            "kind": "content",
                            "module": module_name,
                            "title": candidate.stem,
                            "source_ref": relative,
                            "line": line_number,
                            "snippet": line.strip()[:500],
                            "validation_status": "local_source_match",
                        }
                    )
                    break
        except OSError:
            continue
    return matches


def query_docs(
    root: str | Path, query: str, *, module: str | None = None, limit: int = 6
) -> dict[str, Any]:
    path = Path(root).expanduser().resolve()
    status = docs_status(path)
    if status["status"] != "ready":
        raise ValueError(f"Documentation root is unavailable: {path}")
    terms = _terms(query)
    if not terms:
        raise ValueError("Documentation query must include searchable terms.")

    ranked: list[tuple[int, dict[str, Any]]] = []
    for record in _iter_index_records(path):
        if module and str(record.get("module") or "").casefold() != module.casefold():
            continue
        text = _record_text(record).casefold()
        score = sum(8 if term in text else 0 for term in terms)
        if score == 0:
            continue
        source = _candidate_path(path, record)
        title = (
            record.get("title")
            or record.get("document")
            or record.get("filename")
            or record.get("index_key")
        )
        ranked.append(
            (
                score,
                {
                    "score": score,
                    "kind": record.get("kind"),
                    "module": record.get("module"),
                    "title": str(title or "unknown"),
                    "source_ref": _source_ref(path, source),
                    "validation_status": "local_source_match",
                },
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]["title"].casefold()))
    bounded_limit = max(1, min(limit, 20))
    results = [item for _, item in ranked[:bounded_limit]]
    if len(results) < bounded_limit:
        existing_refs = {item.get("source_ref") for item in results}
        for item in _content_matches(path, terms, module=module, limit=bounded_limit):
            if item.get("source_ref") in existing_refs:
                continue
            results.append(item)
            existing_refs.add(item.get("source_ref"))
            if len(results) >= bounded_limit:
                break
    return {
        "schema_version": 1,
        "query": query,
        "module": module,
        "search_mode": "local-index+bounded-content"
        if any(item.get("kind") == "content" for item in results)
        else "local-index",
        "result_count": len(results),
        "results": results,
        "evidence_boundary": "Documentation matches are not runtime execution evidence.",
    }


def get_doc(
    root: str | Path, source_ref: str, *, focus: str | None = None, max_chars: int = 4000
) -> dict[str, Any]:
    path = Path(root).expanduser().resolve()
    candidate = (path / source_ref).resolve()
    try:
        candidate.relative_to(path)
    except ValueError as exc:
        raise ValueError("Source reference escapes the configured documentation root.") from exc
    if not candidate.is_file() or candidate.suffix.casefold() != ".md":
        raise ValueError(f"Unknown documentation source reference: {source_ref}")
    text = candidate.read_text(encoding="utf-8", errors="replace")
    start = 0
    if focus:
        index = text.casefold().find(focus.casefold())
        if index >= 0:
            start = max(0, index - max_chars // 4)
    excerpt = text[start : start + max(256, min(max_chars, 12000))]
    return {
        "schema_version": 1,
        "source_ref": source_ref,
        "focus": focus,
        "excerpt": excerpt,
        "returned_chars": len(excerpt),
        "truncated": start + len(excerpt) < len(text),
        "evidence_boundary": "This is local documentation evidence, not runtime validation.",
    }
