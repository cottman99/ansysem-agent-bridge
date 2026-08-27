from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import ansysem_agent_bridge.workspace as workspace_module
from ansysem_agent_bridge.project_bundle import sha256_file
from ansysem_agent_bridge.workspace import (
    abort_workspace,
    begin_workspace,
    load_workspace,
    promote_workspace,
    reconcile_workspace,
    rollback_workspace,
    validate_workspace_patch,
    workspace_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "schemas" / "ansysem-operation-result-v1.schema.json").read_text(
        encoding="utf-8"
    )
)


def _validate_result(result: dict[str, Any]) -> None:
    jsonschema.validate(result, RESULT_SCHEMA)


def _bundle(root: Path, name: str = "source") -> Path:
    project = root / f"{name}.aedt"
    project.write_text("source", encoding="utf-8")
    aedb = project.with_suffix(".aedb")
    aedb.mkdir()
    (aedb / "edb.def").write_text("definition", encoding="utf-8")
    (aedb / "cell.dat").write_text("cell-a", encoding="utf-8")
    return project


class FakeAdapter:
    adapter_id = "hfss3dlayout.native/v1"

    def __init__(self, *, passes: bool = True) -> None:
        self.passes = passes
        self.apply_calls = 0
        self.verify_calls = 0

    def apply(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        self.apply_calls += 1
        values = [
            str(operation["value"])
            for operation in plan["operations"]
            if operation["type"] == "set_property"
        ]
        current = project.read_text(encoding="utf-8")
        project.write_text("|".join([current, *values]), encoding="utf-8")
        return {
            "operation_count": len(plan["operations"]),
            "applied_count": len(plan["operations"]),
            "skipped_count": 0,
        }

    def verify(self, project: Path, plan: dict[str, Any]) -> dict[str, Any]:
        self.verify_calls += 1
        return {
            "readback": {"content": project.read_text(encoding="utf-8")},
            "validation": [
                {"id": assertion["id"], "passed": self.passes} for assertion in plan["assertions"]
            ],
        }


def _begin(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    source = _bundle(tmp_path)
    workspace = tmp_path / "workspace"
    result = begin_workspace(
        source_project=source,
        workspace=workspace,
        adapter="hfss3dlayout.native/v1",
        version="2026.1",
        design="Layout1",
        profile="synthetic-profile",
        workspace_id="synthetic-workspace",
    )
    return source, workspace, result


def _patch(revision: str, patch_id: str, value: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "patch_id": patch_id,
        "expected_workspace_revision": revision,
        "adapter": "hfss3dlayout.native/v1",
        "profile": "synthetic-profile",
        "version": "2026.1",
        "design": "Layout1",
        "solve_requested": False,
        "operations": [
            {
                "type": "set_property",
                "server": "trace",
                "property": "Net",
                "value": value,
            }
        ],
        "assertions": [
            {
                "id": "trace.net",
                "type": "property_equals",
                "server": "trace",
                "property": "Net",
                "value": value,
            }
        ],
    }


def test_workspace_reconcile_is_resumable_and_idempotent(tmp_path: Path) -> None:
    source, workspace, begun = _begin(tmp_path)
    source_hash = sha256_file(source)
    adapter = FakeAdapter()
    patch = _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1")

    result = reconcile_workspace(workspace, patch, adapter=adapter)
    _validate_result(begun)
    _validate_result(result)
    assert result["status"] == "passed"
    assert result["readback"]["current_generation"] == 1
    assert result["readback"]["journal_length"] == 1
    assert adapter.apply_calls == 1
    assert sha256_file(source) == source_hash

    repeated = reconcile_workspace(workspace, patch, adapter=adapter)
    _validate_result(repeated)
    assert repeated["status"] == "preserved"
    assert repeated["readback"]["idempotent_replay"] is True
    assert adapter.apply_calls == 1
    assert workspace_status(workspace)["status"] == "ready"


def test_failed_reconcile_preserves_candidate_and_revision(tmp_path: Path) -> None:
    _, workspace, begun = _begin(tmp_path)
    revision = begun["readback"]["workspace_revision"]
    result = reconcile_workspace(
        workspace,
        _patch(revision, "patch-fails", "BAD"),
        adapter=FakeAdapter(passes=False),
    )
    _validate_result(result)
    assert result["status"] == "failed"
    _, manifest = load_workspace(workspace)
    assert manifest["workspace_revision"] == revision
    assert manifest["current_generation"] == 0
    assert manifest["journal"] == []
    assert not list((workspace / "generations").glob(".stage-*"))


def test_workspace_rejects_stale_revision_and_external_drift(tmp_path: Path) -> None:
    _, workspace, begun = _begin(tmp_path)
    patch = _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1")
    first = reconcile_workspace(workspace, patch, adapter=FakeAdapter())
    stale = _patch(begun["readback"]["workspace_revision"], "patch-2", "SIG2")
    with pytest.raises(ValueError, match="revision conflict"):
        reconcile_workspace(workspace, stale, adapter=FakeAdapter())

    _, manifest = load_workspace(workspace)
    candidate = workspace / manifest["current_project"]
    candidate.write_text("external change", encoding="utf-8")
    current = _patch(first["readback"]["workspace_revision"], "patch-2", "SIG2")
    with pytest.raises(ValueError, match="outside the Bridge journal"):
        reconcile_workspace(workspace, current, adapter=FakeAdapter())
    with pytest.raises(ValueError, match="outside the Bridge journal"):
        reconcile_workspace(workspace, patch, adapter=FakeAdapter())
    assert workspace_status(workspace)["status"] == "blocked"


def test_rollback_uses_internal_checkpoint_without_new_revision_artifact(
    tmp_path: Path,
) -> None:
    _, workspace, begun = _begin(tmp_path)
    first = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    second = reconcile_workspace(
        workspace,
        _patch(first["readback"]["workspace_revision"], "patch-2", "SIG2"),
        adapter=FakeAdapter(),
    )
    rolled_back = rollback_workspace(
        workspace,
        expected_workspace_revision=second["readback"]["workspace_revision"],
    )
    _validate_result(rolled_back)
    assert rolled_back["readback"]["rolled_back_patch_id"] == "patch-2"
    assert rolled_back["readback"]["current_generation"] == 1
    _, manifest = load_workspace(workspace)
    candidate = workspace / manifest["current_project"]
    assert candidate.read_text(encoding="utf-8") == "source|SIG1"
    assert len(manifest["journal"]) == 1


def test_promote_cleanly_replays_journal_from_frozen_source(tmp_path: Path) -> None:
    source, workspace, begun = _begin(tmp_path)
    first = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    second = reconcile_workspace(
        workspace,
        _patch(first["readback"]["workspace_revision"], "patch-2", "SIG2"),
        adapter=FakeAdapter(),
    )
    output = tmp_path / "promoted.aedt"
    promoted = promote_workspace(
        workspace,
        output_project=output,
        expected_workspace_revision=second["readback"]["workspace_revision"],
        promotion_id="revision-1",
        adapter=FakeAdapter(),
    )
    _validate_result(promoted)
    assert promoted["status"] == "passed"
    assert promoted["readback"]["clean_replay"] is True
    assert promoted["readback"]["candidate_removed"] is True
    assert output.read_text(encoding="utf-8") == "source|SIG1|SIG2"
    assert source.read_text(encoding="utf-8") == "source"
    assert not (workspace / "generations").exists()
    _, manifest = load_workspace(workspace)
    assert manifest["status"] == "promoted"
    assert manifest["promotion"]["promotion_id"] == "revision-1"
    assert workspace_status(workspace)["status"] == "ready"
    redacted_status = workspace_status(workspace, redact_paths=True)
    assert redacted_status["readback"]["promotion"]["output_project"] == output.name
    assert redacted_status["artifacts"][0]["path"] == output.name

    replay_adapter = FakeAdapter()
    replayed = promote_workspace(
        workspace,
        output_project=output,
        expected_workspace_revision=second["readback"]["workspace_revision"],
        promotion_id="revision-1",
        adapter=replay_adapter,
    )
    _validate_result(replayed)
    assert replayed["status"] == "preserved"
    assert replayed["readback"]["idempotent_replay"] is True
    assert replay_adapter.apply_calls == 0

    output.write_text("external drift", encoding="utf-8")
    assert workspace_status(workspace)["status"] == "blocked"
    with pytest.raises(ValueError, match="recorded bundle digest"):
        promote_workspace(
            workspace,
            output_project=output,
            expected_workspace_revision=second["readback"]["workspace_revision"],
            promotion_id="revision-1",
            adapter=FakeAdapter(),
        )


def test_interrupted_promotion_recovers_committed_output_without_reapplying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, workspace, begun = _begin(tmp_path)
    reconciled = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    requested_revision = reconciled["readback"]["workspace_revision"]
    output = tmp_path / "promoted.aedt"
    real_save_manifest = workspace_module._save_manifest

    class PowerLoss(BaseException):
        pass

    def crash_before_promoted_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        if manifest.get("status") == "promoted":
            raise PowerLoss
        return real_save_manifest(root, manifest)

    monkeypatch.setattr(workspace_module, "_save_manifest", crash_before_promoted_manifest)
    with pytest.raises(PowerLoss):
        promote_workspace(
            workspace,
            output_project=output,
            expected_workspace_revision=requested_revision,
            promotion_id="revision-1",
            adapter=FakeAdapter(),
        )
    monkeypatch.setattr(workspace_module, "_save_manifest", real_save_manifest)

    _, interrupted = load_workspace(workspace)
    assert interrupted["status"] == "promoting"
    assert output.is_file()
    interrupted_status = workspace_status(workspace, redact_paths=True)
    _validate_result(interrupted_status)
    assert interrupted_status["failure"]["reason"] == "promotion_interrupted"
    assert interrupted_status["readback"]["promotion"]["output_project"] == output.name
    assert interrupted_status["readback"]["promotion"]["staging_root"].startswith(".ansysem-stage-")

    recovery_adapter = FakeAdapter()
    recovered = promote_workspace(
        workspace,
        output_project=output,
        expected_workspace_revision=requested_revision,
        promotion_id="revision-1",
        adapter=recovery_adapter,
    )
    _validate_result(recovered)
    assert recovered["status"] == "preserved"
    assert recovered["readback"]["interrupted_promotion_recovered"] is True
    assert recovered["readback"]["apply_replayed"] is False
    assert recovery_adapter.apply_calls == 0
    assert recovery_adapter.verify_calls == 1
    assert not (workspace / "generations").exists()


def test_interrupted_promotion_replays_after_cleaning_owned_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, workspace, begun = _begin(tmp_path)
    reconciled = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    requested_revision = reconciled["readback"]["workspace_revision"]
    output = tmp_path / "promoted.aedt"
    real_execute = workspace_module.execute_operation_plan

    class PowerLoss(BaseException):
        pass

    def crash_before_transaction(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise PowerLoss

    monkeypatch.setattr(workspace_module, "execute_operation_plan", crash_before_transaction)
    with pytest.raises(PowerLoss):
        promote_workspace(
            workspace,
            output_project=output,
            expected_workspace_revision=requested_revision,
            promotion_id="revision-1",
            adapter=FakeAdapter(),
        )
    monkeypatch.setattr(workspace_module, "execute_operation_plan", real_execute)

    _, interrupted = load_workspace(workspace)
    assert interrupted["status"] == "promoting"
    stage = Path(interrupted["promotion_intent"]["staging_root"])
    stage.mkdir()
    (stage / "partial").write_text("partial", encoding="utf-8")
    output.write_text("partial", encoding="utf-8")

    recovery_adapter = FakeAdapter()
    recovered = promote_workspace(
        workspace,
        output_project=output,
        expected_workspace_revision=requested_revision,
        promotion_id="revision-1",
        adapter=recovery_adapter,
    )
    _validate_result(recovered)
    assert recovered["status"] == "passed"
    assert recovered["readback"]["interrupted_promotion_recovered"] is True
    assert recovered["readback"]["apply_replayed"] is True
    assert recovery_adapter.apply_calls == 1
    assert output.read_text(encoding="utf-8") == "source|SIG1"
    assert not stage.exists()


def test_failed_promotion_returns_workspace_to_draft_with_new_revision(tmp_path: Path) -> None:
    _, workspace, begun = _begin(tmp_path)
    reconciled = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    requested_revision = reconciled["readback"]["workspace_revision"]
    output = tmp_path / "failed.aedt"

    failed = promote_workspace(
        workspace,
        output_project=output,
        expected_workspace_revision=requested_revision,
        promotion_id="revision-fails",
        adapter=FakeAdapter(passes=False),
    )

    _validate_result(failed)
    assert failed["status"] == "failed"
    assert failed["readback"]["workspace_status"] == "draft"
    assert failed["readback"]["workspace_revision"] != requested_revision
    _, manifest = load_workspace(workspace)
    assert manifest["status"] == "draft"
    assert "promotion_intent" not in manifest
    assert not output.exists()
    assert workspace_status(workspace)["status"] == "ready"


def test_promotion_full_digest_catches_change_hidden_from_state_revision(
    tmp_path: Path,
) -> None:
    source, workspace, begun = _begin(tmp_path)
    reconciled = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )
    cell = source.with_suffix(".aedb") / "cell.dat"
    original_stat = cell.stat()
    cell.write_text("cell-b", encoding="utf-8")
    os.utime(cell, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    output = tmp_path / "must-not-exist.aedt"

    with pytest.raises(ValueError, match="Full source bundle digest mismatch"):
        promote_workspace(
            workspace,
            output_project=output,
            expected_workspace_revision=reconciled["readback"]["workspace_revision"],
            adapter=FakeAdapter(),
        )

    assert not output.exists()


def test_abort_removes_only_owned_candidate_and_keeps_journal_manifest(tmp_path: Path) -> None:
    source, workspace, begun = _begin(tmp_path)
    aborted = abort_workspace(
        workspace,
        expected_workspace_revision=begun["readback"]["workspace_revision"],
    )
    _validate_result(aborted)
    assert aborted["status"] == "passed"
    assert source.is_file()
    assert not (workspace / "generations").exists()
    _, manifest = load_workspace(workspace)
    assert manifest["status"] == "aborted"
    assert manifest["current_project"] is None

    repeated = abort_workspace(
        workspace,
        expected_workspace_revision=begun["readback"]["workspace_revision"],
    )
    _validate_result(repeated)
    assert repeated["status"] == "preserved"


def test_workspace_patch_requires_typed_operations_and_stable_assertion_ids() -> None:
    patch = _patch("0" * 64, "patch-1", "SIG")
    validate_workspace_patch(patch)
    patch["operations"] = [{"type": "run_python", "code": "print('no')"}]
    with pytest.raises(ValueError, match="Unsupported typed operation"):
        validate_workspace_patch(patch)

    patch = _patch("0" * 64, "patch-1", "SIG")
    patch["assertions"][0].pop("id")
    with pytest.raises(ValueError, match="stable non-empty id"):
        validate_workspace_patch(patch)


def test_workspace_refuses_candidate_inside_source_bundle(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    with pytest.raises(ValueError, match="inside the frozen source"):
        begin_workspace(
            source_project=source,
            workspace=source.with_suffix(".aedb") / "candidate",
            adapter="hfss3dlayout.native/v1",
            version="2026.1",
            design="Layout1",
        )


def test_reconcile_recovers_stale_lock_and_abandoned_owned_stage(tmp_path: Path) -> None:
    _, workspace, begun = _begin(tmp_path)
    stale_stage = workspace / "generations" / ".stage-interrupted"
    stale_stage.mkdir()
    (stale_stage / "partial").write_text("partial", encoding="utf-8")
    orphan_generation = workspace / "generations" / "000001"
    orphan_generation.mkdir()
    (orphan_generation / "partial").write_text("partial", encoding="utf-8")
    (workspace / ".workspace.lock").write_text(
        json.dumps({"host": socket.gethostname(), "pid": 2_147_483_647}),
        encoding="utf-8",
    )

    result = reconcile_workspace(
        workspace,
        _patch(begun["readback"]["workspace_revision"], "patch-1", "SIG1"),
        adapter=FakeAdapter(),
    )

    assert result["status"] == "passed"
    assert not stale_stage.exists()
    assert (orphan_generation / "model.aedt").is_file()
    assert not (orphan_generation / "partial").exists()
    assert not (workspace / ".workspace.lock").exists()
