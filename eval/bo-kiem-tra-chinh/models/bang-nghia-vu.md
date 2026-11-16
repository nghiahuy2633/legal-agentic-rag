# Đóng góp của bảng nghĩa vụ trên bộ hỏi đáp

Đây là đo mô tả, làm sau khi đã có kết quả bộ kiểm tra chính. Không đổi hệ thống và không đổi bộ đề. Dùng đáp án chuẩn đã sửa sau soát tay (`summary-48.md`).

## 1. Truy nguồn bằng chứng (bản full, 48 câu, không gọi thêm LLM)

Mỗi bằng chứng trong ngữ cảnh đều ghi nguồn: `retrieval`, `obligation` hoặc `high_risk`. Bảng nghĩa vụ chỉ thêm căn cứ chưa có trong ngữ cảnh (`append_evidence` bỏ qua parent đã có). Vì vậy, số ý bắt buộc mà căn cứ chỉ đến từ bảng là cận trên cho đóng góp của bảng qua đường bằng chứng.

| | flash-lite | 3.6-flash |
|---|---|---|
| Câu có bằng chứng từ bảng | 21/48 | 22/48 |
| Ý bắt buộc có căn cứ chỉ đến từ bảng | 1/202 | 3/202 |
| Trong đó được phủ | 1 | 3 |

## 2. Ablation thu nhỏ: full so với `no_obligations`

- Mô hình flash-lite.
- 21 câu có bằng chứng từ bảng trong lượt full.
- Chỉ lớp câu trả lời, chấm bằng judge B.
- So ghép cặp được 20 câu: `t010` của `no_obligations` bị judge trả sai schema ở cả ba lần chấm.
- Mỗi cấu hình chạy một lần. Phần chênh lệch có lẫn dao động do sinh không tất định.

| Chỉ số | full | no_obligations | Chênh [CI95] |
|---|---:|---:|---|
| Phủ ý | 0.537 | 0.463 | +0.074 [−0.027; +0.187] |
| Đúng nghĩa | 0.350 | 0.400 | −0.050 [−0.300; +0.200] |
| Khẳng định thiếu căn cứ TB | 1.300 | 0.850 | +0.450 [−0.250; +1.250] |
| Recall ngữ cảnh | 0.721 | 0.708 | +0.013 [+0.000; +0.037] |
| Độ dài TB (ký tự) | 5 487 | 4 247 | +1 240 [+395; +2 114] |
| Lượt LLM TB | 4.45 | 4.25 | +0.20 [+0.05; +0.40] |

Phủ ý từng câu (full / no_obligations): t004 0.25/0.00, t008 0.50/0.67, t009 0.83/0.83, t011 0.00/0.00, t012 0.67/0.67, t013 0.17/0.50, t015 0.17/0.33, t018 0.60/0.80, t021 1.00/1.00, t023 0.75/0.25, t024 0.50/0.33, t035 0.17/0.33, t038 0.50/0.50, t039 0.33/0.33, t041 0.80/0.20, t042 0.83/0.83, t045 0.67/0.33, t051 1.00/0.83, t053 0.67/0.33, t054 0.33/0.17.

## Đọc kết quả

- Trên bộ hỏi đáp, bảng nghĩa vụ gần như không thêm căn cứ mới: recall chỉ chênh +0.013. Tìm kiếm đã lấy được hầu hết căn cứ mà bảng mang tới.
- Phủ ý có xu hướng cao hơn khi có bảng (+0.074), nhưng CI chứa 0 và kết quả từng câu lẫn lộn. Chưa đủ để kết luận bảng giúp câu trả lời đầy đủ hơn.
- Khi có bảng, câu trả lời dài hơn rõ rệt và có xu hướng nhiều khẳng định thiếu căn cứ hơn.
- Bộ này không đo tính năng đánh giá tuân thủ (điều kiện áp dụng, dữ kiện còn thiếu, báo cáo), là chỗ bảng nghĩa vụ được dùng chính.
