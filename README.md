# Agentic RAG hỗ trợ đánh giá tuân thủ pháp lý cho sản phẩm AI tại Việt Nam

Hệ thống giúp người làm sản phẩm AI biết mình phải tuân thủ những gì theo pháp luật Việt Nam. Nó làm hai việc:

- **Hỏi đáp có căn cứ:** người dùng đặt câu hỏi bằng tiếng Việt, nhận câu trả lời kèm trích dẫn tới Điều, Khoản, Điểm.
- **Rà soát nghĩa vụ cho một sản phẩm:** người dùng khai thông tin sản phẩm, nhận danh sách nghĩa vụ áp dụng và hiện trạng của từng nghĩa vụ.

Kết quả là hướng dẫn sơ bộ, không thay tư vấn pháp lý.

## Kho luật

| Văn bản | Số trang PDF | Dạng |
|---|---|---|
| Luật Trí tuệ nhân tạo 134/2025/QH15 | 20 | Ảnh scan |
| Nghị định 142/2026/NĐ-CP (trang 1–45, bỏ phụ lục biểu mẫu) | 97 | Ảnh scan |
| Thông tư 05/2026/TT-BKHCN | 9 | Có lớp chữ |
| Quyết định 33/2026/QĐ-TTg (Danh mục hệ thống AI rủi ro cao) | 16 | Ảnh scan |

133 trong 142 trang là ảnh scan nên kho luật được dựng bằng OCR, sau đó hiệu đính bằng cách đối chiếu với ảnh PDF. File PDF gốc nằm ở `data/raw/pdf/`, dữ liệu đã xử lý nằm sẵn ở `data/processed/`.

## Kiến trúc

```
                ┌──────────────────────── dựng một lần ────────────────────────┐
 PDF chính thức │ OCR, hiệu đính → tách Điều/Khoản/Điểm → đoạn tìm + đơn vị đọc │ → kho luật
                └──────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
                       Truy xuất: tra số Điều + BM25 + dense → gộp → xếp hạng lại
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     ▼                                                     ▼
          Agent hỏi đáp (đồ thị có trạng thái)                Rà soát tuân thủ
          phạm vi → truy vấn → bằng chứng → trả lời           dữ kiện → bảng nghĩa vụ → chấm hiện trạng
          → kiểm trích dẫn                                                 │
                     └──────────────────────────┬──────────────────────────┘
                                                ▼
                                    API FastAPI + giao diện web
```

### Nguyên tắc thiết kế

1. **Tìm bằng đơn vị nhỏ, đọc bằng đơn vị đủ nghĩa.** Tìm trên từng Khoản, Điểm để khớp chính xác; khi trúng thì đưa cho mô hình cả Khoản chứa nó để không mất điều kiện và ngoại lệ.
2. **Giới hạn ngữ cảnh theo token, không theo số đoạn,** vì độ dài các Khoản chênh nhau nhiều.
3. **Việc làm được bằng quy tắc thì không giao cho mô hình.** Chọn nghĩa vụ nào áp dụng và kiểm trích dẫn đều bằng quy tắc, nên kết quả lặp lại được.
4. **Thiếu căn cứ thì không khẳng định;** có căn cứ một phần thì trả lời phần đó.

## Luồng xử lý

### 1. Dựng kho luật (chạy một lần)

```
4 file PDF
  → trang có lớp chữ: đọc trực tiếp (9 trang)
  → trang scan: OCR bằng Gemini (77 trang); trang bị bộ lọc nội dung chặn thì Tesseract (4 trang)
  → chuẩn hóa bố cục, áp dụng 46 dòng hiệu đính sau khi đối chiếu ảnh PDF
  → tách Điều, Khoản, Điểm; đọc riêng bảng Danh mục rủi ro cao
  → 931 đoạn để tìm, 580 đơn vị để đọc (cả Khoản hoặc cả Điều), bảng dẫn chiếu giữa các Điều
```

### 2. Truy xuất

```
truy vấn
  → tra chính xác nếu câu hỏi nêu số Điều hoặc số hiệu văn bản
  → BM25 (từ khóa, có kênh bỏ dấu) và dense (jina-embeddings-v3)
  → gộp thứ hạng bằng RRF (k = 60), giới hạn tối đa 3 mục Danh mục ở phần đầu
  → xếp hạng lại 20 ứng viên đầu bằng bge-reranker-v2-m3
  → đổi mỗi đoạn trúng thành đơn vị đọc chứa nó, lấy đến khi đủ 8000 token ước tính
```

### 3. Agent hỏi đáp

Agent là một đồ thị LangGraph 16 nút, tối đa 8 lần gọi mô hình mỗi câu hỏi.

