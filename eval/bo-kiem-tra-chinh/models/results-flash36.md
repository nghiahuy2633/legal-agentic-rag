# Kết quả bộ kiểm tra chính

Câu trả lời chấm được ở cả hai bản: 24/24. Thiếu: []

## Hành vi (30 câu)

| | full | basic |
|---|---|---|
| Từ chối đúng câu ngoài phạm vi | 6/6 | 0/6 |
| Từ chối nhầm câu trong phạm vi | 0/24 [] | 0/24 [] |
| Lỗi chạy | [] | [] |

## Câu trả lời (so ghép cặp full − basic, CI95 bootstrap 2000, hạt giống 7)

| Chỉ số | full | basic | Chênh [CI95] |
|---|---:|---:|---|
| Phủ ý (chính) | 0.775 | 0.576 | +0.199 [+0.073; +0.337] |
| Đúng nghĩa | 0.750 | 0.542 | +0.208 [+0.042; +0.375] |
| Khẳng định thiếu căn cứ TB | 0.667 | 0.417 | +0.250 [-0.125; +0.625] |
| Có lỗi trích dẫn | 0.708 | 0.500 | +0.208 [-0.042; +0.417] |
| Recall ngữ cảnh | 0.815 | 0.558 | +0.256 [+0.155; +0.374] |
| Độ dài TB | 8320.542 | 3624.375 | +4696.167 [+3565.042; +5957.833] |
| Lượt LLM TB | 4.042 | 1.000 | +3.042 [+2.708; +3.375] |

## Giả thuyết đặt trước

- H1 full từ chối đúng nhiều hơn basic: **đạt** (6/6 so với 0/6)
- H2 full từ chối nhầm ≤ 1/24: **đạt** (0/24)
- H3 phủ ý không kém quá 0,05: **đạt** (cận dưới +0.073)
- H4 phủ ý hơn basic: **đạt** (chênh +0.199, cận dưới +0.073)

## Theo tầng (chỉ mô tả)

| Chủ đề | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Phạm vi, định nghĩa | 3 | 0.69 | 0.31 | 0.67 | 0.22 |
| Vai trò | 3 | 0.83 | 0.42 | 0.83 | 0.50 |
| Phân loại, thông báo | 3 | 0.94 | 0.69 | 0.86 | 0.67 |
| Minh bạch, gắn nhãn | 3 | 0.39 | 0.44 | 0.44 | 0.39 |
| Rủi ro cao | 3 | 0.72 | 0.89 | 0.83 | 0.75 |
| Sự cố, chế tài | 3 | 0.93 | 0.93 | 1.00 | 0.75 |
| Cấm, đạo đức, khu vực công | 3 | 0.93 | 0.53 | 0.93 | 0.63 |
| Hiệu lực, chuyển tiếp | 3 | 0.75 | 0.39 | 0.94 | 0.56 |

| Dạng câu | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Tra cứu | 4 | 0.76 | 0.67 | 0.82 | 0.70 |
| Xác nhận | 4 | 0.92 | 0.56 | 0.81 | 0.40 |
| Tình huống | 4 | 0.83 | 0.50 | 0.83 | 0.48 |
| Thủ tục, chi tiết | 4 | 0.62 | 0.50 | 0.62 | 0.38 |
| Tiền đề sai | 4 | 0.69 | 0.65 | 0.88 | 0.79 |
| Nhiều văn bản | 2 | 0.82 | 0.82 | 1.00 | 0.88 |
| Câu rộng | 2 | 0.83 | 0.33 | 0.83 | 0.33 |

| Độ khó | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Dễ | 4 | 0.76 | 0.67 | 0.82 | 0.70 |
| Trung bình | 12 | 0.74 | 0.57 | 0.77 | 0.52 |
| Khó | 8 | 0.83 | 0.54 | 0.88 | 0.54 |

## Phân loại ý bắt buộc

| Loại | full | basic |
|---|---:|---:|
| đạt | 85 (79%) | 64 (59%) |
| lỗi truy xuất (căn cứ không có trong ngữ cảnh) | 13 (12%) | 35 (32%) |
| lỗi sinh (căn cứ có trong ngữ cảnh) | 9 (8%) | 9 (8%) |
| lỗi phạm vi (từ chối) | 0 (0%) | 0 (0%) |
| thiếu ý 'không có quy định' | 1 (1%) | 0 (0%) |

## Từng câu

| id | chủ đề | dạng | phủ ý full | phủ ý basic | recall full | recall basic |
|---|---|---|---:|---:|---:|---:|
| t001 | Phạm vi, định nghĩa | Tra cứu | 0.75 | 0.75 | 0.50 | 0.50 |
| t002 | Phạm vi, định nghĩa | Xác nhận | 1.00 | 0.00 | 1.00 | 0.00 |
| t003 | Phạm vi, định nghĩa | Tình huống | 0.33 | 0.17 | 0.50 | 0.17 |
| t004 | Vai trò | Thủ tục, chi tiết | 0.50 | 0.00 | 0.50 | 0.00 |
| t005 | Vai trò | Tiền đề sai | 1.00 | 0.75 | 1.00 | 1.00 |
| t006 | Vai trò | Tra cứu | 1.00 | 0.50 | 1.00 | 0.50 |
| t007 | Phân loại, thông báo | Xác nhận | 1.00 | 0.75 | 0.75 | 0.50 |
| t008 | Phân loại, thông báo | Tình huống | 1.00 | 0.50 | 0.83 | 0.50 |
| t009 | Phân loại, thông báo | Nhiều văn bản | 0.83 | 0.83 | 1.00 | 1.00 |
| t010 | Minh bạch, gắn nhãn | Thủ tục, chi tiết | 0.33 | 0.33 | 0.00 | 0.00 |
| t011 | Minh bạch, gắn nhãn | Tiền đề sai | 0.00 | 0.33 | 0.50 | 0.50 |
| t012 | Minh bạch, gắn nhãn | Câu rộng | 0.83 | 0.67 | 0.83 | 0.67 |
| t013 | Rủi ro cao | Tra cứu | 0.50 | 0.83 | 1.00 | 1.00 |
| t014 | Rủi ro cao | Xác nhận | 0.67 | 1.00 | 0.50 | 0.50 |
| t015 | Rủi ro cao | Tình huống | 1.00 | 0.83 | 1.00 | 0.75 |
| t016 | Sự cố, chế tài | Thủ tục, chi tiết | 1.00 | 1.00 | 1.00 | 0.50 |
| t017 | Sự cố, chế tài | Tiền đề sai | 1.00 | 1.00 | 1.00 | 1.00 |
| t018 | Sự cố, chế tài | Nhiều văn bản | 0.80 | 0.80 | 1.00 | 0.75 |
| t019 | Cấm, đạo đức, khu vực công | Tra cứu | 0.80 | 0.60 | 0.80 | 0.80 |
| t020 | Cấm, đạo đức, khu vực công | Xác nhận | 1.00 | 0.50 | 1.00 | 0.60 |
| t021 | Cấm, đạo đức, khu vực công | Tình huống | 1.00 | 0.50 | 1.00 | 0.50 |
| t022 | Hiệu lực, chuyển tiếp | Thủ tục, chi tiết | 0.67 | 0.67 | 1.00 | 1.00 |
| t023 | Hiệu lực, chuyển tiếp | Tiền đề sai | 0.75 | 0.50 | 1.00 | 0.67 |
| t024 | Hiệu lực, chuyển tiếp | Câu rộng | 0.83 | 0.00 | 0.83 | 0.00 |
