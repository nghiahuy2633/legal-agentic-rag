"""Kiểm tra checksum và lập danh sách loại trang của các PDF trong registry."""

import csv
from pathlib import Path
import sys

from legal_rag.ingestion.pdf import classify_pages
from legal_rag.ingestion.registry import verify_pdf_hashes


ROOT = Path(__file__).resolve().parents[1]


def inspect_pdfs(root: Path = ROOT) -> None:
    registry = root / "data/source_registry/documents.csv"
    output = root / "data/processed/page_inventory.csv"
    with registry.open(encoding="utf-8", newline="") as source:
        documents = list(csv.DictReader(source))

    # Xác minh tất cả PDF trước khi phân loại hoặc mở file đầu ra.
    verify_pdf_hashes(documents, root)

    rows = []
    summaries = []
    for document in documents:
        pages = classify_pages(root / document["pdf_path"])
        document_id = document["document_id"]
        for page in pages:
            rows.append((document_id, page.page, page.kind, page.content_chars))
        scans = sum(page.kind == "scan" for page in pages)
        summaries.append(
            f"{document_id}: {len(pages)} trang, scan={scans}, text={len(pages) - scans}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        writer.writerow(("document_id", "page", "kind", "content_chars"))
        writer.writerows(rows)
    for summary in summaries:
        print(summary)


def main() -> int:
    try:
        inspect_pdfs()
    except (OSError, ValueError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
