"""Official SDK backends. Session ownership is separate from product methods."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eda_bridge_runtime.errors import ExecutionError


@dataclass(frozen=True)
class Backend:
    runtime: str
    modes: tuple[str, ...]
    resource_kind: str
    sdk_module: str

    def open(self, path: Path, selectors: dict, *, mode: str, binding: dict | None = None):
        if self.runtime == "ansys.pyedb":
            from pyedb import Edb

            return Edb(str(path), version=str(selectors["version"]), grpc=True)
        from ansys.aedt.core import Hfss3dLayout

        live = mode == "live"
        if live and not binding:
            raise ExecutionError(
                "session_unavailable", "Live execution requires an exact existing session"
            )
        kwargs = {"port": int(binding["port"])} if live else {}
        app = Hfss3dLayout(
            project=str(path),
            design=str(selectors["design"]),
            version=str(selectors["version"]),
            non_graphical=False,
            new_desktop=not live,
            close_on_exit=not live,
            **kwargs,
        )
        if live:
            actual_path = Path(str(app.project_path)) / (str(app.project_name) + ".aedt")
            if (
                int(app.odesktop.GetProcessID()) != int(binding["pid"])
                or str(app.design_name) != str(selectors["design"])
                or actual_path.resolve() != path.resolve()
            ):
                self.close(app, mode=mode)
                raise ExecutionError(
                    "target_changed", "Attached AEDT session does not match the requested target"
                )
        return app

    def save(self, app: Any) -> None:
        result = app.save() if self.runtime == "ansys.pyedb" else app.save_project()
        if result is False:
            raise ExecutionError("save_failed", "Official SDK reported a save failure")

    def close(self, app: Any, *, mode: str) -> None:
        if self.runtime == "ansys.pyedb":
            app.close()
        else:
            app.release_desktop(close_projects=mode != "live", close_desktop=mode != "live")


BACKENDS = {
    item.runtime: item
    for item in (
        Backend(
            "ansys.pyaedt.hfss3dlayout", ("live", "background"), "aedt-project", "ansys.aedt.core"
        ),
        Backend("ansys.pyedb", ("offline",), "edb-database", "pyedb"),
    )
}


def backend_for(runtime: str, mode: str) -> Backend:
    backend = BACKENDS.get(runtime)
    if backend is None or mode not in backend.modes:
        raise ExecutionError(
            "runtime_unsupported",
            f"Runtime {runtime!r} does not support mode {mode!r}",
            phase="environment",
        )
    return backend
