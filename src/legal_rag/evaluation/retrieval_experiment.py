"""Chạy thí nghiệm BM25 và exact; tách khỏi runtime truy xuất."""

from dataclasses import asdict
from time import perf_counter

from legal_rag.evaluation.retrieval import evaluate, gold_units, label_summary, ranked_units
from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever
from legal_rag.retrieval.exact import exact_lookup

CONFIGS = {"A": BM25Config("syllable", "keep", "body"),
           "B": BM25Config("syllable", "keep", "index_text"),
           "C": BM25Config("pyvi", "keep", "index_text"),
           "D": BM25Config("pyvi", "both", "index_text")}


def _legacy_experiments(chunks, gold):
    runs = {}
    for name, config in CONFIGS.items():
        start = perf_counter()
        retriever = BM25Retriever(chunks, config)
        build_ms = (perf_counter() - start) * 1000
        predictions, latency = {}, {}
        for row in gold:
            start = perf_counter()
            predictions[row["id"]] = retriever.search(row["question"])
            latency[row["id"]] = (perf_counter() - start) * 1000
        runs[name] = {"config": asdict(config), "build_ms": build_ms,
                      "metrics": evaluate(gold, predictions, latency),
                      "predictions": predictions, "latency_ms": latency}
    # Chọn theo Recall@10 parent, rồi Điều, MRR parent; hòa thì A/B/C/D.
    def selection(name):
        all_metrics = runs[name]["metrics"]["all"]
        return tuple(all_metrics[level][metric] or 0 for level, metric in
                     (("parent", "recall@10"), ("article", "recall@10"), ("parent", "mrr")))
    best = max(CONFIGS, key=selection)
    exact_predictions, exact_latency = {}, {}
    combined_predictions, combined_latency = {}, {}
    for row in gold:
        start = perf_counter()
        exact_predictions[row["id"]] = exact_lookup(row["question"], chunks)["results"]
        exact_latency[row["id"]] = (perf_counter() - start) * 1000
        seen = set()
        combined_predictions[row["id"]] = []
        promoted = [hit for hit in exact_predictions[row["id"]] if hit["match_level"] == "article"]
        for hit in promoted + runs[best]["predictions"][row["id"]]:
            if hit["chunk_id"] not in seen:
                combined_predictions[row["id"]].append(hit)
                seen.add(hit["chunk_id"])
        combined_latency[row["id"]] = (perf_counter() - start) * 1000 + runs[best]["latency_ms"][row["id"]]
    direct = [r for r in gold if r["category"] == "tra_cuu_truc_tiep"]
    runs["exact"] = {"metrics": evaluate(direct, exact_predictions, exact_latency),
                     "predictions": {r["id"]: exact_predictions[r["id"]] for r in direct}}
    runs["best_exact"] = {"base": best, "metrics": evaluate(gold, combined_predictions, combined_latency),
                          "predictions": combined_predictions}
    # So hồ sơ chuẩn với chỉ câu hiện tại, chỉ trên các lượt kịch bản.
    turns = [r for r in gold if "scenario_id" in r]
    retriever = BM25Retriever(chunks, CONFIGS[best])
    turn_predictions = {r["id"]: retriever.search(r["turn_text"]) for r in turns}
    runs["best_turn_only"] = {"base": best, "metrics": evaluate(turns, turn_predictions),
                              "predictions": turn_predictions}
    return {"best_bm25": best, "labels": label_summary(gold), "runs": runs}


SELECTION_RULE = ("questions: recall@3000 parent, recall@3000 article, mrr parent; "
                  "hòa hoàn toàn lấy dòng xuất hiện trước; không loại theo độ trễ")


def selection_key(run):
    metrics = run["metrics"]["questions"]
    return tuple(metrics[level][key] if metrics[level][key] is not None else -1
                 for level, key in (("parent", "recall@3000"),
                                    ("article", "recall@3000"), ("parent", "mrr")))


def choose_best(runs, names):
    return max(names, key=lambda name: selection_key(runs[name]))


def validate_reachability(chunks, gold, parents=None):
    """Dừng trước phép đo nếu đơn vị hệ thống trả về không chạm được nhãn."""
    for level in ("parent", "article"):
        reachable = set(ranked_units(chunks, level))
        for row in gold:
            missing = set(gold_units(row, level)) - reachable
            if missing:
                raise ValueError(f"Nhãn không chạm được: {row['id']} {level}: {sorted(missing)}")
    if parents is not None:
        from legal_rag.retrieval.context import clause_unit
        ids = set(parents) if isinstance(parents, dict) else {p["parent_id"] for p in parents}
        missing = {clause_unit(c) for c in chunks} - ids
        if missing:
            raise ValueError(f"Thiếu parent cho ngữ cảnh: {sorted(missing)}")


def rebuild_overlap(root):
    """Dựng bốn bộ chunk trong bộ nhớ; không sửa corpus đã xử lý."""
    import csv
    import json
    from pathlib import Path
    from legal_rag.ingestion.chunking import build_outputs
    root = Path(root)
    def read(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))
    folder = root / "data/processed/articles"
    articles = {d["document_id"]: read(folder / f"{d['document_id']}.jsonl") for d in documents
                if (folder / f"{d['document_id']}.jsonl").exists()}
    supplements = {d: read(folder / f"{d}.appendices.jsonl") for d in articles
                   if (folder / f"{d}.appendices.jsonl").exists()}
    risk_path = root / "data/processed/high_risk_list.jsonl"
    risk = read(risk_path) if risk_path.exists() else []
    return {f"chunk_{size}_o{overlap}": build_outputs(
                documents, articles, overlap_sentences=overlap, max_chars=size,
                supplements=supplements, high_risk_items=risk)
            for size in (3500, 400) for overlap in (0, 1)}


