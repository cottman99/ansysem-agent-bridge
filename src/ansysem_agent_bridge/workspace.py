from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import state_revision
from .project_bundle import (
    bundle_state_revision,
    copy_project_bundle,
    sync_directory,
)
from .transaction import (
    OperationAdapter,
    _adapter_for,
    _stable_bundle_summary,
    execute_operation_plan,
    validate_operation_plan,
)

_MANIFEST_NAME = "workspace.json"
_LOCK_NAME = ".workspace.lock"
_GENERATIONS_NAME = "generations"
_SUPPORTED_ADAPTERS = {"hfss3dlayout.native/v1", "hfss3dlayout.pyedb-native/v1"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _display_path(path: Path, *, redact: bool) -> str:
    return path.name if redact else str(path)


def _manifest_path(workspace: Path) -> Path:
    return workspace / _MANIFEST_NAME


def _load_json(path: str | Path) -> dict[str, Any]:
    if str(path) == "-":
        data = json.loads(sys.stdin.read())
    else:
        data = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON document must be an object.")
    return data


def load_workspace_patch(path: str | Path) -> dict[str, Any]:
    patch = _load_json(path)
    validate_workspace_patch(patch)
    return patch


def validate_workspace_patch(patch: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "patch_id",
        "expected_workspace_revision",
        "adapter",
        "version",
        "design",
        "operations",
        "assertions",
    }
    allowed = required | {"profile", "runtime", "solve_requested", "redact_paths"}
    missing = sorted(required - set(patch))
    extra = sorted(set(patch) - allowed)
    if missing:
        raise ValueError(f"Workspace patch is missing required fields: {missing}")
    if extra:
        raise ValueError(f"Workspace patch contains unsupported fields: {extra}")
    if patch["schema_version"] != 1:
        raise ValueError(f"Unsupported workspace patch schema: {patch['schema_version']}")
    for field in ("patch_id", "expected_workspace_revision", "version", "design"):
        if not isinstance(patch[field], str) or not patch[field].strip():
            raise ValueError(f"Workspace patch field {field} must be a non-empty string.")
    revision = patch["expected_workspace_revision"]
    if len(revision) != 64 or any(char not in "0123456789abcdefABCDEF" for char in revision):
        raise ValueError("expected_workspace_revision must be a SHA-256 hex digest.")
    for assertion in patch["assertions"]:
        if not isinstance(assertion, dict) or not isinstance(assertion.get("id"), str):
            raise ValueError("Every workspace assertion requires a stable non-empty id.")
        if not assertion["id"].strip():
            raise ValueError("Every workspace assertion requires a stable non-empty id.")
    synthetic = {
        "schema_version": 1,
        "operation_id": patch["patch_id"],
        "adapter": patch["adapter"],
        "source_project": "source.aedt",
        "output_project": "output.aedt",
        "version": patch["version"],
        "design": patch["design"],
        "operations": patch["operations"],
        "assertions": patch["assertions"],
        "solve_requested": patch.get("solve_requested", False),
    }
    for key in ("profile", "runtime", "redact_paths"):
        if key in patch:
            synthetic[key] = patch[key]
    validate_operation_plan(synthetic)


def _save_manifest(workspace: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(manifest))
    payload["updated_at"] = _utc_now()
    payload.pop("workspace_revision", None)
    payload["workspace_revision"] = state_revision(payload)
    handle, temporary_name = tempfile.mkstemp(prefix="workspace-", suffix=".json", dir=workspace)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, _manifest_path(workspace))
        sync_directory(workspace)
    finally:
        if temporary.exists():
            temporary.unlink()
    return payload


def load_workspace(workspace: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    path = _manifest_path(root)
    if not path.is_file():
        raise ValueError(f"Workspace manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported workspace schema: {manifest.get('schema_version')}")
    expected = manifest.get("workspace_revision")
    check = dict(manifest)
    check.pop("workspace_revision", None)
    if expected != state_revision(check):
        raise ValueError("Workspace manifest revision is invalid or was modified externally.")
    return root, manifest


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _boot_id() -> str | None:
    path = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


@contextmanager
def _workspace_lock(workspace: Path) -> Iterator[None]:
    path = workspace / _LOCK_NAME
    token = uuid.uuid4().hex
    record = {
        "token": token,
        "host": socket.gethostname(),
        "boot_id": _boot_id(),
        "pid": os.getpid(),
        "created_at": _utc_now(),
    }
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            same_host = existing.get("host") == socket.gethostname()
            current_boot = _boot_id()
            different_boot = bool(
                current_boot and existing.get("boot_id") and current_boot != existing["boot_id"]
            )
            stale = same_host and (
                different_boot
                or isinstance(existing.get("pid"), int)
                and not _pid_alive(existing["pid"])
            )
            if stale:
                path.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"Workspace is locked by {existing or 'an unknown owner'}") from None
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
            break
    else:
        raise RuntimeError("Could not acquire workspace lock.")
    try:
        yield
    finally:
        with suppress(OSError, json.JSONDecodeError):
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("token") == token:
                path.unlink()


def _candidate_path(workspace: Path, manifest: dict[str, Any]) -> Path:
    relative = manifest.get("current_project")
    if not relative:
        raise ValueError(f"Workspace has no active candidate in state {manifest['status']!r}.")
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("Workspace candidate escapes its owned directory.") from exc
    return candidate


