# Kết quả bộ kiểm tra chính (eval/bo-kiem-tra-chinh/, eval/bo-kiem-tra-chinh/ext-)

Câu trả lời chấm được ở cả hai bản: 47/48. Thiếu: ['t054']

## Hành vi (60 câu)

| | full | basic |
|---|---|---|
| Từ chối đúng câu ngoài phạm vi | 12/12 | 0/12 |
| Từ chối nhầm câu trong phạm vi | 0/48 [] | 0/48 [] |
| Lỗi chạy | [] | [] |

## Câu trả lời (so ghép cặp full − basic, CI95 bootstrap 2000, hạt giống 7)

| Chỉ số | full | basic | Chênh [CI95] |
|---|---:|---:|---|
| Phủ ý (chính) | 0.547 | 0.416 | +0.131 [+0.043; +0.220] |
| Đúng nghĩa | 0.532 | 0.426 | +0.106 [-0.064; +0.277] |
| Khẳng định thiếu căn cứ TB | 0.766 | 0.426 | +0.340 [-0.064; +0.745] |
| Có lỗi trích dẫn | 0.532 | 0.404 | +0.128 [+0.021; +0.255] |
| Recall ngữ cảnh | 0.754 | 0.608 | +0.146 [+0.082; +0.218] |
| Độ dài TB | 3504.681 | 1467.553 | +2037.128 [+1568.723; +2572.191] |
| Lượt LLM TB | 3.830 | 1.000 | +2.830 [+2.574; +3.085] |

## Giả thuyết đặt trước

- H1 full từ chối đúng nhiều hơn basic: **đạt** (12/12 so với 0/12)
- H2 full từ chối nhầm ≤ 1/24 (≤ 2/48): **đạt** (0/48)
- H3 phủ ý không kém quá 0,05: **đạt** (cận dưới +0.043)
- H4 phủ ý hơn basic: **đạt** (chênh +0.131, cận dưới +0.043)

## Theo tầng (chỉ mô tả)

| Chủ đề | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Phạm vi, định nghĩa | 6 | 0.46 | 0.21 | 0.53 | 0.25 |
| Vai trò | 6 | 0.32 | 0.32 | 0.58 | 0.61 |
| Phân loại, thông báo | 6 | 0.61 | 0.53 | 0.79 | 0.64 |
| Minh bạch, gắn nhãn | 6 | 0.47 | 0.37 | 0.49 | 0.38 |
| Rủi ro cao | 6 | 0.50 | 0.58 | 0.89 | 0.82 |
| Sự cố, chế tài | 6 | 0.67 | 0.48 | 0.91 | 0.70 |
| Cấm, đạo đức, khu vực công | 6 | 0.86 | 0.49 | 0.97 | 0.79 |
| Hiệu lực, chuyển tiếp | 5 | 0.48 | 0.33 | 0.90 | 0.69 |

| Dạng câu | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Tra cứu | 8 | 0.55 | 0.57 | 0.81 | 0.77 |
| Xác nhận | 8 | 0.69 | 0.40 | 0.78 | 0.53 |
| Tình huống | 8 | 0.57 | 0.35 | 0.75 | 0.53 |
| Thủ tục, chi tiết | 8 | 0.36 | 0.28 | 0.65 | 0.52 |
| Tiền đề sai | 8 | 0.52 | 0.42 | 0.74 | 0.69 |
| Nhiều văn bản | 4 | 0.57 | 0.53 | 0.88 | 0.69 |
| Câu rộng | 3 | 0.67 | 0.44 | 0.72 | 0.50 |

| Độ khó | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |
|---|---:|---:|---:|---:|---:|
| Dễ | 8 | 0.55 | 0.57 | 0.81 | 0.77 |
| Trung bình | 24 | 0.52 | 0.36 | 0.72 | 0.58 |
| Khó | 15 | 0.59 | 0.42 | 0.78 | 0.57 |

## Phân loại ý bắt buộc

| Loại | full | basic |
|---|---:|---:|
| đạt | 115 (55%) | 87 (42%) |
| lỗi truy xuất (căn cứ không có trong ngữ cảnh) | 35 (17%) | 67 (32%) |
| lỗi sinh (căn cứ có trong ngữ cảnh) | 50 (24%) | 49 (23%) |
| lỗi phạm vi (từ chối) | 0 (0%) | 0 (0%) |
| thiếu ý 'không có quy định' | 9 (4%) | 6 (3%) |

## Từng câu

| id | chủ đề | dạng | phủ ý full | phủ ý basic | recall full | recall basic |
|---|---|---|---:|---:|---:|---:|
| t001 | Phạm vi, định nghĩa | Tra cứu | 0.75 | 0.75 | 0.50 | 0.50 |
| t002 | Phạm vi, định nghĩa | Xác nhận | 0.00 | 0.00 | 0.00 | 0.00 |
| t003 | Phạm vi, định nghĩa | Tình huống | 0.50 | 0.17 | 0.50 | 0.17 |
| t004 | Vai trò | Thủ tục, chi tiết | 0.25 | 0.00 | 0.00 | 0.00 |
| t005 | Vai trò | Tiền đề sai | 0.25 | 0.50 | 1.00 | 1.00 |
| t006 | Vai trò | Tra cứu | 0.00 | 0.00 | 0.50 | 0.50 |
| t007 | Phân loại, thông báo | Xác nhận | 0.50 | 0.50 | 0.75 | 0.50 |
| t008 | Phân loại, thông báo | Tình huống | 0.50 | 0.33 | 0.83 | 0.50 |
| t009 | Phân loại, thông báo | Nhiều văn bản | 0.83 | 0.67 | 1.00 | 1.00 |
| t010 | Minh bạch, gắn nhãn | Thủ tục, chi tiết | 0.00 | 0.33 | 0.00 | 0.00 |
| t011 | Minh bạch, gắn nhãn | Tiền đề sai | 0.00 | 0.33 | 0.00 | 0.50 |
| t012 | Minh bạch, gắn nhãn | Câu rộng | 0.67 | 0.50 | 0.83 | 0.67 |
| t013 | Rủi ro cao | Tra cứu | 0.17 | 0.50 | 1.00 | 1.00 |
| t014 | Rủi ro cao | Xác nhận | 0.67 | 0.33 | 0.50 | 0.50 |
| t015 | Rủi ro cao | Tình huống | 0.17 | 0.67 | 1.00 | 0.75 |
| t016 | Sự cố, chế tài | Thủ tục, chi tiết | 0.60 | 0.60 | 1.00 | 0.50 |
| t017 | Sự cố, chế tài | Tiền đề sai | 1.00 | 1.00 | 1.00 | 1.00 |
| t018 | Sự cố, chế tài | Nhiều văn bản | 0.60 | 0.60 | 1.00 | 0.75 |
| t019 | Cấm, đạo đức, khu vực công | Tra cứu | 0.80 | 0.80 | 0.80 | 0.80 |
| t020 | Cấm, đạo đức, khu vực công | Xác nhận | 0.67 | 0.33 | 1.00 | 0.60 |
| t021 | Cấm, đạo đức, khu vực công | Tình huống | 1.00 | 0.50 | 1.00 | 0.50 |
| t022 | Hiệu lực, chuyển tiếp | Thủ tục, chi tiết | 0.00 | 0.33 | 1.00 | 1.00 |
| t023 | Hiệu lực, chuyển tiếp | Tiền đề sai | 0.75 | 0.50 | 1.00 | 0.67 |
| t024 | Hiệu lực, chuyển tiếp | Câu rộng | 0.50 | 0.00 | 0.50 | 0.00 |
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
