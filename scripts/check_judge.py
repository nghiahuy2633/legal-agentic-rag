"""Kiểm tra prompt chấm bằng file bẫy do điều hành cung cấp."""

import argparse
import json
import os
from pathlib import Path
import sys

from legal_rag.config import ENV_FILE, get_llm_settings
from legal_rag.evaluation.answers import judge_answer
from legal_rag.llm import CachedChat, HTTPChatClient, OfflineClient
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_traps(path):
    rows, ids = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Dòng {number}: phải là đối tượng")
        for field in ("id", "question", "answer", "reference_answer"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Dòng {number}: sai {field}")
        if row["id"] in ids:
            raise ValueError(f"Dòng {number}: id trùng")
        ids.add(row["id"])
        if not isinstance(row.get("required_points"), list) or any(
                not isinstance(p, str) or not p.strip() for p in row["required_points"]):
            raise ValueError(f"Dòng {number}: sai required_points")
        if not isinstance(row.get("evidence"), list) or any(
                not isinstance(e, dict) or not isinstance(e.get("id"), str)
                or not isinstance(e.get("text"), str) for e in row["evidence"]):
            raise ValueError(f"Dòng {number}: sai evidence")
        expect = row.get("expect")
        if not isinstance(expect, dict) or not expect or set(expect) - {
                "meaning_ok", "citations_relevant", "citation_issue_codes"}:
            raise ValueError(f"Dòng {number}: sai expect")
        for key, value in expect.items():
            if key == "citation_issue_codes":
                import re
                valid = isinstance(value, list) and all(
                    isinstance(code, str) and re.fullmatch(r"E\d+", code) for code in value)
            else:
                valid = type(value) is bool
            if not valid:
                raise ValueError(f"Dòng {number}: sai expect.{key}")
        rows.append(row)
    return rows


def main(argv=None, root=ROOT, chat=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = Path(root)
    path = args.file if args.file is not None else root / "eval/judge_traps.jsonl"
    try:
        rows = load_traps(path)
        if args.dry_run:
            print(f"Schema hợp lệ: {len(rows)} dòng; không gọi LLM.")
            return 0
        load_dotenv(ENV_FILE, override=False)
        model = os.environ.get("RAG_JUDGE_MODEL", "").strip()
        if not model:
            raise ValueError("Thiếu RAG_JUDGE_MODEL")
        if chat is None:
            settings = get_llm_settings()
            client = OfflineClient() if settings.offline else HTTPChatClient(
                settings.base_url, settings.api_key, rate_wait_max=65)
            chat = CachedChat(client, root / ".cache/llm")
        totals, passed = {}, {}
        success = True
        print("id | Kỳ vọng | Thực tế | Đạt")
        for row in rows:
            judgment = judge_answer(row, row, chat, model)
            actual = dict(meaning_ok=judgment.get("meaning_ok"),
                          citations_relevant=judgment.get("citations_relevant"),
                          citation_issue_codes=sorted({issue["code"] for issue in judgment.get("citation_issues", [])}))
            matches = []
            for key, expected in row["expect"].items():
                totals[key] = totals.get(key, 0) + 1
                expected = sorted(set(expected)) if key == "citation_issue_codes" else expected
                ok = not judgment.get("judge_error") and actual[key] == expected
                passed[key] = passed.get(key, 0) + int(ok)
                matches.append(ok)
            ok = all(matches)
            success &= ok
            print(f"{row['id']} | {json.dumps(row['expect'], ensure_ascii=False)} | "
                  f"{json.dumps(judgment if judgment.get('judge_error') else actual, ensure_ascii=False)} | {ok}")
        for key in sorted(totals):
            print(f"{key}: {passed[key]}/{totals[key]} = {passed[key] / totals[key]:.2%}")
        return 0 if success else 1
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Lỗi file hoặc cấu hình {path}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
