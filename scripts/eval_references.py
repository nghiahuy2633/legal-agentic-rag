"""Đo tham chiếu một bước chỉ từ cache, không nạp model."""

import argparse
import json
from pathlib import Path
import sys

from legal_rag.evaluation.retrieval import gold_units, label_summary
from legal_rag.evaluation.retrieval_experiment import validate_reachability
from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.context import estimate_tokens, select_context
from legal_rag.retrieval.dense import DenseRetriever
from legal_rag.retrieval.exact import exact_lookup
from legal_rag.retrieval.fusion import cap_list_items, rrf
from legal_rag.retrieval.rerank import CachedScorer, rerank
from legal_rag.retrieval.references import ReferenceGraph, expand_references

ROOT = Path(__file__).resolve().parents[1]
SELECTION_RULE = (
    "Chọn (R,K) có recall questions cao nhất; hòa lấy R nhỏ hơn rồi K nhỏ hơn. "
    "Chỉ bật khi questions tăng ít nhất 0,02 so với base, turns không giảm, "
    "và questions không thua plain@(3000+R) quá 0,01. Không đạt thì giữ tắt."
)
REFERENCE_SETTINGS = [(r, k) for r in (500, 1000, 1500, 3000) for k in (3, 5)]


class CacheOnlyScorer(CachedScorer):
    def score(self, pairs):
        missing = [self.pair_key(pair) for pair in pairs if self.pair_key(pair) not in self.entries]
        if missing:
            raise FileNotFoundError(f"Thiếu cache rerank tại {self.path}: {len(set(missing))} cặp; "
                                    f"khóa đầu {missing[0]}. Không nạp model để chấm thêm.")
        return super().score(pairs)


def choose_references(runs):
    def recall(name, group):
        return runs[name]["metrics"][group]["recall"]
    candidates = [(r, k) for r, k in REFERENCE_SETTINGS if recall(f"ref@{r},top@{k}", "questions") is not None]
    if not candidates:
        return dict(candidate=None, enabled=False, reason="Thiếu nhãn questions.")
    r, k = min(candidates, key=lambda pair: (-recall(f"ref@{pair[0]},top@{pair[1]}", "questions"), *pair))
    name = f"ref@{r},top@{k}"
    before, after = recall("base", "turns"), recall(name, "turns")
    base, plain = recall("base", "questions"), recall(f"plain@{3000+r}", "questions")
    gain = recall(name, "questions") - base if base is not None else None
    gap = plain - recall(name, "questions") if plain is not None else None
    enabled = (gain is not None and gain >= .02 - 1e-12 and before is not None
               and after is not None and after >= before - 1e-12
               and gap is not None and gap <= .01 + 1e-12)
    return dict(candidate=dict(budget=r, top_units=k), enabled=enabled,
                questions_gain=gain, turns_before=before, turns_after=after, plain_gap=gap,
                reason="Đủ điều kiện bật." if enabled else "Giữ enable_references=False theo quy tắc chọn.")


def reference_coverage(references, graph):
    rows = [row for row in references if row["resolved"] and row.get("target_article")]
    missing = [row for row in rows if not graph._target_ids(row)]
    return dict(resolved_with_article=len(rows), with_targets=len(rows) - len(missing), missing=missing)


def predict(chunks, gold, dense, scorer):
    bm25 = BM25Retriever(chunks, BM25Config("syllable", "both", "index_text"))
    predictions = {}
    for row in gold:
        query = row["question"]
        hits = cap_list_items(rrf([bm25.search(query), dense.search(query)]), chunks, 3)
        hits = rerank(query, hits, chunks, scorer, 20)
        exact = [hit for hit in exact_lookup(query, chunks)["results"] if hit["match_level"] == "article"]
        seen, result = set(), []
        for hit in exact + hits:
            if hit["chunk_id"] not in seen:
                seen.add(hit["chunk_id"])
                result.append(hit)
        predictions[row["id"]] = result
    return predictions