def _remove_owned_tree(workspace: Path, path: Path) -> None:
    resolved_workspace = workspace.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError(f"Refusing to remove path outside workspace: {resolved}") from exc
    if not relative.parts or relative.parts[0] != _GENERATIONS_NAME:
        raise ValueError(f"Refusing to remove non-generation path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
        sync_directory(resolved.parent)


def _cleanup_staging(workspace: Path) -> None:
    generations = workspace / _GENERATIONS_NAME
    if not generations.is_dir():
        return
    for path in generations.glob(".stage-*"):
        _remove_owned_tree(workspace, path)


def _cleanup_orphan_generations(workspace: Path, manifest: dict[str, Any]) -> None:
    generations = workspace / _GENERATIONS_NAME
    if not generations.is_dir():
        return
    current = int(manifest.get("current_generation") or 0)
    for path in generations.iterdir():
        if path.is_dir() and path.name.isdigit() and int(path.name) > current:
            _remove_owned_tree(workspace, path)


def _cleanup_workspace_debris(workspace: Path, manifest: dict[str, Any]) -> None:
    _cleanup_staging(workspace)
    _cleanup_orphan_generations(workspace, manifest)


def _validate_source_fingerprint(
    actual: dict[str, str], expected: dict[str, str] | None
) -> dict[str, str]:
    if expected is not None:
        normalized_expected = {key: str(value).casefold() for key, value in expected.items()}
        normalized_actual = {key: value.casefold() for key, value in actual.items()}
        if normalized_expected != normalized_actual:
            raise ValueError(
                "Source fingerprint mismatch before workspace creation. "
                f"Expected {expected}, found {actual}."
            )
    return actual


def _state_unchanged(project: Path, expected: str) -> bool:
    try:
        return bundle_state_revision(project) == expected
    except (OSError, ValueError):
        return False


def begin_workspace(
    *,
    source_project: str | Path,
    workspace: str | Path,
    adapter: str,
    version: str,
    design: str,
    profile: str | None = None,
    workspace_id: str | None = None,
    source_fingerprint: dict[str, str] | None = None,
    redact_paths: bool = False,
) -> dict[str, Any]:
    source = Path(source_project).expanduser().resolve()
    root = Path(workspace).expanduser().resolve()
    if adapter not in _SUPPORTED_ADAPTERS:
        raise ValueError(f"Unsupported operation adapter: {adapter}")
    if not version.strip() or not design.strip():
        raise ValueError("Workspace version and design must be non-empty.")
    source_summary, source_state_revision = _stable_bundle_summary(source)
    pair_fingerprint = _validate_source_fingerprint(
        {
            "aedt_sha256": source_summary["aedt_sha256"],
            "edb_definition_sha256": source_summary["edb_definition_sha256"],
        },
        source_fingerprint,
    )
    if root.is_relative_to(source.with_suffix(".aedb")):
        raise ValueError("Workspace path must not be inside the frozen source EDB bundle.")
    if root.exists():
        raise ValueError(f"Workspace path already exists; overwrite is refused: {root}")
    if not root.parent.is_dir():
        raise ValueError(f"Workspace parent does not exist: {root.parent}")
    root.mkdir()
    try:
        candidate = root / _GENERATIONS_NAME / "000000" / "model.aedt"
        source_digest = source_summary["bundle_sha256"]
        copy_readback = copy_project_bundle(source, candidate)
        if bundle_state_revision(source) != source_state_revision:
            raise RuntimeError("Source project bundle changed during workspace creation.")
        created = _utc_now()
        manifest = _save_manifest(
            root,
            {
                "schema_version": 1,
                "workspace_id": workspace_id or uuid.uuid4().hex,
                "status": "draft",
                "source_project": str(source),
                "source_fingerprint": pair_fingerprint,
                "source_bundle_sha256": source_digest,
                "source_state_revision": source_state_revision,
                "adapter": adapter,
                "profile": profile,
                "version": version,
                "design": design,
                "current_generation": 0,
                "current_project": candidate.relative_to(root).as_posix(),
                "current_state_revision": bundle_state_revision(candidate),
                "journal": [],
                "assertions": [],
                "promotion": None,
                "created_at": created,
                "updated_at": created,
            },
        )
    except Exception:
        if root.exists():
            shutil.rmtree(root)
        raise
    return {
        "schema_version": 1,
        "operation": "model.workspace.begin",
        "status": "passed",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact_paths),
            "source_project": _display_path(source, redact=redact_paths),
            "adapter": adapter,
            "design": design,
        },
        "readback": {
            "workspace_status": "draft",
            "workspace_revision": manifest["workspace_revision"],
            "current_generation": 0,
            "source_unchanged": _state_unchanged(source, manifest["source_state_revision"]),
            "candidate_copy": copy_readback,
            "solve_run": False,
        },
        "artifacts": [
            {
                "path": _display_path(candidate, redact=redact_paths),
                "state_revision": manifest["current_state_revision"],
                "kind": "mutable_candidate",
            }
        ],
        "validation": [
            {"id": "source.bundle_complete", "passed": True},
            {"id": "candidate.bundle_complete", "passed": True},
        ],
        "warnings": [
            "The candidate is a mutable workspace generation, not a frozen model revision."
        ],
        "failure": None,
        "safe_next_actions": [
            "Submit one typed workspace patch using the returned workspace revision."
        ],
    }


