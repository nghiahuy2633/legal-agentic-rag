import csv
from copy import deepcopy

import pytest

from legal_rag.ingestion.normalize import apply_corrections


def correction_file(tmp_path, old, **overrides):
    path = tmp_path / "corrections.csv"
    row = dict(document_id="doc", page=2, old=old, new="đúng", evidence="Đã xem ảnh p2",
               verified_by="test giả")
    row.update(overrides)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, row)
        writer.writeheader()
        writer.writerow(row)
    return path


@pytest.mark.parametrize("text", ["không có", "sai sai"])
def test_requires_one_occurrence(tmp_path, text):
    with pytest.raises(ValueError, match="cần đúng 1 lần"):
        apply_corrections([dict(document_id="doc", page=2, text=text)],
                          correction_file(tmp_path, "sai"))


def test_right_document_page_and_immutable(tmp_path):
    pages = [dict(document_id=doc, page=page, text="sai")
             for doc, page in [("doc", 1), ("doc", 2), ("other", 2)]]
    original = deepcopy(pages)
    corrected = apply_corrections(pages, correction_file(tmp_path, "sai"))
    assert [p["text"] for p in corrected] == ["sai", "đúng", "sai"]
    assert pages == original


def test_missing_target_page(tmp_path):
    with pytest.raises(ValueError, match="Không có trang"):
        apply_corrections([dict(document_id="doc", page=1, text="sai")],
                          correction_file(tmp_path, "sai"))


def test_requires_evidence(tmp_path):
    with pytest.raises(ValueError, match="Thiếu"):
        apply_corrections([dict(document_id="doc", page=2, text="sai")],
                          correction_file(tmp_path, "sai", evidence=""))


def test_multiline_csv_after_windows_checkout(tmp_path):
    path = correction_file(tmp_path, "sai\nchữ")
    # Mô phỏng core.autocrlf, gồm cả xuống dòng bên trong ô old.
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    result = apply_corrections([dict(document_id="doc", page=2, text="sai\nchữ")], path)
    assert result[0]["text"] == "đúng"
