"""Source-only descriptions from the active, explicitly selected SDK environment."""

from importlib.metadata import PackageNotFoundError, distribution

from eda_bridge_runtime.source_symbols import describe_symbols


def describe(query, *, sdk="pyaedt", limit=6):
    locations = {"pyaedt": "ansys/aedt/core", "pyedb": "pyedb"}
    if sdk not in locations:
        raise ValueError("sdk must be pyaedt or pyedb")
    try:
        package = distribution(sdk)
    except PackageNotFoundError:
        return {"status": "source_missing", "results": [], "execution_available": True}
    return describe_symbols(
        [package.locate_file(locations[sdk])],
        query,
        version=package.version,
        limit=limit,
    )