def workspace_status(workspace: str | Path, *, redact_paths: bool = False) -> dict[str, Any]:
    root, manifest = load_workspace(workspace)
    source = Path(manifest["source_project"])
    source_unchanged = _state_unchanged(source, manifest["source_state_revision"])
    candidate_complete: bool | None = None
    candidate_unchanged: bool | None = None
    candidate_path: Path | None = None
    if manifest.get("current_project"):
        candidate_path = _candidate_path(root, manifest)
        try:
            candidate_revision = bundle_state_revision(candidate_path)
        except (OSError, ValueError):
            candidate_complete = False
            candidate_unchanged = False
        else:
            candidate_complete = True
            candidate_unchanged = candidate_revision == manifest.get("current_state_revision")
    output_complete: bool | None = None
    output_matches_manifest: bool | None = None
    if manifest["status"] == "draft":
        healthy = source_unchanged and candidate_complete is True and candidate_unchanged is True
        validations = [
            {"id": "source.unchanged", "passed": source_unchanged},
            {"id": "candidate.consistent", "passed": candidate_unchanged is True},
        ]
    elif manifest["status"] == "promoting":
        intent = manifest.get("promotion_intent") or {}
        try:
            bundle_state_revision(intent["output_project"])
        except (KeyError, OSError, ValueError):
            output_complete = False
        else:
            output_complete = True
        healthy = False
        validations = [
            {"id": "source.unchanged", "passed": source_unchanged},
            {"id": "promotion.recovery_required", "passed": False},
        ]
    elif manifest["status"] == "promoted":
        promotion = manifest.get("promotion") or {}
        try:
            output_revision = bundle_state_revision(promotion["output_project"])
        except (KeyError, OSError, ValueError):
            output_complete = False
            output_matches_manifest = False
        else:
            output_complete = True
            output_matches_manifest = output_revision == promotion.get("output_state_revision")
        healthy = output_matches_manifest is True
        validations = [
            {"id": "promoted_output.consistent", "passed": output_matches_manifest is True}
        ]
    elif manifest["status"] == "aborted":
        candidate_removed = not (root / _GENERATIONS_NAME).exists()
        healthy = candidate_removed
        validations = [{"id": "candidate.removed", "passed": candidate_removed}]
    else:
        healthy = False
        validations = [{"id": "workspace.known_state", "passed": False}]
    artifacts: list[dict[str, Any]] = []
    if manifest["status"] == "promoted" and (manifest.get("promotion") or {}).get("output_project"):
        artifacts.append(
            {
                "path": _display_path(
                    Path(manifest["promotion"]["output_project"]), redact=redact_paths
                ),
                "kind": "promoted_output",
                "bundle_sha256": manifest["promotion"].get("output_bundle_sha256"),
            }
        )
    elif candidate_path is not None:
        artifacts.append(
            {
                "path": _display_path(candidate_path, redact=redact_paths),
                "kind": "mutable_candidate",
            }
        )
    promotion_readback = manifest.get("promotion") or manifest.get("promotion_intent")
    if promotion_readback is not None:
        promotion_readback = json.loads(json.dumps(promotion_readback))
        promotion_readback.pop("validation", None)
        if redact_paths and promotion_readback.get("output_project"):
            promotion_readback["output_project"] = Path(promotion_readback["output_project"]).name
        if redact_paths and promotion_readback.get("staging_root"):
            promotion_readback["staging_root"] = Path(promotion_readback["staging_root"]).name
    recovery_pending = manifest["status"] == "promoting"
    return {
        "schema_version": 1,
        "operation": "model.workspace.status",
        "status": "ready" if healthy else "blocked",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact_paths),
            "source_project": _display_path(source, redact=redact_paths),
            "adapter": manifest["adapter"],
            "design": manifest["design"],
        },
        "readback": {
            "workspace_status": manifest["status"],
            "workspace_revision": manifest["workspace_revision"],
            "current_generation": manifest.get("current_generation"),
            "journal_length": len(manifest["journal"]),
            "source_unchanged": source_unchanged,
            "candidate_bundle_complete": candidate_complete,
            "candidate_matches_manifest": candidate_unchanged,
            "promoted_output_bundle_complete": output_complete,
            "promoted_output_matches_manifest": output_matches_manifest,
            "locked": (root / _LOCK_NAME).exists(),
            "promotion": promotion_readback,
        },
        "artifacts": artifacts,
        "validation": validations,
        "warnings": ["Promotion was interrupted; retry the exact recorded promotion request."]
        if recovery_pending
        else [],
        "failure": None
        if healthy
        else {
            "reason": "promotion_interrupted"
            if recovery_pending
            else "workspace_state_inconsistent"
        },
        "safe_next_actions": []
        if healthy
        else [
            "Retry the exact promotion id, output, retain policy, and requested revision."
            if recovery_pending
            else "Do not mutate or promote until the workspace state is reconciled."
        ],
    }


def _assert_workspace_identity(manifest: dict[str, Any], patch: dict[str, Any]) -> None:
    for field in ("adapter", "version", "design"):
        if patch[field] != manifest[field]:
            raise ValueError(
                f"Workspace {field} mismatch: workspace={manifest[field]!r} patch={patch[field]!r}"
            )
    if patch.get("profile") and patch["profile"] != manifest.get("profile"):
        raise ValueError(
            f"Workspace profile mismatch: workspace={manifest.get('profile')!r} "
            f"patch={patch['profile']!r}"
        )


def _operation_plan_for_candidate(
    manifest: dict[str, Any], patch: dict[str, Any], project: Path
) -> dict[str, Any]:
    plan = {
        "schema_version": 1,
        "operation_id": patch["patch_id"],
        "adapter": manifest["adapter"],
        "source_project": str(project),
        "output_project": str(project.parent / "unused-output.aedt"),
        "version": manifest["version"],
        "design": manifest["design"],
        "operations": patch["operations"],
        "assertions": patch["assertions"],
        "solve_requested": False,
    }
    for key in ("profile", "runtime", "redact_paths"):
        value = patch.get(key, manifest.get(key))
        if value is not None:
            plan[key] = value
    return plan


