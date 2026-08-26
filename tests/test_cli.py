import json
from pathlib import Path

from ansysem_agent_bridge.cli import _exit_code, main


def test_project_inspect_cli(tmp_path: Path, capsys) -> None:
    project = tmp_path / "synthetic.aedt"
    project.write_text("synthetic", encoding="utf-8")
    aedb = tmp_path / "synthetic.aedb"
    aedb.mkdir()
    (aedb / "edb.def").write_text("synthetic", encoding="utf-8")
    code = main(["project", "inspect", "--project", str(project), "--redact-paths"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["result"]["bundle_complete"] is True
    assert payload["result"]["project"] == "synthetic.aedt"


def test_cli_error_is_structured(tmp_path: Path, capsys) -> None:
    code = main(["project", "inspect", "--project", str(tmp_path / "missing.aedt")])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["result"]["reason"] == "project_missing"


def test_non_success_json_status_never_has_zero_exit_code() -> None:
    for status in ("attention_required", "blocked", "failed", "partial", "error"):
        assert _exit_code({"status": status}) == 1
    for status in ("ready", "passed", "preserved", "removed"):
        assert _exit_code({"status": status}) == 0
