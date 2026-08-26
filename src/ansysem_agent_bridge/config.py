from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def agent_home(*, ensure: bool = False) -> Path:
    configured = os.environ.get("ANSYSEM_AGENT_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".ansysem-agent"
    if ensure:
        root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def config_path() -> Path:
    return agent_home() / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {"schema_version": 1, "instances": [], "default_instance": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("instances"), list):
        raise ValueError(f"Unsupported AnsysEM Agent config: {path}")
    return data


def save_config(data: dict[str, Any]) -> Path:
    root = agent_home(ensure=True)
    handle, temporary_name = tempfile.mkstemp(prefix="config-", suffix=".json", dir=root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, config_path())
    finally:
        if temporary.exists():
            temporary.unlink()
    return config_path()


def upsert_instance(record: dict[str, Any], *, make_default: bool = True) -> dict[str, Any]:
    data = load_config()
    instances = [
        item for item in data["instances"] if item.get("instance_id") != record["instance_id"]
    ]
    instances.append(record)
    instances.sort(key=lambda item: str(item.get("instance_id") or ""))
    data["instances"] = instances
    if make_default:
        data["default_instance"] = record["instance_id"]
    save_config(data)
    return data
