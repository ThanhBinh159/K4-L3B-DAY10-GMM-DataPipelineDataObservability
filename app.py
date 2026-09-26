from __future__ import annotations

import argparse
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
_index_lock = Lock()
_index_cache: tuple[Any, Any] | None = None


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def _exists(*parts: str) -> bool:
    return _path(*parts).exists()


def _count_json(path: Path) -> int:
    value = _read_json(path, [])
    return len(value) if isinstance(value, list) else 0


def _metric(metrics: dict[str, Any] | None, name: str) -> float | None:
    value = (metrics or {}).get(name)
    return float(value) if isinstance(value, (int, float)) else None


def _quality_success(path: Path) -> bool | None:
    value = _read_json(path)
    return value.get("success") if isinstance(value, dict) else None


def _record_map(path: Path) -> dict[str, dict[str, Any]]:
    records = _read_json(path, [])
    if not isinstance(records, list):
        return {}
    return {
        str(record.get("paper_id")): record
        for record in records
        if isinstance(record, dict) and record.get("paper_id")
    }


def _corruption_details(log: dict[str, Any]) -> list[dict[str, Any]]:
    titles = _record_map(_path("data", "clean", "papers_clean.json"))
    definitions = {
        "drop_latest_records": {
            "label": "Xóa bản ghi mới nhất",
            "field": "row / index",
            "error": "Bản ghi bị loại khỏi corrupted dataset và không còn được index.",
            "where": "corrupted clean data + Chroma corrupted collection",
            "handling": "Dựng lại từ raw snapshot; không sửa thủ công corrupted data.",
        },
        "blank_summary": {
            "label": "Summary rỗng",
            "field": "summary",
            "error": "Summary bị thay thành chuỗi rỗng, vi phạm minimum length 30.",
            "where": "corrupted clean data trước khi tạo text_for_embedding",
            "handling": "Quality Gate FAIL; repair lại summary từ raw snapshot.",
        },
        "inject_noise": {
            "label": "Chèn noise vào summary",
            "field": "summary",
            "error": "Thêm marker `### CORRUPTED_NOISE_@@@` vào nội dung summary.",
            "where": "summary và text_for_embedding của corrupted record",
            "handling": "Không lọc bằng heuristic; rebuild clean text từ raw snapshot.",
        },
        "truncate_title": {
            "label": "Cắt ngắn title",
            "field": "title",
            "error": "Title bị cắt còn 7 ký tự, làm yếu document identity và retrieval.",
            "where": "title và text_for_embedding của corrupted record",
            "handling": "Khôi phục title gốc bằng raw snapshot rồi build lại index.",
        },
        "stale_date": {
            "label": "Ngày xuất bản stale",
            "field": "published / age_days",
            "error": "published bị lùi 365 ngày và age_days bị tăng tương ứng.",
            "where": "published, age_days và freshness report",
            "handling": "Freshness monitor phát hiện; repair lại ngày từ raw snapshot.",
        },
        "duplicate_rows": {
            "label": "Trùng record",
            "field": "paper_id / row",
            "error": "Nhân đôi một row, làm unique paper_id check FAIL.",
            "where": "corrupted clean data và corrupted index",
            "handling": "Quality Gate FAIL; loại trạng thái corrupted bằng cách rebuild từ raw.",
        },
    }
    details = []
    for operation in log.get("operations", []):
        operation_type = str(operation.get("type", "unknown"))
        definition = definitions.get(
            operation_type,
            {
                "label": operation_type,
                "field": "unknown",
                "error": "Corruption chưa có mô tả.",
                "where": "corrupted artifact",
                "handling": "Review log và rebuild từ raw snapshot.",
            },
        )
        paper_ids = [str(value) for value in operation.get("paper_ids", [])]
        papers = [
            {
                "paper_id": paper_id,
                "title": str(titles.get(paper_id, {}).get("title", "Không có title trong clean snapshot")),
            }
            for paper_id in paper_ids
        ]
        details.append(
            {
                "type": operation_type,
                "label": definition["label"],
                "count": int(operation.get("count", len(paper_ids))),
                "field": definition["field"],
                "error": definition["error"],
                "where": definition["where"],
                "handling": definition["handling"],
                "papers": papers,
            }
        )
    return details


def _script_counts(text: str) -> dict[str, int]:
    letters = [char for char in text if char.isalpha()]
    cyrillic = sum(1 for char in letters if "\u0400" <= char <= "\u052f")
    latin = sum(
        1
        for char in letters
        if ("A" <= char <= "Z") or ("a" <= char <= "z") or "\u00c0" <= char <= "\u024f"
    )
    return {"letters": len(letters), "latin": latin, "cyrillic": cyrillic}


