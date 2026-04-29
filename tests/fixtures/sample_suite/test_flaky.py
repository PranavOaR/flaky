"""Randomly failing test to demonstrate flakiness detection."""

import random


def test_sometimes_fails():
    # Fails ~40% of the time — intentionally flaky for demo purposes
    assert random.random() >= 0.4


def test_always_passes():
    assert True
