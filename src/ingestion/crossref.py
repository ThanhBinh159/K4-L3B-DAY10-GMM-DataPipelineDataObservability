from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.config import Settings


CROSSREF_WORKS_URL = "https://api.crossref.org/works"
CROSSREF_ROWS = 30
REQUEST_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def _clean_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(part) for part in value if part)
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]*>", " ", unescape(value))
    return " ".join(value.split())


def _date_from_crossref(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        date_value = item.get(key)
        if not isinstance(date_value, dict):
            continue
        date_parts = date_value.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts or not date_parts[0]:
            continue
        parts = date_parts[0]
        if not isinstance(parts, list) or not parts:
            continue
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        except (TypeError, ValueError):
            continue
    return ""


def _crossref_item_to_record(item: dict[str, Any]) -> PaperRecord | None:
    paper_id = _clean_text(item.get("DOI") or item.get("doi"))
    title = _clean_text(item.get("title"))
    if not paper_id or not title:
        return None

    authors: list[str] = []
    for author in item.get("author", []) or []:
        if not isinstance(author, dict):
            continue
        name = _clean_text(author.get("name")) or _clean_text(
            " ".join(filter(None, [author.get("given"), author.get("family")]))
        )
        if name:
            authors.append(name)

    categories = [
        text for subject in (item.get("subject", []) or [])
        if (text := _clean_text(subject))
    ]
    published = _date_from_crossref(
        item, "published-print", "published-online", "published", "issued", "created"
    )
    updated = _date_from_crossref(item, "updated", "indexed", "created") or published
    abs_url = _clean_text(item.get("URL")) or f"https://doi.org/{paper_id}"
    pdf_url = abs_url
    links = item.get("link", []) or []
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and "pdf" in str(link.get("content-type", "")).lower():
                pdf_url = _clean_text(link.get("URL")) or abs_url
                break
    if pdf_url == abs_url:
        resources = item.get("resource")
        if isinstance(resources, dict):
            primary = resources.get("primary")
            if isinstance(primary, dict):
                pdf_url = _clean_text(primary.get("URL")) or abs_url

    return PaperRecord(
        paper_id=paper_id,
        title=title,
        summary=_clean_text(item.get("abstract")),
        authors=authors,
        categories=categories,
        primary_category=categories[0] if categories else "",
        published=published,
        updated=updated,
        abs_url=abs_url,
        pdf_url=pdf_url,
        comment=_clean_text(item.get("comment")),
    )


def parse_crossref_payload(payload: dict[str, Any]) -> list[PaperRecord]:
    """Parse either a Crossref works list or a single-DOI response."""
    message = payload.get("message", {})
    if not isinstance(message, dict):
        return []
    items = message.get("items")
    if items is None:
        items = [message]
    if not isinstance(items, list):
        return []

    records: list[PaperRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _crossref_item_to_record(item)
        if record is not None:
            records.append(record)
    return records


def _build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "day10-data-observability-lab/1.0"})
    return session


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_to_dict(record: PaperRecord) -> dict[str, Any]:
    return {
        "paper_id": record.paper_id,
        "title": record.title,
        "summary": record.summary,
        "authors": record.authors,
        "categories": record.categories,
        "primary_category": record.primary_category,
        "published": record.published,
        "updated": record.updated,
        "abs_url": record.abs_url,
        "pdf_url": record.pdf_url,
        "comment": record.comment,
    }


def fetch_source_records(settings: Settings, doi: str | None = None) -> list[PaperRecord]:
    """Fetch Crossref works (or one DOI), falling back to the saved API snapshot."""
    if doi:
        doi_path = doi.strip()
        if doi_path.lower().startswith("doi/"):
            endpoint = f"{CROSSREF_WORKS_URL}/doi/{quote(doi_path[4:], safe='/')}"
        else:
            endpoint = f"{CROSSREF_WORKS_URL}/{quote(doi_path, safe='')}"
        params = None
    else:
        endpoint = CROSSREF_WORKS_URL
        params = {
            "rows": CROSSREF_ROWS,
            "query": settings.source_query,
            "filter": settings.source_filter,
        }

    raw_path = settings.paths.raw_api_response
    try:
        response = _build_session().get(
            endpoint, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Crossref response must be a JSON object")
        records = parse_crossref_payload(payload)
        if not records:
            raise ValueError("Crossref response contained no valid records")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as fetch_error:
        if not raw_path.exists():
            raise
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        records = parse_crossref_payload(payload)
        if doi:
            requested_doi = doi.strip().removeprefix("doi/").casefold()
            records = [record for record in records if record.paper_id.casefold() == requested_doi]
        if not records:
            if doi:
                raise fetch_error
            raise ValueError(f"Crossref snapshot contains no valid records: {raw_path}")

    if not doi:
        records = records[: settings.max_results]
    _write_json(raw_path, payload)
    _write_json(settings.paths.raw_records_json, [_record_to_dict(record) for record in records])
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load normalized PaperRecord objects from the saved records artifact."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of records in {path}")
    records: list[PaperRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = _crossref_item_to_record(
            {
                "DOI": item.get("paper_id"),
                "title": item.get("title"),
                "abstract": item.get("summary"),
                "author": [{"name": name} for name in item.get("authors", [])],
                "subject": item.get("categories", []),
                "published": {"date-parts": [[int(part) for part in item["published"].split("-")]]}
                if item.get("published") else {},
                "updated": {"date-parts": [[int(part) for part in item["updated"].split("-")]]}
                if item.get("updated") else {},
                "URL": item.get("abs_url"),
                "comment": item.get("comment"),
            }
        )
        if record is not None:
            pdf_url = _clean_text(item.get("pdf_url"))
            records.append(
                PaperRecord(**{**_record_to_dict(record), "pdf_url": pdf_url or record.pdf_url})
            )
    return records
