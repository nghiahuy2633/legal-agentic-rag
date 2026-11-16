# Kết quả bộ kiểm tra chính (eval/bo-kiem-tra-chinh/ext-)

Câu trả lời chấm được ở cả hai bản: 23/24. Thiếu: ['t054']

## Hành vi (30 câu)

| | full | basic |
|---|---|---|
| Từ chối đúng câu ngoài phạm vi | 6/6 | 0/6 |
| Từ chối nhầm câu trong phạm vi | 0/24 [] | 0/24 [] |
| Lỗi chạy | [] | [] |

## Câu trả lời (so ghép cặp full − basic, CI95 bootstrap 2000, hạt giống 7)

| Chỉ số | full | basic | Chênh [CI95] |
|---|---:|---:|---|
| Phủ ý (chính) | 0.633 | 0.405 | +0.228 [+0.109; +0.351] |
| Đúng nghĩa | 0.609 | 0.348 | +0.261 [+0.000; +0.522] |
| Khẳng định thiếu căn cứ TB | 0.522 | 0.522 | +0.000 [-0.696; +0.565] |
| Có lỗi trích dẫn | 0.522 | 0.435 | +0.087 [+0.000; +0.217] |
| Recall ngữ cảnh | 0.814 | 0.660 | +0.154 [+0.059; +0.264] |
| Độ dài TB | 3777.000 | 1487.348 | +2289.652 [+1488.913; +3289.348] |
| Lượt LLM TB | 3.696 | 1.000 | +2.696 [+2.348; +3.087] |

## Giả thuyết đặt trước

- H1 full từ chối đúng nhiều hơn basic: **đạt** (6/6 so với 0/6)
- H2 full từ chối nhầm ≤ 1/24 (≤ 1/24): **đạt** (0/24)
- H3 phủ ý không kém quá 0,05: **đạt** (cận dưới +0.109)
- H4 phủ ý hơn basic: **đạt** (chênh +0.228, cận dưới +0.109)

## Theo tầng (chỉ mô tả)

| Chủ đề | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Phạm vi, định nghĩa | 3 | 0.51 | 0.11 | 0.72 | 0.28 |
| Vai trò | 3 | 0.47 | 0.47 | 0.67 | 0.72 |
| Phân loại, thông báo | 3 | 0.61 | 0.56 | 0.72 | 0.61 |
| Minh bạch, gắn nhãn | 3 | 0.71 | 0.34 | 0.69 | 0.36 |
| Rủi ro cao | 3 | 0.67 | 0.67 | 0.94 | 0.89 |
| Sự cố, chế tài | 3 | 0.60 | 0.23 | 0.82 | 0.66 |
| Cấm, đạo đức, khu vực công | 3 | 0.89 | 0.44 | 1.00 | 0.94 |
| Hiệu lực, chuyển tiếp | 2 | 0.58 | 0.42 | 1.00 | 0.90 |

| Dạng câu | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Tra cứu | 4 | 0.67 | 0.62 | 0.92 | 0.83 |
| Xác nhận | 4 | 0.92 | 0.50 | 1.00 | 0.67 |
| Tình huống | 4 | 0.59 | 0.29 | 0.67 | 0.58 |
| Thủ tục, chi tiết | 4 | 0.51 | 0.24 | 0.79 | 0.67 |
| Tiền đề sai | 4 | 0.53 | 0.26 | 0.72 | 0.59 |
| Nhiều văn bản | 2 | 0.42 | 0.42 | 0.75 | 0.50 |
| Câu rộng | 1 | 0.83 | 0.83 | 0.83 | 0.83 |

| Độ khó | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Dễ | 4 | 0.67 | 0.62 | 0.92 | 0.83 |
| Trung bình | 12 | 0.65 | 0.33 | 0.84 | 0.64 |
| Khó | 7 | 0.58 | 0.40 | 0.71 | 0.60 |

## Phân loại ý bắt buộc

| Loại | full | basic |
|---|---:|---:|
| đạt | 59 (58%) | 38 (38%) |
| lỗi truy xuất (căn cứ không có trong ngữ cảnh) | 16 (16%) | 31 (31%) |
| lỗi sinh (căn cứ có trong ngữ cảnh) | 21 (21%) | 27 (27%) |
| lỗi phạm vi (từ chối) | 0 (0%) | 0 (0%) |
| thiếu ý 'không có quy định' | 5 (5%) | 5 (5%) |

## Từng câu

| id | chủ đề | dạng | phủ ý full | phủ ý basic | recall full | recall basic |
|---|---|---|---:|---:|---:|---:|
| t031 | Phạm vi, định nghĩa | Tra cứu | 0.33 | 0.33 | 0.67 | 0.33 |
| t032 | Phạm vi, định nghĩa | Xác nhận | 1.00 | 0.00 | 1.00 | 0.00 |
| t033 | Phạm vi, định nghĩa | Tình huống | 0.20 | 0.00 | 0.50 | 0.50 |
| t034 | Vai trò | Thủ tục, chi tiết | 0.25 | 0.25 | 0.67 | 0.67 |
| t035 | Vai trò | Tiền đề sai | 0.17 | 0.17 | 0.33 | 0.50 |
| t036 | Vai trò | Tra cứu | 1.00 | 1.00 | 1.00 | 1.00 |
| t037 | Phân loại, thông báo | Xác nhận | 1.00 | 0.67 | 1.00 | 0.67 |
| t038 | Phân loại, thông báo | Tình huống | 0.50 | 0.33 | 0.33 | 0.33 |
| t039 | Phân loại, thông báo | Nhiều văn bản | 0.33 | 0.67 | 0.83 | 0.83 |
| t040 | Minh bạch, gắn nhãn | Thủ tục, chi tiết | 0.50 | 0.00 | 0.50 | 0.00 |
| t041 | Minh bạch, gắn nhãn | Tiền đề sai | 0.80 | 0.20 | 0.75 | 0.25 |
| t042 | Minh bạch, gắn nhãn | Câu rộng | 0.83 | 0.83 | 0.83 | 0.83 |
| t043 | Rủi ro cao | Tra cứu | 0.33 | 0.50 | 1.00 | 1.00 |
| t044 | Rủi ro cao | Xác nhận | 1.00 | 1.00 | 1.00 | 1.00 |
| t045 | Rủi ro cao | Tình huống | 0.67 | 0.50 | 0.83 | 0.67 |
| t046 | Sự cố, chế tài | Thủ tục, chi tiết | 0.80 | 0.20 | 1.00 | 1.00 |
| t047 | Sự cố, chế tài | Tiền đề sai | 0.50 | 0.33 | 0.80 | 0.80 |
| t048 | Sự cố, chế tài | Nhiều văn bản | 0.50 | 0.17 | 0.67 | 0.17 |
| t049 | Cấm, đạo đức, khu vực công | Tra cứu | 1.00 | 0.67 | 1.00 | 1.00 |
| t050 | Cấm, đạo đức, khu vực công | Xác nhận | 0.67 | 0.33 | 1.00 | 1.00 |
| t051 | Cấm, đạo đức, khu vực công | Tình huống | 1.00 | 0.33 | 1.00 | 0.83 |
| t052 | Hiệu lực, chuyển tiếp | Thủ tục, chi tiết | 0.50 | 0.50 | 1.00 | 1.00 |
| t053 | Hiệu lực, chuyển tiếp | Tiền đề sai | 0.67 | 0.33 | 1.00 | 0.80 |
