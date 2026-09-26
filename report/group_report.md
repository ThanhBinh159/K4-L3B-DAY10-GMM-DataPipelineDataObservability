# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
|---|---|
| Khóa/Lớp | `K4` |
| Tên nhóm | `GMM` |
| Repository | `K4-L3B-DAY10-GMM-DataPipelineDataObservability` |
| Ngày hoàn thành | `2026-09-26` |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
|---:|---|---|---|---|
| 1 | `Nguyễn Thanh Bình` | `2A202602777` | Owner toàn bộ pipeline và UI demo; Contribution `100%` | Ingestion, cleaning, evaluation, observability, RAG/index, corruption/repair, orchestration, reporting, UI |

## 2. Tóm tắt kết quả

Pipeline đã hoàn thành từ Crossref raw snapshot đến cleaned dataset, embedding/index, evaluation, quality/freshness, corruption, repair và UI demo. Dataset có 24 bài báo sạch; evaluation set có 10 câu hỏi thuộc bốn nhóm `summary`, `authors`, `date`, `categories`. Baseline đạt `retrieval_hit_rate=1.000`, `mean_token_f1=0.500`, `judge_accuracy=0.500` và `mean_judge_score=3.0`. Corruption áp dụng sáu loại lỗi, tạo dataset 20 dòng; quality gate chuyển FAIL và retrieval hit rate giảm còn `0.500`. Repair dựng lại từ raw snapshot, đưa dữ liệu về 24 dòng, quality gate về PASS và các metrics chính trở lại baseline. UI `app.py` hiển thị traceability theo từng lỗi, paper bị tác động, field, artifact, cách xử lý và tỷ lệ phục hồi. Thông tin cá nhân đang để `TBD` và cần thay trước khi nộp.

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
Crossref API
    -> raw response/raw records
    -> cleaning và data modeling
    -> embedding + ChromaDB index
    -> evaluation baseline
    -> quality/freshness reports
    -> corruption
    -> corrupted evaluation/index
    -> repair từ raw snapshot
    -> repaired evaluation/index
    -> comparison report và UI demo
```

### Trách nhiệm của từng khối

| Khối | Input | Xử lý chính | Output/artifact | Owner |
|---|---|---|---|---|
| Ingestion | Crossref `/works`, query và filter | Fetch, parse, fallback raw snapshot | `data/raw/` — 24 records | Solo Member |
| Cleaning | Raw records | Normalize, deduplicate, derived fields | `data/clean/` — 24 rows | Solo Member |
| Embedding/index | Clean `text_for_embedding` | MiniLM embedding, persistent ChromaDB | `data/embeddings/`, `data/chroma/` | Solo Member |
| Evaluation | Clean dataset | 10 câu hỏi và metrics | `data/eval/`, `data/results/` | Solo Member |
| Observability | Clean/corrupted/repaired DataFrame | Quality expectations và freshness SLA | `data/quality/` | Solo Member |
| Corruption/repair | Clean data và raw snapshot | Sáu lỗi, audit log, rebuild từ raw | `data/results/`, repaired artifacts | Solo Member |
| Orchestration | Các artifact theo thứ tự phụ thuộc | Baseline và corruption flow | `data/reports/` | Solo Member |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
|---|---|
| `LLM_PROVIDER` | Đọc từ `.env` runtime; không ghi secret |
| `LLM_MODEL` | Đọc từ `.env` runtime; không ghi secret |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Source query | `agentic retrieval augmented generation large language model` |
| Số lượng Crossref records | 24 |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày |
| Freshness stale ratio limit | 0.25 |
| Random seed | Không dùng; test set và corruption deterministic |

### Lệnh cài đặt

Môi trường sử dụng Python `3.12.0` trong `.venv`:

```powershell
python -m pip install -e .
```

### Lệnh chạy

Baseline:

```powershell
python script/run_phase1.py
```

Corruption flow:

```powershell
python script/run_corruption_flow.py
```

UI:

```powershell
python app.py --port 8000
```

### Kết quả tái hiện

| Lệnh | Trạng thái | Bằng chứng |
|---|---|---|
| Baseline pipeline | Thành công | `data/results/baseline_metrics.json`, `data/reports/phase1_report.md` |
| Corruption flow | Thành công | `data/results/corruption_log.json`, `data/reports/corruption_report.md` |
| UI demo | Thành công | `app.py`, local `POST /api/query` |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
|---|---|
| Source | Crossref REST API: `https://api.crossref.org/works` |
| Query/filter | `agentic retrieval augmented generation large language model`, `has-abstract:true`, from-pub-date theo freshness threshold |
| Thời điểm lấy dữ liệu | Raw snapshot được lưu; timestamp fetch không được ghi riêng trong report |
| Số record nhận được | 24 |
| Cơ chế retry/fallback | Parse Crossref response và dùng raw snapshot offline khi cần |

