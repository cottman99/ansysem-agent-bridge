"""Owned worker entry point; the parent supervises wall-clock and output limits."""

import argparse
import json
from pathlib import Path

from eda_bridge_runtime.errors import error_facts

from .native_program import execute_bound_program


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        result = execute_bound_program(**request)
        record = {"ok": True, "result": result}
    except Exception as exc:
        record = {"ok": False, "error": error_facts(exc)}
    temporary = args.result.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(args.result)
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
