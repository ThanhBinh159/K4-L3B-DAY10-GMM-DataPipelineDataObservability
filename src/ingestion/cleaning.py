from __future__ import annotations

from datetime import datetime

import pandas as pd

from ingestion.crossref import PaperRecord


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _join_values(values: list[str]) -> str:
    return "; ".join(
        normalized
        for value in values
        if (normalized := _normalize_text(value))
    )


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Normalize raw records into the dataframe consumed by the RAG pipeline."""
    columns = [
        "paper_id",
        "title",
        "summary",
        "authors",
        "categories",
        "primary_category",
        "published",
        "updated",
        "abs_url",
        "pdf_url",
        "comment",
        "authors_joined",
        "categories_joined",
        "summary_chars",
        "age_days",
        "text_for_embedding",
    ]
    rows: list[dict[str, object]] = []
    for record in records:
        paper_id = _normalize_text(record.paper_id)
        title = _normalize_text(record.title)
        if not paper_id or not title:
            continue

        authors = [_normalize_text(value) for value in record.authors if _normalize_text(value)]
        categories = [
            _normalize_text(value)
            for value in record.categories
            if _normalize_text(value)
        ]
        rows.append(
            {
                "paper_id": paper_id,
                "title": title,
                "summary": _normalize_text(record.summary),
                "authors": authors,
                "categories": categories,
                "primary_category": _normalize_text(record.primary_category),
                "published": _normalize_text(record.published),
                "updated": _normalize_text(record.updated),
                "abs_url": _normalize_text(record.abs_url),
                "pdf_url": _normalize_text(record.pdf_url),
                "comment": _normalize_text(record.comment),
                "authors_joined": _join_values(authors),
                "categories_joined": _join_values(categories),
            }
        )

    frame = pd.DataFrame(rows).drop_duplicates("paper_id", keep="first")
    if frame.empty:
        return pd.DataFrame(columns=columns)

    published_dates = pd.to_datetime(frame["published"], errors="coerce", utc=True)
    updated_dates = pd.to_datetime(frame["updated"], errors="coerce", utc=True)
    run_timestamp = pd.Timestamp(run_date)
    if run_timestamp.tzinfo is None:
        run_timestamp = run_timestamp.tz_localize("UTC")
    else:
        run_timestamp = run_timestamp.tz_convert("UTC")

    frame["published"] = published_dates.dt.strftime("%Y-%m-%d").fillna("")
    frame["updated"] = updated_dates.dt.strftime("%Y-%m-%d").fillna("")
    frame["summary_chars"] = frame["summary"].str.len()
    frame["age_days"] = (run_timestamp.normalize() - published_dates.dt.normalize()).dt.days
    frame["text_for_embedding"] = (
        "Title: "
        + frame["title"]
        + "\nAuthors: "
        + frame["authors_joined"]
        + "\nPublished: "
        + frame["published"]
        + "\nCategories: "
        + frame["categories_joined"]
        + "\nSummary: "
        + frame["summary"]
    )
    return (
        frame.loc[:, columns]
        .sort_values(["published", "paper_id"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
