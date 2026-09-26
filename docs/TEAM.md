# Danh sách thành viên và phân công nhóm

- **Tên nhóm:** `GMM`
- **Mã nhóm / lớp:** `L3B`
- **Repository:** `K4-L3B-DAY10-GMM-DataPipelineDataObservability`
- **Mô hình thực hiện:** 

## Thành viên và tỷ lệ đóng góp

| STT | Họ và tên | MSSV | Email | Vai trò cụ thể | Contribution | Báo cáo cá nhân |
|---:|---|---|---|---|---:|---|
| 1 | `Nguyễn Thanh Bình` | `2A202602777` | `BinhNT1509204@gmail.com` | Owner toàn bộ pipeline: ingestion, cleaning, evaluation, observability, RAG/index, corruption/repair, orchestration và UI demo | **100%** | [`report/individual_2A202602777_NguyenThanhBinh.md`](../report/individual_2A202602777_NguyenThanhBinh.md) |

Contribution `100%` là tỷ lệ tự chấm tạm thời của mô hình solo-team. Thay tên, MSSV và email trước khi nộp chính thức.

## Phân công công việc

| Khối công việc | File/module chính | Output và bằng chứng |
|---|---|---|
| Ingestion | `src/ingestion/crossref.py` | Raw snapshot Crossref và **24 bài báo** |
| Cleaning và data modeling | `src/ingestion/cleaning.py` | Clean CSV/JSON **24 dòng**, deduplicate, `age_days`, `text_for_embedding` |
| Evaluation set | `src/evaluation/testset.py` | **10 câu hỏi**, đủ `summary`, `authors`, `date`, `categories` |
| Quality và freshness | `src/observability/quality.py` | Quality gate và freshness reports |
| RAG và vector index | `src/retrieval/embeddings.py`, `src/retrieval/index.py`, `src/retrieval/qa.py` | ChromaDB index, MiniLM embedding, retrieval top-k 4 |
| Baseline pipeline | `src/pipelines/phase1.py`, `src/observability/reporting.py` | Hit rate `1.000`, token F1 `0.500` |
| Corruption và repair | `src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py` | 6 lỗi, corrupted 20 dòng, repaired 24 dòng |
| UI demo | `app.py` | Dashboard tiếng Việt, query API, corruption traceability và raw-language review |

## Kết quả đã xác minh

| Trạng thái | Retrieval hit rate | Mean token F1 | Judge accuracy | Mean judge score | Quality | Freshness |
|---|---:|---:|---:|---:|---|---|
| Baseline | 1.000 | 0.500 | 0.500 | 3.0 | PASS | PASS |
| Corrupted | 0.500 | 0.221 | 0.200 | 1.8 | FAIL | PASS, stale ratio 0.05 |
| Repaired | 1.000 | 0.500 | 0.500 | 3.0 | PASS | PASS |
