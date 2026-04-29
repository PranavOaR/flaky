"""Randomly failing test to demonstrate flakiness detection."""

import random


def test_sometimes_fails():
    # Fails ~40% of the time — intentionally flaky for demo purposes.
    val = random.random()
    assert val >= 0.4, f"random.random() returned {val}, below threshold (uses random.choice)"


def test_always_passes():
    assert True
