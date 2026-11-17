# Kế hoạch so sánh mô hình ngôn ngữ trên bộ kiểm tra chính (ghi trước khi chạy)

Bổ sung cho `plan.md`. Bộ đề, đáp án chuẩn và script phân tích giữ nguyên như đã chốt (commit `6e7ae27`, `528b7c1`). Không sửa hệ thống hay bộ đề theo kết quả.

## Câu hỏi

1. Chất lượng câu trả lời phụ thuộc vào mô hình sinh bao nhiêu?
2. Các kết luận agent so với basic có giữ nguyên khi đổi mô hình không?
   - full hơn basic ở hành vi và recall;
   - full không hơn basic ở phủ ý.

## Hệ thống

- Hệ thống bản nộp, cấu hình mặc định. Gồm câu trả lời thường bằng `answer_v2` và ghi số token.
- Mô hình được thay ở mọi lượt gọi LLM của bản đang chạy (biến `RAG_LLM_MODEL`):
  - basic: một lượt sinh;
  - full: phân tích, chấm bằng chứng, sinh, kiểm chứng, sửa.

## Mô hình

| Mô hình | Vai trò | Lớp chạy |
|---|---|---|
| `gemini-3.5-flash-lite` | mô hình hệ thống đang dùng, nhẹ | basic và full: câu trả lời (24) và hành vi (30) |
| `gemini-3.6-flash` | bản flash mới nhất gọi được | basic và full: câu trả lời (24); hành vi (30) nếu còn hạn mức |

- `gemma-4-26b-a4b-it` không chạy: mô hình này trả phần suy nghĩ ngay trong nội dung câu trả lời. Nếu sau này xử lý được phần đó thì chạy bổ sung và ghi rõ là chạy sau.
- Lần chạy này đo hệ thống cuối.

## Chấm

- Judge B, prompt `judge_v2`, cho mọi mô hình và cả hai bản.
  - Trên bộ này, judge B đồng thuận với judge A 0,93 ở từng ý.
  - Không dùng judge A vì hạn mức không đủ để chấm mọi bản như nhau.
- Phân tích bằng `eval/bo-kiem-tra-chinh/analyze.py`, không đổi.

## Chỉ số và so sánh

- Theo từng mô hình, ghép cặp full − basic (CI95 bootstrap 2000, hạt giống 7):
  - phủ ý (chính);
  - đúng nghĩa;
  - khẳng định thiếu căn cứ;
  - lỗi trích dẫn;
  - recall ngữ cảnh;
  - từ chối đúng và từ chối nhầm.
- Theo từng bản, ghép cặp giữa hai mô hình: phủ ý.
- Mô tả, không kiểm định:
  - token vào, ra, tổng mỗi câu;
  - lượt LLM;
  - độ dài;
  - thời gian;
  - phân loại ý bỏ sót (lỗi truy xuất, lỗi sinh).

## Giới hạn đã biết trước

- Prompt và quy tắc được tinh chỉnh trên `gemini-3.5-flash-lite`; mô hình khác có thể chịu thiệt.
- Mỗi cấu hình chạy một lần; n = 24 và 30.
- Một số lượt flash-lite có thể lấy từ cache cũ chưa có số token. `calls_with_usage` cho biết mức đủ của số liệu token.
