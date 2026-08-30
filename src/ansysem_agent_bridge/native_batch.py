"""Governed official PyAEDT execution inside an owned project transaction."""

from __future__ import annotations

import builtins
import json
import os
import shutil
import signal
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from eda_bridge_runtime import validate_native_batch, validate_python_program_policy

from .project_bundle import (
    bundle_content_sha256,
    commit_staged_project_bundle,
    copy_project_bundle,
)

_RUNTIME = "ansys.pyaedt.hfss3dlayout"
_ALLOWED_IMPORTS = ("ansys.aedt.core", "json", "math")
_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "Exception",
        "RuntimeError",
        "ValueError",
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "range",
        "round",
        "set",
        "str",
        "sum",
        "tuple",
        "zip",
    )
}


class _ProgramTimeoutError(TimeoutError):
    pass


def _ensure_supported_platform() -> None:
    if os.name != "posix":
        raise RuntimeError("AnsysEM governed native batch is currently supported only on POSIX")


def _run_with_timeout(function, api, context, timeout_seconds: int):
    if os.name != "posix":
        raise RuntimeError("governed native batch timeout is currently available only on POSIX")

    def on_timeout(_signum, _frame):
        raise _ProgramTimeoutError(f"native batch program exceeded {timeout_seconds} seconds")

    previous = signal.signal(signal.SIGALRM, on_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return function(api, dict(context))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or not any(
        name == prefix or name.startswith(prefix + ".") for prefix in _ALLOWED_IMPORTS
    ):
        raise ImportError(f"native batch import is outside the declared runtime: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _execute_program(
    program: dict[str, str],
    *,
    entrypoint: str,
    api: Any,
    context: dict[str, Any],
    max_output_bytes: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    if program["language"] != "python":
        raise ValueError("AnsysEM native batch currently requires official Python")
    validate_python_program_policy(program["source"], allowed_import_prefixes=_ALLOWED_IMPORTS)
    namespace = {"__builtins__": {**_SAFE_BUILTINS, "__import__": _controlled_import}}
    exec(compile(program["source"], "<ansysem-native-batch>", "exec"), namespace, namespace)
    function = namespace.get(entrypoint)
    if not callable(function):
        raise ValueError(f"native batch program did not define callable {entrypoint}")
    result = _run_with_timeout(function, api, context, timeout_seconds)
    if not isinstance(result, dict):
        raise TypeError(f"native batch {entrypoint} must return an object")
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
        "utf-8"
    )
    if len(encoded) > max_output_bytes:
        raise ValueError("native batch result exceeds limits.max_output_bytes")
    return result


def _copy_results(source: Path, destination: Path) -> bool:
    source_results = Path(str(source) + "results")
    if not source_results.is_dir():
        return False
    shutil.copytree(source_results, Path(str(destination) + "results"))
    return True


def _open_project(project: Path, *, design: str, version: str):
    from ansys.aedt.core import Hfss3dLayout

    return Hfss3dLayout(
        project=str(project),
        design=design,
        version=version,
        non_graphical=False,
        new_desktop=True,
        close_on_exit=True,
    )


def _validate_ansys_plan(value: Any) -> dict[str, Any]:
    plan = validate_native_batch(value)
    if plan["runtime"] != _RUNTIME or plan["program"]["language"] != "python":
        raise ValueError(f"AnsysEM native batch supports only runtime {_RUNTIME}")
    scope = plan["scope"]
    if scope["resource_kind"] != "aedt-project" or len(scope["read_paths"]) != 1:
        raise ValueError("AnsysEM native batch requires one aedt-project read path")
    selectors = scope["selectors"]
    unknown = sorted(set(selectors) - {"version", "design", "include_results"})
    if unknown:
        raise ValueError("AnsysEM native batch selectors are unsupported: " + ", ".join(unknown))
    if not selectors.get("version") or not selectors.get("design"):
        raise ValueError("AnsysEM native batch requires version and design selectors")
    if "include_results" in selectors and not isinstance(selectors["include_results"], bool):
        raise ValueError("include_results must be boolean")
    expected_writes = 0 if plan["effect"] == "observe" else 1 + bool(scope["artifacts"])
    if len(scope["write_paths"]) != expected_writes:
        raise ValueError("AnsysEM native batch write scope does not match effect and artifacts")
    source = str(Path(scope["read_paths"][0]).expanduser().resolve())
    if (
        plan["effect"] == "staged_mutation"
        and source not in plan["transaction"]["source_fingerprints"]
    ):
        raise ValueError("AnsysEM staged mutation requires the project bundle fingerprint")
    return plan


def execute_native_batch(value: Any, *, redact_paths: bool = True) -> dict[str, Any]:
    plan = _validate_ansys_plan(value)
    _ensure_supported_platform()
    scope = plan["scope"]
    selectors = scope["selectors"]
    source = Path(scope["read_paths"][0]).expanduser().resolve()
    effect = plan["effect"]
    output = (
        Path(scope["write_paths"][0]).expanduser().resolve()
        if effect == "staged_mutation"
        else None
    )
    include_results = bool(selectors.get("include_results"))
    if output is not None and source == output:
        raise ValueError("native staged mutation refuses in-place output")
    if include_results and output is not None and source.name != output.name:
        raise ValueError("persisted AEDT results require the source and output basename to match")
    source_before = bundle_content_sha256(source)
    expected = plan["transaction"]["source_fingerprints"].get(str(source))
    if expected and expected != source_before:
        raise ValueError("native batch source fingerprint does not match")
    if output is not None:
        final_artifacts = (
            Path(scope["write_paths"][1]).expanduser().resolve() if scope["artifacts"] else None
        )
        targets = [output, output.with_suffix(".aedb"), Path(str(output) + "results")]
        if final_artifacts is not None:
            targets.append(final_artifacts)
        if any(item.exists() for item in targets):
            raise FileExistsError("native batch refuses to overwrite output or artifacts")
        stage_parent = output.parent
        staged_name = output.name
    else:
        final_artifacts = None
        stage_parent = source.parent
        staged_name = source.name
    stage_root = stage_parent / f".ansysem-native-stage-{uuid.uuid4().hex}"
    staged_project = stage_root / staged_name
    staged_artifacts = stage_root / "artifacts"
    app = None
    try:
        stage_root.mkdir(parents=True)
        copy_result = copy_project_bundle(source, staged_project)
        results_included = _copy_results(source, staged_project) if include_results else False
        if scope["artifacts"]:
            staged_artifacts.mkdir()
        context = {
            "project": str(staged_project),
            "design": str(selectors["design"]),
            "version": str(selectors["version"]),
            "artifact_root": str(staged_artifacts),
            "effect": effect,
        }
        app = _open_project(
            staged_project,
            design=str(selectors["design"]),
            version=str(selectors["version"]),
        )
        program_result = _execute_program(
            plan["program"],
            entrypoint="run",
            api=app,
            context=context,
            max_output_bytes=plan["limits"]["max_output_bytes"],
            timeout_seconds=plan["limits"]["timeout_seconds"],
        )
        if effect == "observe":
            app.release_desktop(close_projects=True, close_desktop=True)
            app = None
            if bundle_content_sha256(source) != source_before:
                raise RuntimeError("native observe batch changed the source project")
            return {
                "status": "passed",
                "batch_id": plan["batch_id"],
                "effect": effect,
                "runtime": _RUNTIME,
                "source_preserved": True,
                "source_fingerprint": source_before,
                "program_result": program_result,
                "copy": {**copy_result, "results_included": results_included},
            }

        if not app.save_project():
            raise RuntimeError("AEDT project save returned failure after native batch")
        app.release_desktop(close_projects=True, close_desktop=True)
        app = None
        app = _open_project(
            staged_project,
            design=str(selectors["design"]),
            version=str(selectors["version"]),
        )
        validation_result = _execute_program(
            plan["validation"]["program"],
            entrypoint="validate",
            api=app,
            context=context,
            max_output_bytes=plan["limits"]["max_output_bytes"],
            timeout_seconds=plan["limits"]["timeout_seconds"],
        )
        if validation_result.get("status") != "passed":
            raise RuntimeError("native batch fresh-reopen validation did not pass")
        app.release_desktop(close_projects=True, close_desktop=True)
        app = None
        for relative in plan["validation"]["required_artifacts"]:
            if not (staged_artifacts / relative).is_file():
                raise RuntimeError(f"native batch required artifact is missing: {relative}")
        if bundle_content_sha256(source) != source_before:
            raise RuntimeError("native staged mutation changed the source project")
        output_fingerprint = bundle_content_sha256(staged_project)
        extra_moves = []
        staged_results = Path(str(staged_project) + "results")
        if staged_results.exists():
            extra_moves.append((staged_results, Path(str(output) + "results")))
        if final_artifacts is not None:
            extra_moves.append((staged_artifacts, final_artifacts))
        commit_staged_project_bundle(staged_project, output, extra_moves=extra_moves)
        return {
            "status": "passed",
            "batch_id": plan["batch_id"],
            "effect": effect,
            "runtime": _RUNTIME,
            "source_preserved": True,
            "source_fingerprint": source_before,
            "output_fingerprint": output_fingerprint,
            "output_project": output.name if redact_paths else str(output),
            "program_result": program_result,
            "validation_result": validation_result,
            "fresh_reopen": True,
            "copy": {**copy_result, "results_included": results_included},
            "artifacts": scope["artifacts"],
        }
    finally:
        if app is not None:
            with suppress(Exception):
                app.release_desktop(close_projects=True, close_desktop=True)
        with suppress(OSError):
            if stage_root.exists():
                shutil.rmtree(stage_root)
