from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from core.config import Settings, load_settings
from core.utils import read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex


def _save_clean_artifacts(df: pd.DataFrame, csv_path, json_path) -> None:
    write_csv(df, csv_path)
    write_json(json_path, df.to_dict(orient="records"))


def repair_from_raw_snapshot(settings: Settings) -> pd.DataFrame:
    """Rebuild clean data from the immutable raw records snapshot."""
    repaired = build_clean_dataframe(
        load_raw_records(settings.paths.raw_records_json),
        datetime.now(UTC),
    )
    _save_clean_artifacts(
        repaired,
        settings.paths.repaired_clean_csv,
        settings.paths.repaired_clean_json,
    )
    return repaired


def run_corruption_flow_pipeline(settings: Settings) -> dict[str, dict]:
    if not settings.paths.clean_json.exists():
        raise FileNotFoundError("Run script/run_phase1.py before the corruption flow.")

    baseline_metrics = read_json(settings.paths.baseline_metrics)
    clean_df = pd.read_json(settings.paths.clean_json)
    corrupted_df = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    _save_clean_artifacts(
        corrupted_df,
        settings.paths.corrupted_clean_csv,
        settings.paths.corrupted_clean_json,
    )

    corrupted_index = LocalEmbeddingIndex.build(
        corrupted_df,
        settings,
        embeddings_output_path=settings.paths.corrupted_embeddings_json,
    )
    corrupted_bundle = evaluate_pipeline(
        settings,
        corrupted_index,
        settings.paths.eval_testset,
        settings.paths.corrupted_metrics,
        settings.paths.corrupted_answers,
    )
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")

    repaired_df = repair_from_raw_snapshot(settings)
    repaired_index = LocalEmbeddingIndex.build(
        repaired_df,
        settings,
        embeddings_output_path=settings.paths.repaired_embeddings_json,
    )
    repaired_bundle = evaluate_pipeline(
        settings,
        repaired_index,
        settings.paths.eval_testset,
        settings.paths.repaired_metrics,
        settings.paths.repaired_answers,
    )
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")

    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_metrics,
        corrupted_bundle.summary,
        repaired_bundle.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_quality["freshness"],
        repaired_quality["freshness"],
    )
    return {
        "baseline": baseline_metrics,
        "corrupted": corrupted_bundle.summary,
        "repaired": repaired_bundle.summary,
    }


def main() -> None:
    results = run_corruption_flow_pipeline(load_settings())
    print("Baseline vs Corrupted vs Repaired")
    for state in ("baseline", "corrupted", "repaired"):
        metrics = results[state]
        print(
            f"{state}: retrieval_hit_rate={metrics['retrieval_hit_rate']:.3f}, "
            f"mean_token_f1={metrics['mean_token_f1']:.3f}"
        )
