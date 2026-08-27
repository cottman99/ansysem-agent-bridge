from pathlib import Path

import pytest

from ansysem_agent_bridge.project_bundle import (
    bundle_content_sha256,
    bundle_state_revision,
    copy_project_bundle,
    inspect_project_bundle,
)


def test_complete_project_bundle(tmp_path: Path) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("synthetic fixture", encoding="utf-8")
    aedb = tmp_path / "synthetic.aedb"
    aedb.mkdir()
    (aedb / "edb.def").write_text("synthetic", encoding="utf-8")
    result = inspect_project_bundle(project, redact_paths=True)
    assert result["bundle_complete"] is True
    assert result["project"] == "synthetic.aedt"
    assert len(result["project_sha256"]) == 64


def test_missing_aedb_is_not_complete(tmp_path: Path) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("synthetic fixture", encoding="utf-8")
    result = inspect_project_bundle(project)
    assert result["bundle_complete"] is False
    assert result["reason"] == "aedb_missing"


def test_rejects_non_aedt_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected an .aedt"):
        inspect_project_bundle(tmp_path / "not-a-project.txt")


def test_bundle_copy_is_isolated_and_reports_copy_strategy(tmp_path: Path) -> None:
    source = tmp_path / "source.aedt"
    source.write_text("source", encoding="utf-8")
    source_aedb = source.with_suffix(".aedb")
    source_aedb.mkdir()
    (source_aedb / "edb.def").write_text("definition", encoding="utf-8")
    (source_aedb / "cell.dat").write_text("cell", encoding="utf-8")
    destination = tmp_path / "candidate.aedt"

    copied = copy_project_bundle(source, destination)

    assert copied["strategy"] in {"copy", "mixed", "reflink"}
    assert copied["file_count"] == 3
    assert copied["logical_bytes"] > 0
    assert bundle_content_sha256(destination) != ""
    destination.write_text("candidate", encoding="utf-8")
    assert source.read_text(encoding="utf-8") == "source"


def test_state_revision_is_lightweight_but_content_digest_is_cryptographic(
    tmp_path: Path,
) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("first", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    definition = aedb / "edb.def"
    definition.write_text("definition", encoding="utf-8")
    state_before = bundle_state_revision(project)
    content_before = bundle_content_sha256(project)

    definition.write_text("changed", encoding="utf-8")

    assert bundle_state_revision(project) != state_before
    assert bundle_content_sha256(project) != content_before
