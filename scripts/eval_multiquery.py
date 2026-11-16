"""So sánh truy vấn con ở cấp parent, không tự thay cấu hình agent."""

import argparse
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

from legal_rag.evaluation.retrieval import gold_units, label_summary
from legal_rag.evaluation.retrieval_experiment import validate_reachability
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.dense import ModelEncoder
from legal_rag.retrieval.pipeline import RetrievalPipeline
from legal_rag.retrieval.rerank import CachedScorer

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ("first", "multi_message", "multi_joined")
SELECTION_RULE = ("Chọn recall questions cao nhất trong first, multi_message, multi_joined; "
                  "hòa theo thứ tự đó. Không cấu hình nào đạt base - 0,02 thì giữ multi_message "
                  "và báo phân rã làm giảm truy xuất. Script không tự đổi cấu hình.")


def choose_multiquery(runs):
    base = runs["base"]["metrics"]["questions"]["recall"]
    candidates = [name for name in CANDIDATES if runs[name]["metrics"]["questions"]["recall"] is not None]
    if base is None or not candidates:
        return dict(candidate="multi_message", accepted=False, reason="Thiếu nhãn questions.")
    best = max(candidates, key=lambda name: runs[name]["metrics"]["questions"]["recall"])
    accepted = runs[best]["metrics"]["questions"]["recall"] >= base - .02 - 1e-12
    return dict(candidate=best if accepted else "multi_message", accepted=accepted,
                reason="Đạt ngưỡng." if accepted else "Phân rã làm giảm truy xuất; giữ multi_message.")


def validate_baseline(runs):
    errors = []
    for group, expected in (("questions", .6952), ("turns", .5264)):
        value = runs["base"]["metrics"][group]["recall"]
        print(f"base {group}: {value:.4f}" if value is not None else f"base {group}: null")
        if value is None or round(value, 4) != expected:
            errors.append(f"base {group} lệch {expected:.4f}")
    if errors:
        raise ValueError("; ".join(errors) + "; dừng chọn cấu hình.")


def query_settings(row, analysis):
    group = "scenarios" if "scenario_id" in row else "questions"
    records = analysis.get(group, {}).get("results", [])
    record = next((r for r in records if r["id"] == row["id"]), {})
    queries = record.get("sub_queries")
    queries = list(dict.fromkeys(q.strip() for q in queries if isinstance(q, str) and q.strip()))[:3] if isinstance(queries, list) else []
    original = row["turn_text"] if "scenario_id" in row else row["question"]
    fallback = not queries
    queries = queries or [original]
    return {"base": ([row["question"]], row["question"]),
            "first": (queries[:1], queries[0]), "multi_message": (queries, original),
            "multi_joined": (queries, " ".join(queries))}, fallback


def summarize(gold, counts, times):
    runs = {}
    for name in counts:
        metrics = {}
        for group in ("questions", "turns"):
            rows = [r for r in gold if ("scenario_id" in r) == (group == "turns")]
            labeled = [r for r in rows if gold_units(r, "parent")]
            recalls = [counts[name][r["id"]] / len(set(gold_units(r, "parent"))) for r in labeled]
            latencies = [times[name][r["id"]] for r in rows]
            metrics[group] = dict(recall=sum(recalls) / len(recalls) if recalls else None,
                median_ms=median(latencies) if latencies else None, labeled_questions=len(labeled),
                increased=sum(counts[name][r["id"]] > counts["base"][r["id"]] for r in labeled),
                decreased=sum(counts[name][r["id"]] < counts["base"][r["id"]] for r in labeled))
        runs[name] = dict(metrics=metrics)
    return runs



def measure(gold, analysis, pipeline, enforce_baseline=False):
    counts, times = {}, {}
    fallback = dict(questions=0, turns=0)
    settings = {}
    for row in gold:
        settings[row["id"]], missing = query_settings(row, analysis)
        fallback["turns" if "scenario_id" in row else "questions"] += int(missing)
    for name in ("base", *CANDIDATES):
        counts[name], times[name] = {}, {}
        for i, row in enumerate(gold, 1):
            queries, rerank_query = settings[row["id"]][name]
            start = perf_counter()
            units = pipeline.context_many(queries, rerank_query, 3000)
            times[name][row["id"]] = (perf_counter() - start) * 1000
            counts[name][row["id"]] = len({p["parent_id"] for p in units} & set(gold_units(row, "parent")))
            if i % 10 == 0:
                print(f"{name}: đã xử lý {i}/{len(gold)} dòng", file=sys.stderr, flush=True)
        if name == "base" and enforce_baseline:
            validate_baseline(summarize(gold, counts, times))
    return summarize(gold, counts, times), fallback


class CachedEncoder:
    def __init__(self, cache):
        self.cache = cache
        self.encoder = ModelEncoder("jina")

    def encode_queries(self, queries):
        vectors, _ = self.cache.build_queries(queries, self.encoder)
        return [vectors[q] for q in queries]


def main(argv=None, root=ROOT, pipeline_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=root / "runs/t18/scope-analyze_v2.json")
    parser.add_argument("--output", type=Path, default=root / "runs/t20c/multiquery.json")
    args = parser.parse_args(argv)
    print(SELECTION_RULE, flush=True)
    def read(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        chunks = read(root / "data/processed/chunks.jsonl")
        parents = read(root / "data/processed/parents.jsonl")
        gold = read(root / "eval/retrieval.jsonl")
        validate_reachability(chunks, gold, parents)
        analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
        if pipeline_factory is None:
            cache = VectorCache(root / ".cache/index", chunks, "jina")
            encoder = CachedEncoder(cache)
            vectors = cache.build_documents(encoder.encoder)
            pipeline = RetrievalPipeline(chunks, parents, encoders={"jina": encoder},
                vectors={"jina": vectors}, scorer=CachedScorer(root / ".cache/rerank/scores.jsonl"))
        else:
            pipeline = pipeline_factory(chunks, parents)
        runs, fallback = measure(gold, analysis, pipeline, enforce_baseline=True)
        result = dict(selection_rule=SELECTION_RULE, labels=label_summary(gold),
                      fallback_queries=fallback, runs=runs, selection=choose_multiquery(runs))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
