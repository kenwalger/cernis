"""Tests for per-host pacing, with injected time."""

import pytest
from fetch_support import FakeTime

from cernis.fetch.pacing import Pacer


def test_the_first_request_to_a_host_does_not_wait() -> None:
    """Nothing has gone to the host yet."""
    time = FakeTime()

    Pacer(1.0, time.clock, time.sleep).wait("example.com")

    assert time.sleeps == []


def test_a_second_request_waits_out_the_interval() -> None:
    """Back-to-back requests to one host are an interval apart."""
    time = FakeTime()
    pacer = Pacer(1.0, time.clock, time.sleep)

    pacer.wait("example.com")
    time.now += 0.25
    pacer.wait("example.com")

    assert time.sleeps == [0.75]


def test_no_wait_once_the_interval_has_passed() -> None:
    """Time spent elsewhere counts."""
    time = FakeTime()
    pacer = Pacer(1.0, time.clock, time.sleep)

    pacer.wait("example.com")
    time.now += 5
    pacer.wait("example.com")

    assert time.sleeps == []


def test_hosts_are_paced_separately() -> None:
    """A request to one host does not delay another."""
    time = FakeTime()
    pacer = Pacer(1.0, time.clock, time.sleep)

    pacer.wait("example.com")
    pacer.wait("other.example")

    assert time.sleeps == []


def test_a_negative_interval_is_rejected() -> None:
    """A negative gap means nothing."""
    time = FakeTime()
    with pytest.raises(ValueError, match="interval"):
        Pacer(-1.0, time.clock, time.sleep)