def measure_contexts(gold, predictions, parents, graph):
    primary = {row["id"]: select_context(predictions[row["id"]], parents, 3000)[0] for row in gold}
    contexts = {"base": primary}
    for budget in (3500, 4000, 4500, 6000):
        contexts[f"plain@{budget}"] = {
            row["id"]: select_context(predictions[row["id"]], parents, budget)[0] for row in gold}
    for r, k in REFERENCE_SETTINGS:
        contexts[f"ref@{r},top@{k}"] = {
            key: units + expand_references(units, graph, parents, r, k) for key, units in primary.items()}
    counts = {name: {row["id"]: len({p["parent_id"] for p in units[row["id"]]}
                                   & set(gold_units(row, "parent"))) for row in gold}
              for name, units in contexts.items()}
    runs = {}
    for name, units in contexts.items():
        metrics, changes = {}, []
        for group in ("questions", "turns"):
            group_rows = [row for row in gold if ("scenario_id" in row) == (group == "turns")]
            rows = [row for row in group_rows if gold_units(row, "parent")]
            recalls = [counts[name][row["id"]] / len(set(gold_units(row, "parent"))) for row in rows]
            tokens = [sum(estimate_tokens(p["text"]) for p in units[row["id"]]) for row in group_rows]
            metrics[group] = dict(labeled_questions=len(rows),
                                  recall=sum(recalls) / len(rows) if rows else None,
                                  mean_tokens=sum(tokens) / len(tokens) if tokens else None)
        for row in gold:
            key = row["id"]
            if counts[name][key] != counts["base"][key]:
                changes.append(dict(id=key, group="turns" if "scenario_id" in row else "questions",
                                    before=counts["base"][key], after=counts[name][key]))
        runs[name] = dict(metrics=metrics, changed_parent_labels=changes)
    return runs


def validate_baseline(runs):
    mismatches = []
    for group, expected in (("questions", .6952), ("turns", .5264)):
        value = runs["base"]["metrics"][group]["recall"]
        print(f"base {group}: {value:.4f}" if value is not None else f"base {group}: null")
        if value is None or round(value, 4) != expected:
            mismatches.append(f"base {group} lệch số đã chốt {expected:.4f}")
    if mismatches:
        raise ValueError("; ".join(mismatches) + "; dừng chọn cấu hình.")


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "runs/t20b/references.json")
    args = parser.parse_args(argv)

    def read(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    print(SELECTION_RULE)
    try:
        chunks = read(root / "data/processed/chunks.jsonl")
        parents = read(root / "data/processed/parents.jsonl")
        references = read(root / "data/processed/references.jsonl")
        graph = ReferenceGraph(references, parents, chunks)
        coverage = reference_coverage(references, graph)
        print("Độ phủ dẫn chiếu:", json.dumps(coverage, ensure_ascii=False))
        gold = read(root / "eval/retrieval.jsonl")
        validate_reachability(chunks, gold, parents)
        cache = VectorCache(root / ".cache/index", chunks, "jina")
        vectors = cache.load_documents()
        queries = {}
        for query in dict.fromkeys(row["question"] for row in gold):
            try:
                cached, _ = cache.load_queries([query])
            except FileNotFoundError as error:
                raise FileNotFoundError(f"{error}; file {cache.query_path(query)}") from error
            queries.update(cached)
        path = root / ".cache/rerank/scores.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"Thiếu cache rerank: {path}")
        predictions = predict(chunks, gold, DenseRetriever(chunks, vectors, queries), CacheOnlyScorer(path))
        runs = measure_contexts(gold, predictions, parents, graph)
        validate_baseline(runs)
        result = dict(selection_rule=SELECTION_RULE, labels=label_summary(gold), coverage=coverage,
                      runs=runs, selection=choose_references(runs))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    for name, run in runs.items():
        for group, metrics in run["metrics"].items():
            print(name, group, json.dumps(metrics, ensure_ascii=False))
    print("Áp dụng quy tắc:", json.dumps(result["selection"], ensure_ascii=False))
    print("Chi tiết:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
