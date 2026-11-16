"""Đo T11 từ vector cache; chỉ bật reranker khi có --rerank."""

import argparse
import json
from pathlib import Path
import sys

from legal_rag.evaluation.retrieval_experiment import rebuild_overlap, run_experiments, validate_reachability
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.dense import DenseRetriever
from legal_rag.retrieval.rerank import CachedScorer

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "runs/t11/retrieval.json")
    parser.add_argument("--cache-dir", type=Path, default=root / ".cache/index")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-cache", type=Path, default=root / ".cache/rerank/scores.jsonl")
    args = parser.parse_args(argv)
    def read(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        chunks = read(root / "data/processed/chunks.jsonl")
        parents = read(root / "data/processed/parents.jsonl")
        gold = read(root / "eval/retrieval.jsonl")
        validate_reachability(chunks, gold, parents)
        queries = [r["question"] for r in gold] + [r["turn_text"] for r in gold if "turn_text" in r]
        dense, times = {}, {}
        for name in ("jina", "viet"):
            cache = VectorCache(args.cache_dir, chunks, name)
            vectors = cache.load_documents()
            query_vectors, times[name] = cache.load_queries(queries)
            dense[name] = DenseRetriever(chunks, vectors, query_vectors)
        result = run_experiments(chunks, gold, parents, dense, times,
                                 scorer=CachedScorer(args.rerank_cache) if args.rerank else None,
                                 overlap_outputs=rebuild_overlap(root))
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("best_bm25=" + result["best_bm25"])
    print(result["selection_rule"])
    print(result["reranker"])
    for name, run in result["runs"].items():
        print(name, json.dumps(run["metrics"]["all"], ensure_ascii=False))
    print("Chi tiết:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
