"""Cernis: a content discoverability auditor for published articles."""

from importlib.metadata import version

# pyproject.toml is the only place the version is written; this reads it back
# from the installed distribution's metadata.
__version__: str = version("cernis")
