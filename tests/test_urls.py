"""Tests for the URL helpers in :mod:`cernis.urls`."""

from cernis.urls import normalize_url


def test_normalize_url_placeholder_returns_url_unchanged() -> None:
    """Until Phase 3, normalization is the identity, so keys depend on the exact URL."""
    assert normalize_url("https://Example.com/post/") == "https://Example.com/post/"
