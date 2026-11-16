"""Chuẩn hóa trang thuần túy, không hiệu đính nội dung OCR."""

import re
import unicodedata
import csv
from pathlib import Path


def normalize_ocr_layout(text: str) -> str:
    """Chuẩn hóa bố cục bản OCR, không đổi chữ.

    Các engine OCR khác nhau về dòng trống, khoảng trắng, in đậm cả dòng và cách ngắt dòng
    trong ô bảng (`<br>`). Parser không dùng các khác biệt này; chuẩn hóa trước để bảng
    hiệu đính chỉ còn các chỗ sửa chữ.
    """
    lines = []
    for line in unicodedata.normalize("NFC", text).splitlines():
        line = re.sub(r"[ \t]+", " ", line.replace("<br>", " ")).strip()
        line = re.sub(r"^\*\*(.+)\*\*$", r"\1", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"


def apply_corrections(pages: list[dict], path: Path) -> list[dict]:
    """Chuẩn hóa bố cục trang OCR, rồi áp hiệu đính có bằng chứng lên bản sao, trước phân tích."""
    result = [dict(page) for page in pages]
    for page in result:
        if page.get("source") == "ocr":
            page["text"] = normalize_ocr_layout(page["text"])
    if not path.exists():
        return result
    index = {}
    for page in result:
        key = (page["document_id"], int(page["page"]))
        if key in index:
            raise ValueError(f"Trang trùng: {key}")
        index[key] = page
    documents = {key[0] for key in index}
    # Checkout Git trên Windows có thể đổi cả xuống dòng trong ô CSV sang CRLF.
    # Đọc universal newlines để old/new vẫn dùng LF như hợp đồng dữ liệu.
    with path.open(encoding="utf-8", newline=None) as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["document_id", "page", "old", "new", "evidence", "verified_by"]:
            raise ValueError("Sai cột text_corrections.csv")
        for row in reader:
            if row["document_id"] not in documents:
                continue
            key = (row["document_id"], int(row["page"]))
            if key not in index:
                raise ValueError(f"Không có trang cần sửa: {key}")
            if not row["old"] or not row["evidence"].strip() or not row["verified_by"].strip():
                raise ValueError(f"Thiếu nội dung/bằng chứng hiệu đính: {key}")
            page = index[key]
            count = page["text"].count(row["old"])
            if count != 1:
                raise ValueError(f"{key}: old xuất hiện {count} lần, cần đúng 1 lần")
            page["text"] = page["text"].replace(row["old"], row["new"], 1)
    return result


def normalize_page(text: str, page: int) -> str:
    """Bỏ số trang đầu và đúng khối metadata chữ ký số đầu trang 1."""
    lines = unicodedata.normalize("NFC", text).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    if start < len(lines) and re.fullmatch(r"\d+", lines[start].strip()):
        del lines[start]
    if page == 1:
        start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
        # Hai dòng logo có trong bản xuất Cổng thông tin điện tử Chính phủ.
        if lines[start:start + 2] == ["VGP", "CHINHPHU.VN"]:
            start += 2
        prefixes = ("Người ký:", "Email:", "Cơ quan:", "Thời gian ký:")
        block = lines[start:start + len(prefixes)]
        if len(block) == len(prefixes) and all(
            line.strip().startswith(prefix) for line, prefix in zip(block, prefixes)
        ):
            del lines[start:start + len(prefixes)]
    return "\n".join(lines)
