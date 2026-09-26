from __future__ import annotations

from datetime import UTC, datetime

from core.config import Settings, load_settings
from core.utils import read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records, load_raw_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex


def run_phase1_pipeline(settings: Settings) -> dict:
    records_path = settings.paths.raw_records_json
    if settings.refresh_source or not records_path.exists():
        records = fetch_source_records(settings)
    else:
        records = load_raw_records(records_path)

    clean_df = build_clean_dataframe(records, datetime.now(UTC))
    write_csv(clean_df, settings.paths.clean_csv)
    write_json(settings.paths.clean_json, clean_df.to_dict(orient="records"))

    quality = run_data_quality_checks(clean_df, settings, "baseline")
    if not quality["success"]:
        raise RuntimeError("Baseline data quality gate failed.")

    index = LocalEmbeddingIndex.build(
        clean_df,
        settings,
        embeddings_output_path=settings.paths.embeddings_json,
    )
    if settings.refresh_test_set or not settings.paths.eval_testset.exists():
        build_test_set(clean_df, settings.paths.eval_testset)
    else:
        read_json(settings.paths.eval_testset)

    bundle = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        settings.paths.baseline_metrics,
        settings.paths.baseline_answers,
    )
    generate_phase1_report(
        settings.paths.baseline_report,
        {
            "source_api": settings.source_api,
            "records": len(records),
            "clean_rows": len(clean_df),
            "embedding_model": settings.embedding_model,
            "collection": settings.baseline_collection_name,
        },
        bundle.summary,
        quality,
        quality["freshness"],
    )
    return bundle.summary


def main() -> None:
    summary = run_phase1_pipeline(load_settings())
    print(
        "Baseline complete: "
        f"retrieval_hit_rate={summary['retrieval_hit_rate']:.3f}, "
        f"mean_token_f1={summary['mean_token_f1']:.3f}"
    )
