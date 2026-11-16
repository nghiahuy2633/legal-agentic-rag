"""Trích corpus giới hạn body_last_page, tiếp tục từ cache khi chạy lại.

Trang scan đọc bằng Gemini; trang bị bộ lọc nội dung chặn tự chuyển sang Tesseract
(trừ khi --no-fallback). Bản máy đọc được người soát hiệu đính qua text_corrections.csv.
"""

import argparse
from pathlib import Path
import sys

from legal_rag.config import get_ocr_settings
from legal_rag.ingestion.corpus import RequestPacer, extract_corpus
from legal_rag.ingestion.ocr import GeminiEngine, TesseractEngine
from legal_rag.llm import HTTPChatClient


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=5)
    parser.add_argument("--on-block", choices=("stop", "skip"), default="stop")
    parser.add_argument("--retry-blocked", action="store_true")
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--no-fallback", action="store_true",
                        help="không dùng Tesseract cho trang bị bộ lọc chặn")
    args = parser.parse_args()
    try:
        settings = get_ocr_settings()
        client = HTTPChatClient(settings.base_url, settings.api_key,
                                before_request=RequestPacer(args.delay))
        engine = GeminiEngine(settings, client=client)
        extract_corpus(engine, ROOT, dry_run=args.dry_run, on_block=args.on_block,
                       retry_blocked=args.retry_blocked, model=settings.model, no_api=args.no_api,
                       fallback=None if args.no_fallback else TesseractEngine(settings))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