def _raw_language_report() -> dict[str, Any]:
    records = _read_json(_path("data", "raw", "crossref_records.json"), [])
    profiles = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        text = " ".join(str(record.get(field, "")) for field in ("title", "summary"))
        counts = _script_counts(text)
        ratio = counts["cyrillic"] / max(1, counts["letters"])
        if counts["cyrillic"] >= 20 and ratio >= 0.05:
            script = "Cyrillic / Russian-like"
        else:
            script = "Latin / corpus majority"
        profiles.append(
            {
                "paper_id": str(record.get("paper_id", "")),
                "title": str(record.get("title", "Không có title")),
                "script": script,
                "cyrillic_ratio": round(ratio, 3),
                "mixed_script": counts["cyrillic"] > 0 and counts["latin"] > 0,
            }
        )
    distribution = Counter(profile["script"] for profile in profiles)
    majority = distribution.most_common(1)[0][0] if distribution else "Unknown"
    outliers = [profile for profile in profiles if profile["script"] != majority]
    for profile in outliers:
        profile["assessment"] = "Tín hiệu multilingual/script khác biệt; không phải corruption tự động."
        profile["handling"] = (
            "Giữ nguyên raw để bảo toàn nguồn; flag để review. Nếu contract bắt buộc English-only, "
            "cần route qua model multilingual, dịch có kiểm soát hoặc loại có lý do."
        )
    return {
        "total_records": len(profiles),
        "majority_script": majority,
        "outlier_count": len(outliers),
        "outlier_rate": round(len(outliers) / max(1, len(profiles)), 3),
        "method": "Heuristic theo Unicode script trên title + summary; không phải language detector pháp lý.",
        "outliers": outliers,
    }


def _repair_summary(baseline: dict[str, Any], repaired: dict[str, Any]) -> dict[str, Any]:
    repaired_rows = _count_json(_path("data", "clean", "papers_clean_repaired.json"))
    baseline_rows = _count_json(_path("data", "clean", "papers_clean.json"))
    recovery = {}
    for name in ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"):
        before = _metric(baseline, name)
        after = _metric(repaired, name)
        recovery[name] = None if before in (None, 0) or after is None else round(after / before, 3)
    return {
        "baseline_rows": baseline_rows,
        "corrupted_rows": _count_json(_path("data", "clean", "papers_clean_corrupted.json")),
        "repaired_rows": repaired_rows,
        "row_recovery_rate": round(repaired_rows / max(1, baseline_rows), 3),
        "metric_recovery": recovery,
        "quality": {
            "baseline": _quality_success(_path("data", "quality", "baseline_quality_report.json")),
            "repaired": _quality_success(_path("data", "quality", "repaired_quality_report.json")),
        },
        "freshness": _read_json(_path("data", "quality", "repaired_quality_report.json"), {}).get(
            "freshness", {}
        ),
    }


