# Phase 1 Report

## Source

- **source_api:** Crossref REST API
- **records:** 24
- **clean_rows:** 24
- **embedding_model:** sentence-transformers/all-MiniLM-L6-v2
- **collection:** papers-baseline

## Metrics

- **samples:** 10
- **retrieval_hit_rate:** 1.0
- **mean_token_f1:** 0.5
- **judge_accuracy:** 0.5
- **mean_judge_score:** 3
- **ragas:** {
  "skipped": "Set RUN_RAGAS=1 to enable the slower Ragas pass."
}

## Data Quality

- **success:** True
- **stage:** baseline

## Freshness

- **latest_published:** 2026-09-15
- **oldest_published:** 2026-04-01
- **stale_rows:** 0
- **total_rows:** 24
- **stale_ratio:** 0.0
- **threshold_days:** 180
- **stale_ratio_limit:** 0.25
- **is_fresh:** True
