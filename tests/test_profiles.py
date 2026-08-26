from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from ansysem_agent_bridge.config import remove_profile, upsert_profile
from ansysem_agent_bridge.profiles import (
    apply_profile,
    ensure_profile_process,
    get_profile,
    parse_assignment,
)


def test_profile_applies_environment_and_python_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent-home"))
    module_path = tmp_path / "modules"
    module_path.mkdir()
    upsert_profile(
        {
            "profile_id": "test",
            "python_executable": sys.executable,
            "display": ":4.0",
            "environment": {"ANSYSEM_TEST_EXACT": "exact"},
            "prepend_environment": {"ANSYSEM_TEST_PATH": "first"},
            "python_paths": [str(module_path)],
        }
    )
    monkeypatch.setenv("ANSYSEM_TEST_PATH", "second")
    result = apply_profile("test")
    assert result["status"] == "ready"
    assert os.environ["DISPLAY"] == ":4.0"
    assert os.environ["ANSYSEM_TEST_EXACT"] == "exact"
    assert os.environ["ANSYSEM_TEST_PATH"] == os.pathsep.join(("first", "second"))
    assert sys.path[0] == str(module_path.resolve())


def test_profile_rejects_wrong_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent-home"))
    wrong_python = tmp_path / "python"
    wrong_python.write_text("not an interpreter", encoding="utf-8")
    upsert_profile(
        {
            "profile_id": "wrong",
            "python_executable": str(wrong_python),
            "display": ":4.0",
            "environment": {},
            "prepend_environment": {},
            "python_paths": [],
        }
    )
    with pytest.raises(RuntimeError, match="controlled profile launcher"):
        apply_profile("wrong")


def test_profile_launcher_reexecs_exact_cli_with_prelaunch_environment(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent-home"))
    monkeypatch.delenv("ANSYSEM_ACTIVE_PROFILE", raising=False)
    module_path = tmp_path / "modules"
    module_path.mkdir()
    upsert_profile(
        {
            "profile_id": "launch",
            "python_executable": sys.executable,
            "display": ":4.0",
            "environment": {"ANSYSEM_ROOT_TEST": "/aedt"},
            "prepend_environment": {"LD_LIBRARY_PATH": "/compat"},
            "python_paths": [str(module_path)],
        }
    )
    captured = {}

    def fake_execve(executable, arguments, environment):
        captured.update(
            executable=executable, arguments=arguments, environment=environment
        )
        raise RuntimeError("exec captured")

    monkeypatch.setattr(os, "execve", fake_execve)
    with pytest.raises(RuntimeError, match="exec captured"):
        ensure_profile_process("launch", ["--profile", "launch", "doctor"])
    assert captured["executable"] == os.path.abspath(sys.executable)
    assert captured["arguments"][1:3] == ["-m", "ansysem_agent_bridge.cli"]
    assert captured["environment"]["DISPLAY"] == ":4.0"
    assert captured["environment"]["LD_LIBRARY_PATH"].split(os.pathsep)[0] == "/compat"
    assert captured["environment"]["ANSYSEM_ACTIVE_PROFILE"]


def test_profile_config_is_backward_compatible(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "agent-home"
    home.mkdir()
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps({"schema_version": 1, "instances": [], "default_instance": None}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="No runtime profile"):
        get_profile()


def test_remove_profile_and_assignment_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANSYSEM_AGENT_HOME", str(tmp_path / "agent-home"))
    upsert_profile(
        {
            "profile_id": "temporary",
            "python_executable": sys.executable,
            "display": ":4.0",
            "environment": {},
            "prepend_environment": {},
            "python_paths": [],
        }
    )
    remove_profile("temporary")
    with pytest.raises(ValueError, match="Unknown runtime profile"):
        get_profile("temporary")
    assert parse_assignment("KEY=value") == ("KEY", "value")
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_assignment("KEY")
