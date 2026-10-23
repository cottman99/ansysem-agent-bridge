import json
from pathlib import Path

from ansysem_agent_bridge.docs_ingest import ensure_docs


def test_preparation_resumes_bounded_batches_without_reconverting_completed_files(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent"))
    source = tmp_path / "sources"
    source.mkdir()
    for index in range(3):
        (source / f"page{index}.html").write_text(f"<main>symbol_{index}</main>")
    first = ensure_docs(source, version="2026.1", batch_size=1, background=False)
    assert first["status"] == "partial" and first["document_count"] == 1
    second = ensure_docs(source, version="2026.1", batch_size=1, background=False)
    assert second["root"] == first["root"] and second["document_count"] == 2
    final = ensure_docs(source, version="2026.1", batch_size=1, background=False)
    assert final["status"] == "ready" and final["build_complete"]
    assert final["document_count"] == 3


def test_first_query_prepares_raw_html_and_source_change_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "home"))
    source = tmp_path / "official"
    source.mkdir()
    raw = source / "api.html"
    raw.write_text(
        "<html><nav>Menu</nav><main><h1>Official API</h1><p>open_project(path)</p></main></html>"
    )
    state = ensure_docs(source, version="2026.1")
    assert state["status"] == "ready"
    output = Path(state["root"]) / "markdown" / "api.html.md"
    assert "open_project(path)" in output.read_text()
    assert "Menu" not in output.read_text()
    assert ensure_docs(source, version="2026.1")["root"] == state["root"]
    raw.write_text("<main><p>open_project(path, version)</p></main>")
    updated = ensure_docs(source, version="2026.1")
    assert updated["fingerprint"] != state["fingerprint"]
    assert updated["root"] != state["root"]
    assert raw.read_text().startswith("<main>")


def test_sdk_symbols_are_evidence_and_never_imported(tmp_path, monkeypatch):
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "home"))
    source = tmp_path / "sdk"
    source.mkdir()
    (source / "official.py").write_text(
        'raise RuntimeError("must not import")\n\ndef compute(width: float = 3):\n'
        '    """Compute geometry."""\n    pass\n'
    )
    state = ensure_docs(source, version="1.4")
    records = json.loads(
        (Path(state["root"]) / "retrieval/indexes/document_index.json").read_text()
    )
    assert records[0]["source_kind"] == "sdk_source"
    assert records[0]["source_version"] == "1.4"
    assert records[0]["runtime_verified"] is False
    assert "compute(width:float=3)" in (
        Path(state["root"]) / "markdown/official.py.md"
    ).read_text().replace(" ", "")


def test_missing_docs_and_existing_markdown_do_not_gate_execution(tmp_path):
    assert ensure_docs(tmp_path / "missing")["execution_available"] is True
    source = tmp_path / "docs"
    source.mkdir()
    raw = source / "user.md"
    raw.write_text("# User maintained\n")
    assert ensure_docs(source)["root"] == str(source.resolve())
    assert raw.read_text() == "# User maintained\n"
