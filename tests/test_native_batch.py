import hashlib
from pathlib import Path

import pytest

from ansysem_agent_bridge.native_batch import _execute_program, _validate_ansys_plan


def _program(entrypoint: str, body: str = "return {'status': 'passed'}"):
    source = f"def {entrypoint}(api, context):\n    {body}\n"
    return {
        "language": "python",
        "source": source,
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
    }


def _observe():
    return {
        "schema_version": "eda.native-batch/v1",
        "batch_id": "inspect_layout",
        "runtime": "ansys.pyaedt.hfss3dlayout",
        "effect": "observe",
        "program": _program("run", "return {'design': context['design']}"),
        "scope": {
            "resource_kind": "aedt-project",
            "selectors": {"version": "2026.1", "design": "Layout1"},
            "read_paths": ["/projects/demo.aedt"],
            "write_paths": [],
            "artifacts": [],
        },
        "transaction": {
            "strategy": "none",
            "source_fingerprints": {},
            "fresh_reopen": False,
            "promotion": "none",
        },
        "validation": {"program": None, "required_artifacts": []},
        "limits": {"timeout_seconds": 60, "max_output_bytes": 65536},
    }


def test_ansys_native_observe_accepts_exact_official_runtime():
    assert _validate_ansys_plan(_observe())["runtime"] == "ansys.pyaedt.hfss3dlayout"


def test_ansys_native_batch_rejects_unregistered_runtime():
    plan = _observe()
    plan["runtime"] = "ansys.unknown"
    with pytest.raises(ValueError, match="supports only runtime"):
        _validate_ansys_plan(plan)


def test_governed_program_receives_api_and_context_and_returns_bounded_json(monkeypatch):
    from ansysem_agent_bridge import native_batch

    monkeypatch.setattr(
        native_batch,
        "_run_with_timeout",
        lambda function, api, context, _timeout: function(api, context),
    )
    plan = _observe()
    result = _execute_program(
        plan["program"],
        entrypoint="run",
        api=object(),
        context={"design": "Layout1"},
        max_output_bytes=1024,
        timeout_seconds=1,
    )
    assert result == {"design": "Layout1"}


def test_governed_program_rejects_shell_import():
    source = "import subprocess\ndef run(api, context):\n    return {}\n"
    with pytest.raises(ValueError, match="undeclared module"):
        _execute_program(
            {
                "language": "python",
                "source": source,
                "sha256": hashlib.sha256(source.encode()).hexdigest(),
            },
            entrypoint="run",
            api=object(),
            context={},
            max_output_bytes=1024,
            timeout_seconds=1,
        )


def test_observe_result_reports_the_fingerprint_already_used_for_source_protection(
    monkeypatch, tmp_path: Path
):
    from ansysem_agent_bridge import native_batch

    source = tmp_path / "source.aedt"
    source.write_text("fixture")
    plan = _observe()
    plan["scope"]["read_paths"] = [str(source)]
    monkeypatch.setattr(native_batch, "bundle_content_sha256", lambda _path: "a" * 64)
    monkeypatch.setattr(
        native_batch,
        "copy_project_bundle",
        lambda source, destination: {"method": "copy"},
    )
    monkeypatch.setattr(
        native_batch,
        "_execute_program",
        lambda *args, **kwargs: {"design": "Layout1"},
    )

    class App:
        def release_desktop(self, **kwargs):
            return True

    monkeypatch.setattr(native_batch, "_open_project", lambda *args, **kwargs: App())
    monkeypatch.setattr(native_batch, "_ensure_supported_platform", lambda: None)

    result = native_batch.execute_native_batch(plan)

    assert result["source_fingerprint"] == "a" * 64
