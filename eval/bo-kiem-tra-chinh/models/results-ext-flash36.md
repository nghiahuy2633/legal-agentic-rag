# Kết quả bộ kiểm tra chính (eval/bo-kiem-tra-chinh/ext-)

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
| Phủ ý (chính) | 0.773 | 0.759 | +0.014 [-0.097; +0.132] |
| Đúng nghĩa | 0.833 | 0.875 | -0.042 [-0.208; +0.083] |
| Khẳng định thiếu căn cứ TB | 0.708 | 0.250 | +0.458 [-0.042; +1.000] |
| Có lỗi trích dẫn | 0.583 | 0.583 | +0.000 [-0.167; +0.167] |
| Recall ngữ cảnh | 0.846 | 0.667 | +0.178 [+0.064; +0.306] |
| Độ dài TB | 7792.708 | 4182.792 | +3609.917 [+2362.292; +4971.667] |
| Lượt LLM TB | 3.833 | 1.000 | +2.833 [+2.583; +3.083] |

## Giả thuyết đặt trước

- H1 full từ chối đúng nhiều hơn basic: **đạt** (6/6 so với 0/6)
- H2 full từ chối nhầm ≤ 1/24 (≤ 1/24): **đạt** (0/24)
- H3 phủ ý không kém quá 0,05: **không đạt** (cận dưới -0.097)
- H4 phủ ý hơn basic: **không đạt** (chênh +0.014, cận dưới -0.097)

## Theo tầng (chỉ mô tả)

| Chủ đề | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Phạm vi, định nghĩa | 3 | 0.69 | 0.69 | 0.61 | 0.28 |
| Vai trò | 3 | 0.81 | 0.86 | 0.72 | 0.72 |
| Phân loại, thông báo | 3 | 0.61 | 0.89 | 0.78 | 0.61 |
| Minh bạch, gắn nhãn | 3 | 0.81 | 0.48 | 0.94 | 0.36 |
| Rủi ro cao | 3 | 0.83 | 0.67 | 1.00 | 0.89 |
| Sự cố, chế tài | 3 | 0.66 | 0.66 | 0.89 | 0.66 |
| Cấm, đạo đức, khu vực công | 3 | 1.00 | 0.94 | 1.00 | 0.94 |
| Hiệu lực, chuyển tiếp | 3 | 0.78 | 0.89 | 0.82 | 0.88 |

| Dạng câu | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Tra cứu | 4 | 0.88 | 0.83 | 0.83 | 0.83 |
| Xác nhận | 4 | 1.00 | 0.88 | 1.00 | 0.67 |
| Tình huống | 4 | 0.64 | 0.73 | 0.75 | 0.58 |
| Thủ tục, chi tiết | 4 | 0.89 | 0.64 | 0.92 | 0.67 |
| Tiền đề sai | 4 | 0.65 | 0.78 | 0.82 | 0.59 |
| Nhiều văn bản | 2 | 0.42 | 0.50 | 0.75 | 0.50 |
| Câu rộng | 2 | 0.75 | 0.92 | 0.75 | 0.83 |

| Độ khó | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Dễ | 4 | 0.88 | 0.83 | 0.83 | 0.83 |
| Trung bình | 12 | 0.85 | 0.76 | 0.91 | 0.64 |
| Khó | 8 | 0.61 | 0.72 | 0.75 | 0.62 |

## Phân loại ý bắt buộc

| Loại | full | basic |
|---|---:|---:|
| đạt | 77 (72%) | 79 (74%) |
| lỗi truy xuất (căn cứ không có trong ngữ cảnh) | 15 (14%) | 22 (21%) |
| lỗi sinh (căn cứ có trong ngữ cảnh) | 12 (11%) | 4 (4%) |
| lỗi phạm vi (từ chối) | 0 (0%) | 0 (0%) |
| thiếu ý 'không có quy định' | 3 (3%) | 2 (2%) |

## Từng câu

| id | chủ đề | dạng | phủ ý full | phủ ý basic | recall full | recall basic |
|---|---|---|---:|---:|---:|---:|
| t031 | Phạm vi, định nghĩa | Tra cứu | 0.67 | 0.67 | 0.33 | 0.33 |
| t032 | Phạm vi, định nghĩa | Xác nhận | 1.00 | 1.00 | 1.00 | 0.00 |
| t033 | Phạm vi, định nghĩa | Tình huống | 0.40 | 0.40 | 0.50 | 0.50 |
| t034 | Vai trò | Thủ tục, chi tiết | 0.75 | 0.75 | 0.67 | 0.67 |
| t035 | Vai trò | Tiền đề sai | 0.67 | 0.83 | 0.50 | 0.50 |
| t036 | Vai trò | Tra cứu | 1.00 | 1.00 | 1.00 | 1.00 |
| t037 | Phân loại, thông báo | Xác nhận | 1.00 | 1.00 | 1.00 | 0.67 |
| t038 | Phân loại, thông báo | Tình huống | 0.50 | 0.83 | 0.50 | 0.33 |
| t039 | Phân loại, thông báo | Nhiều văn bản | 0.33 | 0.83 | 0.83 | 0.83 |
| t040 | Minh bạch, gắn nhãn | Thủ tục, chi tiết | 1.00 | 0.00 | 1.00 | 0.00 |
| t041 | Minh bạch, gắn nhãn | Tiền đề sai | 0.60 | 0.60 | 1.00 | 0.25 |
| t042 | Minh bạch, gắn nhãn | Câu rộng | 0.83 | 0.83 | 0.83 | 0.83 |
| t043 | Rủi ro cao | Tra cứu | 0.83 | 0.67 | 1.00 | 1.00 |
| t044 | Rủi ro cao | Xác nhận | 1.00 | 0.50 | 1.00 | 1.00 |
| t045 | Rủi ro cao | Tình huống | 0.67 | 0.83 | 1.00 | 0.67 |
| t046 | Sự cố, chế tài | Thủ tục, chi tiết | 0.80 | 0.80 | 1.00 | 1.00 |
| t047 | Sự cố, chế tài | Tiền đề sai | 0.67 | 1.00 | 1.00 | 0.80 |
| t048 | Sự cố, chế tài | Nhiều văn bản | 0.50 | 0.17 | 0.67 | 0.17 |
| t049 | Cấm, đạo đức, khu vực công | Tra cứu | 1.00 | 1.00 | 1.00 | 1.00 |
| t050 | Cấm, đạo đức, khu vực công | Xác nhận | 1.00 | 1.00 | 1.00 | 1.00 |
| t051 | Cấm, đạo đức, khu vực công | Tình huống | 1.00 | 0.83 | 1.00 | 0.83 |
| t052 | Hiệu lực, chuyển tiếp | Thủ tục, chi tiết | 1.00 | 1.00 | 1.00 | 1.00 |
| t053 | Hiệu lực, chuyển tiếp | Tiền đề sai | 0.67 | 0.67 | 0.80 | 0.80 |
| t054 | Hiệu lực, chuyển tiếp | Câu rộng | 0.67 | 1.00 | 0.67 | 0.83 |
