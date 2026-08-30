from pathlib import Path

from eda_bridge_runtime import validate_experience_library

from ansysem_agent_bridge.experience_shortcuts import validate_shortcut


def test_packaged_experience_library_and_all_compiled_shortcuts_match():
    root = Path(__file__).parents[1] / "src" / "ansysem_agent_bridge" / "experience_assets"
    manifest = validate_experience_library(root)

    assert len(manifest["assets"]) == 3
    for operation in ("model.apply", "layout.build", "layout.solve"):
        assert validate_shortcut(operation, version="2026.1")["fallback"] == (
            "governed_native_execution"
        )
