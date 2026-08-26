from pathlib import Path

import pytest

from ansysem_agent_bridge.project_bundle import inspect_project_bundle


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
