from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from . import __version__
from .capabilities import capability_map
from .config import agent_home, load_config, remove_profile, upsert_instance, upsert_profile
from .discovery import _instance_id, discover_installations, select_installation
from .docs_backend import docs_status, get_doc, query_docs
from .live_probe import live_hfss3dlayout_probe
from .operations import export_layout_image
from .profiles import ensure_profile_process, parse_assignment, profile_status
from .project_bundle import inspect_project_bundle
from .runtime import runtime_snapshot
from .skill_installer import install_skills, skill_status, uninstall_skills
from .transaction import execute_operation_plan, load_operation_plan
from .workspace import (
    abort_workspace,
    begin_workspace,
    load_workspace,
    load_workspace_patch,
    promote_workspace,
    reconcile_workspace,
    rollback_workspace,
    workspace_status,
)


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
        skills = install_skills("bridge", target=args.skill_target, force=args.force_skill)
    return {
        "status": "ready" if skills.get("status") in {"ready", "skipped"} else "attention_required",
        "instance": record,
        "skills": skills,
        "config": config,
    }


def _doctor(profile: str | None = None) -> dict[str, Any]:
    records = [item.to_dict() for item in discover_installations()]
    runtime_profile: dict[str, Any] | None = None
    selected_profile = profile or load_config().get("default_profile")
    if selected_profile:
        runtime_profile = profile_status(selected_profile)
    return {
        "status": "ready"
        if records and (runtime_profile is None or runtime_profile["status"] == "ready")
        else "attention_required",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "display": os.environ.get("DISPLAY"),
        "agent_home": str(agent_home()),
        "config_present": bool(load_config().get("instances")),
        "pyaedt_available": importlib.util.find_spec("ansys.aedt.core") is not None,
        "pyedb_available": importlib.util.find_spec("pyedb") is not None,
        "instances": records,
        "runtime_profile": runtime_profile,
        "skills": skill_status("all"),
    }