def run_experiments(chunks, gold, parents=None, dense_retrievers=None,
                    query_latency_ms=None, scorer=None, overlap_outputs=None):
    """T11: chỉ đọc vector đã có; scorer giả hoặc cache nạp model lười do CLI cung cấp.

    Không truyền parents giữ giao diện và bảng T10 để tương thích lời gọi cũ.
    """
    if parents is None:
        validate_reachability(chunks, gold)
        return _legacy_experiments(chunks, gold)
    from legal_rag.retrieval.fusion import rrf, cap_list_items
    from legal_rag.retrieval.rerank import rerank
    validate_reachability(chunks, gold, parents)
    dense_retrievers = dense_retrievers or {}
    if set(dense_retrievers) != {"jina", "viet"}:
        raise ValueError("T11 cần vector đã cache của cả jina và viet")
    overlap_outputs = overlap_outputs or {}
    for output in overlap_outputs.values():
        validate_reachability(output["chunks"], gold, output["parents"])
    configs = {**CONFIGS, "E": BM25Config("syllable", "both", "index_text")}
    runs, runners = {}, {}
    query_latency_ms = query_latency_ms or {}

    def timed_search(retriever, query, extra=0):
        start = perf_counter()
        hits = retriever.search(query)
        return hits, (perf_counter() - start) * 1000 + extra

    def record(name, runner, rows=gold, run_parents=parents, **metadata):
        predictions, latency = {}, {}
        for row in rows:
            predictions[row["id"]], latency[row["id"]] = runner(row["question"])
        runs[name] = dict(metadata, metrics=evaluate(rows, predictions, latency, parents=run_parents),
                          predictions=predictions, latency_ms=latency)
        runners[name] = runner

    def alias(name, source):
        runs[name] = dict(runs[source], base=source)
        runners[name] = runners[source]

    for name, config in configs.items():
        start = perf_counter()
        retriever = BM25Retriever(chunks, config)
        build_ms = (perf_counter() - start) * 1000
        record(name, lambda q, r=retriever: timed_search(r, q), config=asdict(config), build_ms=build_ms)
    best_bm25 = choose_best(runs, list(configs))
    alias("bm25_best", best_bm25)
    for name in ("jina", "viet"):
        def dense_search(q, name=name):
            times = query_latency_ms.get(name, {})
            if q not in times:
                raise ValueError(f"Thiếu thời gian mã hóa truy vấn {name}: {q!r}")
            return timed_search(dense_retrievers[name], q, times[q])
        record("dense_" + name, dense_search, model=name)
    best_dense = choose_best(runs, ["dense_jina", "dense_viet"])
    alias("dense_best", best_dense)

    def fused(q):
        first, t1 = runners["bm25_best"](q)
        second, t2 = runners["dense_best"](q)
        start = perf_counter()
        hits = rrf([first, second])
        return hits, t1 + t2 + (perf_counter() - start) * 1000
    record("rrf", fused)

    def capped(q):
        hits, elapsed = fused(q)
        start = perf_counter()
        return cap_list_items(hits, chunks, 3), elapsed + (perf_counter() - start) * 1000
    record("rrf_cap3", capped, cap=3)
    base = choose_best(runs, ["rrf", "rrf_cap3"])
    alias("base", base)
    if scorer is not None:
        for pool in (20, 40):
            def reranked(q, pool=pool):
                hits, elapsed = runners["base"](q)
                start = perf_counter()
                result = rerank(q, hits, chunks, scorer, pool)
                wall = (perf_counter() - start) * 1000
                if hits and hasattr(scorer, "last_latency_ms"):
                    wall += scorer.last_latency_ms - scorer.last_call_wall_ms
                return result, elapsed + wall
            record(f"rerank{pool}", reranked, base=base, pool=pool)
    candidates = ["base"] + (["rerank20", "rerank40"] if scorer is not None else [])
    final = choose_best(runs, candidates)
    alias("final", final)

    def with_exact(q):
        hits, elapsed = runners["final"](q)
        start = perf_counter()
        exact = [h for h in exact_lookup(q, chunks)["results"] if h["match_level"] == "article"]
        result, seen = [], set()
        for hit in exact + hits:
            if hit["chunk_id"] not in seen:
                result.append(hit)
                seen.add(hit["chunk_id"])
        return result, elapsed + (perf_counter() - start) * 1000
    record("final_exact", with_exact, base=final)
    turns = [{**row, "question": row["turn_text"]} for row in gold if "scenario_id" in row]
    record("final_turn_only", runners["final"], rows=turns, base=final)
    for name, output in overlap_outputs.items():
        retriever = BM25Retriever(output["chunks"], configs[best_bm25])
        record(name, lambda q, r=retriever: timed_search(r, q), run_parents=output["parents"],
               base=best_bm25, split_count=output["split_count"], chunk_count=len(output["chunks"]))
    return {"selection_rule": SELECTION_RULE, "best_bm25": best_bm25,
            "best_dense": best_dense, "base": base, "final": final,
            "reranker": "bật" if scorer is not None else "bỏ rerank20/rerank40: không có cờ --rerank",
            "labels": label_summary(gold), "runs": runs}
