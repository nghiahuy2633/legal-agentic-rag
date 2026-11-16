"""Đo T17 chỉ từ cache Jina và reranker, không mã hóa hay nạp model."""

import argparse
import json
from math import isclose
from pathlib import Path
import sys

from legal_rag.evaluation.retrieval import evaluate, gold_units, label_summary
from legal_rag.evaluation.retrieval_experiment import validate_reachability
from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.context import select_context
from legal_rag.retrieval.dense import DenseRetriever
from legal_rag.retrieval.exact import exact_lookup
from legal_rag.retrieval.fusion import cap_list_items, rrf
from legal_rag.retrieval.rerank import CachedScorer, rerank

ROOT = Path(__file__).resolve().parents[1]
SELECTION_RULE = (
    "Chọn N* có recall@3000 parent nhóm questions cao nhất; hòa lấy N nhỏ hơn. "
    "Chỉ nhận N* > 0 khi tăng ít nhất 0,02 so với N=0 và recall@3000 parent "
    "nhóm turns giảm không quá 0,01; nếu không thì giữ N=0."
)


class CacheOnlyScorer(CachedScorer):
    def score(self, pairs):
        missing = [self.pair_key(pair) for pair in pairs
                   if self.pair_key(pair) not in self.entries]
        if missing:
            raise FileNotFoundError(
                f"Thiếu cache rerank tại {self.path}: {len(set(missing))} cặp; "
                f"khóa đầu {missing[0]}. Không nạp model để chấm thêm.")
        return super().score(pairs)


def choose_siblings(runs):
    def recall(n, group):
        return runs[str(n)]["metrics"][group]["parent"]["recall@3000"]

    if any(recall(n, "questions") is None for n in range(4)):
        return {"candidate": None, "selected": 0, "reason": "Thiếu nhãn questions để chọn N."}
    best = max(range(4), key=lambda n: recall(n, "questions"))
    gain = recall(best, "questions") - recall(0, "questions")
    before, after = recall(0, "turns"), recall(best, "turns")
    drop = before - after if before is not None and after is not None else None
    accepted = (best > 0 and (gain >= 0.02 or isclose(gain, 0.02, rel_tol=0, abs_tol=1e-12))
                and drop is not None and (drop <= 0.01 or isclose(drop, 0.01, rel_tol=0, abs_tol=1e-12)))
    return {"candidate": best, "selected": best if accepted else 0,
            "questions_gain": gain, "turns_drop": drop,
            "reason": "Đủ ngưỡng nhận N*." if accepted else "Giữ N=0 theo quy tắc chọn."}


def run_siblings(chunks, parents, gold, dense, scorer):
    validate_reachability(chunks, gold, parents)
    bm25 = BM25Retriever(chunks, BM25Config("syllable", "both", "index_text"))
    predictions = {}
    for row in gold:
        query = row["question"]
        hits = cap_list_items(rrf([bm25.search(query), dense.search(query)]), chunks, 3)
        hits = rerank(query, hits, chunks, scorer, 20)
        exact = [h for h in exact_lookup(query, chunks)["results"]
                 if h["match_level"] == "article"]
        seen, result = set(), []
        for hit in exact + hits:
            if hit["chunk_id"] not in seen:
                seen.add(hit["chunk_id"])
                result.append(hit)
        predictions[row["id"]] = result

    runs, baseline = {}, {}
    keys = ("recall@1500", "recall@3000", "recall@6000", "hit@3000")
    for n in range(4):
        measured = evaluate(gold, predictions, parents=parents, sibling_articles=n)
        metrics = {group: {
            level: {key: measured[group][level][key] for key in ("labeled_questions", *keys)}
            for level in ("parent", "article")}
            for group in ("questions", "turns")}
        changes = []
        for row in gold:
            units, _ = select_context(predictions[row["id"]], parents, 3000, n)
            found = len({p["parent_id"] for p in units} & set(gold_units(row, "parent")))
            if n == 0:
                baseline[row["id"]] = found
            elif found != baseline[row["id"]]:
                changes.append({"id": row["id"],
                                "group": "turns" if "scenario_id" in row else "questions",
                                "before": baseline[row["id"]], "after": found})
        runs[str(n)] = {"metrics": metrics, "changed_parent_labels_at_3000": changes}
    return {"selection_rule": SELECTION_RULE, "labels": label_summary(gold),
            "runs": runs, "selection": choose_siblings(runs)}


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "runs/t17/siblings.json")
    args = parser.parse_args(argv)

    def read(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    print(SELECTION_RULE)
    try:
        chunks = read(root / "data/processed/chunks.jsonl")
        parents = read(root / "data/processed/parents.jsonl")
        gold = read(root / "eval/retrieval.jsonl")
        validate_reachability(chunks, gold, parents)
        cache = VectorCache(root / ".cache/index", chunks, "jina")
        vectors = cache.load_documents()
        queries = {}
        for query in dict.fromkeys(r["question"] for r in gold):
            try:
                cached, _ = cache.load_queries([query])
            except FileNotFoundError as error:
                raise FileNotFoundError(f"{error}; file {cache.query_path(query)}") from error
            queries.update(cached)
        path = root / ".cache/rerank/scores.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"Thiếu cache rerank: {path}")
        result = run_siblings(chunks, parents, gold,
                              DenseRetriever(chunks, vectors, queries), CacheOnlyScorer(path))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
                               + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    print("N nhóm cấp recall@1500 recall@3000 recall@6000 hit@3000")
    for n, run in result["runs"].items():
        for group, levels in run["metrics"].items():
            for level, metrics in levels.items():
                values = ["null" if metrics[key] is None else f"{metrics[key]:.4f}"
                          for key in ("recall@1500", "recall@3000", "recall@6000", "hit@3000")]
                print(n, group, level, *values)
    print("Áp dụng quy tắc:", json.dumps(result["selection"], ensure_ascii=False))
    print("Chi tiết:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
