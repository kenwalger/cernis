"""Reports: the run as JSON (complete, versioned) and as Markdown (for people)."""

from cernis.report.json_report import FORMAT, FORMAT_VERSION, report_json
from cernis.report.markdown import report_markdown

__all__ = ["FORMAT", "FORMAT_VERSION", "report_json", "report_markdown"]
