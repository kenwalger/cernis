"""A local cache of response bodies for conditional requests (DESIGN.md section 6).

Each cached URL has a small JSON entry with its validators (``ETag`` and
``Last-Modified``) and the SHA-256 of its body. Bodies are stored once, under
their hash. A body whose hash no longer matches its name is treated as
missing, so a damaged cache can cost a full fetch but never supply the wrong
body.

The cache is an optimization. Any problem reading or writing it is treated
as a cache miss, never as a fetch failure. Reads are bounded: an entry
larger than a few kilobytes, a body larger than the fetcher's size limit, or
anything that is not a regular file is a miss.

The cache is the user's own local state, like a browser cache. Its hashes
detect damage, not tampering: anyone who can write the cache directory can
choose what a later ``304`` is taken to validate.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CACHE_DIR = Path(".cernis-cache")
"""The cache directory used when none is given, relative to the working directory."""

# A validator is sent back as a request header, so only visible ASCII and
# spaces are accepted; anything else is a miss.
_HEADER_VALUE = re.compile(r"[\x20-\x7e]+")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_ENTRY_BYTES = 16 * 1024
_DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, kw_only=True)
class CacheEntry:
    """A cached body and the validators to revalidate it.

    :param url: The request URL the body was the answer to.
    :param etag: The ``ETag`` the server sent, if any.
    :param last_modified: The ``Last-Modified`` the server sent, if any.
    :param body: The body, as stored.
    :param body_sha256: The SHA-256 of ``body``, in lowercase hex.
    """

    url: str
    etag: str | None
    last_modified: str | None
    body: bytes
    body_sha256: str


def _usable_validator(value: object) -> str | None:
    """Return ``value`` if it can be sent back as a header value, else ``None``.

    :param value: A value read from a cache entry.
    :return: The value, or ``None``.
    """
    if isinstance(value, str) and _HEADER_VALUE.fullmatch(value):
        return value
    return None


def _read_bounded(path: Path, limit: int) -> bytes | None:
    """Read a regular file of at most ``limit`` bytes.

    :param path: The file.
    :param limit: The most bytes it may hold.
    :return: Its contents, or ``None`` if it is missing, not a regular file,
        larger than ``limit``, or unreadable.
    """
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        return None
    return data if len(data) <= limit else None


def _write_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file in the same directory.

    :param path: The destination.
    :param data: The bytes to write. An :class:`OSError` from writing is
        left to the caller.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        # After a successful replace the temporary name is gone already.
        Path(temporary).unlink(missing_ok=True)


class Cache:
    """A cache directory holding entries and bodies.

    The directory is created on first write, with a ``.gitignore`` that
    ignores everything in it, so a cache placed inside a repository is never
    committed. A directory that already exists is used as it is.

    :param directory: The cache directory.
    :param max_body_bytes: The largest body the cache returns, so a body
        stored under a larger limit is never reused.
    """

    def __init__(self, directory: Path, max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES) -> None:
        self._directory = directory
        self._max_body_bytes = max_body_bytes

    def _entry_path(self, url: str) -> Path:
        """Return where the entry for ``url`` is stored.

        :param url: The request URL.
        :return: A path named by the URL's SHA-256, so no URL can choose it.
        """
        name = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._directory / "entries" / f"{name}.json"

    def _body_path(self, body_sha256: str) -> Path:
        """Return where a body with this hash is stored.

        :param body_sha256: The body's SHA-256, in lowercase hex.
        :return: The path.
        """
        return self._directory / "bodies" / body_sha256

    def lookup(self, url: str) -> CacheEntry | None:
        """Return the cached entry for ``url`` if it is whole and usable.

        :param url: The request URL.
        :return: The entry, or ``None`` if there is none, it cannot be read,
            it has no usable validator, or its body is missing, too large, or
            does not match its hash.
        """
        raw = _read_bounded(self._entry_path(url), _MAX_ENTRY_BYTES)
        if raw is None:
            return None
        try:
            record = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            return None
        if not isinstance(record, dict) or record.get("url") != url:
            return None
        etag = _usable_validator(record.get("etag"))
        last_modified = _usable_validator(record.get("last_modified"))
        digest = record.get("body_sha256")
        if (etag is None and last_modified is None) or not (
            isinstance(digest, str) and _SHA256_HEX.fullmatch(digest)
        ):
            return None
        body = _read_bounded(self._body_path(digest), self._max_body_bytes)
        if body is None or hashlib.sha256(body).hexdigest() != digest:
            return None
        return CacheEntry(
            url=url, etag=etag, last_modified=last_modified, body=body, body_sha256=digest
        )

    def store(self, url: str, *, etag: str | None, last_modified: str | None, body: bytes) -> None:
        """Cache ``body`` as the answer to ``url``, or forget ``url`` if it cannot be revalidated.

        :param url: The request URL.
        :param etag: The response's ``ETag``, if any.
        :param last_modified: The response's ``Last-Modified``, if any.
        :param body: The whole response body.
        """
        etag = _usable_validator(etag)
        last_modified = _usable_validator(last_modified)
        if etag is None and last_modified is None:
            self.drop(url)
            return
        digest = hashlib.sha256(body).hexdigest()
        record = {"url": url, "etag": etag, "last_modified": last_modified, "body_sha256": digest}
        try:
            if not self._directory.exists():
                self._directory.mkdir(parents=True)
                self._write_gitignore()
            body_path = self._body_path(digest)
            stored = _read_bounded(body_path, len(body))
            if stored is None or hashlib.sha256(stored).hexdigest() != digest:
                _write_atomically(body_path, body)
            _write_atomically(self._entry_path(url), json.dumps(record).encode("utf-8"))
        except OSError:
            return

    def refresh(self, entry: CacheEntry, *, etag: str | None, last_modified: str | None) -> None:
        """Update an entry's validators after a ``304``, keeping any the response left out.

        :param entry: The entry the ``304`` validated.
        :param etag: The ``304``'s ``ETag``, if any.
        :param last_modified: The ``304``'s ``Last-Modified``, if any.
        """
        new_etag = _usable_validator(etag) or entry.etag
        new_last_modified = _usable_validator(last_modified) or entry.last_modified
        if (new_etag, new_last_modified) != (entry.etag, entry.last_modified):
            self.store(entry.url, etag=new_etag, last_modified=new_last_modified, body=entry.body)

    def drop(self, url: str) -> None:
        """Forget the entry for ``url``, if any. Bodies are kept, since others may share them.

        :param url: The request URL.
        """
        try:
            self._entry_path(url).unlink(missing_ok=True)
        except OSError:
            return

    def _write_gitignore(self) -> None:
        """Write a ``.gitignore`` that ignores everything, into a directory Cernis just created.

        Only a directory Cernis created gets one, so pointing the cache at an
        existing directory never hides that directory's files from git. An
        :class:`OSError` from writing it is left to the caller.
        """
        _write_atomically(
            self._directory / ".gitignore",
            b"# Created by Cernis: the cache is never committed.\n*\n",
        )
