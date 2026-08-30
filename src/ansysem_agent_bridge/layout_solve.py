"""Typed HFSS 3D Layout solve, numeric readback, and native report creation."""

from __future__ import annotations

import re
import shutil
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from .project_bundle import (
    bundle_content_sha256,
    commit_staged_project_bundle,
    copy_project_bundle,
)

_SCHEMA = "ansysem.hfss3dlayout-solve/v1"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_ _.-]{0,127}")
_FREQUENCY = re.compile(
    r"(?P<value>[+]?(?:\d+(?:\.\d*)?|\.\d+))(?P<unit>Hz|kHz|MHz|GHz|THz)",
    re.IGNORECASE,
)


def validate_layout_solve_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("layout.solve requires a structured plan object")
    plan = dict(value)
    allowed = {
        "schema_version",
        "operation_id",
        "source_project",
        "output_project",
        "version",
        "design",
        "source_fingerprint",
        "setup",
        "sweep",
        "expressions",
        "report_name",
        "minimum_points",
        "cores",
    }
    unknown = sorted(set(plan) - allowed)
    if unknown:
        raise ValueError("layout solve plan contains unsupported fields: " + ", ".join(unknown))
    required = (
        "schema_version",
        "operation_id",
        "source_project",
        "output_project",
        "version",
        "design",
        "setup",
        "sweep",
        "expressions",
        "report_name",
    )
    missing = [name for name in required if not plan.get(name)]
    if missing:
        raise ValueError("layout solve plan is missing: " + ", ".join(missing))
    if plan["schema_version"] != _SCHEMA:
        raise ValueError(f"unsupported layout solve schema: {plan['schema_version']}")
    for field in ("operation_id", "design", "setup", "report_name"):
        if not _IDENTIFIER.fullmatch(str(plan[field])):
            raise ValueError(f"{field} must be a bounded identifier")
    sweep = plan["sweep"]
    if not isinstance(sweep, dict) or set(sweep) != {"name", "start", "stop", "step"}:
        raise ValueError("sweep must contain name, start, stop, and step")
    if not _IDENTIFIER.fullmatch(str(sweep["name"])):
        raise ValueError("sweep.name must be a bounded identifier")
    frequencies = {}
    for field in ("start", "stop", "step"):
        match = _FREQUENCY.fullmatch(str(sweep[field]))
        if not match:
            raise ValueError(f"sweep.{field} must be a positive frequency")
        frequencies[field] = {
            "value": float(match.group("value")),
            "unit": match.group("unit"),
        }
    if len({item["unit"].casefold() for item in frequencies.values()}) != 1:
        raise ValueError("sweep frequencies must use one common unit")
    if frequencies["stop"]["value"] < frequencies["start"]["value"]:
        raise ValueError("sweep.stop must be greater than or equal to sweep.start")
    fingerprint = plan.get("source_fingerprint")
    if fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", str(fingerprint)):
        raise ValueError("source_fingerprint must be a lowercase SHA-256 digest")
    expressions = plan["expressions"]
    if not isinstance(expressions, list) or not expressions or len(expressions) > 64:
        raise ValueError("expressions must contain between 1 and 64 entries")
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > 256
        or any(character in item for character in "\r\n\x00")
        for item in expressions
    ):
        raise ValueError("expressions contains an invalid entry")
    minimum_points = plan.get("minimum_points", 1)
    cores = plan.get("cores", 1)
    if (
        not isinstance(minimum_points, int)
        or isinstance(minimum_points, bool)
        or minimum_points < 1
    ):
        raise ValueError("minimum_points must be a positive integer")
    if not isinstance(cores, int) or isinstance(cores, bool) or not 1 <= cores <= 64:
        raise ValueError("cores must be between 1 and 64")
    plan["minimum_points"] = minimum_points
    plan["cores"] = cores
    plan["expressions"] = list(expressions)
    plan["sweep"] = {"name": str(sweep["name"]), **frequencies}
    return plan


def _open_from_edb(staged_project: Path, plan: dict[str, Any]):
    from ansys.aedt.core import Hfss3dLayout

    staged_project.unlink()
    app = Hfss3dLayout(
        project=str(staged_project.with_suffix(".aedb")),
        design=str(plan["design"]),
        version=str(plan["version"]),
        non_graphical=False,
        new_desktop=True,
        close_on_exit=True,
    )
    if not app.save_project(str(staged_project)):
        app.release_desktop(close_projects=True, close_desktop=True)
        raise RuntimeError("AEDT project save-as returned failure")
    return app


def _select_sweep(app: Any, setup: str, requested: str) -> str:
    sweeps = [str(item) for item in app.existing_analysis_sweeps]
    qualified = requested if " : " in requested else f"{setup} : {requested}"
    if qualified not in sweeps:
        raise RuntimeError(f"requested sweep is unavailable: {qualified}; found {sweeps}")
    return qualified


def _finite_solution(solution: Any, expressions: list[str], minimum_points: int) -> int:
    import numpy as np

    frequencies = list(solution.primary_sweep_values)
    if len(frequencies) < minimum_points:
        raise RuntimeError(
            f"solution has {len(frequencies)} points; expected at least {minimum_points}"
        )
    real, imag = solution.full_matrix_real_imag
    for expression in expressions:
        if expression not in real or expression not in imag:
            raise RuntimeError(f"solution is missing expression data: {expression}")
        real_values = np.asarray(real[expression], dtype=float)
        imag_values = np.asarray(imag[expression], dtype=float)
        if (
            real_values.size == 0
            or imag_values.size == 0
            or not np.isfinite(real_values).all()
            or not np.isfinite(imag_values).all()
        ):
            raise RuntimeError(f"solution contains non-finite data: {expression}")
    return len(frequencies)


