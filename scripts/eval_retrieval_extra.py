"""Đo các cấu hình thêm sau khi đã thấy kết quả thí nghiệm chính; không thuộc quy tắc chọn đã chốt."""

import argparse
import json
from pathlib import Path
from statistics import median

from legal_rag.evaluation.retrieval import evaluate
from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.dense import DenseRetriever
from legal_rag.retrieval.fusion import cap_list_items, rrf
from legal_rag.retrieval.rerank import CachedScorer, rerank

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {"rrf_E_jina_cap3": ("jina",), "rrf_E_jina_viet_cap3": ("jina", "viet")}
POOLS = (None, 20, 40)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/retrieval-extra.json")
    args = parser.parse_args()
    chunks = read_jsonl(ROOT / "data/processed/chunks.jsonl")
    parents = read_jsonl(ROOT / "data/processed/parents.jsonl")
    gold = read_jsonl(ROOT / "eval/retrieval.jsonl")
    queries = [row["question"] for row in gold]
    bm25 = BM25Retriever(chunks, BM25Config("syllable", "both", "index_text"))
    dense = {}
    for name in ("jina", "viet"):
        cache = VectorCache(ROOT / ".cache/index", chunks, name)
        dense[name] = DenseRetriever(chunks, cache.load_documents(), cache.load_queries(queries)[0])
    lookup = {c["chunk_id"]: c for c in chunks}
    scorer = CachedScorer(ROOT / ".cache/rerank/scores.jsonl")
    result = {}
    for name, models in CONFIGS.items():
        base = {r["id"]: cap_list_items(rrf([bm25.search(r["question"])]
                                            + [dense[m].search(r["question"]) for m in models]), chunks, 3)
                for r in gold}
        for pool in POOLS:
            predictions, latency = base, []
            if pool:
                predictions = {}
                for row in gold:
                    predictions[row["id"]] = rerank(row["question"], base[row["id"]], lookup, scorer, pool)
                    latency.append(scorer.last_latency_ms)
            key = f"{name}_r{pool}" if pool else name
            result[key] = {"metrics": evaluate(gold, predictions, parents=parents),
                           "rerank_median_ms": median(latency) if latency else 0}
            print(key, json.dumps(result[key]["metrics"]["questions"]["parent"], ensure_ascii=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
