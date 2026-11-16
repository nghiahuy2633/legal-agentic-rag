# Nguồn bộ sản phẩm mẫu

`eval/assessments.jsonl` được sinh bằng:

```
.venv/Scripts/python.exe eval/assessments_src/build_gold.py
```

- `gold.py`: danh sách nghĩa vụ chuẩn (G01 đến G48) dựng trực tiếp từ văn bản luật. Mỗi nghĩa vụ có vai trò áp dụng, mức rủi ro, điều kiện, và tập căn cứ ở mức Khoản hoặc Điểm. Danh sách này **độc lập với bảng nghĩa vụ** `src/legal_rag/knowledge/obligations.yaml`; hai bên chỉ được so qua mã căn cứ.
- `products.py`: 12 sản phẩm mẫu. Mỗi sản phẩm có tin nhắn người dùng, dữ kiện chuẩn, mô tả, lời khai hiện trạng, đáp án hiện trạng theo G, và dấu hiệu hành vi bị cấm.
- `optional: true` là nghĩa vụ còn tranh cãi về phạm vi. Hệ thống chọn hay không chọn nghĩa vụ này đều không bị tính lỗi.
- Một đáp án hiện trạng là danh sách khi nhiều nhãn đều chấp nhận được.
- `review_status: user_reviewed`: đáp án đã được người dùng soát.
