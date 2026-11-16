"""Đo bộ kiểm chứng nội dung; dry-run không đọc cấu hình LLM."""

import argparse
import csv
import json
from pathlib import Path

from legal_rag.agent.verify import verify_answer
from legal_rag.config import get_llm_settings
from legal_rag.generation.evidence import build_evidence
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None, root=ROOT, client_factory=HTTPChatClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    rows = read_jsonl(root / "eval/verifier_traps.jsonl")
    if args.dry_run:
        print(json.dumps(dict(total=len(rows), bat=sum(r["expect"] == "bat" for r in rows),
                              dat=sum(r["expect"] == "dat" for r in rows)), ensure_ascii=False))
        return 0
    parents = {p["parent_id"]: p for p in read_jsonl(root / "data/processed/parents.jsonl")}
    # Kiểm tra mọi căn cứ chạm được trước khi tạo client hay chạy phép đo.
    missing = sorted({key for row in rows for key in row["parents"] if key not in parents})
    if missing:
        raise ValueError("Căn cứ không chạm được: " + ", ".join(missing))
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))
    settings = get_llm_settings()
    fallback = getattr(settings, "fallback_models", ())
    client = client_factory(settings.base_url, settings.api_key, **({"max_attempts": 3} if fallback else {}))
    chat = FallbackChat(CachedChat(client, root / ".cache/llm"), fallback)
    results = []
    for row in rows:
        result = dict(row, issues=[], caught=False, correct=False)
        try:
            checked = verify_answer(row["answer"], build_evidence([parents[k] for k in row["parents"]], documents),
                                    chat, settings.model)
            result.update(checked, caught=bool(checked["issues"]))
            if not checked["verify_ok"]:
                result["error"] = "Phản hồi kiểm chứng hỏng."
            else:
                result["correct"] = result["caught"] == (row["expect"] == "bat")
        except LLMError as error:
            result["error"] = str(error)
        results.append(result)
    bat = [r for r in results if r["expect"] == "bat"]
    dat = [r for r in results if r["expect"] == "dat"]
    report = dict(catch_rate=sum(r["correct"] for r in bat) / len(bat) if bat else None,
                  false_positive_rate=sum(r["caught"] for r in dat) / len(dat) if dat else None,
                  errors=sum("error" in r for r in results),
                  mismatches=[r for r in results if not r["correct"]], results=results)
    output = root / "runs/t21/verifier.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
