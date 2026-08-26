from ansysem_agent_bridge.models import (
    CapabilityDescriptor,
    CapabilityState,
    TargetIdentity,
    state_revision,
)


def test_state_revision_is_stable() -> None:
    payload = {"b": 2, "a": 1}
    assert state_revision(payload) == state_revision({"a": 1, "b": 2})
    assert len(state_revision(payload)) == 64


def test_target_identity_redacts_project_path() -> None:
    target = TargetIdentity(host="host", platform="Linux", project_path="/private/example.aedt")
    assert target.to_dict(redact_paths=True)["project_path"] == "example.aedt"


def test_capability_descriptor_has_separate_state_dimensions() -> None:
    descriptor = CapabilityDescriptor(
        capability_id="example",
        category="test",
        safety="safe",
        lanes=("host",),
        mutates=False,
        latency_class="fast",
        requirements=(),
        state=CapabilityState(True, True, False, True, True, "missing target", ("select target",)),
    ).to_dict()
    assert descriptor["state"]["declared"] is True
    assert descriptor["state"]["available"] is False
    assert descriptor["state"]["reason"] == "missing target"