```
câu hỏi
  1. Kiểm đầu vào       rỗng, chào hỏi, quá 4000 ký tự → trả lời ngay;
                        hỏi mục lục ("liệt kê các điều của Luật…") → trả danh sách
                        từ kho, không gọi mô hình
  2. Phân tích          phạm vi, loại câu hỏi, dữ kiện sản phẩm trong câu
  3. Kiểm phạm vi       ngoài phạm vi → từ chối kèm hướng dẫn
  4. Cập nhật hồ sơ     lưu dữ kiện sản phẩm vào phiên
  5. Lập truy vấn       tách câu hỏi thành các truy vấn con
  6. Truy xuất          như mục 2, gộp kết quả các truy vấn
  7. Chấm bằng chứng    đủ / thiếu → viết lại truy vấn và tìm lại (tối đa 1 lần)
  8. Danh mục rủi ro cao   đối chiếu khi câu hỏi liên quan
  9. Bảng nghĩa vụ      lấy các dòng liên quan khi hỏi về nghĩa vụ
 10. Sinh câu trả lời   mỗi khẳng định gắn mã căn cứ
 11. Kiểm trích dẫn     bằng quy tắc: mã căn cứ có thật; số Điều, số hiệu, số tiền,
                        thời hạn phải có trong bằng chứng → có lỗi thì sửa một lần
 12. Hỏi lại            khi thiếu dữ kiện cần cho câu trả lời (tối đa một lần mỗi phiên)
 13. Trả kết quả        câu trả lời, trích dẫn, trace từng bước
```

Nhánh tra mục lục được thêm sau các lượt đo trong mục "Kết quả đo", nên các số ở đó không tính nhánh này. Tắt bằng `enable_navigation=False` trong `agent/config.py`.

Cấu hình đối chứng **RAG một lượt** chỉ gồm truy xuất và sinh câu trả lời, dùng cùng bộ truy xuất và cùng ngân sách ngữ cảnh.

### 4. Rà soát tuân thủ

```
người dùng khai sản phẩm (vai trò, lĩnh vực, mức rủi ro, có tạo nội dung không…)
  → trích dữ kiện từ lời khai, mỗi dữ kiện phải có câu trích làm bằng chứng
  → quy tắc chọn các dòng áp dụng trong bảng 92 nghĩa vụ
  → mô hình chấm hiện trạng từng nghĩa vụ theo tiêu chí: đã làm / chưa / chưa rõ
  → gợi ý các mục Danh mục rủi ro cao có thể liên quan (chỉ gợi ý, mức rủi ro do người dùng khai)
  → bản đánh giá, tải về được dạng Markdown
```

Bảng nghĩa vụ nằm ở `src/legal_rag/knowledge/obligations.yaml`. Mỗi dòng là một nghĩa vụ, có chủ thể, điều kiện áp dụng và căn cứ.

### Ai quyết định việc gì

| Việc | Do |
|---|---|
| Nghĩa vụ nào áp dụng cho sản phẩm | Quy tắc trên bảng nghĩa vụ |
| Trích dẫn có hợp lệ không | Quy tắc |
| Câu hỏi trong hay ngoài phạm vi, bằng chứng đã đủ chưa | Mô hình |
| Viết câu trả lời, chấm hiện trạng | Mô hình |
| Mức rủi ro của sản phẩm | Người dùng khai |

## Kết quả đo

Trên bộ kiểm tra chính 48 câu (kế hoạch và giả thuyết ghi trong `eval/bo-kiem-tra-chinh/`, so ghép cặp agent với RAG một lượt, khoảng tin cậy 95% bằng bootstrap):

| Chỉ số | Mô hình sinh | Agent | RAG một lượt | Chênh lệch |
|---|---|---|---|---|
| Phủ ý (tỷ lệ ý bắt buộc được nêu) | gemini-3.5-flash-lite | 0,547 | 0,416 | +0,131 [+0,043; +0,220] |
| Phủ ý | gemini-3.6-flash | 0,774 | 0,667 | +0,107 [+0,016; +0,207] |
| Recall ngữ cảnh | gemini-3.5-flash-lite | 0,754 | 0,608 | |
| Recall ngữ cảnh | gemini-3.6-flash | 0,830 | 0,613 | |

- Câu ngoài phạm vi bị từ chối: 12/12; câu trong phạm vi bị từ chối nhầm: 0/48.
- Trung bình 3,8 lần gọi mô hình mỗi câu.
- Kiểm trích dẫn trên bộ lỗi cài sẵn: bắt 20/20, báo nhầm 0/10.
- Rà soát trên 12 sản phẩm mẫu: precision/recall 1,00/0,97 với bảng và quy tắc, so với 0,73/0,32 khi chỉ dùng mô hình; chạy ba lần cho cùng danh sách nghĩa vụ (độ trùng 1,00 so với 0,28).

