"""Edge-case fixtures: parametrize, unicode output, xfail, slow test."""

import time

import pytest


@pytest.mark.parametrize("value,expected", [
    (2 + 2, 4),
    (10 - 3, 7),
])
def test_with_params(value, expected):
    assert value == expected


def test_with_unicode_output():
    msg = "héllo wörld — 你好 — ✓"
    print(msg)
    assert len(msg) > 0


@pytest.mark.xfail(reason="intentional xfail for parser testing")
def test_xfail():
    assert False


def test_slow():
    time.sleep(0.1)
    assert True