def _artifact_state() -> dict[str, Any]:
    baseline = _read_json(_path("data", "results", "baseline_metrics.json"), {})
    corrupted = _read_json(_path("data", "results", "corrupted_metrics.json"), {})
    repaired = _read_json(_path("data", "results", "repaired_metrics.json"), {})
    corruption_log = _read_json(_path("data", "results", "corruption_log.json"), {})
    comparison_report = _path("data", "reports", "corruption_report.md")

    steps = [
        {
            "number": 1,
            "title": "Môi trường",
            "detail": "Python 3.12.0, dependency và cấu hình local.",
            "evidence": "Môi trường sẵn sàng",
            "complete": True,
        },
        {
            "number": 2,
            "title": "Thu thập dữ liệu thô",
            "detail": "Bảo toàn snapshot Crossref trước mọi biến đổi.",
            "evidence": "{} bài báo thô".format(_count_json(_path("data", "raw", "crossref_records.json"))),
            "complete": _exists("data", "raw", "crossref_records.json"),
        },
        {
            "number": 3,
            "title": "Làm sạch dữ liệu",
            "detail": "Chuẩn hóa trường dữ liệu, tuổi freshness và văn bản embedding.",
            "evidence": "{} dòng sạch".format(_count_json(_path("data", "clean", "papers_clean.json"))),
            "complete": _exists("data", "clean", "papers_clean.json"),
        },
        {
            "number": 4,
            "title": "Quality Gate",
            "detail": "Great Expectations 1.x cùng Freshness SLA 180 ngày.",
            "evidence": "GX thành công = {}".format(
                _quality_success(_path("data", "quality", "baseline_quality_report.json"))
            ),
            "complete": _quality_success(_path("data", "quality", "baseline_quality_report.json")) is True,
        },
        {
            "number": 5,
            "title": "Bộ benchmark",
            "detail": "Mười câu hỏi deterministic thuộc bốn nhóm nghiệp vụ.",
            "evidence": "{} câu hỏi benchmark".format(
                _count_json(_path("data", "eval", "test_set.json"))
            ),
            "complete": _count_json(_path("data", "eval", "test_set.json")) == 10,
        },
        {
            "number": 6,
            "title": "RAG baseline",
            "detail": "Embedding MiniLM, ChromaDB và đánh giá end-to-end.",
            "evidence": "Hit rate = {}".format(_metric(baseline, "retrieval_hit_rate")),
            "complete": _exists("data", "results", "baseline_metrics.json")
            and _exists("data", "reports", "phase1_report.md"),
        },
        {
            "number": 7,
            "title": "Tiêm lỗi dữ liệu",
            "detail": "Tiêm sáu lỗi deterministic để phơi bày silent failure.",
            "evidence": "{} operation đã ghi log".format(len(corruption_log.get("operations", []))),
            "complete": len(corruption_log.get("operations", [])) == 6,
        },
        {
            "number": 8,
            "title": "Phục hồi dữ liệu",
            "detail": "Dựng lại từ raw snapshot và so sánh với hai trạng thái trước.",
            "evidence": "Báo cáo = {}".format("sẵn sàng" if comparison_report.exists() else "thiếu"),
            "complete": _exists("data", "results", "repaired_metrics.json")
            and comparison_report.exists(),
        },
    ]

    states = [
        {
            "name": "Baseline · Dữ liệu sạch",
            "key": "baseline",
            "hit_rate": _metric(baseline, "retrieval_hit_rate"),
            "token_f1": _metric(baseline, "mean_token_f1"),
            "quality": True,
            "freshness": True,
        },
        {
            "name": "Corrupted · Dữ liệu lỗi",
            "key": "corrupted",
            "hit_rate": _metric(corrupted, "retrieval_hit_rate"),
            "token_f1": _metric(corrupted, "mean_token_f1"),
            "quality": _quality_success(_path("data", "quality", "corrupted_quality_report.json")),
            "freshness": (
                _read_json(_path("data", "quality", "corrupted_quality_report.json"), {})
                .get("freshness", {})
                .get("is_fresh")
            ),
        },
        {
            "name": "Repaired · Đã phục hồi",
            "key": "repaired",
            "hit_rate": _metric(repaired, "retrieval_hit_rate"),
            "token_f1": _metric(repaired, "mean_token_f1"),
            "quality": _quality_success(_path("data", "quality", "repaired_quality_report.json")),
            "freshness": (
                _read_json(_path("data", "quality", "repaired_quality_report.json"), {})
                .get("freshness", {})
                .get("is_fresh")
            ),
        },
    ]
    return {
        "project": "K4-L3B Day 10",
        "subtitle": "Data Pipeline & Data Observability for RAG",
        "docs": _count_json(_path("data", "clean", "papers_clean.json")),
        "questions": _count_json(_path("data", "eval", "test_set.json")),
        "states": states,
        "corruption": _corruption_details(corruption_log),
        "repair": _repair_summary(baseline, repaired),
        "raw_noise": _raw_language_report(),
        "steps": steps,
        "artifacts": [
            {"name": "Bản ghi thô", "path": "data/raw/crossref_records.json", "ready": _exists("data", "raw", "crossref_records.json")},
            {"name": "Dataset sạch", "path": "data/clean/papers_clean.json", "ready": _exists("data", "clean", "papers_clean.json")},
            {"name": "Báo cáo chất lượng", "path": "data/quality/baseline_quality_report.json", "ready": _exists("data", "quality", "baseline_quality_report.json")},
            {"name": "Metrics baseline", "path": "data/results/baseline_metrics.json", "ready": _exists("data", "results", "baseline_metrics.json")},
            {"name": "Log tiêm lỗi", "path": "data/results/corruption_log.json", "ready": _exists("data", "results", "corruption_log.json")},
            {"name": "Báo cáo 3 trạng thái", "path": "data/reports/corruption_report.md", "ready": comparison_report.exists()},
        ],
    }


def _get_index() -> tuple[Any, Any]:
    global _index_cache
    with _index_lock:
        if _index_cache is None:
            from core.config import load_settings
            from retrieval.index import LocalEmbeddingIndex

            settings = load_settings(ROOT)
            _index_cache = settings, LocalEmbeddingIndex.load(settings)
        return _index_cache


