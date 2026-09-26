# Báo cáo cá nhân — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Trường | Nội dung |
|---|---|
| Họ và tên | `Nguyễn Thanh Bình` |
| MSSV | `2A202602777` |
| Khóa/lớp | `K4` |
| Tên nhóm | `GMMM` |
| Vai trò chính | Owner toàn bộ pipeline và UI demo |
| Contribution | `100%` |
| Repository | `K4-L3B-DAY10-GMM-DataPipelineDataObservability` |
| Ngày hoàn thành | `2026-09-26` |

## 2. Phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Ingestion | `src/ingestion/crossref.py` | Crossref API/raw snapshot | 24 raw records | Hoàn thành |
| Cleaning | `src/ingestion/cleaning.py` | Raw records | Clean CSV/JSON và `text_for_embedding` | Hoàn thành |
| Evaluation/quality | `src/evaluation/testset.py`, `src/observability/quality.py` | Clean DataFrame | 10 câu hỏi, quality/freshness reports | Hoàn thành |
| RAG/index/QA | `src/retrieval/embeddings.py`, `src/retrieval/index.py`, `src/retrieval/qa.py` | Clean embedding text | ChromaDB index và evidence | Hoàn thành |
| Pipeline/reporting | `src/pipelines/phase1.py`, `src/observability/reporting.py` | Raw/clean/evaluation artifacts | Baseline metrics/report | Hoàn thành |
| Corruption/repair | `src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py` | Clean data/raw snapshot | 6 lỗi, corrupted/repaired artifacts | Hoàn thành |
| UI observability | `app.py` | Artifacts và local index | Dashboard tiếng Việt, traceability và raw-language review | Hoàn thành |

## 3. Kết quả và cách xác minh

- Raw dataset: **24 bài báo**.
- Clean dataset: **24 dòng**, có chuẩn hóa, deduplicate, `age_days` và `text_for_embedding`.
- Evaluation set: **10 câu hỏi**, đủ `summary`, `authors`, `date`, `categories`.
- Baseline: retrieval hit rate `1.000`, mean token F1 `0.500`.
- Corruption: **6 operations**, corrupted dataset **20 dòng**.
- Repair: rebuilt từ raw snapshot, repaired dataset **24 dòng**, quality gate PASS.
- UI: hiển thị từng loại corruption, paper ID/title, field bị lỗi, vị trí, cách repair, tỷ lệ phục hồi và raw-language outlier.

Artifact chính:

- `data/raw/crossref_records.json`
- `data/clean/papers_clean.json`
- `data/eval/test_set.json`
- `data/embeddings/papers_embeddings.json`
- `data/results/baseline_metrics.json`
- `data/results/corrupted_metrics.json`
- `data/results/repaired_metrics.json`
- `data/results/corruption_log.json`
- `data/quality/`
- `data/reports/phase1_report.md`
- `data/reports/corruption_report.md`
- `app.py`

## 4. Giải thích kỹ thuật

Pipeline lưu raw snapshot trước khi biến đổi. Cleaning chuẩn hóa title/summary/authors/categories, loại duplicate `paper_id`, tính `age_days` và tạo `text_for_embedding`. MiniLM tạo embedding; ChromaDB lưu các collection baseline, corrupted và repaired. Evaluation set giữ ground-truth document ID và được dùng chung cho cả ba trạng thái.

Quality Gate kiểm tra row count, not-null, unique ID và độ dài summary. Freshness kiểm tra ngày xuất bản với threshold 180 ngày và stale ratio limit 0.25.

UI đọc các artifacts trực tiếp. Corruption trace lấy `corruption_log.json` và map paper ID sang title trong clean snapshot. Raw-language review dùng heuristic Unicode script trên title + summary; đây là tín hiệu review, không phải language detector tuyệt đối.

## 5. Corruption và repair

| Loại lỗi | Paper/record | Field/vị trí | Xử lý |
|---|---|---|---|
| Drop latest records | 5 paper mới nhất | Row/index, corrupted dataset | Rebuild từ raw |
| Blank summary | `10.28932/jutisi.v12i2.13099` | `summary` | Quality FAIL, lấy lại summary từ raw |
| Inject noise | `10.20944/preprints202608.1849.v1` | `summary`, `text_for_embedding` | Rebuild embedding text từ raw |
| Truncate title | `10.21203/rs.3.rs-10423755/v1` | `title`, `text_for_embedding` | Khôi phục title từ raw |
| Stale date | `10.3390/knowledge6030022` | `published`, `age_days` | Freshness flag, khôi phục ngày từ raw |
| Duplicate row | `10.36948/ijfmr.2026.v08i04.85777` | `paper_id`, row | Quality FAIL, rebuild dataset |