Bộ đề, kế hoạch và kết quả chi tiết nằm ở `eval/bo-kiem-tra-chinh/`.

### Truy xuất: đóng góp của từng thành phần

Đo trên bộ phát triển, 55 câu hỏi đơn, kho 931 đoạn; căn cứ chấm ở mức Khoản. Đây là phép đo lúc chọn cấu hình truy xuất, với một truy vấn mỗi câu.

| Cấu hình | Hit@5 | Recall@5 | Recall@10 | MRR | Recall trong 3000 token |
|---|---:|---:|---:|---:|---:|
| BM25 (tách âm tiết, có dấu và bỏ dấu) | 0,585 | 0,354 | 0,463 | 0,490 | 0,532 |
| Vector ngữ nghĩa (jina-embeddings-v3) | 0,736 | 0,471 | 0,536 | 0,669 | 0,666 |
| BM25 + vector, gộp RRF, giới hạn mục Danh mục | 0,774 | 0,493 | 0,625 | 0,656 | 0,683 |
| Thêm xếp hạng lại 20 đoạn đầu (cấu hình được chọn) | 0,811 | 0,510 | 0,653 | 0,718 | 0,695 |

Hệ thống cuối đọc theo ngân sách 8000 token thay vì 5 hay 10 kết quả đầu. Trên 52 câu đơn có nhãn của bộ phát triển, recall trong ngân sách này là 0,847 với một truy vấn và 0,893 khi agent tách truy vấn con (ở mức 3000 token: 0,713 và 0,709).

## Cài đặt

Cần Python 3.12 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Truy xuất dùng `jinaai/jina-embeddings-v3` và `BAAI/bge-reranker-v2-m3`, tải về ở lần chạy đầu. Muốn chạy không có mạng, đặt `HF_HOME` tới thư mục đã có model, cùng `HF_HUB_OFFLINE=1` và `TRANSFORMERS_OFFLINE=1`.

Tạo chỉ mục dense một lần trước khi chạy (không nằm trong repo):

```powershell
.\.venv\Scripts\python.exe scripts/build_index.py --model jina
```

## Cấu hình

Chép `.env.example` thành `.env` rồi điền. File `.env` không được đưa vào repo.

| Biến | Ý nghĩa |
|---|---|
| `RAG_LLM_MODEL` | Mô hình chính |
| `RAG_LLM_FALLBACK_MODELS` | Mô hình dự phòng, cách nhau bằng dấu phẩy |
| `RAG_LLM_MODELS` | Mô hình người dùng giao diện web được chọn; để trống thì không hiện ô chọn |
| `RAG_LLM_BASE_URL`, `RAG_LLM_API_KEY` | Endpoint tương thích OpenAI và khóa API |
| `RAG_JUDGE_MODEL` | Mô hình chấm câu trả lời khi đánh giá |
| `RAG_LLM_OFFLINE=1` | Chỉ phát lại câu đã có trong cache, không gọi mạng |

Không có khóa API trong `.env` vẫn chạy được giao diện: người dùng nhập khóa ở mục "Kết nối AI" và khóa chỉ sống trong phiên.

## Chạy

```powershell
.\.venv\Scripts\python.exe scripts/serve.py      # giao diện web tại http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/chat.py       # chat nhiều lượt trên terminal
.\.venv\Scripts\python.exe scripts/ask.py --query "Bên triển khai là gì?" --budget 8000   # hỏi một lượt (RAG một lượt)
.\.venv\Scripts\python.exe scripts/assess.py --help   # rà soát từ dữ kiện có cấu trúc
```

`scripts/chat.py` có các cờ `--no-rewrite`, `--no-verifier`, `--no-high-risk`, `--no-obligations`, `--references` để bật hoặc tắt từng thành phần.

Trên CPU, một câu mới mất khoảng 40 giây đến một phút, phần lớn do bước xếp hạng lại.

API chính:

| Phương thức | Đường dẫn | Việc |
|---|---|---|
| GET | `/api/health` | Trạng thái server và mô hình |
| POST | `/api/chat` | Hỏi đáp nhiều lượt theo `session_id` |
| GET, POST, DELETE | `/api/connection` | Kết nối khóa API theo phiên |
| POST | `/api/assess/start`, `/describe`, `/facts`, `/run`, `/answer`, `/check` | Các bước rà soát |
| GET | `/api/assess/next`, `/state`, `/report.md` | Câu hỏi tiếp theo, trạng thái, bản đánh giá |

## Demo không cần gọi mô hình

Các kịch bản demo nằm ở `eval/demo_scenarios.jsonl`: tra định nghĩa, câu ngoài phạm vi, robot phẫu thuật và Danh mục rủi ro cao, mức phạt, tình huống ứng dụng giáo dục.

