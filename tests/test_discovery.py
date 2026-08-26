from pathlib import Path

from ansysem_agent_bridge.discovery import discover_installations


def test_environment_discovery_is_explicit_and_versioned(tmp_path: Path, monkeypatch) -> None:
    agent_home = tmp_path / "agent-home"
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(agent_home))
    root = tmp_path / "v261"
    executable = root / "Linux64" / "ansysedt"
    executable.parent.mkdir(parents=True)
    executable.write_text("synthetic", encoding="utf-8")
    records = discover_installations({"ANSYSEM_ROOT261": str(root)})
    assert len(records) == 1
    assert records[0].version == "2026.1"
    assert records[0].executable == str(executable)
