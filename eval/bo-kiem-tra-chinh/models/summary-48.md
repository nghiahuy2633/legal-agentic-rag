# Kết quả bộ kiểm tra chính 48 câu (t001–t060)

Theo `eval/bo-kiem-tra-chinh/plan-extension.md`: kết quả chính là bộ gộp 48 câu trả lời và 60 câu hành vi, kèm bảng tách hai nửa. Hệ thống sau T62, cấu hình mặc định, không đổi giữa hai nửa. Chấm bằng judge B, prompt `judge_v2`. Bảng đầy đủ: `results-48-flash-lite.md`, `results-48-flash36.md` (gộp), `results-ext-*.md` (nửa mới), `results-flash-lite.md`, `results-flash36.md` (nửa cũ).

## Ghép cặp full − basic, bộ gộp (CI95 bootstrap 2000, hạt giống 7)

| Chỉ số | flash-lite (n = 47) | 3.6-flash (n = 48) |
|---|---|---|
| Phủ ý (chính) | 0.547 vs 0.416, +0.131 [+0.043; +0.220] | 0.774 vs 0.667, +0.107 [+0.016; +0.207] |
| Đúng nghĩa | 0.532 vs 0.426, +0.106 [−0.064; +0.277] | 0.792 vs 0.708, +0.083 [−0.021; +0.208] |
| Recall ngữ cảnh | 0.754 vs 0.608, +0.146 [+0.082; +0.218] | 0.830 vs 0.613, +0.217 [+0.135; +0.305] |
| Khẳng định thiếu căn cứ TB | 0.766 vs 0.426, +0.340 [−0.064; +0.745] | 0.688 vs 0.333, +0.354 [+0.042; +0.688] |
| Có lỗi trích dẫn | 0.532 vs 0.404, +0.128 [+0.021; +0.255] | 0.646 vs 0.542, +0.104 [−0.042; +0.250] |
| Từ chối đúng (full / basic) | 12/12 / 0/12 | 12/12 / 0/12 |
| Từ chối nhầm (full / basic) | 0/48 / 0/48 | 0/48 / 0/48 |

Giả thuyết đặt trước: cả hai mô hình đạt H1–H4.

## Tách hai nửa (phủ ý)

| | Nửa cũ t001–t030 | Nửa mới t031–t060 | Gộp |
|---|---|---|---|
| flash-lite full / basic | 0.465 / 0.427 | 0.633 / 0.405 | 0.547 / 0.416 |
| flash-lite chênh | +0.038 [−0.069; +0.142] | +0.228 [+0.109; +0.351] | +0.131 [+0.043; +0.220] |
| 3.6-flash full / basic | 0.775 / 0.576 | 0.773 / 0.759 | 0.774 / 0.667 |
| 3.6-flash chênh | +0.199 [+0.073; +0.337] | +0.014 [−0.097; +0.132] | +0.107 [+0.016; +0.207] |
| Recall chênh (lite / 3.6) | +0.14 / +0.26 | +0.15 / +0.18 | +0.15 / +0.22 |

Hai nửa khác nhau trong phạm vi dao động của mẫu 24 câu. Chênh recall dương ở mọi ô.

## Phân loại ý bắt buộc, bộ gộp

| Loại | lite full | lite basic | 3.6 full | 3.6 basic |
|---|---:|---:|---:|---:|
| đạt | 55% | 42% | 75% | 67% |
| lỗi truy xuất | 17% | 32% | 13% | 27% |
| lỗi sinh | 24% | 23% | 10% | 6% |

## Token và chi phí mỗi câu, bộ gộp (lớp câu trả lời, mô tả)

Cách tính và giá như `summary.md`: token suy nghĩ = tổng − vào − ra, tính theo giá ra.

| | Lượt LLM | Vào | Ra | Suy nghĩ | Tổng | Chi phí / câu | 48 câu |
|---|---:|---:|---:|---:|---:|---:|---:|
| flash-lite basic | 1.00 | 11 248 | 406 | 0 | 11 654 | $0.0044 | $0.21 |
| flash-lite full | 3.81 | 28 404 | 1 228 | 0 | 29 632 | $0.0116 | $0.56 |
| 3.6-flash basic | 1.00 | 11 248 | 1 104 | 3 851 | 16 203 | $0.0270 | $1.30 |
| 3.6-flash full | 3.94 | 30 448 | 2 661 | 8 402 | 41 511 | $0.0643 | $3.09 |

Giá 3.6-flash từ 01/01/2027 (vào 1.50, ra 7.50) làm chi phí gấp đôi: basic $0.054, full $0.129 mỗi câu.

## Soát tay và sửa đáp án chuẩn

Người soát tay một mẫu 6 câu của nửa cũ (`t001`, `t006`, `t009`, `t010`, `t017`, `t019`), đối chiếu với nguyên văn văn bản:

- **Đáp án chuẩn:** 23/24 ý đúng, 1 ý chưa chắc (`t006` ý 2).
- **Judge:** người soát đồng ý với 24/24 phán quyết "có phủ" hoặc "không phủ".

Sau soát tay, sửa 3 đáp án chuẩn, không xét đến kết quả hệ thống:

- `t006` ý 2: viết lại sát nguyên văn khoản 2 Điều 1 Thông tư 05.
- `t019`: bỏ câu về khoản 5 Điều 7 khỏi đoạn đáp án, vì câu này không có ý bắt buộc tương ứng.
- `t001` ý 2: bỏ định nghĩa trí tuệ nhân tạo (khoản 1 Điều 3) khỏi ý bắt buộc và khỏi căn cứ vàng, vì đây là định nghĩa phụ. Nội dung vẫn giữ trong đoạn đáp án.

Chấm lại 3 câu này cho cả 4 lượt chạy. Kết quả gộp gần như không đổi và không đổi kết luận nào; chi tiết ở `results-48-*-dap-an-sua.md`.

| Phủ ý full − basic | Đáp án gốc | Đáp án đã sửa |
|---|---|---|
| flash-lite | +0.131 [+0.043; +0.220] | +0.141 [+0.056; +0.230] |
| 3.6-flash | +0.107 [+0.016; +0.207] | +0.111 [+0.019; +0.211] |

Giới hạn của judge mà mẫu soát tay cho thấy: judge chỉ xét câu trả lời có phủ từng ý hay không, nên không bắt được các lỗi sau.

- `t006`, flash-lite basic: từ chối oan. Câu trả lời đã trích định nghĩa nhưng vẫn kết luận chưa đủ dữ kiện.
- `t009`, flash-lite basic: nêu sai tên lĩnh vực trong Danh mục ("tài chính", thực tế là "ngân hàng").
- `t019`, 3.6-flash full: dẫn Quyết định 33 như một quy định cấm của Luật, và có nhiều nội dung thừa.
- `t017`, 3.6-flash full: vẫn hỏi lại vai trò ở cuối câu trả lời dù không cần.

Mẫu chỉ có 6 câu và phần lớn là câu dễ.

## Ghi chú

- `t054` basic của flash-lite: judge trả mã lỗi trích dẫn `P30` (mã không có trong bằng chứng của câu trả lời), sai mẫu `E…` của bộ kiểm schema, lặp lại ở hai lần chấm lại. Câu này bị loại khỏi so sánh ghép cặp của flash-lite. Không sửa judge sau khi thấy kết quả.
- `t037` basic và `t047` full của flash-lite lỗi JSON ở lần chấm đầu, chấm lại được.
- Mỗi cấu hình chạy một lần. Một số câu chạy lại sau lỗi 429; chỉ lấy bản không lỗi.
