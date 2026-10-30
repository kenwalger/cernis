"""Helpers for the parser tests: synthetic fixtures as receipts and bodies."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from cernis.model import ErrorKind, Receipt

FIXTURES = Path(__file__).parent / "fixtures"

DEV_URL = "https://dev.to/example-author/a-synthetic-post-1a2b"
WORDPRESS_URL = "https://blog.example.com/2026/10/a-synthetic-post/"


def fixture(name: str) -> bytes:
    """Read a fixture's bytes.

    :param name: The file name, without ``.html``.
    :return: The bytes.
    """
    return (FIXTURES / f"{name}.html").read_bytes()


def receipt_for(
    body: bytes,
    url: str = WORDPRESS_URL,
    content_type: str | None = "text/html; charset=utf-8",
    receipt_id: str = "r-001",
) -> Receipt:
    """Build the receipt a 200 with this body would have.

    :param body: The body.
    :param url: The URL that answered.
    :param content_type: The ``Content-Type`` header, or ``None`` for none.
    :param receipt_id: The receipt id.
    :return: The receipt.
    """
    headers = (("content-type", content_type),) if content_type is not None else ()
    return Receipt(
        id=receipt_id,
        requested_url=url,
        final_url=url,
        status_code=200,
        error_kind=ErrorKind.NONE,
        fetched_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        body_sha256=hashlib.sha256(body).hexdigest(),
        headers=headers,
        cernis_version="0.1.0.dev0",
        user_agent="Cernis/0.1.0.dev0 (+https://github.com/kenwalger/cernis)",
    )
