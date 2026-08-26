from ansysem_agent_bridge.live_probe import _validation_result


def test_validation_result_accepts_boolean() -> None:
    assert _validation_result(True)["passed"] is True


def test_validation_result_uses_boolean_from_release_specific_tuple() -> None:
    result = _validation_result((["validation message"], False))
    assert result["supported"] is True
    assert result["passed"] is False


def test_validation_result_does_not_treat_nonempty_unknown_value_as_success() -> None:
    assert _validation_result("unknown release shape")["passed"] is False
