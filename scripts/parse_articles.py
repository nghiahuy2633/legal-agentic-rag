"""Phân tích các Điều từ text JSONL, xuất nguyên tử qua file tạm."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from legal_rag.ingestion.parser import parse_articles
from legal_rag.ingestion.normalize import apply_corrections
from legal_rag.ingestion.supplements import parse_appendices, parse_high_risk_list


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _parse_document(document: str, root: Path) -> list[dict]:
    source = root / "data/processed/text" / f"{document}.jsonl"
    pages = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if any(page["document_id"] != document for page in pages):
        raise ValueError(f"{document}: mã văn bản trong JSONL không khớp --document")
    try:
        return parse_articles(apply_corrections(pages, root / "data/processed/text_corrections.csv"))
    except ValueError as error:
        raise ValueError(f"{document}: {error}") from error


def _write(document: str, articles: list[dict], root: Path) -> None:
    target = root / "data/processed" / ("high_risk_list.jsonl" if document == "high_risk_list" else f"articles/{document}.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=target.parent,
                                prefix=target.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            for article in articles:
                stream.write(json.dumps(article, ensure_ascii=False) + "\n")
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True, action="append")
    args = parser.parse_args(argv)
    if any(not document or set(document) - ALLOWED for document in args.document):
        parser.error("Mã văn bản chỉ gồm chữ, số, dấu - và _")
    try:
        # Phân tích hết trước khi ghi: một văn bản lỗi thì không ghi văn bản nào.
        parsed = {document: _parse_document(document, root) for document in dict.fromkeys(args.document)}
        extras = {}
        for document in parsed:
            pages = [json.loads(line) for line in (root / f"data/processed/text/{document}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            pages = apply_corrections(pages, root / "data/processed/text_corrections.csv")
            if document == "05-2026-TT-BKHCN":
                extras[document + ".appendices"] = parse_appendices(pages)
            if document == "33-2026-QD-TTg":
                extras["high_risk_list"] = parse_high_risk_list(pages)
        for name, rows in extras.items():
            _write(name, rows, root)
        for document, articles in parsed.items():
            _write(document, articles, root)
            clauses = [clause for article in articles for clause in article["clauses"]]
            print(f"{document}: {len(articles)} Điều, {len(clauses)} Khoản, "
                  f"{sum(len(clause['points']) for clause in clauses)} Điểm")
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
