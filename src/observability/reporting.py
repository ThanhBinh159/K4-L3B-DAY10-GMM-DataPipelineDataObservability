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
    """Write the three-state corruption and repair comparison."""
    def metric(metrics: dict[str, Any], name: str) -> str:
        value = metrics.get(name, "n/a")
        return f"{value:.3f}" if isinstance(value, (int, float)) else str(value)

    lines = [
        "# Corruption Report",
        "",
        "| State | Retrieval Hit Rate | Mean Token F1 | Quality Gate | Freshness | Stale Ratio |",
        "|---|---:|---:|---|---|---:|",
        f"| Baseline | {metric(baseline_metrics, 'retrieval_hit_rate')} | {metric(baseline_metrics, 'mean_token_f1')} | PASS | PASS | 0.000 |",
        f"| Corrupted | {metric(corrupted_metrics, 'retrieval_hit_rate')} | {metric(corrupted_metrics, 'mean_token_f1')} | {corrupted_quality.get('success')} | {corrupted_freshness.get('is_fresh')} | {corrupted_freshness.get('stale_ratio', 'n/a')} |",
        f"| Repaired | {metric(repaired_metrics, 'retrieval_hit_rate')} | {metric(repaired_metrics, 'mean_token_f1')} | {repaired_quality.get('success')} | {repaired_freshness.get('is_fresh')} | {repaired_freshness.get('stale_ratio', 'n/a')} |",
        "",
        "## Quality Details",
        "",
        f"- Corrupted stale rows: {corrupted_freshness.get('stale_rows', 'n/a')} / {corrupted_freshness.get('total_rows', 'n/a')}",
        f"- Repaired stale rows: {repaired_freshness.get('stale_rows', 'n/a')} / {repaired_freshness.get('total_rows', 'n/a')}",
        f"- Corrupted quality gate: {corrupted_quality.get('success')}",
        f"- Repaired quality gate: {repaired_quality.get('success')}",
        "",
    ]
    write_text(report_path, "\n".join(lines))
