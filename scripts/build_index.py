"""Mã hóa index_text và truy vấn đánh giá bằng đúng một model, lưu cache nối chuỗi."""

import argparse
import json
from pathlib import Path
import sys

from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.dense import ModelEncoder

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None, root=ROOT, encoder_factory=ModelEncoder):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("jina", "viet"), required=True)
    parser.add_argument("--cache-dir", type=Path, default=root / ".cache/index")
    args = parser.parse_args(argv)
    try:
        chunks = read_jsonl(root / "data/processed/chunks.jsonl")
        rows = read_jsonl(root / "eval/retrieval.jsonl")
        queries = [r["question"] for r in rows] + [r["turn_text"] for r in rows if "turn_text" in r]
        encoder = encoder_factory(args.model)
        cache = VectorCache(args.cache_dir, chunks, args.model)
        cache.build_documents(encoder)
        cache.build_queries(queries, encoder)
        meta = json.loads((cache.path / "meta.json").read_text(encoding="utf-8"))
        truncated_queries = sum(json.loads(cache.query_path(q).read_text(encoding="utf-8"))["truncated"]
                                for q in dict.fromkeys(queries))
        print(json.dumps({"model": args.model, "cache": str(cache.path), "chunks": len(chunks),
                          "queries": len(set(queries)), "truncated_documents": meta["truncated_documents"],
                          "truncated_queries": truncated_queries}, ensure_ascii=False))
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
