import csv
from hashlib import sha256
import importlib.util
from pathlib import Path

import pymupdf
import pytest


spec = importlib.util.spec_from_file_location(
    "inspect_pdfs", Path(__file__).resolve().parents[2] / "scripts/inspect_pdfs.py"
)
inspect_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspect_module)


@pytest.fixture
def corpus(tmp_path):
    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), "Sample document content longer than thirty characters.")
        document.new_page()
        document.save(pdf)
    registry = tmp_path / "data/source_registry/documents.csv"
    registry.parent.mkdir(parents=True)
    with registry.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("document_id", "pdf_path", "pdf_sha256"))
        writer.writerow(("sample", "sample.pdf", sha256(pdf.read_bytes()).hexdigest()))
    return tmp_path, pdf


def test_inventory_contract_and_repeatability(corpus, capsys):
    root, _ = corpus
    inspect_module.inspect_pdfs(root)
    output = root / "data/processed/page_inventory.csv"
    first = output.read_bytes()
    assert not first.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in first
    assert first.decode("utf-8").splitlines() == [
        "document_id,page,kind,content_chars",
        "sample,1,text,54",
        "sample,2,scan,0",
    ]
    assert capsys.readouterr().out == "sample: 2 trang, scan=1, text=1\n"
    inspect_module.inspect_pdfs(root)
    assert output.read_bytes() == first


def test_checksum_mismatch_preserves_inventory(corpus):
    root, pdf = corpus
    output = root / "data/processed/page_inventory.csv"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous inventory\n")
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA-256.*sample"):
        inspect_module.inspect_pdfs(root)
    assert output.read_bytes() == b"previous inventory\n"
