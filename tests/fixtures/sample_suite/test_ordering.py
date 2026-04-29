"""Order-dependent test: fails when run after test_stable's test_addition."""

_state: dict = {}


def test_setup_state():
    _state["ready"] = True


def test_depends_on_state():
    # Fails if test_setup_state hasn't run first (ordering sensitivity)
    assert _state.get("ready") is True, "state not initialised — ordering issue"