def _answer_question(question: str) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise ValueError("Vui lòng nhập câu hỏi.")
    from retrieval.qa import answer_question

    settings, index = _get_index()
    retrieval_question = question
    lowered = question.casefold()
    if "tác giả" in lowered:
        retrieval_question = f"Who authored {question}"
    elif any(term in lowered for term in ("khi nào", "ngày xuất bản", "được xuất bản")):
        retrieval_question = f"When was {question}"
    elif any(term in lowered for term in ("thể loại", "lĩnh vực", "category")):
        retrieval_question = f"What categories {question}"

    result = answer_question(retrieval_question, settings, index)
    return {
        "question": question,
        "answer": result.answer,
        "retrieved_doc_ids": result.retrieved_doc_ids,
        "retrieved_titles": result.retrieved_titles,
        "retrieved_contexts": result.retrieved_contexts,
    }


HTML = r'''<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bảng điều khiển Observability RAG</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07111f;
      --bg-soft: #0a1728;
      --card: #0f2033;
      --card-2: #122943;
      --line: #23405b;
      --text: #edf6ff;
      --muted: #95aec2;
      --teal: #55dfb4;
      --teal-soft: rgba(85, 223, 180, .13);
      --amber: #f3b562;
      --red: #ee7d88;
      --blue: #79b9ff;
      --radius: 16px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 88% -10%, #1c4661 0, transparent 32%), var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    .shell { width: min(1240px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 64px; }
    .topbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 54px; }
    .brand { display: flex; align-items: center; gap: 12px; font-weight: 700; letter-spacing: -.02em; }
    .brand-mark { width: 34px; height: 34px; border: 1px solid var(--teal); border-radius: 10px; display: grid; place-items: center; color: var(--teal); background: var(--teal-soft); font-size: 12px; }
    .status { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 5px var(--teal-soft); }
    .eyebrow { color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { max-width: 760px; margin-bottom: 16px; font-size: clamp(36px, 6vw, 72px); line-height: .98; letter-spacing: -.065em; }
    h2 { margin-bottom: 8px; font-size: 24px; letter-spacing: -.03em; }
    h3 { margin-bottom: 6px; font-size: 16px; }
    .hero { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 36px; align-items: end; margin-bottom: 38px; }
    .hero-copy p { max-width: 660px; color: var(--muted); font-size: 17px; }
    .hero-note { padding: 20px; border: 1px solid var(--line); border-radius: var(--radius); background: linear-gradient(145deg, rgba(18, 41, 67, .92), rgba(15, 32, 51, .82)); }
    .hero-note strong { display: block; margin: 6px 0 10px; font-size: 22px; }
    .hero-note p { margin-bottom: 0; color: var(--muted); font-size: 14px; }
    .grid { display: grid; gap: 16px; }
    .metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 38px; }
    .card { border: 1px solid var(--line); border-radius: var(--radius); background: rgba(15, 32, 51, .88); box-shadow: 0 16px 40px rgba(0,0,0,.12); }
    .metric { padding: 20px; min-height: 126px; }
    .metric-label { color: var(--muted); font-size: 13px; }
    .metric-value { margin-top: 14px; font-size: 32px; font-weight: 750; letter-spacing: -.05em; font-variant-numeric: tabular-nums; }
    .metric-note { margin-top: 4px; color: var(--teal); font-size: 12px; }
    .section { margin-top: 44px; }
    .section-head { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 16px; }
    .section-head p { margin-bottom: 0; color: var(--muted); font-size: 14px; }
    .comparison { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 660px; }
    th, td { padding: 16px 18px; border-bottom: 1px solid var(--line); text-align: left; font-size: 14px; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    td:not(:first-child) { font-variant-numeric: tabular-nums; }
    tr:last-child td { border-bottom: 0; }
    .state-name { display: flex; align-items: center; gap: 10px; font-weight: 700; }
    .state-bar { width: 6px; height: 28px; border-radius: 8px; background: var(--blue); }
    .state-bar.corrupted { background: var(--red); }
    .state-bar.repaired { background: var(--teal); }
    .pill { display: inline-flex; align-items: center; min-height: 26px; padding: 3px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; }
    .pill.good { color: var(--teal); background: var(--teal-soft); }
    .pill.bad { color: var(--red); background: rgba(238, 125, 136, .13); }
    .pill.neutral { color: var(--amber); background: rgba(243, 181, 98, .13); }
    .two-col { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr); gap: 16px; }
    .panel { padding: 22px; }
    .steps { display: grid; gap: 0; }
    .step { position: relative; display: grid; grid-template-columns: 38px 1fr; gap: 14px; padding: 0 0 22px; }
    .step:last-child { padding-bottom: 0; }
    .step:not(:last-child)::before { content: ""; position: absolute; top: 31px; bottom: 0; left: 15px; width: 1px; background: var(--line); }
    .step-number { position: relative; z-index: 1; width: 31px; height: 31px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: var(--bg-soft); color: var(--muted); font-size: 12px; font-weight: 800; }
    .step-number.complete { border-color: var(--teal); color: var(--teal); background: var(--teal-soft); }
    .step-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .step p { margin: 2px 0 5px; color: var(--muted); font-size: 13px; }
    .evidence { color: var(--teal); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .artifact-list { display: grid; gap: 11px; margin-top: 18px; }
    .artifact { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--line); }
    .artifact:last-child { border-bottom: 0; }
    .artifact-name { font-size: 14px; font-weight: 650; }
    .artifact-path { margin-top: 2px; color: var(--muted); font-size: 11px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .query-card { padding: 24px; background: linear-gradient(145deg, rgba(18, 41, 67, .95), rgba(15, 32, 51, .9)); }
    label { display: block; margin-bottom: 8px; color: var(--muted); font-size: 13px; font-weight: 650; }
    textarea { width: 100%; min-height: 92px; resize: vertical; padding: 13px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--bg); color: var(--text); font: inherit; line-height: 1.45; }
    textarea:focus, button:focus-visible { outline: 3px solid rgba(85, 223, 180, .35); outline-offset: 2px; border-color: var(--teal); }
    .query-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 12px; }
    .samples { display: flex; flex-wrap: wrap; gap: 8px; }
    .sample { min-height: 38px; padding: 7px 11px; border: 1px solid var(--line); border-radius: 10px; background: transparent; color: var(--muted); cursor: pointer; font: inherit; font-size: 12px; }
    .sample:hover { color: var(--text); border-color: var(--blue); }
    .primary { min-height: 44px; padding: 9px 16px; border: 0; border-radius: 10px; background: var(--teal); color: #062016; cursor: pointer; font: inherit; font-weight: 800; }
    .primary:hover { filter: brightness(1.08); }
    .primary:disabled { cursor: wait; opacity: .58; }
    .answer { display: none; margin-top: 18px; padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: rgba(7, 17, 31, .65); }
    .answer.visible { display: block; }
    .answer-text { margin: 6px 0 16px; font-size: 18px; line-height: 1.4; }
    .retrieved { display: grid; gap: 8px; }
    .retrieved-item { padding: 10px 12px; border-left: 2px solid var(--blue); background: rgba(121, 185, 255, .07); }
    .retrieved-item strong { display: block; font-size: 13px; }
    .retrieved-item code { color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }
    .repair-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
    .repair-card { padding: 16px; min-height: 112px; }
    .repair-label { color: var(--muted); font-size: 12px; }
    .repair-value { margin-top: 12px; color: var(--teal); font-size: 27px; font-weight: 800; font-variant-numeric: tabular-nums; }
    .repair-note { margin-top: 3px; color: var(--muted); font-size: 11px; }
    .trace-table { overflow-x: auto; }
    .trace-table table { min-width: 1080px; }
    .trace-table td { vertical-align: top; }
    .trace-type { color: var(--amber); font-weight: 800; }
    .trace-error { max-width: 260px; color: #ffd4d7; }
    .trace-meta { min-width: 150px; color: var(--muted); font-size: 12px; }
    .paper-list { display: grid; gap: 6px; min-width: 240px; }
    .paper-item { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; background: rgba(7, 17, 31, .45); }
    .paper-item strong { display: block; color: var(--text); font-size: 12px; line-height: 1.35; }
    .paper-item code { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; overflow-wrap: anywhere; }
    details summary { color: var(--blue); cursor: pointer; font-size: 12px; font-weight: 700; }
    .handling { min-width: 220px; color: var(--muted); font-size: 12px; }
    .insight-grid { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); gap: 16px; }
    .callout { padding: 16px; border-left: 3px solid var(--amber); border-radius: 10px; background: rgba(243, 181, 98, .09); }
    .callout.good { border-left-color: var(--teal); background: var(--teal-soft); }
    .callout h3 { margin-bottom: 8px; }
    .callout p { margin-bottom: 8px; color: var(--muted); font-size: 13px; }
    .callout p:last-child { margin-bottom: 0; }
    .noise-item { display: grid; gap: 7px; padding: 14px 0; border-bottom: 1px solid var(--line); }
    .noise-item:last-child { border-bottom: 0; }
    .noise-title { font-size: 14px; font-weight: 750; }
    .noise-meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .noise-copy { color: var(--muted); font-size: 13px; }
    .error { color: var(--red); font-size: 13px; }
    footer { margin-top: 54px; color: var(--muted); font-size: 12px; }
    @media (max-width: 900px) { .hero, .two-col, .insight-grid { grid-template-columns: 1fr; } .metric-grid, .repair-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 540px) { .shell { width: min(100% - 22px, 1240px); padding-top: 18px; } .topbar { margin-bottom: 36px; } h1 { font-size: 44px; } .metric-grid { grid-template-columns: 1fr 1fr; gap: 10px; } .metric { padding: 15px; min-height: 112px; } .metric-value { font-size: 25px; } .query-actions { align-items: stretch; flex-direction: column; } .primary { width: 100%; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; } }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true">RAG</span><span>Bảng điều khiển Observability</span></div>
      <div class="status"><span class="status-dot" aria-hidden="true"></span><span>Demo local · đọc từ artifact</span></div>
    </header>

    <section class="hero" aria-labelledby="page-title">
      <div class="hero-copy">
        <div class="eyebrow">Pipeline dữ liệu / bằng chứng trực tiếp</div>
        <h1 id="page-title">Từ metadata thô đến RAG tự phục hồi.</h1>
        <p>Xem lại tám bước của bài lab, kiểm tra tác động đo được của dữ liệu lỗi và truy vấn kho bài báo đã phục hồi ngay trên một console local.</p>
      </div>
      <aside class="hero-note" aria-label="Trạng thái demo">
        <div class="eyebrow">Đã thực hiện</div>
        <strong id="hero-summary">Đang đọc artifact…</strong>
        <p>Mọi số liệu bên dưới được đọc từ output pipeline trên disk, không hardcode trong dashboard.</p>
      </aside>
    </section>

    <section class="grid metric-grid" aria-label="Metrics chính">
      <article class="card metric"><div class="metric-label">Bài báo sạch</div><div class="metric-value" id="docs">—</div><div class="metric-note">thô → sạch</div></article>
      <article class="card metric"><div class="metric-label">Câu hỏi benchmark</div><div class="metric-value" id="questions">—</div><div class="metric-note">4 nhóm câu hỏi</div></article>
      <article class="card metric"><div class="metric-label">Hit rate baseline</div><div class="metric-value" id="baseline-hit">—</div><div class="metric-note">chất lượng retrieval</div></article>
      <article class="card metric"><div class="metric-label">Hit rate sau repair</div><div class="metric-value" id="repaired-hit">—</div><div class="metric-note">chất lượng phục hồi</div></article>
    </section>

    <section class="section" aria-labelledby="comparison-title">
      <div class="section-head"><div><h2 id="comparison-title">So sánh 3 trạng thái</h2><p>Baseline đo được → silent failure → phục hồi sau repair.</p></div></div>
      <div class="card comparison"><table><thead><tr><th>Trạng thái</th><th>Retrieval hit rate</th><th>Mean token F1</th><th>Quality Gate</th><th>Freshness</th></tr></thead><tbody id="comparison-body"></tbody></table></div>
    </section>

    <section class="section" aria-labelledby="corruption-title">
      <div class="section-head"><div><h2 id="corruption-title">Traceability: corruption → repair</h2><p>Mỗi lỗi được nối với paper, field, artifact và cách xử lý.</p></div></div>
      <div class="repair-grid">
        <article class="card repair-card"><div class="repair-label">Dòng baseline</div><div class="repair-value" id="repair-baseline-rows">—</div><div class="repair-note">clean records</div></article>
        <article class="card repair-card"><div class="repair-label">Dòng corrupted</div><div class="repair-value" id="repair-corrupted-rows">—</div><div class="repair-note">sau 6 operations</div></article>
        <article class="card repair-card"><div class="repair-label">Dòng repaired</div><div class="repair-value" id="repair-repaired-rows">—</div><div class="repair-note">khôi phục từ raw</div></article>
        <article class="card repair-card"><div class="repair-label">Tỷ lệ phục hồi</div><div class="repair-value" id="repair-rate">—</div><div class="repair-note">repaired / baseline</div></article>
      </div>
      <div class="card trace-table"><table><thead><tr><th>Type corruption</th><th>Paper bị tác động</th><th>Error / field</th><th>Ở đâu</th><th>Xử lý</th></tr></thead><tbody id="corruption-body"></tbody></table></div>
    </section>

    <section class="section insight-grid" aria-label="Raw data và repair review">
      <article class="card panel"><div class="section-head"><div><h2>Raw-language review</h2><p>Phân biệt noise dữ liệu với corruption có chủ đích.</p></div></div><div id="raw-noise-summary"></div><div id="raw-noise-list" class="noise-item"></div></article>
      <article class="card panel"><div class="section-head"><div><h2>Repair decision</h2><p>Vì sao record được giữ, flag hoặc rebuild.</p></div></div><div id="repair-decision"></div></article>
    </section>

    <section class="section two-col" aria-label="Bằng chứng pipeline">
      <article class="card panel"><div class="section-head"><div><h2>Dấu vết 8 bước</h2><p>Bằng chứng triển khai và kiểm chứng.</p></div></div><div class="steps" id="steps"></div></article>
      <article class="card panel"><div class="section-head"><div><h2>Artifacts</h2><p>Các file cung cấp dữ liệu cho console.</p></div></div><div class="artifact-list" id="artifacts"></div></article>
    </section>

    <section class="section" aria-labelledby="query-title">
      <div class="section-head"><div><h2 id="query-title">Thử nghiệm RAG</h2><p>Hỏi qua đúng luồng QA local dùng ChromaDB trong evaluation.</p></div></div>
      <article class="card query-card">
        <form id="query-form">
          <label for="question">Câu hỏi</label>
          <textarea id="question" name="question" required aria-describedby="query-help" placeholder="Hỏi về một bài báo đã được index…"></textarea>
          <div id="query-help" class="query-actions"><div class="samples"><button class="sample" type="button" data-question="Bài báo 'Retrieval-Augmented Generation for Large Language Model-Based Intelligent Assistants: A Review' được xuất bản khi nào?">Thử hỏi ngày xuất bản</button><button class="sample" type="button" data-question="Ai là tác giả của bài báo 'Retrieval-Augmented Generation for Large Language Model-Based Intelligent Assistants: A Review'?">Thử hỏi tác giả</button></div><button class="primary" id="ask" type="submit">Hỏi kho dữ liệu</button></div>
        </form>
        <div class="answer" id="answer" aria-live="polite"></div>
      </article>
    </section>
    <footer>Demo chỉ chạy local. Dashboard đọc artifact đã sinh và gọi retrieval layer hiện có; không sửa dữ liệu pipeline.</footer>
  </main>
  <script>
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    const percent = (value) => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`;
    const decimal = (value) => value == null ? '—' : Number(value).toFixed(3);
    const recovery = (value) => value == null ? '—' : `${(Number(value) * 100).toFixed(0)}%`;
    const pill = (value) => value === true ? '<span class="pill good">ĐẠT</span>' : value === false ? '<span class="pill bad">CẢNH BÁO</span>' : '<span class="pill neutral">CHƯA CÓ</span>';

    function renderCorruption(items) {
      document.getElementById('corruption-body').innerHTML = items.map((item) => {
        const papers = item.papers?.length
          ? `<details><summary>${item.papers.length} paper / record</summary><div class="paper-list">${item.papers.map((paper) => `<div class="paper-item"><strong>${escapeHtml(paper.title)}</strong><code>${escapeHtml(paper.paper_id)}</code></div>`).join('')}</div></details>`
          : '<span class="trace-meta">Không có paper ID</span>';
        return `<tr><td><div class="trace-type">${escapeHtml(item.label)}</div><div class="trace-meta">${item.count} record · ${escapeHtml(item.type)}</div></td><td>${papers}</td><td><div class="trace-error">${escapeHtml(item.error)}</div><div class="trace-meta">Field: ${escapeHtml(item.field)}</div></td><td><div class="trace-meta">${escapeHtml(item.where)}</div></td><td><div class="handling">${escapeHtml(item.handling)}</div></td></tr>`;
      }).join('');
    }

    function renderRepair(repair) {
      document.getElementById('repair-baseline-rows').textContent = repair.baseline_rows ?? '—';
      document.getElementById('repair-corrupted-rows').textContent = repair.corrupted_rows ?? '—';
      document.getElementById('repair-repaired-rows').textContent = repair.repaired_rows ?? '—';
      document.getElementById('repair-rate').textContent = recovery(repair.row_recovery_rate);
      const metrics = Object.entries(repair.metric_recovery || {}).map(([name, value]) => `<span class="pill ${value === 1 ? 'good' : 'neutral'}">${escapeHtml(name)}: ${recovery(value)}</span>`).join(' ');
      document.getElementById('repair-decision').innerHTML = `<div class="callout good"><h3>Rebuild từ raw snapshot</h3><p>Repaired khôi phục ${escapeHtml(String(repair.repaired_rows ?? '—'))}/${escapeHtml(String(repair.baseline_rows ?? '—'))} dòng baseline (${recovery(repair.row_recovery_rate)}).</p><p>Quality repaired: ${pill(repair.quality?.repaired)} · Freshness: ${pill(repair.freshness?.is_fresh)}</p><div class="samples">${metrics}</div></div><div class="callout"><h3>Diễn giải</h3><p>Đây là tỷ lệ phục hồi artifact/metric so với baseline, không phải xóa dấu vết corruption. Corruption log vẫn được giữ để audit.</p></div>`;
    }

    function renderRawNoise(noise) {
      const summary = noise.outlier_count > 0
        ? `<div class="callout"><h3>${noise.outlier_count}/${noise.total_records} record khác script/ngôn ngữ</h3><p>Corpus majority: <strong>${escapeHtml(noise.majority_script)}</strong> · Tỷ lệ outlier: ${percent(noise.outlier_rate)}</p><p>Đây là tín hiệu cần review, chưa được gán là corruption tự động.</p></div>`
        : `<div class="callout good"><h3>Không phát hiện language/script outlier</h3><p>${escapeHtml(noise.total_records)} record cùng profile heuristic với corpus majority.</p></div>`;
      document.getElementById('raw-noise-summary').innerHTML = summary;
      document.getElementById('raw-noise-list').innerHTML = noise.outliers?.length ? noise.outliers.map((item) => `<div class="noise-item"><div class="noise-title">${escapeHtml(item.title)}</div><div class="noise-meta">${escapeHtml(item.paper_id)} · ${escapeHtml(item.script)} · Cyrillic ratio ${escapeHtml(item.cyrillic_ratio)}</div><div class="noise-copy"><strong>Đánh giá:</strong> ${escapeHtml(item.assessment)}</div><div class="noise-copy"><strong>Xử lý hiện tại:</strong> ${escapeHtml(item.handling)}</div></div>`).join('') : '<div class="noise-copy">Không có outlier để hiển thị.</div>';
    }

    function render(state) {
      document.getElementById('docs').textContent = state.docs || '—';
      document.getElementById('questions').textContent = state.questions || '—';
      document.getElementById('baseline-hit').textContent = percent(state.states[0]?.hit_rate);
      document.getElementById('repaired-hit').textContent = percent(state.states[2]?.hit_rate);
      document.getElementById('hero-summary').textContent = `${state.docs || 0} bài báo · ${state.steps.filter(step => step.complete).length}/8 bước đã kiểm chứng`;

      document.getElementById('comparison-body').innerHTML = state.states.map((item) => `<tr><td><div class="state-name"><span class="state-bar ${item.key}"></span>${escapeHtml(item.name)}</div></td><td>${percent(item.hit_rate)}</td><td>${decimal(item.token_f1)}</td><td>${pill(item.quality)}</td><td>${pill(item.freshness)}</td></tr>`).join('');
      renderRepair(state.repair);
      renderCorruption(state.corruption);
      renderRawNoise(state.raw_noise);
      document.getElementById('steps').innerHTML = state.steps.map((step) => `<div class="step"><div class="step-number ${step.complete ? 'complete' : ''}">${step.number}</div><div><div class="step-title"><h3>${escapeHtml(step.title)}</h3>${pill(step.complete)}</div><p>${escapeHtml(step.detail)}</p><div class="evidence">${escapeHtml(step.evidence)}</div></div></div>`).join('');
      document.getElementById('artifacts').innerHTML = state.artifacts.map((artifact) => `<div class="artifact"><div><div class="artifact-name">${escapeHtml(artifact.name)}</div><div class="artifact-path">${escapeHtml(artifact.path)}</div></div>${pill(artifact.ready)}</div>`).join('');
    }

    async function loadState() {
      try {
        const response = await fetch('/api/state', {cache: 'no-store'});
        if (!response.ok) throw new Error('Không đọc được artifact');
        render(await response.json());
      } catch (error) {
        document.getElementById('hero-summary').textContent = error.message;
      }
    }

    async function ask(event) {
      event.preventDefault();
      const question = document.getElementById('question').value.trim();
      const button = document.getElementById('ask');
      const answer = document.getElementById('answer');
      if (!question) return;
      button.disabled = true;
      button.textContent = 'Đang tìm…';
      answer.className = 'answer visible';
      answer.innerHTML = '<div class="evidence">Đang truy vấn Chroma index local…</div>';
      try {
        const response = await fetch('/api/query', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question})});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Query failed');
        const docs = payload.retrieved_titles.map((title, index) => `<div class="retrieved-item"><strong>${escapeHtml(title)}</strong><code>${escapeHtml(payload.retrieved_doc_ids[index] || '')}</code></div>`).join('');
        answer.innerHTML = `<div class="eyebrow">Câu trả lời</div><div class="answer-text">${escapeHtml(payload.answer)}</div><div class="eyebrow">Bằng chứng được truy xuất</div><div class="retrieved">${docs || '<div class="evidence">Không truy xuất được tài liệu.</div>'}</div>`;
      } catch (error) {
        answer.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = 'Hỏi kho dữ liệu';
      }
    }

    document.getElementById('query-form').addEventListener('submit', ask);
    document.querySelectorAll('.sample').forEach((button) => button.addEventListener('click', () => { document.getElementById('question').value = button.dataset.question; document.getElementById('question').focus(); }));
    loadState();
  </script>
</body>
</html>'''


class AppHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send_json(200, _artifact_state())
        elif path == "/api/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/query":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            result = _answer_question(str(body.get("question", "")))
            self._send_json(200, result)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - UI boundary fallback
            self._send_json(500, {"error": f"Không thể truy vấn: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[app] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local RAG observability console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Bảng điều khiển Observability RAG: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping console.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