```powershell
.\.venv\Scripts\python.exe scripts/check_demo.py --fill   # gọi mô hình thật, ghi cache các lượt còn thiếu
.\.venv\Scripts\python.exe scripts/check_demo.py          # kiểm tra, không gọi mô hình
$env:RAG_LLM_OFFLINE='1'; .\.venv\Scripts\python.exe scripts/serve.py
```

Ở chế độ này, câu trả lời là câu đã sinh từ trước; câu ngoài cache nhận thông báo chưa có sẵn. Đổi prompt, cấu hình hoặc dữ liệu thì cache cũ không còn trúng.

## Dựng lại kho luật

Dữ liệu đã có sẵn trong `data/processed/`; chỉ cần các lệnh này khi muốn dựng lại từ PDF.

```powershell
.\.venv\Scripts\python.exe scripts/inspect_pdfs.py                       # kiểm checksum, phân loại trang
.\.venv\Scripts\python.exe scripts/extract_corpus.py                     # OCR, có cache theo trang
.\.venv\Scripts\python.exe scripts/parse_articles.py --document <mã văn bản>
.\.venv\Scripts\python.exe scripts/build_chunks.py                       # đoạn tìm, đơn vị đọc, dẫn chiếu
```

## Đánh giá

```powershell
.\.venv\Scripts\python.exe scripts/run_eval.py --run-id r1 --configs full,basic --dry-run      # ước lượng
.\.venv\Scripts\python.exe scripts/run_eval.py --run-id r1 --configs full,basic                # chạy, có thể chạy tiếp
.\.venv\Scripts\python.exe scripts/run_eval.py --run-id r1 --configs full,basic --score-only   # chấm lại, không gọi mô hình
```

`full` là agent, `basic` là RAG một lượt. Kết quả nằm ở `runs/eval/<run-id>/`. Code chạy hệ thống không đọc thư mục `eval/`; nhãn chỉ dùng khi chấm.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest                  # toàn bộ, không gọi mô hình thật, không tải model
.\.venv\Scripts\python.exe -m pytest tests/retrieval  # một thành phần
node --test tests/api/test_ui.js                      # giao diện (tương tự với hai file .js còn lại)
```

| Thư mục | Kiểm gì |
|---|---|
| `tests/ingestion` | PDF, OCR, tách Điều, Khoản, Điểm |
| `tests/retrieval` | Tìm, gộp, xếp hạng lại, chọn ngữ cảnh, dẫn chiếu |
| `tests/generation` | Dựng bằng chứng, prompt, kiểm trích dẫn |
| `tests/agent` | Đồ thị hỏi đáp và các nút |
| `tests/compliance` | Bảng nghĩa vụ, Danh mục, rà soát |
| `tests/api` | API và giao diện |
| `tests/evaluation` | Bộ chạy và chấm |
| `tests/core` | Cấu hình, lớp gọi mô hình |

Trên Windows, nên đặt repo ở đường dẫn ngắn: một số test tạo cây thư mục sâu và sẽ báo `FileNotFoundError` nếu đường dẫn vượt 260 ký tự.

## Cấu trúc thư mục

| Thư mục | Nội dung |
|---|---|
| `src/legal_rag/ingestion/` | Đọc PDF, OCR, tách Điều/Khoản/Điểm, dựng đoạn và đơn vị đọc |
| `src/legal_rag/retrieval/` | Tra chính xác, BM25, dense, gộp, xếp hạng lại, chọn ngữ cảnh |
| `src/legal_rag/generation/` | Dựng bằng chứng, prompt, kiểm trích dẫn bằng quy tắc |
| `src/legal_rag/agent/` | Đồ thị hỏi đáp và các nút |
| `src/legal_rag/knowledge/` | Bảng nghĩa vụ, Danh mục rủi ro cao, quy tắc chọn |
| `src/legal_rag/assessment/` | Luồng rà soát: trích dữ kiện, chấm hiện trạng, báo cáo |
| `src/legal_rag/api/` | API FastAPI, phiên, giao diện web tĩnh |
| `src/legal_rag/evaluation/` | Bộ chạy và chấm đánh giá |
| `scripts/` | Lệnh dòng lệnh mỏng gọi vào `src/` |
| `prompts/` | Prompt có phiên bản; đổi prompt thì tạo phiên bản mới |
| `data/` | PDF gốc, sổ đăng ký văn bản, dữ liệu đã xử lý |
| `eval/` | Bộ câu phát triển, bộ bẫy, sản phẩm mẫu; `eval/bo-kiem-tra-chinh/` là bộ kiểm tra chính |

## Giấy phép mô hình

`jina-embeddings-v3` dùng giấy phép CC BY-NC 4.0, không dùng cho mục đích thương mại. `bge-reranker-v2-m3` dùng Apache 2.0.
