from __future__ import annotations

import json
from typing import Any

from core.utils import write_text


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write the baseline pipeline summary as a Markdown report."""
    lines = [
        "# Phase 1 Report",
        "",
        "## Source",
        "",
        *[f"- **{key}:** {_format_value(value)}" for key, value in source_summary.items()],
        "",
        "## Metrics",
        "",
        *[f"- **{key}:** {_format_value(value)}" for key, value in metrics.items()],
        "",
        "## Data Quality",
        "",
        f"- **success:** {quality.get('success')}",
        f"- **stage:** {quality.get('stage')}",
        "",
        "## Freshness",
        "",
        *[f"- **{key}:** {_format_value(value)}" for key, value in freshness.items()],
        "",
    ]
    write_text(report_path, "\n".join(lines))


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """TODO(student): viet markdown report so sanh baseline/corrupted/repaired."""
    raise NotImplementedError("Student task: implement corruption comparison report.")
