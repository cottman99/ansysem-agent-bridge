from pathlib import Path

from eda_bridge_runtime import validate_compiled_shortcut_binding, validate_experience_library

from ansysem_agent_bridge.experience_shortcuts import get_asset, list_assets, validate_shortcut


def test_packaged_experience_library_and_all_compiled_shortcuts_match():
    root = Path(__file__).parents[1] / "src" / "ansysem_agent_bridge" / "experience_assets"
    manifest = validate_experience_library(root)

    assert len(manifest["assets"]) == 7
    for operation in ("model.apply", "layout.build", "layout.solve"):
        validate_compiled_shortcut_binding(
            validate_shortcut(operation, version="2026.1"),
            library_root=root,
            eda="ansys-electronics-desktop",
            version="2026.1",
            profile="hfss3dlayout",
        )
        assert validate_shortcut(operation, version="2026.1")["fallback"] == (
            "governed_native_execution"
        )
    selected = get_asset("ansysem.hfss3dlayout.build")
    assert selected["implementation"]["operation"] == "layout.build"
    assert (
        selected["implementation"]["contract"]["parameter_schema"]["properties"]["plan"]["schema"]
        == "ansysem.hfss3dlayout-build/v1"
    )
    selected_by_contract = get_asset(
        version="AEDT 2026.1",
        profile="hfss3dlayout",
        capability="layout.solve",
    )
    assert selected_by_contract["asset"]["id"] == ("ansysem.hfss3dlayout.solve-and-validate")


def test_engineering_recipes_are_returned_only_with_selected_experience():
    index = list_assets(intents=["correct port reference geometry"])
    assert [item["id"] for item in index["assets"]] == ["ansysem.hfss3dlayout.gap-port-reference"]
    assert "implementation" not in index["assets"][0]

    selected = get_asset("ansysem.hfss3dlayout.gap-port-reference")
    assert selected["implementation"]["kind"] == "experience_recipe"
    assert selected["implementation"]["callable"] == "compile_gap_port_plan"
    assert len(selected["implementation"]["source_sha256"]) == 64


def test_advisory_recipes_do_not_enter_exact_operation_lookup():
    selected = get_asset(
        version="2026.1",
        profile="hfss3dlayout",
        capability="model.apply",
    )
    assert selected["asset"]["id"] == "ansysem.model.apply-transaction"


def test_absent_knowledge_does_not_disable_compiled_execution(tmp_path, monkeypatch):
    from ansysem_agent_bridge import experience_shortcuts

    monkeypatch.setattr(experience_shortcuts, "_ROOT", tmp_path / "absent")
    for operation in ("model.apply", "layout.build", "layout.solve"):
        binding = validate_shortcut(operation, version="2026.1")
        state = experience_shortcuts.shortcut_state(operation, version="2026.1")
        assert binding["fallback"] == "governed_native_execution"
        assert state["available"] and state["healthy"]
        assert not state["asset_eligible"]
