"""Kiểm tra tính toàn vẹn PDF dùng chung cho inventory và trích corpus."""

from hashlib import file_digest
from pathlib import Path


def verify_pdf_hashes(documents: list[dict], root: Path) -> None:
    for document in documents:
        with (root / document["pdf_path"]).open("rb") as source:
            actual = file_digest(source, "sha256").hexdigest()
        if actual != document["pdf_sha256"]:
            raise ValueError(f"SHA-256 không khớp: {document['document_id']}")
