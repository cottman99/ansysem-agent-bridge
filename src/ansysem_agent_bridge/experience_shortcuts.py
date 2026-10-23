"""Asset-bound compiled shortcut registry, separate from Bridge primitives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eda_bridge_runtime import (
    get_experience_asset,
    list_experience_assets,
    validate_compiled_shortcut_binding,
)

from . import experience_recipes

_ROOT = Path(__file__).with_name("experience_assets")
_APPLIES = {
    "eda": "ansys-electronics-desktop",
    "versions": ["2026.1"],
    "profiles": ["hfss3dlayout"],
    "os": ["linux"],
}
_SHORTCUTS = {
    "model.apply": {
        "asset_id": "ansysem.model.apply-transaction",
        "asset_hash": "38d389520db1aa0bc39410fece6d7ccd4e4320d0892d3dab2121897c79e12ba8",
        "implementation_version": "model-apply-v1",
        "effect_class": "mutation",
        "plan_schema": "ansysem.operation-plan/v1",
        "validation": {"method": "fresh-reopen assertions"},
    },
    "layout.build": {
        "asset_id": "ansysem.hfss3dlayout.build",
        "asset_hash": "076d0caf1ec64bc5d1cc1dc61e44360a40702ff6e073e17658a3a6f8df42b5bb",
        "implementation_version": "layout-build-v1",
        "effect_class": "mutation",
        "plan_schema": "ansysem.hfss3dlayout-build/v1",
        "validation": {"method": "fresh-reopen project readback"},
    },
    "layout.solve": {
        "asset_id": "ansysem.hfss3dlayout.solve-and-validate",
        "asset_hash": "2c6cbb51972d8cee657024ae236af1d1f8c04beab6980897ab7f322300cee217",
        "implementation_version": "layout-solve-v1",
        "effect_class": "job",
        "plan_schema": "ansysem.hfss3dlayout-solve/v1",
        "validation": {"method": "solver artifact assertions"},
    },
}


def experience_recipe_binding(asset_id: str) -> dict[str, Any]:
    """Return a non-discoverable helper only after its experience was selected."""

    item = experience_recipes.recipe_contracts()[asset_id]
    source = Path(experience_recipes.__file__).read_bytes()
    return {
        "kind": "experience_recipe",
        "module": "ansysem_agent_bridge.experience_recipes",
        "implementation_version": "1.0.0",
        **item,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "fallback": "governed_native_execution_or_agent_compiled_plan",
    }


def compiled_shortcut_binding(operation: str) -> dict[str, Any]:
    item = _SHORTCUTS[operation]
    applies_to = {**_APPLIES, "capabilities": [operation]}
    return {
        "implements_asset_id": item["asset_id"],
        "asset_version": "1.0.0",
        "asset_schema_version": "eda.experience-asset/v1",
        "asset_content_hash": item["asset_hash"],
        "implementation_version": item["implementation_version"],
        "applies_to": applies_to,
        "effect_class": item["effect_class"],
        "parameter_schema": {
            "type": "object",
            "required": ["plan"],
            "properties": {"plan": {"schema": item["plan_schema"]}},
        },
        "validation": item["validation"],
        "fallback": "governed_native_execution",
    }


def validate_shortcut(operation: str, *, version: str) -> dict[str, Any]:
    """The compiled contract is independent of optional advisory assets."""
    binding = compiled_shortcut_binding(operation)
    if version not in binding["applies_to"]["versions"]:
        raise ValueError("Compiled workflow does not apply to the selected version")
    return binding


def shortcut_state(operation: str, *, version: str) -> dict[str, Any]:
    try:
        binding = validate_shortcut(operation, version=version)
    except (OSError, TypeError, ValueError) as exc:
        return {"available": False, "healthy": False, "reason": str(exc)}
    try:
        validate_compiled_shortcut_binding(
            binding,
            library_root=_ROOT,
            eda="ansys-electronics-desktop",
            version=version,
            profile="hfss3dlayout",
        )
    except (OSError, TypeError, ValueError) as exc:
        return {
            "available": True,
            "healthy": True,
            "asset_eligible": False,
            "guidance_warning": str(exc),
        }
    return {"available": True, "healthy": True, "asset_eligible": True}


def shortcut_receipt(
    operation: str,
    *,
    version: str,
    plan: dict[str, Any],
    validation_result: Any,
) -> dict[str, Any]:
    binding = validate_shortcut(operation, version=version)
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "implements_asset_id": binding["implements_asset_id"],
        "asset_version": binding["asset_version"],
        "asset_content_hash": binding["asset_content_hash"],
        "implementation_version": binding["implementation_version"],
        "expanded_plan_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "native_execution": "official implementation calls recorded by the workflow result",
        "validation_result": validation_result,
    }


def list_assets(
    *,
    intents: list[str] | None = None,
    tags: list[str] | None = None,
    version: str | None = None,
    profile: str | None = None,
    capability: str | None = None,
):
    result = list_experience_assets(_ROOT, intents=intents, tags=tags)

    def normalized_version(value: str) -> str:
        text = str(value or "").strip().casefold()
        return text[5:].strip() if text.startswith("aedt ") else text

    selected = []
    for asset in result["assets"]:
        applies = asset["applies_to"]
        if version and normalized_version(version) not in {
            normalized_version(item) for item in applies["versions"]
        }:
            continue
        if profile and str(profile) not in applies["profiles"]:
            continue
        if capability and str(capability) not in applies.get("capabilities", []):
            continue
        selected.append(asset)
    return {**result, "assets": selected}


def get_asset(
    asset_id: str | None = None,
    *,
    version: str | None = None,
    profile: str | None = None,
    capability: str | None = None,
    max_chars: int = 8000,
):
    selectors = {
        "version": version,
        "profile": profile,
        "capability": capability,
    }
    supplied_selectors = {key: value for key, value in selectors.items() if value}
    if asset_id and supplied_selectors:
        raise ValueError("experience.get accepts either asset_id or exact selectors, not both")
    if not asset_id:
        if any(not value for value in selectors.values()):
            raise ValueError(
                "experience.get requires asset_id or all exact selectors: "
                "version, profile, capability"
            )
        index = list_assets(
            version=version,
            profile=profile,
            capability=capability,
        )
        matches = index.get("assets", [])
        if len(matches) != 1:
            raise ValueError(
                "experience.get exact selectors matched "
                f"{len(matches)} assets; expected exactly one"
            )
        asset_id = str(matches[0]["id"])
    result = get_experience_asset(_ROOT, asset_id, max_chars=max_chars)
    operation = next(
        (operation for operation, item in _SHORTCUTS.items() if item["asset_id"] == asset_id),
        None,
    )
    if operation:
        implementation = {
            "kind": "compiled_shortcut",
            "operation": operation,
            "contract": compiled_shortcut_binding(operation),
        }
    elif asset_id in experience_recipes.recipe_contracts():
        implementation = experience_recipe_binding(asset_id)
    else:
        implementation = None
    return {**result, **({"implementation": implementation} if implementation else {})}