### Raw và clean schema

| Trường | Kiểu dữ liệu | Bắt buộc? | Ý nghĩa | Xử lý khi thiếu/sai |
|---|---|---|---|---|
| `paper_id` | string | Có | DOI/document identity | Dùng làm identity và kiểm tra unique |
| `title` | string | Có | Tiêu đề | Chuẩn hóa text |
| `summary` | string | Có cho quality gate | Abstract/tóm tắt | Yêu cầu tối thiểu 30 ký tự |
| `authors` | list[string] | Không | Tác giả | Chuẩn hóa và tạo `authors_joined` |
| `categories` | list[string] | Không | Category/subject | Chuẩn hóa và tạo `categories_joined` |
| `published`/`updated` | ISO date string | Không | Ngày xuất bản/cập nhật | Tính `age_days`, freshness |
| `text_for_embedding` | string | Có sau cleaning | Text dùng tạo vector | Ghép title, authors, published, categories, summary |

### Quy tắc cleaning

| Quy tắc | Quality dimension liên quan | Số record bị tác động | Cách xác minh |
|---|---|---:|---|
| Chuẩn hóa text/list và nối authors/categories | Validity/Completeness | 24 | Clean JSON/CSV |
| Deduplicate theo `paper_id` | Uniqueness | 0 ở baseline | Unique quality check |
| Tính `summary_chars`, `age_days` | Validity/Freshness | 24 | Clean artifact/freshness report |
| Tạo `text_for_embedding` | Consistency | 24 | Not-null quality check |

`text_for_embedding` gồm title, authors, published, categories và summary. `paper_id` được giữ ổn định xuyên suốt ingestion, clean, index, evaluation và repair.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
|---|---|
| Số câu hỏi | 10 |
| Các `question_type` | `summary`, `authors`, `date`, `categories` |
| Ground-truth document ID | `paper_id` của record được chọn trong clean dataset |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection | ChromaDB: `papers-baseline`, `papers-corrupted`, `papers-repaired` |
| Retrieval `top_k` | 4 |
| LLM provider/model | Đọc từ `.env` runtime; không ghi secret |
| Test set dùng chung | `data/eval/test_set.json` |

Test set được tạo deterministic từ clean dataset và dùng lại cho baseline, corrupted và repaired. Vì vậy thay đổi metrics được quy cho chất lượng dữ liệu/index thay vì thay đổi evaluation questions.

## 7. Kết quả baseline

### Artifact checklist

| Artifact | Đường dẫn thực tế | Trạng thái | Ghi chú |
|---|---|---|---|
| Raw response/records | `data/raw/` | Có | 24 records |
| Cleaned dataset | `data/clean/` | Có | 24 rows |
| Embedding manifest/index | `data/embeddings/`, `data/chroma/` | Có | Baseline Chroma collection |
| Evaluation set | `data/eval/test_set.json` | Có | 10 questions |
| Baseline metrics | `data/results/baseline_metrics.json` | Có | Metrics đầy đủ |
| Quality/freshness | `data/quality/` | Có | Baseline PASS/fresh |
| Baseline report | `data/reports/phase1_report.md` | Có | Khớp metrics/artifact |

### Baseline metrics

| Metric | Giá trị | Diễn giải |
|---|---:|---|
| `retrieval_hit_rate` | 1.000 | Ground-truth document nằm trong top-k cho các câu hỏi |
| `mean_token_f1` | 0.500 | Token overlap trung bình của answer |
| `judge_accuracy` | 0.500 | Kết quả judge trong artifact |
| `mean_judge_score` | 3.0 | Điểm judge trung bình |
| Ragas | N/A | Chưa chạy; cần `RUN_RAGAS=1` |

## 8. Data quality và freshness

### Quality checks

| Check | Quality dimension | Ngưỡng/kỳ vọng | Baseline | Corrupted | Repaired |
|---|---|---|---|---|---|
| Row count | Completeness | 5–5000 | PASS, 24 | PASS, 20 | PASS, 24 |
| Not-null `paper_id`, `title`, `text_for_embedding` | Completeness | 0 null | PASS | PASS | PASS |
| Unique `paper_id` | Uniqueness | 0 duplicate | PASS | FAIL, 2 unexpected | PASS |
| Summary length | Validity | min 30 chars | PASS | FAIL, 1 empty | PASS |

### Freshness

| Thuộc tính | Giá trị |
|---|---|
| Freshness được đo tại | Clean/corrupted/repaired DataFrame |
| Timestamp mới nhất baseline | `2026-09-15` |
| Timestamp cũ nhất baseline | `2026-04-01` |
| Ngưỡng freshness | 180 ngày |
| Trạng thái baseline | Fresh, stale `0/24` |
| Trạng thái corrupted | Fresh theo SLA, stale `1/20`, ratio `0.05` |
| Trạng thái repaired | Fresh, stale `0/24` |

