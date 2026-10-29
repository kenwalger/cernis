"""Tests against a real HTTP server on 127.0.0.1, through Cernis's real transport.

These are the only tests that open sockets. They check that the error
mapping the mock tests assume (TIMEOUT, TLS) holds for the exceptions httpx
really raises, and that the address screen and the pinned connection work
on a real socket. The network guard allows loopback only, and the fetcher
needs ``allow_loopback`` to reach it.
"""

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Unpack

import pytest
from fetch_support import FIXED_NOW, ConfigOverrides

from cernis.fetch import USER_AGENT, FetchConfig, Fetcher
from cernis.model import ErrorKind


class _Handler(BaseHTTPRequestHandler):
    """Serves ``/robots.txt`` (404), ``/page`` (200), and ``/slow`` (stalls)."""

    requests_seen: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        """Answer one GET."""
        _Handler.requests_seen.append(self.path)
        if self.path == "/page":
            body = f"seen: {self.headers['user-agent']}".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/slow":
            time.sleep(2)
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output quiet.

        :param format: The message format.
        :param *args: The message arguments.
        """


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    """Run the server on a free loopback port for this module.

    :yield: The base address, ``127.0.0.1:<port>``.
    """
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _fetcher(tmp_path: Path, **config: Unpack[ConfigOverrides]) -> Fetcher:
    """Build a fetcher on the real transport, with pacing waits skipped.

    Loopback is allowed unless ``allow_loopback=False`` is passed.

    :param tmp_path: The cache directory.
    :param **config: Other settings.
    :return: The fetcher.
    """
    return Fetcher(
        replace(FetchConfig(cache_dir=tmp_path, allow_loopback=True), **config),
        sleep=lambda seconds: None,
        now=lambda: FIXED_NOW,
    )


def test_a_real_200_is_received(tmp_path: Path, server: str) -> None:
    """robots.txt (404) and the page are fetched over a real socket, with Cernis's agent."""
    with _fetcher(tmp_path) as fetcher:
        result = fetcher.fetch(f"http://{server}/page")

    (robots_receipt,) = result.robots_receipts
    assert robots_receipt.status_code == 404
    (receipt,) = result.receipts
    assert receipt.status_code == 200
    assert result.body == f"seen: {USER_AGENT}".encode()


def test_a_real_read_timeout_is_timeout(tmp_path: Path, server: str) -> None:
    """A server that does not answer in time gives TIMEOUT."""
    with _fetcher(tmp_path, read_timeout=0.2) as fetcher:
        result = fetcher.fetch(f"http://{server}/slow")

    assert result.receipts[0].error_kind is ErrorKind.TIMEOUT


def test_a_real_tls_failure_is_tls(tmp_path: Path, server: str) -> None:
    """An https request to a plain-http server fails TLS, so robots.txt is unreachable."""
    with _fetcher(tmp_path) as fetcher:
        result = fetcher.fetch(f"https://{server}/page")

    assert result.robots_receipts[0].error_kind is ErrorKind.TLS
    assert result.disallowed_url == f"https://{server}/page"


def test_loopback_is_refused_without_the_opt_in(tmp_path: Path, server: str) -> None:
    """By default a loopback address is refused, with a receipt and a reason, and no request."""
    _Handler.requests_seen.clear()
    with _fetcher(tmp_path, allow_loopback=False) as fetcher:
        result = fetcher.fetch(f"http://{server}/page")

    (receipt,) = result.receipts
    assert receipt.error_kind is ErrorKind.ADDRESS_REFUSED
    assert receipt.final_url == f"http://{server}/page"
    (refusal,) = result.refusals
    assert refusal.receipt_id == receipt.id
    assert "127.0.0.1 is loopback" in refusal.reason
    assert result.robots_receipts == ()
    assert _Handler.requests_seen == []


def test_the_real_transport_connects_only_to_screened_hosts(tmp_path: Path, server: str) -> None:
    """A host the fetcher did not screen and pin is refused inside the transport itself."""
    with _fetcher(tmp_path) as fetcher:
        fetcher.fetch(f"http://{server}/page")
        fetcher._network.pins.clear()
        exchange = fetcher._exchange(f"http://{server}/page")

    assert exchange.error is ErrorKind.ADDRESS_REFUSED
    assert exchange.refusal is not None
    assert "was not screened" in exchange.refusal
