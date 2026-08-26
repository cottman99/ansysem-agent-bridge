from __future__ import annotations

import pytest

from ansysem_agent_bridge.hfss3dlayout_adapter import _set_property, outer_edge_index


class FakeEditor:
    def __init__(self) -> None:
        self.values = {"trace": {"Net": "OLD"}}

    def GetProperties(self, tab, server):
        return list(self.values[server])

    def GetPropertyValue(self, tab, server, prop):
        return self.values[server][prop]

    def ChangeProperty(self, payload):
        tab_payload = payload[1]
        server = tab_payload[1][1]
        changed = tab_payload[2][1]
        prop = changed[0].removeprefix("NAME:")
        self.values[server][prop] = changed[2]


def test_typed_property_change_has_precondition_and_readback() -> None:
    editor = FakeEditor()
    result = _set_property(
        editor,
        {
            "type": "set_property",
            "server": "trace",
            "property": "Net",
            "expected_before": "OLD",
            "value": "SIG",
        },
    )
    assert result["value"] == "SIG"
    with pytest.raises(RuntimeError, match="Precondition failed"):
        _set_property(
            editor,
            {
                "type": "set_property",
                "server": "trace",
                "property": "Net",
                "expected_before": "OLD",
                "value": "OTHER",
            },
        )


def test_outer_edge_selection_is_semantic() -> None:
    edges = [
        [[0.0, 0.0], [0.0, 2.0]],
        [[0.0, 2.0], [3.0, 2.0]],
        [[3.0, 2.0], [3.0, 0.0]],
        [[3.0, 0.0], [0.0, 0.0]],
    ]
    assert outer_edge_index(edges, "L") == 0
    assert outer_edge_index(edges, "R") == 2
    assert outer_edge_index(edges, "T") == 1
    assert outer_edge_index(edges, "B") == 3
    with pytest.raises(ValueError, match="L/R/T/B"):
        outer_edge_index(edges, "diagonal")