Corrupted vẫn PASS freshness vì stale ratio `0.05 < 0.25`, nhưng quality gate FAIL do duplicate `paper_id` và summary rỗng.

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair |
|---|---|---:|---|---|---|
| Drop latest records | Xóa 20% bản ghi mới nhất | 5 | Row count giảm | Corrupted còn 20 rows sau toàn bộ flow | Rebuild từ raw |
| Blank summary | Gán summary thành chuỗi rỗng | 1 | Summary length FAIL | 1 summary rỗng | Lấy lại từ raw |
| Inject noise | Thêm `### CORRUPTED_NOISE_@@@` | 1 | Context/answer quality giảm | Noise nằm trong summary và embedding text | Rebuild embedding text |
| Truncate title | Cắt title còn 7 ký tự | 1 | Document identity yếu | Retrieval/title có thể lệch | Khôi phục title từ raw |
| Stale date | Lùi published 365 ngày | 1 | Freshness stale tăng | Stale `1/20`, ratio `0.05` | Khôi phục ngày từ raw |
| Duplicate row | Nhân đôi một row | 1 | Unique ID FAIL | 2 unexpected duplicate values | Rebuild dataset |

Corruption log `data/results/corruption_log.json` ghi đủ 6 operations, paper IDs, counts, `original_rows=24` và `corrupted_rows=20`. Repair đọc lại raw snapshot, chạy lại cleaning và build repaired index; không sửa che trên corrupted data.

Raw snapshot có một paper có tín hiệu Cyrillic/Russian-like trong corpus chủ yếu Latin. Đây không phải corruption tự động vì có thể là nội dung multilingual hợp lệ; tuy nhiên là retrieval risk cần review. Pipeline hiện giữ nguyên raw, flag trong UI bằng heuristic Unicode script và không tự động drop/dịch. Nếu contract yêu cầu English-only, cần chọn policy rõ ràng: model multilingual, dịch có kiểm soát kèm bản gốc, hoặc loại record có lý do và log.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét |
|---|---:|---:|---:|---:|---:|---|
| `retrieval_hit_rate` | 1.000 | 0.500 | 1.000 | -0.500 | 100% | Retrieval phục hồi hoàn toàn |
| `mean_token_f1` | 0.500 | 0.221 | 0.500 | -0.279 | 100% | Answer quality trở lại baseline |
| `judge_accuracy` | 0.500 | 0.200 | 0.500 | -0.300 | 100% | Judge phục hồi theo data |
| `mean_judge_score` | 3.0 | 1.8 | 3.0 | -1.2 | 100% | Repaired bằng baseline |
| Quality checks pass/fail | PASS | FAIL | PASS | FAIL | Phục hồi | Duplicate/summary lỗi bị phát hiện |
| Freshness status | PASS | PASS, ratio 0.05 | PASS | Stale tăng | Phục hồi | Corrupted chưa vượt SLA |

1. Corruption/data change → duplicate/summary quality signals FAIL → retrieval hit rate giảm `1.000 -> 0.500`, token F1 giảm `0.500 -> 0.221`.
2. Repair từ raw snapshot → quality/freshness phục hồi → retrieval và answer metrics trở lại baseline.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** UI từng trả ngày của nearest document khi query có tiêu đề không tồn tại trong corpus.
- **Nguyên nhân:** `lookup()` không match exact title nhưng QA vẫn fallback semantic search và lấy result đầu tiên.
- **Cách xử lý:** explicit title không match được trả no-match và evidence rỗng; generic query vẫn semantic-search.
- **Cách xác minh:** query qua `/api/query` trả document IDs/title đúng cho paper có trong index và không tạo answer sai cho title ngoài corpus.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
|---|---|---|
| RAGAS chưa chạy | Chưa có faithfulness/context recall | Bật `RUN_RAGAS=1`, lưu artifact và so sánh cùng test set |
| UI chưa hiển thị similarity score/request ID | Khó audit từng lượt retrieval | Hiển thị score, request ID và match mode |
| Language review dùng heuristic | Không thay thế language detector | Dùng detector/model multilingual nếu scope yêu cầu |
| Crossref là nguồn sống | Refresh có thể đổi records | Lưu timestamp/hash raw snapshot |

## 13. Checklist trước khi nộp

- [ ] Thông tin nhóm và repository chính xác.
- [ ] Phân công khớp với module, artifact và kết quả thực tế.
- [ ] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [ ] Baseline, corrupted và repaired dùng cùng evaluation set.
- [ ] Bảng metrics khớp với các file trong `data/results/`.
- [ ] Quality/freshness conclusions khớp với `data/quality/`.
- [ ] Các đường dẫn báo cáo và artifact truy cập được.
- [ ] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [ ] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.
