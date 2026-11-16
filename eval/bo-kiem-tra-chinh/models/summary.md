# So sánh mô hình sinh trên bộ kiểm tra chính

Theo `eval/bo-kiem-tra-chinh/plan-models.md`. Hệ thống sau T62, cấu hình mặc định. Chấm bằng judge B, prompt `judge_v2`. Đủ 24 câu trả lời và 30 câu hành vi cho cả hai mô hình, cả hai bản. Chi tiết từng mô hình ở `results-flash-lite.md` và `results-flash36.md`.

## Ghép cặp full − basic theo từng mô hình (CI95 bootstrap 2000, hạt giống 7)

| Chỉ số | flash-lite | 3.6-flash |
|---|---|---|
| Phủ ý (chính) | 0.465 vs 0.427, +0.038 [−0.069; +0.142] | 0.775 vs 0.576, +0.199 [+0.073; +0.337] |
| Đúng nghĩa | 0.458 vs 0.500, −0.042 [−0.250; +0.167] | 0.750 vs 0.542, +0.208 [+0.042; +0.375] |
| Khẳng định thiếu căn cứ TB | 1.000 vs 0.333, +0.667 [+0.250; +1.125] | 0.667 vs 0.417, +0.250 [−0.125; +0.625] |
| Có lỗi trích dẫn | 0.542 vs 0.375, +0.167 [+0.000; +0.375] | 0.708 vs 0.500, +0.208 [−0.042; +0.417] |
| Recall ngữ cảnh | 0.697 vs 0.558, +0.138 [+0.045; +0.228] | 0.815 vs 0.558, +0.256 [+0.155; +0.374] |
| Từ chối đúng (full / basic) | 6/6 / 0/6 | 6/6 / 0/6 |
| Từ chối nhầm (full / basic) | 0/24 / 0/24 | 0/24 / 0/24 |

Giả thuyết đặt trước: flash-lite đạt H1, H2, không đạt H3, H4; 3.6-flash đạt cả H1–H4.

## Ghép cặp 3.6-flash − flash-lite theo từng bản (n = 24)

| Bản | Phủ ý | Đúng nghĩa |
|---|---|---|
| basic | 0.576 vs 0.427, +0.149 [+0.074; +0.233] | 0.542 vs 0.500, +0.042 [−0.083; +0.208] |
| full | 0.775 vs 0.465, +0.310 [+0.182; +0.447] | 0.750 vs 0.458, +0.292 [+0.125; +0.458] |

## Phân loại ý bắt buộc

| Loại | lite full | lite basic | 3.6 full | 3.6 basic |
|---|---:|---:|---:|---:|
| đạt | 52% | 45% | 79% | 59% |
| lỗi truy xuất | 18% | 33% | 12% | 32% |
| lỗi sinh | 27% | 20% | 8% | 8% |

## Token và chi phí mỗi câu (lớp câu trả lời, mô tả)

Token suy nghĩ = tổng − vào − ra; tính giá theo giá ra. Giá trả phí tại thời điểm đo, USD / 1 triệu token: flash-lite vào 0.30, ra 2.50; 3.6-flash vào 0.75, ra 3.75 (đến 31/12/2026).

| | Lượt LLM | Vào | Ra | Suy nghĩ | Tổng | Chi phí ước tính |
|---|---:|---:|---:|---:|---:|---:|
| flash-lite basic | 1.00 | 11 192 | 393 | 0 | 11 586 | $0.0043 |
| flash-lite full | 3.96 | 29 194 | 1 155 | 0 | 30 349 | $0.0116 |
| 3.6-flash basic | 1.00 | 11 192 | 1 028 | 3 637 | 15 858 | $0.0259 |
| 3.6-flash full | 4.04 | 32 441 | 2 860 | 8 544 | 43 844 | $0.0671 |

Mọi lượt đều có số token (`calls_with_usage` bằng số lượt LLM). Thời gian không so được vì lượt chạy bị ngắt và chạy tiếp nhiều lần do hạn mức.

## Giới hạn

- Prompt và quy tắc được tinh chỉnh trên flash-lite.
- Mỗi cấu hình chạy một lần; n = 24 và 30.
- Một số câu chạy lại sau lỗi 503 hoặc 429; chỉ lấy bản không lỗi.
