from __future__ import annotations

from math import ceil
from pathlib import Path

import pandas as pd

from core.utils import write_json


def _rebuild_embedding_text(row: pd.Series) -> str:
    return (
        f"Title: {row['title']}\n"
        f"Authors: {row['authors_joined']}\n"
        f"Published: {row['published']}\n"
        f"Categories: {row['categories_joined']}\n"
        f"Summary: {row['summary']}"
    )


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Apply six deterministic data corruptions and write an audit log."""
    corrupted = df.copy().reset_index(drop=True)
    operations: list[dict[str, object]] = []

    drop_count = min(max(1, ceil(len(corrupted) * 0.2)), max(0, len(corrupted) - 1))
    latest_indices = (
        corrupted.assign(_published_sort=pd.to_datetime(corrupted["published"], errors="coerce"))
        .sort_values("_published_sort", ascending=False, na_position="last")
        .head(drop_count)
        .index
        .tolist()
    )
    dropped_ids = corrupted.loc[latest_indices, "paper_id"].astype(str).tolist()
    corrupted = corrupted.drop(index=latest_indices).reset_index(drop=True)
    operations.append(
        {
            "type": "drop_latest_records",
            "count": len(dropped_ids),
            "paper_ids": dropped_ids,
        }
    )

    def target_id(position: int) -> str:
        return str(corrupted.loc[min(position, len(corrupted) - 1), "paper_id"])

    if not corrupted.empty:
        blank_index = min(0, len(corrupted) - 1)
        blank_id = target_id(0)
        corrupted.loc[blank_index, "summary"] = ""
        operations.append({"type": "blank_summary", "count": 1, "paper_ids": [blank_id]})

        noise_index = min(1, len(corrupted) - 1)
        noise_id = target_id(1)
        corrupted.loc[noise_index, "summary"] = (
            f"{corrupted.loc[noise_index, 'summary']} ### CORRUPTED_NOISE_@@@"
        ).strip()
        operations.append({"type": "inject_noise", "count": 1, "paper_ids": [noise_id]})

        title_index = min(2, len(corrupted) - 1)
        title_id = target_id(2)
        corrupted.loc[title_index, "title"] = str(corrupted.loc[title_index, "title"])[:7]
        operations.append({"type": "truncate_title", "count": 1, "paper_ids": [title_id]})

        stale_index = min(3, len(corrupted) - 1)
        stale_id = target_id(3)
        stale_date = pd.to_datetime(corrupted.loc[stale_index, "published"], errors="coerce")
        if pd.notna(stale_date):
            corrupted.loc[stale_index, "published"] = (
                stale_date - pd.Timedelta(days=365)
            ).strftime("%Y-%m-%d")
        corrupted.loc[stale_index, "age_days"] = pd.to_numeric(
            corrupted.loc[stale_index, "age_days"], errors="coerce"
        ) + 365
        operations.append({"type": "stale_date", "count": 1, "paper_ids": [stale_id]})

        duplicate_index = min(4, len(corrupted) - 1)
        duplicate_id = target_id(duplicate_index)
        corrupted = pd.concat(
            [corrupted, corrupted.iloc[[duplicate_index]].copy()],
            ignore_index=True,
        )
        operations.append({"type": "duplicate_rows", "count": 1, "paper_ids": [duplicate_id]})

    corrupted["summary_chars"] = corrupted["summary"].str.len()
    corrupted["text_for_embedding"] = corrupted.apply(_rebuild_embedding_text, axis=1)
    write_json(
        Path(output_log_path),
        {
            "original_rows": int(len(df)),
            "corrupted_rows": int(len(corrupted)),
            "operations": operations,
        },
    )
    return corrupted.reset_index(drop=True)
