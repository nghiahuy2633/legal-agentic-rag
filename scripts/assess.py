"""Đánh giá tuân thủ từ dữ kiện có cấu trúc và lời khai."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from legal_rag.assessment.pipeline import prepare_assessment, run_assessment
from legal_rag.config import get_llm_settings
from legal_rag.llm import CachedChat, HTTPChatClient, OfflineClient

ROOT = Path(__file__).resolve().parents[1]


def read_checks(path):
    """JSON tự kiểm: danh sách {row_id, criterion_id, status}."""
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("Tự kiểm phải là danh sách")
    checks = {}
    for item in values:
        if not isinstance(item, dict) or set(item) != {"row_id", "criterion_id", "status"}:
            raise ValueError("Sai trường tự kiểm")
        if not all(isinstance(v, str) for v in item.values()) or item["status"] not in ("da", "chua"):
            raise ValueError("Sai giá trị tự kiểm")
        key = (item["row_id"], item["criterion_id"])
        if key in checks:
            raise ValueError("Trùng tiêu chí tự kiểm")
        checks[key] = item["status"]
    return checks


def main(argv=None, root=ROOT, client_factory=HTTPChatClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path)
    parser.add_argument("--message", action="append", default=[])
    for name in ("statement", "description"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-summary", action="store_true")
    args = parser.parse_args(argv)
    if args.facts is None and not args.message:
        parser.error("cần --facts hoặc --message")
    try:
        facts = json.loads(args.facts.read_text(encoding="utf-8")) if args.facts else None
        statement = args.statement.read_text(encoding="utf-8")
        description = args.description.read_text(encoding="utf-8")
        checks = read_checks(args.checks) if args.checks else None
        settings = get_llm_settings()
        client = OfflineClient() if settings.offline else client_factory(settings.base_url, settings.api_key)
        chat = CachedChat(client, root / ".cache/llm")
        prepared = None
        if args.facts is None:
            prepared = prepare_assessment(args.message, chat, settings.model)
            facts = prepared["facts"]
            print("Dữ kiện và câu hỏi lại:")
            print(json.dumps(prepared, ensure_ascii=False, indent=2))
        result = run_assessment(facts, statement, description,
            chat, settings.model,
            checks=checks, summarize_report=not args.no_summary)
        if prepared is not None:
            result["trace"]["preparation"] = prepared
            result["trace"]["llm_calls"] += 1
        out = args.out if args.out is not None else root / "runs/assess" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out.mkdir(parents=True, exist_ok=True)
        for filename, content in (("report.json", json.dumps(result["report"], ensure_ascii=False, indent=2) + "\n"),
                                  ("report.md", result["markdown"]),
                                  ("trace.json", json.dumps(result["trace"], ensure_ascii=False, indent=2) + "\n")):
            (out / filename).write_text(content, encoding="utf-8", newline="\n")
        print(result["markdown"])
    except (OSError, ValueError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) and str(error).startswith("Thiếu biến môi trường:") else "Kiểm tra file đầu vào, dữ kiện, tự kiểm và cấu hình."
        print("Lỗi: " + message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
