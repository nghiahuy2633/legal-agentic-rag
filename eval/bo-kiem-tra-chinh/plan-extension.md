# Kế hoạch mở rộng bộ kiểm tra chính (ghi trước khi tạo câu hỏi)

Bổ sung cho `plan.md` và `plan-models.md`. Mục đích là tăng số câu để khoảng tin cậy hẹp hơn. Cách làm giữ nguyên, không đổi hệ thống.

## Bộ đề thêm

- 30 câu mới, mã `t031`–`t060`:
  - 24 câu trong phạm vi;
  - 6 câu ngoài phạm vi.
- Cùng bảng phân bổ với `t001`–`t030`: 8 chủ đề × 3, cùng tỷ lệ dạng câu, độ khó và cách viết.
  - Vai người hỏi lệch 5, cách viết lệch 2, để không lặp lại đúng tổ hợp cũ.
- Cùng quy trình và mô hình với lần trước:
  1. mô hình viết 2 câu ứng viên mỗi ô;
  2. lọc trùng (Jaccard từ ≥ 0,4) với dev, bộ giữ riêng thứ nhất và cả `t001`–`t030` (câu đã chọn và câu ứng viên);
  3. mô hình khác chọn 1 câu mỗi ô;
  4. soạn đáp án từ toàn văn, mỗi ý có trích nguyên văn đã kiểm tự động;
  5. mô hình khác duyệt.
- Không chọn hay bỏ câu theo kết quả của hệ thống. Đáp án được commit trước khi sinh câu trả lời.

## Hệ thống

Hệ thống tại commit này, cấu hình mặc định, giống hệt hệ thống đã đo trong `plan-models.md`. Không sửa gì giữa hai lượt đo.

## Chạy và chấm

- Hai mô hình `gemini-3.5-flash-lite` và `gemini-3.6-flash`, mỗi mô hình cả basic và full:
  - lớp câu trả lời: 24 câu;
  - lớp hành vi: 30 câu.
- Judge B, prompt `judge_v2`, giống lượt so sánh mô hình.

## Phân tích

- **Kết quả chính:** gộp `t001`–`t060`, tức 48 câu trả lời và 60 câu hành vi.
  - Cùng chỉ số, cùng cách ghép cặp và CI95 như `plan.md` (bootstrap 2000, hạt giống 7).
  - Cùng giả thuyết H1–H4 cho từng mô hình.
- **Bắt buộc kèm bảng tách hai nửa:** `t001`–`t030` và `t031`–`t060`.
- Kết quả nào cũng báo cáo như đo được.

## Ghi chú khi tạo bộ (trước khi chạy hệ thống)

- Hai ô `t048`, `t056` có cả hai câu ứng viên bị loại vì trùng; mô hình viết lại 2 câu mới cho riêng hai ô này rồi chọn như các ô khác.
- Duyệt đáp án: `t031`–`t042` bằng mô hình duyệt như bộ cũ; `t043`–`t054` bằng một mô hình duyệt khác (cùng prompt). Trường `reviewer` trong `ext/reviews.jsonl` ghi rõ.
- `analyze.py` nhận thêm tham số bộ đề để phân tích nửa mới và bộ gộp; cách tính không đổi.
- Kết quả: 24 câu trả lời (107 ý bắt buộc), 30 câu hành vi; mọi trích dẫn đã kiểm tự động.