def execute_layout_solve_plan(value: Any, *, redact_paths: bool = True) -> dict[str, Any]:
    plan = validate_layout_solve_plan(value)
    source = Path(str(plan["source_project"])).expanduser().resolve()
    output = Path(str(plan["output_project"])).expanduser().resolve()
    exports = output.parent / f"{output.stem}_exports"
    results = Path(str(output) + "results")
    if source == output or source.parent != output.parent:
        raise ValueError("source and output projects must be distinct siblings")
    if any(path.exists() for path in (output, output.with_suffix(".aedb"), exports, results)):
        raise FileExistsError("refusing to overwrite solved output, results, or exports")
    source_before = bundle_content_sha256(source)
    if plan.get("source_fingerprint") and plan["source_fingerprint"] != source_before:
        raise ValueError("source project fingerprint does not match the plan")
    stage_root = output.parent / f".ansysem-solve-stage-{uuid.uuid4().hex}"
    staged_project = stage_root / output.name
    staged_exports = stage_root / "exports"
    app = None
    try:
        stage_root.mkdir()
        copy_result = copy_project_bundle(source, staged_project)
        staged_exports.mkdir()
        app = _open_from_edb(staged_project, plan)
        setup = str(plan["setup"])
        if setup not in [str(item) for item in app.setup_names]:
            raise RuntimeError(f"setup is unavailable: {setup}")
        sweep_spec = plan["sweep"]
        unit = sweep_spec["start"]["unit"]
        created_sweep = app.create_linear_step_sweep(
            setup=setup,
            unit=unit,
            start_frequency=sweep_spec["start"]["value"],
            stop_frequency=sweep_spec["stop"]["value"],
            step_size=sweep_spec["step"]["value"],
            name=sweep_spec["name"],
            sweep_type="Discrete",
            save_fields=False,
        )
        if not created_sweep:
            raise RuntimeError(f"failed to create discrete sweep: {sweep_spec['name']}")
        if not app.save_project():
            raise RuntimeError("AEDT project save returned failure after sweep creation")
        if not app.analyze_setup(
            name=setup,
            cores=int(plan["cores"]),
            use_auto_settings=False,
            blocking=True,
        ):
            raise RuntimeError(f"HFSS analysis failed for setup: {setup}")
        sweep = _select_sweep(app, setup, sweep_spec["name"])
        solution = app.post.get_solution_data(
            expressions=plan["expressions"], setup_sweep_name=sweep
        )
        if not solution:
            raise RuntimeError("HFSS returned no solution data")
        point_count = _finite_solution(solution, plan["expressions"], plan["minimum_points"])
        csv_path = staged_exports / "s_parameters.csv"
        if not solution.export_data_to_csv(str(csv_path), delimiter=","):
            raise RuntimeError("solution CSV export returned failure")
        report = app.post.create_report(
            expressions=plan["expressions"],
            setup_sweep_name=sweep,
            plot_name=str(plan["report_name"]),
        )
        if not report:
            raise RuntimeError("native AEDT report creation returned failure")
        if not app.save_project():
            raise RuntimeError("AEDT project save returned failure after solve")
        app.release_desktop(close_projects=True, close_desktop=True)
        app = None

        from ansys.aedt.core import Hfss3dLayout

        app = Hfss3dLayout(
            project=str(staged_project),
            design=str(plan["design"]),
            version=str(plan["version"]),
            non_graphical=False,
            new_desktop=True,
            close_on_exit=True,
        )
        reports = [str(item) for item in app.post.all_report_names]
        sweeps = [str(item) for item in app.existing_analysis_sweeps]
        if plan["report_name"] not in reports or sweep not in sweeps:
            raise RuntimeError(f"fresh-reopen result mismatch: reports={reports}, sweeps={sweeps}")
        reopened_solution = app.post.get_solution_data(
            expressions=plan["expressions"], setup_sweep_name=sweep
        )
        reopened_points = _finite_solution(
            reopened_solution, plan["expressions"], plan["minimum_points"]
        )
        app.release_desktop(close_projects=True, close_desktop=True)
        app = None
        if bundle_content_sha256(source) != source_before:
            raise RuntimeError("source project changed during solve transaction")

        staged_results = Path(str(staged_project) + "results")
        output_fingerprint = bundle_content_sha256(staged_project)
        extra_moves = [(staged_exports, exports)]
        if staged_results.exists():
            extra_moves.append((staged_results, results))
        commit_staged_project_bundle(staged_project, output, extra_moves=extra_moves)
        return {
            "status": "passed",
            "operation_id": plan["operation_id"],
            "source_preserved": True,
            "source_fingerprint": source_before,
            "output_fingerprint": output_fingerprint,
            "output_project": output.name if redact_paths else str(output),
            "copy": copy_result,
            "setup": setup,
            "sweep": sweep,
            "point_count": point_count,
            "fresh_reopen_point_count": reopened_points,
            "expressions": plan["expressions"],
            "report": plan["report_name"],
            "fresh_reopen": True,
            "artifacts": {
                "csv": str(exports / csv_path.name) if not redact_paths else csv_path.name,
                "results": str(results) if not redact_paths and results.exists() else results.name,
            },
        }
    finally:
        if app is not None:
            with suppress(Exception):
                app.release_desktop(close_projects=True, close_desktop=True)
        with suppress(OSError):
            if stage_root.exists():
                shutil.rmtree(stage_root)
