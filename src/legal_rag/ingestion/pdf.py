"""Phân loại lớp text của trang PDF, không chạy OCR."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf


SIGNATURE_PREFIXES = ("Người ký:", "Email:", "Cơ quan:", "Thời gian ký:")


@dataclass(frozen=True)
class PageInfo:
    page: int
    kind: str
    content_chars: int


def classify_pages(pdf_path: Path, min_content_chars: int = 30) -> list[PageInfo]:
    """Đếm ký tự các dòng nội dung đã bỏ khoảng trắng đầu/cuối và xuống dòng.

    Các dòng bắt đầu bằng nhãn chữ ký số không được tính. Khoảng trắng
    bên trong dòng nội dung vẫn được tính; không sửa text hay chạy OCR.
    """
    pages = []
    with pymupdf.open(pdf_path) as document:
        for number, page in enumerate(document, start=1):
            lines = (line.strip() for line in page.get_text().splitlines())
            content_chars = sum(
                len(line) for line in lines if not line.startswith(SIGNATURE_PREFIXES)
            )
            kind = "scan" if content_chars < min_content_chars else "text"
            pages.append(PageInfo(number, kind, content_chars))
    return pages
