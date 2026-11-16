from dataclasses import FrozenInstanceError

import pymupdf
import pytest

from legal_rag.ingestion.pdf import PageInfo, classify_pages


SIGNATURE = (
    "Người ký: NGƯỜI KÝ THỬ\n"
    "Email: test@example.invalid\n"
    "Cơ quan: CƠ QUAN THỬ\n"
    "Thời gian ký: 01.01.2026 12:00:00 +07:00"
)
CONTENT = "Noi dung van ban thu nghiem du dai de phan loai text."


def make_pdf(tmp_path, texts):
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            # HTML dùng font Unicode do PyMuPDF cung cấp, giữ đúng dấu nhãn ký.
            page.insert_htmlbox(pymupdf.Rect(30, 30, 560, 500), f"<pre>{text}</pre>")
        document.save(path)
    return path


def test_regular_text(tmp_path):
    path = make_pdf(tmp_path, [CONTENT])
    assert classify_pages(path) == [PageInfo(1, "text", len(CONTENT))]


def test_signature_only(tmp_path):
    path = make_pdf(tmp_path, [SIGNATURE])
    with pymupdf.open(path) as document:
        assert "Người ký:" in document[0].get_text()
    assert classify_pages(path) == [PageInfo(1, "scan", 0)]


def test_image_only(tmp_path):
    path = tmp_path / "image.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
        pixmap.clear_with(128)
        page.insert_image(pymupdf.Rect(20, 20, 100, 100), pixmap=pixmap)
        document.save(path)
    assert classify_pages(path) == [PageInfo(1, "scan", 0)]


def test_signature_not_counted_with_content(tmp_path):
    path = make_pdf(tmp_path, [SIGNATURE + "\n" + CONTENT])
    assert classify_pages(path) == [PageInfo(1, "text", len(CONTENT))]


def test_threshold_and_page_numbers(tmp_path):
    path = make_pdf(tmp_path, ["a" * 29, "b" * 30])
    assert classify_pages(path) == [PageInfo(1, "scan", 29), PageInfo(2, "text", 30)]
    assert classify_pages(path, min_content_chars=29)[0].kind == "text"


def test_page_info_is_frozen():
    page = PageInfo(1, "scan", 0)
    with pytest.raises(FrozenInstanceError):
        page.kind = "text"