Tỷ lệ phục hồi:

- Row recovery: `24 / 24 = 100%` so với baseline.
- Retrieval hit rate: `1.000 / 1.000 = 100%`.
- Mean token F1: `0.500 / 0.500 = 100%`.
- Quality repaired: PASS; freshness repaired: PASS, stale `0/24`.

## 6. Raw-language noise: đánh giá và xử lý

Raw snapshot có một paper có tín hiệu Cyrillic/Russian-like trong corpus chủ yếu dùng Latin. Đây **không phải corruption tự động**: nội dung đa ngôn ngữ có thể là dữ liệu hợp lệ từ Crossref. Tuy nhiên, vì embedding model hiện tại không được cấu hình như multilingual model, đây là **data quality/retrieval risk** cần flag.

Cách xử lý hiện tại:

1. Giữ nguyên raw để bảo toàn nguồn và không làm mất thông tin.
2. UI đánh dấu paper là language/script outlier với tỷ lệ trên tổng corpus.
3. Không tự động drop hoặc dịch vì project chưa đặt contract English-only.
4. Nếu bài nộp yêu cầu English-only, cần chọn rõ một policy: model multilingual, dịch có kiểm soát kèm bản gốc, hoặc loại record với lý do và log.

## 7. Metrics và phân tích

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét |
|---|---:|---:|---:|---|
| `retrieval_hit_rate` | 1.000 | 0.500 | 1.000 | Giảm do content/identity lỗi, repair phục hồi |
| `mean_token_f1` | 0.500 | 0.221 | 0.500 | Context lỗi làm answer kém hơn |
| `judge_accuracy` | 0.500 | 0.200 | 0.500 | Giảm cùng retrieval |
| `mean_judge_score` | 3.0 | 1.8 | 3.0 | Phục hồi về baseline |
| Quality checks | PASS | FAIL | PASS | Corrupted fail duplicate ID và summary rỗng |
| Freshness | PASS | PASS, stale ratio 0.05 | PASS | Chưa vượt SLA nhưng có stale row |

RAGAS chưa chạy; artifact ghi rõ cần `RUN_RAGAS=1` để bật. Cảnh báo `multiprocess.resource_tracker` lúc kết thúc tiến trình không làm hỏng metrics hoặc artifacts đã kiểm tra.

## 8. Lỗi tích hợp đã xử lý

- `cleaning.py` và `quality.py` ban đầu là stub `NotImplementedError`; đã triển khai function trước khi kiểm chứng bằng CLI/artifact.
- PowerShell gửi JSON tiếng Việt không đúng UTF-8; test API được điều chỉnh để gửi byte UTF-8 rõ ràng.
- UI từng trả nearest document cho tiêu đề không có trong corpus; `qa.py` hiện trả no-match để tránh false-positive.

## 9. Hiểu biết end-to-end

1. Crossref → raw snapshot → cleaning → embedding/index.
2. Evaluation set đối chiếu document ID và answer với ground truth.
3. Quality checks kiểm tra validity/completeness/uniqueness; freshness kiểm tra tuổi dữ liệu.
4. Cùng một test set giúp so sánh công bằng baseline, corrupted và repaired.
5. Repair được xác nhận bằng raw lineage, quality/freshness PASS và metrics quay lại baseline.

## 10. Hướng cải thiện

- Bật RAGAS và lưu thêm faithfulness/context recall.
- Hiển thị similarity score, request ID và match mode trong UI.
- Thêm policy multilingual rõ ràng nếu corpus cần đồng nhất ngôn ngữ.
- Lưu timestamp/hash của raw snapshot để tái lập các lần refresh Crossref.

## 11. Cam kết

- [x] Báo cáo phản ánh mô hình solo-team và Contribution 100%.
- [x] Kết luận có artifact hoặc metric đối chiếu.
- [x] Không ghi RAGAS là đã chạy khi artifact đang ghi skip.
- [x] Không chứa `.env`, API key, token hoặc secret.
- [ ] Thay `TBD` bằng họ tên, MSSV và email thật trước khi nộp.

**Họ và tên:** `Nguyễn Thanh Bình`  
**Ngày xác nhận:** `2026-09-26`
