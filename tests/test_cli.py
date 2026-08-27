import json
from pathlib import Path

import ansysem_agent_bridge.cli as cli_module
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


def test_workspace_cli_begin_status_and_abort(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.aedt"
    source.write_text("source", encoding="utf-8")
    aedb = source.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("definition", encoding="utf-8")
    workspace = tmp_path / "candidate-workspace"
    common = ["--profile", "synthetic", "model", "workspace"]

    code = main(
        [
            *common,
            "begin",
            "--source",
            str(source),
            "--workspace",
            str(workspace),
            "--adapter",
            "hfss3dlayout.native/v1",
            "--version",
            "2026.1",
            "--design",
            "Layout1",
        ]
    )
    begun = json.loads(capsys.readouterr().out)
    assert code == 0
    revision = begun["readback"]["workspace_revision"]

    assert main(["model", "workspace", "status", "--workspace", str(workspace)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["readback"]["workspace_status"] == "draft"

    assert (
        main(
            [
                "model",
                "workspace",
                "abort",
                "--workspace",
                str(workspace),
                "--expected-revision",
                revision,
            ]
        )
        == 0
    )
    aborted = json.loads(capsys.readouterr().out)
    assert aborted["readback"]["candidate_removed"] is True


def test_vendor_stdout_is_routed_away_from_json_contract(monkeypatch, capsys) -> None:
    def noisy_dispatch(args):
        print("vendor progress")
        return {"status": "ready", "result": {"ok": True}}

    monkeypatch.setattr(cli_module, "dispatch", noisy_dispatch)
    code = main(["instances", "list"])
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out) == {"status": "ready", "result": {"ok": True}}
    assert "vendor progress" in captured.err
