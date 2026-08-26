from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def state_revision(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Installation:
    instance_id: str
    root: str
    version: str | None
    executable: str | None
    source: str
    docs_root: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TargetIdentity:
    host: str
    platform: str
    installation_id: str | None = None
    version: str | None = None
    display: str | None = None
    pid: int | None = None
    project_path: str | None = None
    project_name: str | None = None
    design_name: str | None = None
    editor: str | None = None
    lane: str = "host"

    def to_dict(self, *, redact_paths: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        if redact_paths and self.project_path:
            payload["project_path"] = Path(self.project_path).name
        return payload


@dataclass(frozen=True)
class CapabilityState:
    declared: bool
    compatible: bool
    available: bool
    healthy: bool
    authorized: bool
    reason: str | None = None
    safe_next_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["safe_next_actions"] = list(self.safe_next_actions)
        return payload


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    category: str
    safety: str
    lanes: tuple[str, ...]
    mutates: bool
    latency_class: str
    requirements: tuple[str, ...]
    state: CapabilityState
    schema_version: int = 1
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.capability_id,
            "category": self.category,
            "safety": self.safety,
            "lanes": list(self.lanes),
            "mutates": self.mutates,
            "latency_class": self.latency_class,
            "requirements": list(self.requirements),
            "state": self.state.to_dict(),
            "evidence": list(self.evidence),
        }
