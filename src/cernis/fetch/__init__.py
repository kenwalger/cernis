"""Fetching: robots.txt, an address screen, pacing, retries, a cache, and receipts (Phase 2)."""

from cernis.fetch.client import (
    USER_AGENT,
    AddressRefusal,
    FetchConfig,
    Fetcher,
    FetchError,
    FetchResult,
)
from cernis.fetch.robots import RobotsBasis, RobotsDecision

__all__ = [
    "USER_AGENT",
    "AddressRefusal",
    "FetchConfig",
    "FetchError",
    "FetchResult",
    "Fetcher",
    "RobotsBasis",
    "RobotsDecision",
]