def _failed_reconcile_result(
    *,
    manifest: dict[str, Any],
    root: Path,
    patch: dict[str, Any],
    error: Exception,
    redact: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "model.workspace.reconcile",
        "status": "failed",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact),
            "patch_id": patch["patch_id"],
            "adapter": manifest["adapter"],
            "design": manifest["design"],
        },
        "readback": {
            "workspace_status": manifest["status"],
            "workspace_revision": manifest["workspace_revision"],
            "current_generation": manifest["current_generation"],
            "candidate_committed": False,
            "source_unchanged": _state_unchanged(
                Path(manifest["source_project"]), manifest["source_state_revision"]
            ),
            "solve_run": False,
        },
        "artifacts": [],
        "validation": [],
        "warnings": [],
        "failure": {"type": error.__class__.__name__, "message": str(error)},
        "safe_next_actions": [
            "Correct the typed patch and retry with the unchanged workspace revision."
        ],
    }


def reconcile_workspace(
    workspace: str | Path,
    patch: dict[str, Any],
    *,
    adapter: OperationAdapter | None = None,
    redact_paths: bool = False,
) -> dict[str, Any]:
    validate_workspace_patch(patch)
    root, _ = load_workspace(workspace)
    redact = redact_paths or bool(patch.get("redact_paths", False))
    with _workspace_lock(root):
        _, manifest = load_workspace(root)
        _cleanup_workspace_debris(root, manifest)
        if manifest["status"] != "draft":
            raise ValueError(f"Workspace is not mutable in state {manifest['status']!r}.")
        _assert_workspace_identity(manifest, patch)
        current = _candidate_path(root, manifest)
        if bundle_state_revision(current) != manifest["current_state_revision"]:
            raise ValueError("Workspace candidate changed outside the Bridge journal.")
        source = Path(manifest["source_project"])
        if bundle_state_revision(source) != manifest["source_state_revision"]:
            raise ValueError("Frozen workspace source changed; reconcile is refused.")
        digest = _canonical_digest(patch)
        prior = next(
            (item for item in manifest["journal"] if item["patch_id"] == patch["patch_id"]),
            None,
        )
        if prior:
            if prior["patch_digest"] != digest:
                raise ValueError(
                    f"Patch id {patch['patch_id']!r} was already used with different content."
                )
            return {
                "schema_version": 1,
                "operation": "model.workspace.reconcile",
                "status": "preserved",
                "identity": {
                    "workspace_id": manifest["workspace_id"],
                    "workspace": _display_path(root, redact=redact),
                    "patch_id": patch["patch_id"],
                    "adapter": manifest["adapter"],
                    "design": manifest["design"],
                },
                "readback": {
                    "workspace_status": "draft",
                    "workspace_revision": manifest["workspace_revision"],
                    "current_generation": manifest["current_generation"],
                    "idempotent_replay": True,
                    "journal_length": len(manifest["journal"]),
                    "solve_run": False,
                },
                "artifacts": [],
                "validation": prior["validation"],
                "warnings": ["The identical patch was already reconciled; no EDA call ran."],
                "failure": None,
                "safe_next_actions": [],
            }
        if patch["expected_workspace_revision"] != manifest["workspace_revision"]:
            raise ValueError(
                "Workspace revision conflict: "
                f"expected {patch['expected_workspace_revision']}, "
                f"found {manifest['workspace_revision']}."
            )
        generation = int(manifest["current_generation"]) + 1
        staging = root / _GENERATIONS_NAME / f".stage-{uuid.uuid4().hex}"
        staged_project = staging / "model.aedt"
        try:
            copy_readback = copy_project_bundle(current, staged_project)
            plan = _operation_plan_for_candidate(manifest, patch, staged_project)
            selected_adapter = adapter or _adapter_for(plan)
            if selected_adapter.adapter_id != manifest["adapter"]:
                raise ValueError(
                    "Adapter identity mismatch: "
                    f"workspace={manifest['adapter']} runtime={selected_adapter.adapter_id}"
                )
            apply_readback = selected_adapter.apply(staged_project, plan)
            verify_readback = selected_adapter.verify(staged_project, plan)
            validations = list(verify_readback.get("validation", []))
            if not validations or not all(item.get("passed") is True for item in validations):
                raise RuntimeError("One or more workspace patch assertions failed.")
            if bundle_state_revision(source) != manifest["source_state_revision"]:
                raise RuntimeError("Frozen workspace source changed during reconcile.")
            generation_dir = root / _GENERATIONS_NAME / f"{generation:06d}"
            if generation_dir.exists():
                raise RuntimeError(f"Workspace generation already exists: {generation_dir}")
            os.replace(staging, generation_dir)
            sync_directory(generation_dir.parent)
            candidate = generation_dir / "model.aedt"
            after_state_revision = bundle_state_revision(candidate)
            assertion_map = {item["id"]: item for item in manifest["assertions"]}
            assertion_map.update({item["id"]: item for item in patch["assertions"]})
            manifest["journal"].append(
                {
                    "patch_id": patch["patch_id"],
                    "patch_digest": digest,
                    "operations": patch["operations"],
                    "assertions": patch["assertions"],
                    "validation": validations,
                    "before_state_revision": manifest["current_state_revision"],
                    "after_state_revision": after_state_revision,
                    "applied_at": _utc_now(),
                }
            )
            manifest["assertions"] = list(assertion_map.values())
            manifest["current_generation"] = generation
            manifest["current_project"] = candidate.relative_to(root).as_posix()
            manifest["current_state_revision"] = after_state_revision
            manifest = _save_manifest(root, manifest)
        except Exception as exc:
            if staging.exists():
                _remove_owned_tree(root, staging)
            return _failed_reconcile_result(
                manifest=manifest,
                root=root,
                patch=patch,
                error=exc,
                redact=redact,
            )
    return {
        "schema_version": 1,
        "operation": "model.workspace.reconcile",
        "status": "passed",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact),
            "patch_id": patch["patch_id"],
            "adapter": manifest["adapter"],
            "design": manifest["design"],
        },
        "readback": {
            "workspace_status": "draft",
            "workspace_revision": manifest["workspace_revision"],
            "current_generation": generation,
            "journal_length": len(manifest["journal"]),
            "apply": apply_readback,
            "candidate_copy": copy_readback,
            "fresh_reopen": verify_readback.get("readback", {}),
            "source_unchanged": True,
            "solve_run": False,
        },
        "artifacts": [
            {
                "path": _display_path(candidate, redact=redact),
                "state_revision": manifest["current_state_revision"],
                "kind": "mutable_candidate",
            }
        ],
        "validation": validations,
        "warnings": [
            "The reconciled candidate remains mutable and has not been promoted to a revision."
        ],
        "failure": None,
        "safe_next_actions": [
            "Apply another typed patch, roll back one checkpoint, or explicitly promote."
        ],
    }


