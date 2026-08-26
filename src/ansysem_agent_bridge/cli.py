from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .capabilities import capability_map
from .config import agent_home, load_config, upsert_instance
from .discovery import _instance_id, discover_installations, select_installation
from .docs_backend import docs_status, get_doc, query_docs
from .live_probe import live_hfss3dlayout_probe
from .operations import export_layout_image
from .project_bundle import inspect_project_bundle
from .runtime import runtime_snapshot
from .skill_installer import install_skills, skill_status, uninstall_skills


def _emit(payload: Any, *, pretty: bool) -> None:
    print(
        json.dumps(
            payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=pretty, default=str
        )
    )


def _docs_root(explicit: str | None, instance: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("ANSYSEM_DOC_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    installation = select_installation(instance)
    if installation.docs_root:
        return Path(installation.docs_root).expanduser().resolve()
    raise ValueError(
        "No documentation root configured; pass --docs-root or run setup with --docs-root."
    )


def _setup(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.aedt_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"AEDT root does not exist: {root}")
    version = args.version
    instance_id = args.instance_id or _instance_id(root, version)
    executable_candidates = (
        root / "Win64" / "ansysedt.exe",
        root / "Linux64" / "ansysedt",
        root / "ansysedt.exe",
        root / "ansysedt",
    )
    executable = next((item for item in executable_candidates if item.is_file()), None)
    record = {
        "instance_id": instance_id,
        "root": str(root),
        "version": version,
        "executable": str(executable) if executable else None,
        "docs_root": str(Path(args.docs_root).expanduser().resolve()) if args.docs_root else None,
    }
    config = upsert_instance(record, make_default=not args.no_default)
    skills = {"status": "skipped"}
    if not args.skip_skill:
        skills = install_skills("all", target=args.skill_target, force=args.force_skill)
    return {
        "status": "ready" if skills.get("status") in {"ready", "skipped"} else "attention_required",
        "instance": record,
        "skills": skills,
        "config": config,
    }


def _doctor() -> dict[str, Any]:
    records = [item.to_dict() for item in discover_installations()]
    return {
        "status": "ready" if records else "attention_required",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "display": os.environ.get("DISPLAY"),
        "agent_home": str(agent_home()),
        "config_present": bool(load_config().get("instances")),
        "pyaedt_available": importlib.util.find_spec("ansys.aedt.core") is not None,
        "pyedb_available": importlib.util.find_spec("pyedb") is not None,
        "instances": records,
        "skills": skill_status("all"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ansysem-agent", description="Local-first Ansys Electronics Desktop Agent Bridge."
    )
    parser.add_argument("--version", action="version", version=f"ansysem-agent {__version__}")
    parser.add_argument("--pretty", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor")

    setup = commands.add_parser("setup")
    setup.add_argument("--aedt-root", required=True)
    setup.add_argument("--version")
    setup.add_argument("--instance-id")
    setup.add_argument("--docs-root")
    setup.add_argument("--no-default", action="store_true")
    setup.add_argument("--skip-skill", action="store_true")
    setup.add_argument("--skill-target", choices=("codex", "agents"), default="codex")
    setup.add_argument("--force-skill", action="store_true")

    instances = commands.add_parser("instances")
    instances.add_argument("action", choices=("list",))

    project = commands.add_parser("project")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    inspect = project_sub.add_parser("inspect")
    inspect.add_argument("--project", required=True)
    inspect.add_argument("--redact-paths", action="store_true")

    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--project")
    capabilities.add_argument("--docs-root")
    capabilities.add_argument("--display")

    snapshot = commands.add_parser("runtime-snapshot")
    snapshot.add_argument("--instance")
    snapshot.add_argument("--version")
    snapshot.add_argument("--project")
    snapshot.add_argument("--design")
    snapshot.add_argument("--editor")
    snapshot.add_argument("--lane", default="host")
    snapshot.add_argument("--display")
    snapshot.add_argument("--docs-root")
    snapshot.add_argument("--since-revision")
    snapshot.add_argument("--redact-paths", action="store_true")
    snapshot.add_argument("--live", action="store_true")
    snapshot.add_argument("--port", type=int, default=0)
    snapshot.add_argument("--reuse-existing", action="store_true")
    snapshot.add_argument("--leave-open", action="store_true")
    snapshot.add_argument("--validate", action="store_true")

    layout = commands.add_parser("layout")
    layout_sub = layout.add_subparsers(dest="layout_command", required=True)
    export = layout_sub.add_parser("export-image")
    export.add_argument("--project", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--version", required=True)
    export.add_argument("--design")
    export.add_argument("--port", type=int, default=0)
    export.add_argument("--width", type=int, default=1600)
    export.add_argument("--height", type=int, default=1000)
    export.add_argument("--redact-paths", action="store_true")

    docs = commands.add_parser("docs")
    docs_sub = docs.add_subparsers(dest="docs_command", required=True)
    docs_status_parser = docs_sub.add_parser("status")
    docs_status_parser.add_argument("--docs-root")
    docs_status_parser.add_argument("--instance")
    docs_ensure = docs_sub.add_parser("ensure")
    docs_ensure.add_argument("--docs-root")
    docs_ensure.add_argument("--instance")
    query = docs_sub.add_parser("query")
    query.add_argument("query")
    query.add_argument("--docs-root")
    query.add_argument("--instance")
    query.add_argument("--module")
    query.add_argument("--limit", type=int, default=6)
    get = docs_sub.add_parser("get")
    get.add_argument("source_ref")
    get.add_argument("--docs-root")
    get.add_argument("--instance")
    get.add_argument("--focus")
    get.add_argument("--max-chars", type=int, default=4000)

    skill = commands.add_parser("skill")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    for action in ("status", "install", "uninstall"):
        item = skill_sub.add_parser(action)
        item.add_argument("selection", nargs="?", choices=("all", "bridge", "docs"), default="all")
        item.add_argument("--target", choices=("codex", "agents"), default="codex")
        item.add_argument("--root", type=Path)
        if action == "install":
            item.add_argument("--force", action="store_true")
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "doctor":
        return _doctor()
    if args.command == "setup":
        return _setup(args)
    if args.command == "instances":
        return {
            "status": "ready",
            "instances": [item.to_dict() for item in discover_installations()],
        }
    if args.command == "project":
        result = inspect_project_bundle(args.project, redact_paths=args.redact_paths)
        return {
            "status": "ready" if result["bundle_complete"] else "blocked",
            "result": result,
            "safe_next_actions": []
            if result["bundle_complete"]
            else [
                "Provide the exact .aedt project together with its matching .aedb/edb.def bundle."
            ],
        }
    if args.command == "capabilities":
        return {
            "status": "ready",
            "capabilities": capability_map(
                project=args.project, docs_root=args.docs_root, display=args.display
            ),
        }
    if args.command == "runtime-snapshot":
        if args.live:
            if not args.project or not args.version:
                raise ValueError("--live requires --project and --version.")
            return live_hfss3dlayout_probe(
                project=args.project,
                version=args.version,
                design=args.design,
                port=args.port,
                new_desktop=not args.reuse_existing,
                close_desktop=not args.leave_open,
                validate=args.validate,
                redact_paths=args.redact_paths,
                since_revision=args.since_revision,
            )
        return runtime_snapshot(
            installation_id=args.instance,
            version=args.version,
            project=args.project,
            design=args.design,
            editor=args.editor,
            lane=args.lane,
            display=args.display,
            docs_root=args.docs_root,
            since_revision=args.since_revision,
            redact_paths=args.redact_paths,
        )
    if args.command == "layout":
        return export_layout_image(
            project=args.project,
            version=args.version,
            design=args.design,
            port=args.port,
            output=args.output,
            width=args.width,
            height=args.height,
            redact_paths=args.redact_paths,
        )
    if args.command == "docs":
        root = _docs_root(args.docs_root, args.instance)
        if args.docs_command in {"status", "ensure"}:
            return docs_status(root)
        if args.docs_command == "query":
            return query_docs(root, args.query, module=args.module, limit=args.limit)
        return get_doc(root, args.source_ref, focus=args.focus, max_chars=args.max_chars)
    if args.command == "skill":
        if args.skill_command == "status":
            return skill_status(args.selection, target=args.target, root=args.root)
        if args.skill_command == "install":
            return install_skills(
                args.selection, target=args.target, root=args.root, force=args.force
            )
        return uninstall_skills(args.selection, target=args.target, root=args.root)
    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "status": "error",
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
            "safe_next_actions": [
                "Run ansysem-agent doctor and resolve the reported identity or capability "
                "prerequisite."
            ],
        }
    _emit(payload, pretty=args.pretty)
    return 0 if payload.get("status") in {"ready", "passed", "preserved", "removed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
