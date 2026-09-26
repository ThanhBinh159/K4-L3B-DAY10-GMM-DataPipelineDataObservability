from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, write_json


QUESTION_TYPES = ("summary", "authors", "date", "categories")


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(item for item in (_clean_value(item) for item in value) if item)
    if pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _row_value(row: pd.Series, joined_name: str, raw_name: str) -> str:
    return _clean_value(row.get(joined_name)) or _clean_value(row.get(raw_name))


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build a deterministic ten-question benchmark from cleaned papers."""
    if len(df) < 10:
        raise ValueError(f"At least 10 documents are required, got {len(df)}")

    test_set: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(df.head(10).iterrows()):
        paper_id = _clean_value(row.get("paper_id"))
        title = _clean_value(row.get("title"))
        if not paper_id or not title:
            raise ValueError(f"Document {index} must contain paper_id and title")

        question_type = QUESTION_TYPES[index % len(QUESTION_TYPES)]
        summary = _clean_value(row.get("summary"))
        authors = _row_value(row, "authors_joined", "authors") or "No authors listed."
        published = _clean_value(row.get("published")) or "Unknown publication date."
        categories = (
            _row_value(row, "categories_joined", "categories")
            or _clean_value(row.get("primary_category"))
            or "No category listed."
        )

        if question_type == "summary":
            question = f"What is the summary of the paper '{title}'?"
            ground_truth = first_sentence(summary) or "No summary available."
        elif question_type == "authors":
            question = f"Who are the authors of the paper '{title}'?"
            ground_truth = authors
        elif question_type == "date":
            question = f"When was the paper '{title}' published?"
            ground_truth = published
        else:
            question = f"What categories does the paper '{title}' belong to?"
            ground_truth = categories

        test_set.append(
            {
                "id": f"eval_{index + 1:03d}",
                "question_type": question_type,
                "question": question,
                "ground_truth": ground_truth,
                "ground_truth_doc_ids": [paper_id],
            }
        )

    write_json(Path(output_path), test_set)
    return test_set