def _assert_expected_revision(manifest: dict[str, Any], expected: str) -> None:
    if expected != manifest["workspace_revision"]:
        raise ValueError(
            f"Workspace revision conflict: expected {expected}, "
            f"found {manifest['workspace_revision']}."
        )


def _rebuild_assertion_registry(journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assertions: dict[str, dict[str, Any]] = {}
    for entry in journal:
        assertions.update({item["id"]: item for item in entry["assertions"]})
    return list(assertions.values())


def rollback_workspace(
    workspace: str | Path,
    *,
    expected_workspace_revision: str,
    redact_paths: bool = False,
) -> dict[str, Any]:
    root, _ = load_workspace(workspace)
    with _workspace_lock(root):
        _, manifest = load_workspace(root)
        _cleanup_workspace_debris(root, manifest)
        if manifest["status"] != "draft":
            raise ValueError(f"Workspace cannot roll back in state {manifest['status']!r}.")
        _assert_expected_revision(manifest, expected_workspace_revision)
        if not manifest["journal"] or int(manifest["current_generation"]) <= 0:
            raise ValueError("Workspace has no reconciled patch to roll back.")
        removed = manifest["journal"].pop()
        current_generation = int(manifest["current_generation"])
        previous_generation = current_generation - 1
        previous = root / _GENERATIONS_NAME / f"{previous_generation:06d}" / "model.aedt"
        try:
            previous_state_revision = bundle_state_revision(previous)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Previous workspace checkpoint is incomplete.") from exc
        manifest["current_generation"] = previous_generation
        manifest["current_project"] = previous.relative_to(root).as_posix()
        manifest["current_state_revision"] = previous_state_revision
        manifest["assertions"] = _rebuild_assertion_registry(manifest["journal"])
        manifest = _save_manifest(root, manifest)
        removed_generation = root / _GENERATIONS_NAME / f"{current_generation:06d}"
        _remove_owned_tree(root, removed_generation)
    return {
        "schema_version": 1,
        "operation": "model.workspace.rollback",
        "status": "passed",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact_paths),
            "adapter": manifest["adapter"],
            "design": manifest["design"],
        },
        "readback": {
            "workspace_status": "draft",
            "workspace_revision": manifest["workspace_revision"],
            "current_generation": previous_generation,
            "journal_length": len(manifest["journal"]),
            "rolled_back_patch_id": removed["patch_id"],
            "source_unchanged": True,
            "solve_run": False,
        },
        "artifacts": [
            {
                "path": _display_path(previous, redact=redact_paths),
                "kind": "mutable_candidate",
            }
        ],
        "validation": [],
        "warnings": ["Rollback changed only the owned candidate workspace."],
        "failure": None,
        "safe_next_actions": ["Reconcile a corrected patch using the new workspace revision."],
    }


def abort_workspace(
    workspace: str | Path,
    *,
    expected_workspace_revision: str,
    redact_paths: bool = False,
) -> dict[str, Any]:
    root, _ = load_workspace(workspace)
    with _workspace_lock(root):
        _, manifest = load_workspace(root)
        _cleanup_workspace_debris(root, manifest)
        already_aborted = manifest["status"] == "aborted"
        if manifest["status"] not in {"draft", "aborted"}:
            raise ValueError(f"Workspace cannot abort in state {manifest['status']!r}.")
        if not already_aborted:
            _assert_expected_revision(manifest, expected_workspace_revision)
        generations = root / _GENERATIONS_NAME
        if not already_aborted:
            manifest["status"] = "aborted"
            manifest["current_project"] = None
            manifest["current_state_revision"] = None
            manifest["aborted_at"] = _utc_now()
            manifest = _save_manifest(root, manifest)
        if generations.exists():
            _remove_owned_tree(root, generations)
    return {
        "schema_version": 1,
        "operation": "model.workspace.abort",
        "status": "preserved" if already_aborted else "passed",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact_paths),
            "adapter": manifest["adapter"],
            "design": manifest["design"],
        },
        "readback": {
            "workspace_status": "aborted",
            "workspace_revision": manifest["workspace_revision"],
            "candidate_removed": True,
            "source_unchanged": True,
            "solve_run": False,
        },
        "artifacts": [],
        "validation": [],
        "warnings": [
            "The workspace was already aborted; no candidate mutation ran."
            if already_aborted
            else "The operation journal remains in the workspace manifest."
        ],
        "failure": None,
        "safe_next_actions": [],
    }