def _profile_record(args: argparse.Namespace) -> dict[str, Any]:
    environment = dict(parse_assignment(item) for item in args.env)
    prepend_environment = dict(parse_assignment(item) for item in args.prepend_env)
    return {
        "profile_id": args.profile_id,
        "python_executable": str(Path(os.path.abspath(Path(args.python).expanduser()))),
        "display": args.display,
        "environment": environment,
        "prepend_environment": prepend_environment,
        "python_paths": [str(Path(item).expanduser().resolve()) for item in args.python_path],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ansysem-agent", description="Local-first Ansys Electronics Desktop Agent Bridge."
    )
    parser.add_argument("--version", action="version", version=f"ansysem-agent {__version__}")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--profile")
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

    profiles = commands.add_parser("profiles")
    profile_sub = profiles.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser("list")
    profile_show = profile_sub.add_parser("show")
    profile_show.add_argument("profile_id", nargs="?")
    profile_set = profile_sub.add_parser("set")
    profile_set.add_argument("--profile-id", required=True)
    profile_set.add_argument("--python", required=True)
    profile_set.add_argument("--display")
    profile_set.add_argument("--env", action="append", default=[])
    profile_set.add_argument("--prepend-env", action="append", default=[])
    profile_set.add_argument("--python-path", action="append", default=[])
    profile_set.add_argument("--no-default", action="store_true")
    profile_remove = profile_sub.add_parser("remove")
    profile_remove.add_argument("profile_id")

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

    model = commands.add_parser("model")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    apply = model_sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--redact-paths", action="store_true")

    workspace = model_sub.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_begin = workspace_sub.add_parser("begin")
    workspace_begin.add_argument("--source", required=True)
    workspace_begin.add_argument("--workspace", required=True)
    workspace_begin.add_argument(
        "--adapter",
        required=True,
        choices=("hfss3dlayout.native/v1", "hfss3dlayout.pyedb-native/v1"),
    )
    workspace_begin.add_argument("--version", required=True)
    workspace_begin.add_argument("--design", required=True)
    workspace_begin.add_argument("--workspace-id")
    workspace_begin.add_argument("--aedt-sha256")
    workspace_begin.add_argument("--edb-definition-sha256")
    workspace_begin.add_argument("--redact-paths", action="store_true")
    workspace_status_parser = workspace_sub.add_parser("status")
    workspace_status_parser.add_argument("--workspace", required=True)
    workspace_status_parser.add_argument("--redact-paths", action="store_true")
    workspace_reconcile = workspace_sub.add_parser("reconcile")
    workspace_reconcile.add_argument("--workspace", required=True)
    workspace_reconcile.add_argument("--plan", required=True)
    workspace_reconcile.add_argument("--redact-paths", action="store_true")
    workspace_rollback = workspace_sub.add_parser("rollback")
    workspace_rollback.add_argument("--workspace", required=True)
    workspace_rollback.add_argument("--expected-revision", required=True)
    workspace_rollback.add_argument("--redact-paths", action="store_true")
    workspace_abort = workspace_sub.add_parser("abort")
    workspace_abort.add_argument("--workspace", required=True)
    workspace_abort.add_argument("--expected-revision", required=True)
    workspace_abort.add_argument("--redact-paths", action="store_true")
    workspace_promote = workspace_sub.add_parser("promote")
    workspace_promote.add_argument("--workspace", required=True)
    workspace_promote.add_argument("--output", required=True)
    workspace_promote.add_argument("--expected-revision", required=True)
    workspace_promote.add_argument("--promotion-id")
    workspace_promote.add_argument("--retain-candidate", action="store_true")
    workspace_promote.add_argument("--redact-paths", action="store_true")

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

    runtime = commands.add_parser(
        "runtime", help="Submit and observe durable AnsysEM jobs over local or SSH stdio."
    )
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_serve = runtime_sub.add_parser("serve")
    runtime_serve.add_argument("--jobs", type=Path)
    runtime_serve.add_argument("--ledger", type=Path)
    runtime_status_parser = runtime_sub.add_parser("job-status")
    runtime_status_parser.add_argument("--jobs", type=Path)
    runtime_status_parser.add_argument("--job-id", required=True)
    runtime_events = runtime_sub.add_parser("job-events")
    runtime_events.add_argument("--jobs", type=Path)
    runtime_events.add_argument("--job-id", required=True)
    runtime_events.add_argument("--after-cursor", type=int, default=0)
    runtime_worker = runtime_sub.add_parser("worker", help=argparse.SUPPRESS)
    runtime_worker.add_argument("--jobs", type=Path, required=True)
    runtime_worker.add_argument("--ledger", type=Path, required=True)
    runtime_worker.add_argument("--job-id", required=True)

    context_addin = commands.add_parser("context-addin")
    context_addin_sub = context_addin.add_subparsers(dest="context_addin_command", required=True)
    for action in ("install", "status", "uninstall"):
        item = context_addin_sub.add_parser(action)
        item.add_argument("--personal-lib", type=Path)
        if action == "install":
            item.add_argument("--version")
            item.add_argument("--port", type=int)
            item.add_argument("--process-id", type=int)
    context_refresh = context_addin_sub.add_parser("refresh")
    context_refresh.add_argument("--version", required=True)
    context_refresh.add_argument("--port", required=True, type=int)
    context_refresh.add_argument("--process-id", required=True, type=int)
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "context-addin":
        from .context_addin import install, refresh, status, uninstall

        if args.context_addin_command == "install":
            return install(
                args.personal_lib,
                version=args.version,
                port=args.port,
                process_id=args.process_id,
            )
        if args.context_addin_command == "status":
            return status(args.personal_lib)
        if args.context_addin_command == "refresh":
            return refresh(version=args.version, port=args.port, process_id=args.process_id)
        return uninstall(args.personal_lib)
    if args.command == "runtime":
        from .runtime_adapter import (
            default_jobs_path,
            default_ledger_path,
            run_worker,
            serve,
        )

        jobs_path = args.jobs or default_jobs_path()
        if args.runtime_command == "serve":
            # main() redirects vendor chatter to stderr to protect the normal
            # one-document CLI contract. The framed Runtime protocol must keep
            # its dedicated real stdio channel instead of inheriting that redirect.
            serve(
                jobs_path,
                args.ledger or default_ledger_path(),
                sys.__stdin__,
                sys.__stdout__,
                profile_id=args.profile,
            )
            return {"status": "ready", "state": "stopped"}
        if args.runtime_command == "worker":
            return run_worker(jobs_path, args.ledger, args.job_id).to_dict()
        from eda_bridge_runtime import JobStore

        store = JobStore(jobs_path)
        if args.runtime_command == "job-status":
            return {"status": "ready", "job": store.get(args.job_id)}
        return {
            "status": "ready",
            "job_id": args.job_id,
            "events": store.events(args.job_id, args.after_cursor),
        }
    if args.command == "doctor":
        return _doctor(args.profile)
    if args.command == "setup":
        return _setup(args)
    if args.command == "instances":
        return {
            "status": "ready",
            "instances": [item.to_dict() for item in discover_installations()],
        }
    if args.command == "profiles":
        if args.profile_command == "list":
            config = load_config()
            return {
                "status": "ready",
                "default_profile": config.get("default_profile"),
                "profiles": config.get("profiles", []),
            }
        if args.profile_command == "show":
            return profile_status(args.profile_id)
        if args.profile_command == "set":
            record = _profile_record(args)
            config = upsert_profile(record, make_default=not args.no_default)
            return {
                "status": "ready",
                "profile": record,
                "default_profile": config.get("default_profile"),
            }
        config = remove_profile(args.profile_id)
        return {
            "status": "removed",
            "profile_id": args.profile_id,
            "default_profile": config.get("default_profile"),
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
    if args.command == "model":
        if args.model_command == "apply":
            plan = load_operation_plan(args.plan)
            plan_profile = plan.get("profile")
            if args.profile and plan_profile and args.profile != plan_profile:
                raise ValueError(f"Profile mismatch: command={args.profile} plan={plan_profile}")
            if args.redact_paths:
                plan["redact_paths"] = True
            return execute_operation_plan(plan)
        if args.workspace_command == "begin":
            if bool(args.aedt_sha256) != bool(args.edb_definition_sha256):
                raise ValueError(
                    "--aedt-sha256 and --edb-definition-sha256 must be supplied together."
                )
            fingerprint = None
            if args.aedt_sha256:
                fingerprint = {
                    "aedt_sha256": args.aedt_sha256,
                    "edb_definition_sha256": args.edb_definition_sha256,
                }
            selected_profile = args.profile or load_config().get("default_profile")
            return begin_workspace(
                source_project=args.source,
                workspace=args.workspace,
                adapter=args.adapter,
                version=args.version,
                design=args.design,
                profile=selected_profile,
                workspace_id=args.workspace_id,
                source_fingerprint=fingerprint,
                redact_paths=args.redact_paths,
            )
        if args.workspace_command == "status":
            return workspace_status(args.workspace, redact_paths=args.redact_paths)
        if args.workspace_command == "reconcile":
            patch = load_workspace_patch(args.plan)
            if args.redact_paths:
                patch["redact_paths"] = True
            return reconcile_workspace(args.workspace, patch, redact_paths=args.redact_paths)
        if args.workspace_command == "rollback":
            return rollback_workspace(
                args.workspace,
                expected_workspace_revision=args.expected_revision,
                redact_paths=args.redact_paths,
            )
        if args.workspace_command == "abort":
            return abort_workspace(
                args.workspace,
                expected_workspace_revision=args.expected_revision,
                redact_paths=args.redact_paths,
            )
        return promote_workspace(
            args.workspace,
            output_project=args.output,
            expected_workspace_revision=args.expected_revision,
            promotion_id=args.promotion_id,
            redact_paths=args.redact_paths,
            retain_candidate=args.retain_candidate,
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


def _exit_code(payload: dict[str, Any]) -> int:
    return 0 if payload.get("status") in {"ready", "passed", "preserved", "removed"} else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(effective_argv)
    try:
        # Keep the public stdout contract to exactly one JSON document. Vendor
        # packages may print during import or execution; those diagnostics belong
        # on stderr and must not force callers to scrape a mixed stream.
        with redirect_stdout(sys.stderr):
            selected_profile = args.profile
            model_needs_profile = False
            if args.command == "model":
                if args.model_command == "apply":
                    model_needs_profile = True
                    if not selected_profile:
                        if args.plan == "-":
                            raise ValueError(
                                "--profile is required when an operation plan is read from stdin."
                            )
                        selected_profile = load_operation_plan(args.plan).get("profile")
                elif args.workspace_command in {"reconcile", "promote"}:
                    model_needs_profile = True
                    _, manifest = load_workspace(args.workspace)
                    workspace_profile = manifest.get("profile")
                    if (
                        selected_profile
                        and workspace_profile
                        and selected_profile != workspace_profile
                    ):
                        raise ValueError(
                            "Profile mismatch: "
                            f"command={selected_profile} workspace={workspace_profile}"
                        )
                    selected_profile = selected_profile or workspace_profile
            needs_profile = (
                args.command == "layout"
                or model_needs_profile
                or args.command == "runtime-snapshot"
                and args.live
                or args.command == "capabilities"
                and bool(selected_profile)
                or args.command == "runtime"
                and args.runtime_command == "worker"
                and bool(selected_profile)
                or args.command == "context-addin"
                and args.context_addin_command in {"install", "uninstall", "refresh"}
            )
            if needs_profile:
                ensure_profile_process(selected_profile, effective_argv)
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
    return _exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())
