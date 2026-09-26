from __future__ import annotations

from pathlib import Path
from typing import Any

import great_expectations as gx
from great_expectations.expectations import (
    ExpectColumnValueLengthsToBeBetween,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)
import pandas as pd

from core.config import Settings
from core.utils import write_json


FRESHNESS_RATIO_LIMIT = 0.25


def _quality_report_path(settings: Settings, report_name: str) -> Path:
    if report_name == "baseline":
        return settings.paths.baseline_quality_report
    if report_name == "corrupted":
        return settings.paths.corrupted_quality_report
    return settings.paths.quality_dir / f"{report_name}_quality_report.json"


def _serialize_validation_result(result: Any) -> dict[str, Any]:
    return result.to_json_dict() if hasattr(result, "to_json_dict") else dict(result)


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Run the GX 1.x quality gate and persist its result."""
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": df})

    expectations = [
        ExpectTableRowCountToBeBetween(min_value=5, max_value=5000),
        ExpectColumnValuesToNotBeNull(column="paper_id"),
        ExpectColumnValuesToNotBeNull(column="title"),
        ExpectColumnValuesToNotBeNull(column="text_for_embedding"),
        ExpectColumnValuesToBeUnique(column="paper_id"),
        ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30),
    ]
    validation_results = [
        _serialize_validation_result(batch.validate(expectation))
        for expectation in expectations
    ]
    freshness = build_freshness_report(df, settings, settings.paths.freshness_report)
    payload = {
        "success": all(result["success"] for result in validation_results)
        and freshness["is_fresh"],
        "stage": report_name,
        "expectations": validation_results,
        "freshness": freshness,
    }
    write_json(_quality_report_path(settings, report_name), payload)
    return payload


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Summarize publication freshness and persist the SLA result."""
    published = pd.to_datetime(df["published"], errors="coerce", utc=True)
    valid_published = published.dropna()
    ages = pd.to_numeric(df["age_days"], errors="coerce")
    stale_rows = int((ages > settings.freshness_threshold_days).fillna(False).sum())
    total_rows = int(len(df))
    stale_ratio = stale_rows / total_rows if total_rows else 0.0

    report = {
        "latest_published": valid_published.max().strftime("%Y-%m-%d")
        if not valid_published.empty
        else None,
        "oldest_published": valid_published.min().strftime("%Y-%m-%d")
        if not valid_published.empty
        else None,
        "stale_rows": stale_rows,
        "total_rows": total_rows,
        "stale_ratio": stale_ratio,
        "threshold_days": settings.freshness_threshold_days,
        "stale_ratio_limit": FRESHNESS_RATIO_LIMIT,
        "is_fresh": stale_ratio <= FRESHNESS_RATIO_LIMIT,
    }
    write_json(Path(report_path), report)
    return report