def _promotion_plan(
    manifest: dict[str, Any],
    output: Path,
    *,
    operation_id: str,
    redact_paths: bool,
) -> dict[str, Any]:
    operations = [operation for entry in manifest["journal"] for operation in entry["operations"]]
    assertions = list(manifest["assertions"])
    if not assertions:
        raise ValueError("Workspace has no final assertion registry.")
    plan = {
        "schema_version": 1,
        "operation_id": operation_id,
        "adapter": manifest["adapter"],
        "source_project": manifest["source_project"],
        "output_project": str(output),
        "version": manifest["version"],
        "design": manifest["design"],
        "operations": operations,
        "assertions": assertions,
        "source_fingerprint": manifest["source_fingerprint"],
        "solve_requested": False,
        "redact_paths": redact_paths,
    }
    if manifest.get("profile"):
        plan["profile"] = manifest["profile"]
    validate_operation_plan(plan)
    return plan


def _promotion_request_digest(plan: dict[str, Any], retain_candidate: bool) -> str:
    stable_plan = {key: value for key, value in plan.items() if key != "redact_paths"}
    return _canonical_digest({"operation_plan": stable_plan, "retain_candidate": retain_candidate})


def _promotion_stage(intent: dict[str, Any], output: Path) -> Path:
    stage = Path(str(intent.get("staging_root", ""))).expanduser().resolve()
    if stage.parent != output.parent or not stage.name.startswith(".ansysem-stage-"):
        raise ValueError("Promotion intent contains an invalid owned staging root.")
    return stage


def _remove_promotion_stage(intent: dict[str, Any], output: Path) -> None:
    stage = _promotion_stage(intent, output)
    if not stage.exists():
        return
    if not stage.is_dir() or stage.is_symlink():
        raise ValueError("Refusing to remove an invalid promotion staging path.")
    shutil.rmtree(stage)
    sync_directory(stage.parent)


def _remove_incomplete_promotion_output(intent: dict[str, Any], output: Path) -> None:
    if not intent.get("output_absent_at_start"):
        raise ValueError("Promotion intent does not own an incomplete output.")
    aedb = output.with_suffix(".aedb")
    if output.exists():
        if not output.is_file() or output.is_symlink():
            raise ValueError("Refusing to remove an invalid partial promotion project.")
        output.unlink()
    if aedb.exists():
        if not aedb.is_dir() or aedb.is_symlink():
            raise ValueError("Refusing to remove an invalid partial promotion EDB directory.")
        shutil.rmtree(aedb)
    sync_directory(output.parent)


def _assert_matching_promotion_intent(
    manifest: dict[str, Any],
    *,
    plan: dict[str, Any],
    output: Path,
    expected_workspace_revision: str,
    retain_candidate: bool,
) -> dict[str, Any]:
    intent = manifest.get("promotion_intent") or {}
    if intent.get("requested_workspace_revision") != expected_workspace_revision:
        raise ValueError("Interrupted promotion retry must use its original requested revision.")
    if Path(str(intent.get("output_project", ""))).expanduser().resolve() != output:
        raise ValueError("Interrupted promotion retry changed the output project.")
    if intent.get("promotion_id") != plan["operation_id"]:
        raise ValueError("Interrupted promotion retry changed the promotion id.")
    if bool(intent.get("retain_candidate")) != retain_candidate:
        raise ValueError("Interrupted promotion retry changed the retain-candidate policy.")
    if intent.get("request_digest") != _promotion_request_digest(plan, retain_candidate):
        raise ValueError("Interrupted promotion retry no longer matches the recorded request.")
    _promotion_stage(intent, output)
    return intent


def _verify_interrupted_promotion_output(
    manifest: dict[str, Any],
    *,
    output: Path,
    plan: dict[str, Any],
    adapter: OperationAdapter,
    redact_paths: bool,
) -> dict[str, Any]:
    source = Path(manifest["source_project"])
    source_before, _ = _stable_bundle_summary(source)
    if source_before["bundle_sha256"] != manifest["source_bundle_sha256"]:
        raise ValueError("Full source bundle digest changed during interrupted promotion.")
    verify_readback = adapter.verify(output, plan)
    validations = list(verify_readback.get("validation", []))
    if not validations or not all(item.get("passed") is True for item in validations):
        raise RuntimeError("Interrupted promotion output failed final fresh-reopen assertions.")
    source_after, _ = _stable_bundle_summary(source)
    if source_after["bundle_sha256"] != source_before["bundle_sha256"]:
        raise RuntimeError("Frozen source changed while recovering interrupted promotion.")
    output_summary, _ = _stable_bundle_summary(output)
    return {
        "schema_version": 1,
        "operation": "model.apply_transaction",
        "status": "preserved",
        "identity": {
            "operation_id": plan["operation_id"],
            "adapter": adapter.adapter_id,
            "project": _display_path(output, redact=redact_paths),
            "design": manifest["design"],
            "display": os.environ.get("DISPLAY"),
        },
        "readback": {
            "fresh_reopen": verify_readback.get("readback", {}),
            "source_unchanged": True,
            "output_bundle_complete": True,
            "output_bundle_sha256": output_summary["bundle_sha256"],
            "interrupted_promotion_recovered": True,
            "apply_replayed": False,
            "solve_requested": False,
            "solve_run": False,
        },
        "artifacts": [
            {
                "path": _display_path(output, redact=redact_paths),
                "sha256": output_summary["aedt_sha256"],
                "edb_definition_sha256": output_summary["edb_definition_sha256"],
                "bundle_sha256": output_summary["bundle_sha256"],
                "bundle_complete": True,
            }
        ],
        "validation": validations,
        "warnings": [
            "A committed output from an interrupted promotion was verified "
            "without replaying mutation."
        ],
        "failure": None,
        "safe_next_actions": [],
    }


