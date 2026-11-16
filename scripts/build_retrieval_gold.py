"""Sinh nhãn truy xuất xác định; nhãn chưa được người duyệt."""

import argparse
from collections import Counter
import json
from pathlib import Path

from legal_rag.evaluation.retrieval_gold import build_gold
from legal_rag.evaluation.retrieval import label_summary

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "eval/retrieval.jsonl")
    args = parser.parse_args()
    overrides = ROOT / "eval/retrieval_overrides.jsonl"
    rows = build_gold(read_jsonl(ROOT / "eval/questions.jsonl") + read_jsonl(ROOT / "eval/scenarios.jsonl"),
                      read_jsonl(ROOT / "data/processed/parents.jsonl"),
                      read_jsonl(ROOT / "data/processed/chunks.jsonl"),
                      read_jsonl(overrides) if overrides.exists() else [])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
    print(json.dumps({"questions": len(rows), "status": dict(Counter(r["gold_status"] for r in rows))}, ensure_ascii=False))
    for row in rows:
        if row["gold_status"] == "unresolved":
            print(row["id"], row["notes"])
    print(json.dumps(label_summary(rows), ensure_ascii=False))


if __name__ == "__main__":
    main()
