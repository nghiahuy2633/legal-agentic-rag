# Kế hoạch đánh giá trên bộ kiểm tra chính (ghi trước khi chạy)

Bộ đề và kế hoạch này được commit trước khi chạy. Sau khi có kết quả, không sửa hệ thống, bộ đề hay cách tính rồi chạy lại trên bộ này.

## Hệ thống đo

- **full:** agent sau T59 (commit `9cbea08`), cấu hình mặc định.
- **basic:** RAG một lượt, cùng bộ truy xuất và cùng ngân sách ngữ cảnh 8000 token.
- Hai bản đều sinh bằng `gemini-3.5-flash-lite`. Mỗi bản chạy đúng một lần, gồm lớp câu trả lời (24 câu) và lớp hành vi (30 câu).

## Bộ đề

Bảng phân bổ đặt trước (`blueprint.json`) có 30 ô.
- **24 ô trong phạm vi:** 8 chủ đề, mỗi chủ đề 3 ô.
  - Chủ đề: phạm vi và định nghĩa; vai trò; phân loại rủi ro và thông báo; minh bạch và gắn nhãn; hệ thống rủi ro cao; sự cố, thanh tra, xử phạt, bồi thường; hành vi cấm, đạo đức, khu vực công; hiệu lực, chuyển tiếp, thử nghiệm có kiểm soát.
  - Dạng câu, giống cách chia của dev: tra cứu 4, xác nhận 4, thủ tục/chi tiết 4, tiền đề sai 4, tình huống 4, nhiều văn bản 2, câu rộng 2.
  - Độ khó: dễ 4 (tra cứu), trung bình 12 (xác nhận, thủ tục, tiền đề sai), khó 8 (tình huống, nhiều văn bản, câu rộng).
  - Cách viết: một nửa có dấu chuẩn, một phần tư văn nói viết tắt, một phần tư không dấu.
  - Vai người hỏi luân phiên trong 10 vai.
- **6 ô ngoài phạm vi:** thuế, lao động, luật AI nước ngoài, đời sống, viết code, né tránh vi phạm.

Quy trình:
1. Mô hình viết 2 câu ứng viên cho mỗi ô.
2. Bỏ câu có độ trùng từ (Jaccard) từ 0,4 trở lên so với dev và bộ giữ riêng thứ nhất.
3. Một mô hình khác chọn 1 câu mỗi ô và đánh dấu ô không khớp.
4. Đáp án chuẩn do mô hình soạn từ toàn văn 4 văn bản; mỗi ý kèm trích nguyên văn đã kiểm tự động.
5. Một mô hình khác duyệt đáp án.

Không có người duyệt; đáp án ghi `review_status = ai_reviewed`.

## Chấm

- **Judge chính:** judge A (mô hình ngôn ngữ khác họ với mô hình sinh), prompt `judge_v2`.
- **Judge phụ:** `gemini-3.5-flash`, nếu còn hạn mức. Báo tỷ lệ đồng thuận trên các câu chấm được ở cả hai judge.
- Recall ngữ cảnh tính theo `gold_parents` của đáp án chuẩn, không gọi LLM.

## Chỉ số và so sánh

So ghép cặp full với basic. Khoảng tin cậy 95% bằng bootstrap 2000 lần, hạt giống 7.

| Chỉ số | Vai trò |
|---|---|
| Phủ ý (tỷ lệ ý bắt buộc được nêu) | chính |
| Từ chối đúng câu ngoài phạm vi (n = 6) | chính |
| Từ chối nhầm câu trong phạm vi (n = 24) | chính |
| Đúng nghĩa, khẳng định thiếu căn cứ trung bình, có lỗi trích dẫn | phụ |
| Recall ngữ cảnh, độ dài, số lượt LLM trung bình | mô tả |

## Giả thuyết và ngưỡng đặt trước

- **H1 (hành vi):** full từ chối đúng nhiều câu ngoài phạm vi hơn basic.
- **H2 (từ chối nhầm):** full từ chối nhầm không quá 1/24.
- **H3 (không kém):** phủ ý của full không kém basic quá 0,05. Đạt khi cận dưới CI95 của chênh (full − basic) lớn hơn −0,05.
- **H4 (hơn):** phủ ý của full hơn basic. Đạt khi cận dưới CI95 lớn hơn 0.

Báo thêm phủ ý theo chủ đề, dạng câu và độ khó; chỉ mô tả, không kiểm định vì mỗi tầng chỉ có 2–12 câu.

Kết quả nào cũng được báo cáo như đo được, kèm phân tích lỗi theo từng câu: lỗi truy xuất (gold không có trong ngữ cảnh), lỗi sinh (gold có nhưng không nêu), lỗi phạm vi.

## Giới hạn đã biết trước

- Câu hỏi, đáp án chuẩn và judge chính cùng họ mô hình. Judge phụ khác họ được dùng để kiểm tra một phần.
- n nhỏ (24 và 30), nên khoảng tin cậy rộng.
- Sinh câu trả lời không tất định: lần chạy lại cùng cấu hình trên dev dao động khoảng ±0,14 ở chỉ số đúng nghĩa. Phủ ý ổn định hơn.
