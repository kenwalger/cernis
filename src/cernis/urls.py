"""URL helpers.

Phase 3 adds the shared URL comparison function (DESIGN.md section 3, "URL
comparison") and replaces the placeholder below with its normalization.
"""


def normalize_url(url: str) -> str:
    """Normalize a URL for use in a finding key.

    TODO(Phase 3): replace with the normalization from the URL comparison
    rule in DESIGN.md section 3 (scheme and host lowercased, default port and
    fragment removed, trailing slash ignored, percent-encoding normalized).
    Until then this returns the URL unchanged, so keys depend on the exact
    string. Changing it changes every key, so finish it before any run is
    stored (Phase 5).

    :param url: The URL to normalize.
    :return: The URL, unchanged for now.
    """
    return url
