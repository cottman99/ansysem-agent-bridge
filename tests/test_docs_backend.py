import json
from pathlib import Path

import pytest

from ansysem_agent_bridge.docs_backend import get_doc, query_docs


def _docs_fixture(tmp_path: Path) -> Path:
    markdown = tmp_path / "sources" / "markdown" / "hfss_3d_layout"
    markdown.mkdir(parents=True)
    source = markdown / "ScriptingGuide.md"
    source.write_text(
        "# Guide\n\nAddRefPortUsingEdges assigns a reference edge.\n", encoding="utf-8"
    )
    indexes = tmp_path / "retrieval" / "indexes"
    indexes.mkdir(parents=True)
    (indexes / "manifest.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    record = {
        "module": "hfss_3d_layout",
        "title": "HFSS 3D Layout Scripting Guide",
        "relative_path": "hfss_3d_layout/ScriptingGuide.md",
        "keywords": ["AddRefPortUsingEdges", "reference edge"],
    }
    (indexes / "topic_index.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return tmp_path


def test_query_and_get_use_bounded_source_refs(tmp_path: Path) -> None:
    root = _docs_fixture(tmp_path)
    result = query_docs(root, "AddRefPortUsingEdges", module="hfss_3d_layout")
    assert result["result_count"] == len(result["results"])
    assert len(result["results"]) == 1
    source_ref = result["results"][0]["source_ref"]
    assert source_ref == "sources/markdown/hfss_3d_layout/ScriptingGuide.md"
    expanded = get_doc(root, source_ref, focus="AddRefPortUsingEdges")
    assert expanded["returned_chars"] == len(expanded["excerpt"])
    assert "assigns a reference edge" in expanded["excerpt"]


def test_get_rejects_escape(tmp_path: Path) -> None:
    root = _docs_fixture(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        get_doc(root, "../outside.md")


def test_query_falls_back_to_bounded_markdown_content(tmp_path: Path) -> None:
    root = _docs_fixture(tmp_path)
    (root / "retrieval" / "indexes" / "topic_index.jsonl").write_text("", encoding="utf-8")
    result = query_docs(root, "AddRefPortUsingEdges", module="hfss_3d_layout")
    assert result["search_mode"] == "local-index+bounded-content"
    assert result["results"][0]["kind"] == "content"
    assert result["results"][0]["line"] == 3
