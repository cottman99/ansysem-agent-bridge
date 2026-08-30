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
        "asset_hash": "ef493002b88c40450dc7dd8901a37e2bbf84efe4f495942caab7bc00bc29cb41",
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
    binding = compiled_shortcut_binding(operation)
    validate_compiled_shortcut_binding(
        binding,
        library_root=_ROOT,
        eda="ansys-electronics-desktop",
        version=version,
        profile="hfss3dlayout",
    )
    return binding


def shortcut_state(operation: str, *, version: str) -> dict[str, Any]:
    try:
        validate_shortcut(operation, version=version)
    except (OSError, TypeError, ValueError) as exc:
        return {"available": False, "healthy": False, "reason": str(exc)}
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


def list_assets(*, intents: list[str] | None = None, tags: list[str] | None = None):
    return list_experience_assets(_ROOT, intents=intents, tags=tags)


def get_asset(asset_id: str, *, max_chars: int = 8000):
    return get_experience_asset(_ROOT, asset_id, max_chars=max_chars)
