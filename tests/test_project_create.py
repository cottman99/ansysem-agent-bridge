import sys
import types
from pathlib import Path

import pytest

from ansysem_agent_bridge import project_create


class FakeLayout:
    def __init__(self, **kwargs):
        self.project = Path(kwargs["project"])
        self.design_name = kwargs["design"]

    def save_project(self):
        self.project.write_text("project", encoding="utf-8")
        bundle = self.project.with_suffix(".aedb")
        bundle.mkdir()
        (bundle / "edb.def").write_text("edb", encoding="utf-8")
        return True

    def release_desktop(self, **_kwargs):
        return True


def test_create_project_refuses_display_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":4.0")
    with pytest.raises(RuntimeError, match="DISPLAY mismatch"):
        project_create.create_hfss3dlayout_project(
            project=tmp_path / "demo.aedt",
            design="Layout1",
            version="2026.1",
            expected_display=":5.0",
        )


def test_create_project_persists_reopens_and_returns_opaque_context(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":4.0")
    core = types.ModuleType("ansys.aedt.core")
    core.Hfss3dLayout = FakeLayout
    monkeypatch.setitem(sys.modules, "ansys", types.ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt", types.ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core)
    monkeypatch.setattr(
        project_create,
        "live_hfss3dlayout_probe",
        lambda **kwargs: {
            "status": "ready",
            "identity": {"design_name": kwargs["design"]},
        },
    )
    monkeypatch.setattr(project_create, "store_context", lambda *_a, **_k: "opaque")

    result = project_create.create_hfss3dlayout_project(
        project=tmp_path / "demo.aedt",
        design="Layout1",
        version="2026.1",
        connection_id="ansys-display4",
        expected_display=":4.0",
    )

    assert result["status"] == "passed"
    assert result["fresh_reopen"]["status"] == "ready"
    assert result["eda_context"] == "opaque"
    assert result["project"] == "demo.aedt"


def test_create_project_refuses_existing_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":4.0")
    project = tmp_path / "demo.aedt"
    project.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        project_create.create_hfss3dlayout_project(
            project=project,
            design="Layout1",
            version="2026.1",
            expected_display=":4.0",
        )


def test_create_project_removes_its_partial_bundle_on_post_save_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":4.0")
    core = types.ModuleType("ansys.aedt.core")
    core.Hfss3dLayout = FakeLayout
    monkeypatch.setitem(sys.modules, "ansys", types.ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt", types.ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core)
    monkeypatch.setattr(
        project_create,
        "live_hfss3dlayout_probe",
        lambda **_kwargs: {"status": "ready"},
    )
    monkeypatch.setattr(
        project_create,
        "store_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("context failed")),
    )
    project = tmp_path / "demo.aedt"

    with pytest.raises(RuntimeError, match="context failed"):
        project_create.create_hfss3dlayout_project(
            project=project,
            design="Layout1",
            version="2026.1",
            expected_display=":4.0",
        )

    assert not project.exists()
    assert not project.with_suffix(".aedb").exists()
