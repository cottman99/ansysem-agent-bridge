import pytest


@pytest.fixture(autouse=True)
def _isolate_eda_runtime_home(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_RUNTIME_HOME", str(tmp_path / "eda-runtime"))
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "ansys-agent"))
