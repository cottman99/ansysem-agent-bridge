"""One official-program execution path for live AEDT, owned AEDT and offline EDB."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from eda_bridge_runtime import validate_native_program
from eda_bridge_runtime.admission import assert_admission
from eda_bridge_runtime.errors import ExecutionError
from eda_bridge_runtime.process_execution import run_owned_process
from eda_bridge_runtime.promotion import promote_paths
from eda_bridge_runtime.python_execution import execute_python
from eda_bridge_runtime.retention import retain_stage

from .config import agent_home
from .native_backends import backend_for
from .project_bundle import bundle_content_sha256, commit_staged_project_bundle, copy_project_bundle


def _validate_ansys_plan(value: Any) -> dict[str, Any]:
    plan = validate_native_program(value)
    backend = backend_for(plan["runtime"], plan["mode"])
    scope = plan["scope"]
    selectors = scope["selectors"]
    if plan["program"]["language"] != "python":
        raise ExecutionError(
            "runtime_unsupported", "Ansys backends accept official Python programs"
        )
    if scope["resource_kind"] != backend.resource_kind or len(scope["read_paths"]) != 1:
        raise ValueError(f"{backend.runtime} requires one {backend.resource_kind} source")
    if not selectors.get("version") or (
        backend.resource_kind == "aedt-project" and not selectors.get("design")
    ):
        raise ValueError("An exact SDK version and applicable design are required")
    expected_writes = 0 if plan["effect"] == "observe" else 1 + bool(scope["artifacts"])
    if len(scope["write_paths"]) != expected_writes:
        raise ValueError("Declared write scope does not match effect and artifacts")
    if plan["mode"] == "live" and plan["transaction"]["strategy"] != "none":
        raise ExecutionError(
            "runtime_unsupported", "This AEDT live backend has no general vendor transaction"
        )
    if plan["mode"] == "live" and scope["artifacts"]:
        raise ValueError("Live artifacts require a dedicated artifact workflow")
    return plan


def _fingerprint(path: Path, kind: str) -> str:
    if kind == "aedt-project":
        return bundle_content_sha256(path)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def execute_native_program(
    value: Any,
    *,
    redact_paths: bool = True,
    binding: dict | None = None,
    admission: dict | None = None,
) -> dict[str, Any]:
    plan = _validate_ansys_plan(value)
    assert_admission(admission or {})
    if plan["mode"] == "live" and not binding:
        raise ExecutionError(
            "session_unavailable", "Bind a captured or owned AEDT session for live execution"
        )
    run_dir = agent_home(ensure=True) / "runtime" / "native-runs" / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    request_path, result_path = run_dir / "request.json", run_dir / "result.json"
    request_path.write_text(
        json.dumps(
            {"plan": plan, "redact_paths": redact_paths, "binding": binding, "admission": admission}
        ),
        encoding="utf-8",
    )
    try:
        completed = run_owned_process(
            [
                sys.executable,
                "-m",
                "ansysem_agent_bridge.native_program_worker",
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ],
            timeout=plan["limits"]["timeout_seconds"],
            max_output_bytes=plan["limits"]["max_output_bytes"] + 1048576,
            kill_tree=plan["mode"] != "live",
            log_path=str(run_dir / "worker.log"),
        )
        if not result_path.is_file():
            raise ExecutionError(
                "execution_uncertain",
                "Native worker returned no result",
                uncertain=True,
                evidence={"stderr": completed.stderr[-2000:]},
            )
        if result_path.stat().st_size > plan["limits"]["max_output_bytes"] + 65536:
            raise ExecutionError("output_limit", "Native worker result exceeds its bound")
        record = json.loads(result_path.read_text(encoding="utf-8"))
        if completed.returncode or not record.get("ok"):
            facts = record.get("error") or {}
            raise ExecutionError(
                facts.get("code", "execution_failed"),
                facts.get("message", "Native worker failed"),
                phase=facts.get("phase", "execution"),
                evidence={**facts.get("evidence", {}), "worker_log": str(run_dir / "worker.log")},
                uncertain=bool(facts.get("execution_uncertain")),
            )
        return record["result"]
    except ExecutionError as exc:
        exc.evidence["run_record"] = str(run_dir)
        retain_stage(run_dir, uncertain=exc.uncertain)
        raise


def execute_bound_program(
    plan: dict, *, redact_paths: bool, binding: dict | None, admission: dict
) -> dict:
    """Worker-only lifecycle; all modes use the same program and verification engine."""
    plan = _validate_ansys_plan(plan)
    assert_admission(admission)
    backend = backend_for(plan["runtime"], plan["mode"])
    scope, mode, effect = plan["scope"], plan["mode"], plan["effect"]
    source = Path(scope["read_paths"][0]).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    source_before = _fingerprint(source, backend.resource_kind)
    expected = plan["transaction"]["source_fingerprints"].get(scope["read_paths"][0])
    if expected and expected != source_before:
        raise ExecutionError("target_changed", "Source fingerprint changed before execution")
    live = mode == "live"
    output = Path(scope["write_paths"][0]).expanduser().resolve() if effect == "mutate" else None
    if live and output is not None and output != source:
        raise ValueError("Live write scope must identify the selected source project")
    if not live and output is not None and output == source:
        raise ValueError("Background and offline mutations require a distinct output")
    if (
        not live
        and output is not None
        and (output.exists() or output.with_suffix(".aedb").exists())
    ):
        raise FileExistsError("Output project or database already exists")
    stage_root = None
    succeeded = False
    app = None
    path = source
    try:
        if not live:
            parent = (
                output.parent if output else agent_home(ensure=True) / "runtime" / "native-stages"
            )
            stage_root = parent / (".native-" + uuid.uuid4().hex)
            stage_root.mkdir(parents=True)
            path = stage_root / (output.name if output else source.name)
            if backend.resource_kind == "aedt-project":
                copy_project_bundle(source, path)
                if (
                    scope["selectors"].get("include_results")
                    and Path(str(source) + "results").is_dir()
                ):
                    if source.name != path.name:
                        raise ValueError("Persisted results require matching project basenames")
                    shutil.copytree(Path(str(source) + "results"), Path(str(path) + "results"))
            else:
                shutil.copytree(source, path)
        artifacts = (
            (stage_root / "artifacts")
            if stage_root
            else agent_home(ensure=True) / "runtime" / "native-artifacts" / uuid.uuid4().hex
        )
        if scope["artifacts"]:
            artifacts.mkdir(parents=True)
        context = {
            **scope["selectors"],
            "project": str(path),
            "source_project": str(source),
            "artifact_root": str(artifacts),
            "mode": mode,
            "effect": effect,
        }
        app = backend.open(path, scope["selectors"], mode=mode, binding=binding)
        assert_admission(admission)
        result = execute_python(
            plan["program"], app, context, max_output_bytes=plan["limits"]["max_output_bytes"]
        )
        verification = None
        if effect == "mutate" and not live:
            backend.save(app)
            backend.close(app, mode=mode)
            app = None
            app = backend.open(path, scope["selectors"], mode=mode)
        if plan["validation"]["program"] is not None:
            verification = execute_python(
                plan["validation"]["program"],
                app,
                context,
                entrypoint="validate",
                max_output_bytes=plan["limits"]["max_output_bytes"],
            )
            if verification.get("status") != "passed":
                raise ExecutionError(
                    "validation_failed",
                    "Independent native validation failed",
                    phase="validation",
                    evidence={"program_result": result, "validation": verification},
                )
        backend.close(app, mode=mode)
        app = None
        for relative in plan["validation"]["required_artifacts"]:
            if not (artifacts / relative).is_file():
                raise ExecutionError(
                    "validation_failed",
                    f"Required artifact missing: {relative}",
                    phase="validation",
                )
        if not live and _fingerprint(source, backend.resource_kind) != source_before:
            raise ExecutionError("target_changed", "Original source changed during execution")
        output_fingerprint = None
        if not live and output is not None:
            assert_admission(admission)
            output_fingerprint = _fingerprint(path, backend.resource_kind)
            extra = []
            if Path(str(path) + "results").exists():
                extra.append((Path(str(path) + "results"), Path(str(output) + "results")))
            if scope["artifacts"]:
                extra.append((artifacts, Path(scope["write_paths"][1]).expanduser().resolve()))
            if backend.resource_kind == "aedt-project":
                commit_staged_project_bundle(path, output, extra_moves=extra)
            else:
                promote_paths([(path, output), *extra])
        succeeded = True
        return {
            "status": "passed",
            "program_id": plan["program_id"],
            "runtime": plan["runtime"],
            "mode": mode,
            "effect": effect,
            "execution": "completed",
            "validation": "passed" if verification else "not_requested",
            "source_preserved": not live,
            "source_fingerprint": source_before,
            "output_fingerprint": output_fingerprint,
            "program_result": result,
            "validation_result": verification,
            "fresh_reopen": effect == "mutate" and not live,
            "output_project": (output.name if redact_paths else str(output)) if output else None,
        }
    except Exception as exc:
        from eda_bridge_runtime.errors import error_facts

        facts = error_facts(exc)
        retain_stage(stage_root, uncertain=bool(facts.get("execution_uncertain")))
        evidence = {
            **facts.get("evidence", {}),
            "retained_stage": str(stage_root) if stage_root else None,
        }
        raise ExecutionError(
            facts["code"],
            facts["message"],
            phase=facts.get("phase", "execution"),
            evidence=evidence,
            uncertain=bool(facts.get("execution_uncertain")),
        ) from exc
    finally:
        if app is not None:
            with suppress(Exception):
                backend.close(app, mode=mode)
        if succeeded and stage_root is not None:
            shutil.rmtree(stage_root)
