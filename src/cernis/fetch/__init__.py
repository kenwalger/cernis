"""Fetching: robots.txt, pacing, retries, a cache, and receipts (DESIGN.md Phase 2)."""

from cernis.fetch.client import (
    USER_AGENT,
    FetchConfig,
    Fetcher,
    FetchError,
    FetchResult,
)
from cernis.fetch.robots import RobotsBasis, RobotsDecision

__all__ = [
    "USER_AGENT",
    "FetchConfig",
    "FetchError",
    "FetchResult",
    "Fetcher",
    "RobotsBasis",
    "RobotsDecision",
]
