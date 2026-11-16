"""Chạy đúng sáu trang mẫu T02, ghi bản chép và thời gian từng trang."""

import argparse
import csv
from pathlib import Path
import sys

from legal_rag.config import get_ocr_settings
from legal_rag.ingestion.ocr import GeminiEngine, SAMPLES, TesseractEngine, recognize_page
from legal_rag.llm import LLMError


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=("tesseract", "gemini"))
    args = parser.parse_args()
    try:
        settings = get_ocr_settings()
        engine = (TesseractEngine if args.engine == "tesseract" else GeminiEngine)(settings)
        output = ROOT / "runs/ocr_samples" / engine.name
        output.mkdir(parents=True, exist_ok=True)
        with (ROOT / "data/source_registry/documents.csv").open(
            encoding="utf-8", newline=""
        ) as source:
            documents = {row["document_id"]: row for row in csv.DictReader(source)}
        # Ghi từng trang ngay khi hoàn thành để giữ thời gian nếu trang sau lỗi.
        with (output / "timing.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("document_id", "page", "seconds", "cached"))
            for document_id, page, _ in SAMPLES:
                pdf = ROOT / documents[document_id]["pdf_path"]
                result = recognize_page(engine, pdf, page)
                (output / f"{document_id}_p{page}.txt").write_text(
                    result.text, encoding="utf-8", newline=""
                )
                cached = str(result.cached).lower()
                writer.writerow((document_id, page, f"{result.seconds:.6f}", cached))
                stream.flush()
                print(f"{document_id} p{page}: {result.seconds:.6f}s, cached={cached}", flush=True)
    except (OSError, ValueError, RuntimeError, LLMError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