def _reset_failed_promotion(
    root: Path, manifest: dict[str, Any], result: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest["status"] = "draft"
    manifest.pop("promotion_intent", None)
    manifest = _save_manifest(root, manifest)
    result["operation"] = "model.workspace.promote"
    result.setdefault("identity", {})["workspace_id"] = manifest["workspace_id"]
    result.setdefault("readback", {}).update(
        {
            "workspace_status": "draft",
            "workspace_revision": manifest["workspace_revision"],
            "clean_replay": True,
        }
    )
    return manifest, result


def _commit_promotion(
    root: Path,
    manifest: dict[str, Any],
    *,
    output: Path,
    plan: dict[str, Any],
    result: dict[str, Any],
    retain_candidate: bool,
    redact_paths: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest["status"] = "promoted"
    manifest.pop("promotion_intent", None)
    manifest["promotion"] = {
        "promotion_id": plan["operation_id"],
        "output_project": str(output),
        "output_bundle_sha256": result["readback"]["output_bundle_sha256"],
        "output_state_revision": bundle_state_revision(output),
        "promoted_at": _utc_now(),
        "clean_replay": True,
        "retain_candidate": retain_candidate,
        "validation": result["validation"],
    }
    manifest = _save_manifest(root, manifest)
    candidate_removed = False
    if not retain_candidate:
        _remove_owned_tree(root, root / _GENERATIONS_NAME)
        manifest["current_project"] = None
        manifest["current_state_revision"] = None
        manifest["candidate_removed_after_promotion"] = True
        manifest = _save_manifest(root, manifest)
        candidate_removed = True
    result["operation"] = "model.workspace.promote"
    result["identity"]["workspace_id"] = manifest["workspace_id"]
    result["identity"]["workspace"] = _display_path(root, redact=redact_paths)
    result["readback"].update(
        {
            "workspace_status": "promoted",
            "workspace_revision": manifest["workspace_revision"],
            "journal_length": len(manifest["journal"]),
            "clean_replay": True,
            "candidate_removed": candidate_removed,
            "source_bundle_sha256": manifest["source_bundle_sha256"],
            "output_bundle_sha256": manifest["promotion"]["output_bundle_sha256"],
        }
    )
    result.setdefault("warnings", []).append(
        "Promotion replayed the typed journal from the frozen source before committing output."
    )
    return manifest, result


def _preserved_promotion_result(
    *,
    root: Path,
    manifest: dict[str, Any],
    output: Path,
    promotion_id: str | None,
    retain_candidate: bool,
    redact_paths: bool,
) -> dict[str, Any]:
    promotion = manifest.get("promotion") or {}
    recorded_output = Path(str(promotion.get("output_project", ""))).expanduser().resolve()
    if recorded_output != output:
        raise ValueError(f"Workspace was already promoted to a different output: {recorded_output}")
    if promotion_id and promotion_id != promotion.get("promotion_id"):
        raise ValueError(
            "Workspace was already promoted with a different promotion_id: "
            f"{promotion.get('promotion_id')!r}"
        )
    if retain_candidate != bool(promotion.get("retain_candidate", False)):
        raise ValueError("Promotion retry changed the retain-candidate policy.")
    output_summary, current_output_state = _stable_bundle_summary(output)
    if output_summary["bundle_sha256"] != promotion.get("output_bundle_sha256"):
        raise ValueError("Promoted output no longer matches its recorded bundle digest.")

    manifest_changed = False
    if current_output_state != promotion.get("output_state_revision"):
        manifest["promotion"]["output_state_revision"] = current_output_state
        manifest_changed = True
    candidate_removed = not (root / _GENERATIONS_NAME).exists()
    if not retain_candidate and not candidate_removed:
        _remove_owned_tree(root, root / _GENERATIONS_NAME)
        manifest["current_project"] = None
        manifest["current_state_revision"] = None
        manifest["candidate_removed_after_promotion"] = True
        manifest_changed = True
        candidate_removed = True
    if manifest_changed:
        manifest = _save_manifest(root, manifest)
    return {
        "schema_version": 1,
        "operation": "model.workspace.promote",
        "status": "preserved",
        "identity": {
            "workspace_id": manifest["workspace_id"],
            "workspace": _display_path(root, redact=redact_paths),
            "operation_id": promotion["promotion_id"],
            "adapter": manifest["adapter"],
            "project": _display_path(output, redact=redact_paths),
            "design": manifest["design"],
            "display": os.environ.get("DISPLAY"),
        },
        "readback": {
            "workspace_status": "promoted",
            "workspace_revision": manifest["workspace_revision"],
            "journal_length": len(manifest["journal"]),
            "clean_replay": True,
            "idempotent_replay": True,
            "candidate_removed": candidate_removed,
            "source_unchanged_at_promotion": True,
            "output_bundle_complete": True,
            "source_bundle_sha256": manifest["source_bundle_sha256"],
            "output_bundle_sha256": promotion["output_bundle_sha256"],
            "solve_run": False,
        },
        "artifacts": [
            {
                "path": _display_path(output, redact=redact_paths),
                "sha256": output_summary["aedt_sha256"],
                "edb_definition_sha256": output_summary["edb_definition_sha256"],
                "bundle_sha256": output_summary["bundle_sha256"],
                "bundle_complete": True,
            }
        ],
        "validation": list(promotion.get("validation", [])),
        "warnings": ["The identical promotion was already committed; no EDA call ran."],
        "failure": None,
        "safe_next_actions": [],
    }


def promote_workspace(
    workspace: str | Path,
    *,
    output_project: str | Path,
    expected_workspace_revision: str,
    promotion_id: str | None = None,
    adapter: OperationAdapter | None = None,
    redact_paths: bool = False,
    retain_candidate: bool = False,
) -> dict[str, Any]:
    root, _ = load_workspace(workspace)
    output = Path(output_project).expanduser().resolve()
    if output.is_relative_to((root / _GENERATIONS_NAME).resolve()):
        raise ValueError("Promotion output must be outside owned candidate generations.")
    with _workspace_lock(root):
        _, manifest = load_workspace(root)
        _cleanup_workspace_debris(root, manifest)
        if manifest["status"] == "promoted":
            return _preserved_promotion_result(
                root=root,
                manifest=manifest,
                output=output,
                promotion_id=promotion_id,
                retain_candidate=retain_candidate,
                redact_paths=redact_paths,
            )
        if manifest["status"] not in {"draft", "promoting"}:
            raise ValueError(f"Workspace cannot promote in state {manifest['status']!r}.")
        source = Path(manifest["source_project"])
        operation_id = promotion_id or f"promote-{manifest['workspace_id']}"
        plan = _promotion_plan(
            manifest,
            output,
            operation_id=operation_id,
            redact_paths=redact_paths,
        )
        selected_adapter = adapter or _adapter_for(plan)
        if selected_adapter.adapter_id != manifest["adapter"]:
            raise ValueError(
                "Adapter identity mismatch: "
                f"workspace={manifest['adapter']} runtime={selected_adapter.adapter_id}"
            )

        if manifest["status"] == "promoting":
            intent = _assert_matching_promotion_intent(
                manifest,
                plan=plan,
                output=output,
                expected_workspace_revision=expected_workspace_revision,
                retain_candidate=retain_candidate,
            )
            try:
                bundle_state_revision(output)
            except (OSError, ValueError):
                if output.exists() or output.with_suffix(".aedb").exists():
                    _remove_incomplete_promotion_output(intent, output)
                _remove_promotion_stage(intent, output)
                try:
                    result = execute_operation_plan(
                        plan,
                        adapter=selected_adapter,
                        expected_source_bundle_sha256=manifest["source_bundle_sha256"],
                        staging_root=_promotion_stage(intent, output),
                    )
                except Exception:
                    manifest["status"] = "draft"
                    manifest.pop("promotion_intent", None)
                    _save_manifest(root, manifest)
                    raise
                if result["status"] != "passed":
                    _, result = _reset_failed_promotion(root, manifest, result)
                    return result
                result["readback"]["interrupted_promotion_recovered"] = True
                result["readback"]["apply_replayed"] = True
            else:
                _remove_promotion_stage(intent, output)
                result = _verify_interrupted_promotion_output(
                    manifest,
                    output=output,
                    plan=plan,
                    adapter=selected_adapter,
                    redact_paths=redact_paths,
                )
        else:
            _assert_expected_revision(manifest, expected_workspace_revision)
            if not manifest["journal"]:
                raise ValueError("Workspace has no reconciled patches to promote.")
            current = _candidate_path(root, manifest)
            if bundle_state_revision(current) != manifest["current_state_revision"]:
                raise ValueError("Workspace candidate changed outside the Bridge journal.")
            if bundle_state_revision(source) != manifest["source_state_revision"]:
                raise ValueError("Frozen workspace source changed; promotion is refused.")
            if source == output:
                raise ValueError("Frozen source and promotion output must differ.")
            if output.suffix.casefold() != ".aedt":
                raise ValueError("Promotion output must be an .aedt project.")
            if not output.parent.is_dir():
                raise ValueError(f"Promotion output parent does not exist: {output.parent}")
            if output.exists() or output.with_suffix(".aedb").exists():
                raise ValueError("Promotion output already exists; overwrite is refused.")
            stage_root = output.parent / f".ansysem-stage-{uuid.uuid4().hex}"
            manifest["status"] = "promoting"
            manifest["promotion_intent"] = {
                "promotion_id": plan["operation_id"],
                "output_project": str(output),
                "staging_root": str(stage_root),
                "retain_candidate": retain_candidate,
                "requested_workspace_revision": expected_workspace_revision,
                "request_digest": _promotion_request_digest(plan, retain_candidate),
                "output_absent_at_start": True,
                "started_at": _utc_now(),
            }
            manifest = _save_manifest(root, manifest)
            try:
                result = execute_operation_plan(
                    plan,
                    adapter=selected_adapter,
                    expected_source_bundle_sha256=manifest["source_bundle_sha256"],
                    staging_root=stage_root,
                )
            except Exception:
                manifest["status"] = "draft"
                manifest.pop("promotion_intent", None)
                _save_manifest(root, manifest)
                raise
            if result["status"] != "passed":
                _, result = _reset_failed_promotion(root, manifest, result)
                return result

        _, result = _commit_promotion(
            root,
            manifest,
            output=output,
            plan=plan,
            result=result,
            retain_candidate=retain_candidate,
            redact_paths=redact_paths,
        )
        return result
