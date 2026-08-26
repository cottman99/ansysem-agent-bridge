from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from .models import CapabilityDescriptor, CapabilityState
from .project_bundle import inspect_project_bundle


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def capability_descriptors(
    *,
    project: str | Path | None = None,
    docs_root: str | Path | None = None,
    display: str | None = None,
) -> list[CapabilityDescriptor]:
    project_path = Path(project).expanduser().resolve() if project else None
    project_file_ready = bool(
        project_path and project_path.is_file() and project_path.suffix.casefold() == ".aedt"
    )
    project_ready = bool(
        project_file_ready
        and inspect_project_bundle(project_path, redact_paths=True).get("bundle_complete")
    )
    docs_path = Path(docs_root).expanduser().resolve() if docs_root else None
    docs_ready = bool(docs_path and docs_path.is_dir())
    pyaedt_ready = _module_available("ansys.aedt.core")
    pyedb_ready = _module_available("pyedb")
    active_display = display or os.environ.get("DISPLAY")

    return [
        CapabilityDescriptor(
            capability_id="installation.discovery",
            category="runtime",
            safety="safe",
            lanes=("host",),
            mutates=False,
            latency_class="fast",
            requirements=(),
            state=CapabilityState(True, True, True, True, True),
            evidence=("configured instances", "environment capability roots"),
        ),
        CapabilityDescriptor(
            capability_id="project.inspect",
            category="project",
            safety="safe",
            lanes=("host",),
            mutates=False,
            latency_class="fast",
            requirements=("explicit .aedt path",),
            state=CapabilityState(
                True,
                True,
                project_file_ready,
                True,
                True,
                None if project_file_ready else "An explicit readable .aedt project is required.",
                ("Pass --project with the exact project path.",) if not project_file_ready else (),
            ),
            evidence=(".aedt hash", ".aedb/edb.def presence"),
        ),
        CapabilityDescriptor(
            capability_id="docs.query",
            category="knowledge",
            safety="safe",
            lanes=("docs",),
            mutates=False,
            latency_class="fast",
            requirements=("configured local documentation root",),
            state=CapabilityState(
                True,
                True,
                docs_ready,
                True,
                True,
                None if docs_ready else "No local documentation root is configured.",
                ("Run setup with --docs-root or pass --docs-root.",) if not docs_ready else (),
            ),
            evidence=("bounded local source matches",),
        ),
        CapabilityDescriptor(
            capability_id="aedt.live_snapshot",
            category="runtime",
            safety="bounded",
            lanes=("pyaedt-live",),
            mutates=False,
            latency_class="moderate",
            requirements=("PyAEDT", "explicit project", "graphical display when required"),
            state=CapabilityState(
                True,
                pyaedt_ready,
                pyaedt_ready and project_ready,
                bool(active_display) or os.name == "nt",
                True,
                None
                if pyaedt_ready and project_ready and (active_display or os.name == "nt")
                else (
                    "PyAEDT, a complete .aedt/.aedb project bundle, and a usable display "
                    "are required for this lane."
                ),
                tuple(
                    action
                    for condition, action in (
                        (
                            not pyaedt_ready,
                            "Use the AEDT host Python environment with PyAEDT installed.",
                        ),
                        (
                            not project_ready,
                            "Provide the exact .aedt file with its matching .aedb/edb.def bundle.",
                        ),
                        (
                            not active_display and os.name != "nt",
                            "Set the intended DISPLAY for graphical AEDT.",
                        ),
                    )
                    if condition
                ),
            ),
            evidence=("live project/design readback", "AEDT process identity"),
        ),
        CapabilityDescriptor(
            capability_id="aedt.layout_export_image",
            category="artifact",
            safety="bounded",
            lanes=("native-aedt", "pyaedt-live"),
            mutates=False,
            latency_class="moderate",
            requirements=("live HFSS 3D Layout editor", "explicit output path"),
            state=CapabilityState(
                True,
                pyaedt_ready,
                pyaedt_ready and project_ready,
                bool(active_display) or os.name == "nt",
                True,
                None
                if pyaedt_ready and project_ready
                else "The live HFSS 3D Layout lane is not ready.",
                ("Establish a live snapshot for the exact project first.",)
                if not (pyaedt_ready and project_ready)
                else (),
            ),
            evidence=("exported image hash", "live editor identity"),
        ),
        CapabilityDescriptor(
            capability_id="edb.offline_probe",
            category="runtime",
            safety="safe",
            lanes=("pyedb-offline",),
            mutates=False,
            latency_class="moderate",
            requirements=("PyEDB", "complete .aedb bundle"),
            state=CapabilityState(
                True,
                pyedb_ready,
                pyedb_ready and project_ready,
                True,
                True,
                None if pyedb_ready else "PyEDB is unavailable in the selected Python environment.",
                ("Use the AEDT host Python environment with PyEDB installed.",)
                if not pyedb_ready
                else (),
            ),
            evidence=("EDB open/readback",),
        ),
    ]


def capability_map(**kwargs: Any) -> dict[str, dict[str, Any]]:
    return {item.capability_id: item.to_dict() for item in capability_descriptors(**kwargs)}
