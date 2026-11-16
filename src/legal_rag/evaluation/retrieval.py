"""Các phép đo thuần: macro theo câu, loại mẫu không nhãn ở từng cấp."""

from statistics import median

from legal_rag.retrieval.context import clause_unit, select_context


def unique(values):
    return list(dict.fromkeys(v for v in values if v is not None))


def ranked_units(results: list[dict], level: str) -> list[str]:
    units = unique(clause_unit(r) for r in results)
    if level == "parent":
        return units
    if level != "article":
        raise ValueError("level phải là parent hoặc article")
    return unique(u.split("_khoan-")[0] if "_dieu-" in u else u for u in units)


def gold_units(row: dict, level: str) -> list[str]:
    """Mục không có Điều là một đơn vị riêng ở cả hai cấp."""
    if level == "parent":
        return unique(row["gold_parents"])
    if level != "article":
        raise ValueError("level phải là parent hoặc article")
    return unique([*row["gold_articles"],
                   *(p for p in row["gold_parents"] if "_dieu-" not in p)])


def label_summary(rows: list[dict]) -> dict:
    """Trần macro lý thuyết do k và danh sách nguồn chưa giải được."""
    partial = [r for r in rows if r.get("unresolved_sources") and
               (r["gold_parents"] or r["gold_articles"])]
    result = {"partially_unresolved_count": len(partial),
              "partially_unresolved": [{"id": r["id"], "sources": r["unresolved_sources"]}
                                        for r in partial],
              "unresolved_count": sum(r.get("gold_status") == "unresolved" for r in rows)}
    for level in ("parent", "article"):
        counts = [len(gold_units(r, level)) for r in rows if gold_units(r, level)]
        result[level] = {"labeled_questions": len(counts),
                         "more_than_5": sum(n > 5 for n in counts),
                         "recall@5_ceiling": sum(min(5, n) / n for n in counts) / len(counts) if counts else None}
    return result


def metrics(ranked: list[str], gold: list[str]) -> dict | None:
    gold = set(gold)
    if not gold:
        return None
    ranked = unique(ranked)
    ranks = [i for i, item in enumerate(ranked, 1) if item in gold]
    return {"hit@5": float(any(r <= 5 for r in ranks)),
            "recall@5": sum(r <= 5 for r in ranks) / len(gold),
            "recall@10": sum(r <= 10 for r in ranks) / len(gold),
            "mrr": 1 / min(ranks) if ranks else 0.0}


def block_coverage(ranked: list[str], blocks: dict[str, list[str]], k: int) -> float:
    """Tỷ lệ khối nội dung có ít nhất một đơn vị trong top k."""
    return sum(bool(set(ranked[:k]) & set(units)) for units in blocks.values()) / len(blocks)


def evaluate(gold_rows: list[dict], predictions: dict[str, list[dict]],
             latency_ms: dict[str, float] | None = None, parents=None,
             budgets=(1500, 3000, 6000), sibling_articles=0) -> dict:
    contexts = {}
    if parents is not None:
        parents = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
        for row in gold_rows:
            for budget in budgets:
                selected, _ = select_context(predictions.get(row["id"], []), parents, budget,
                                             sibling_articles)
                contexts[row["id"], budget] = [{"parent_id": p["parent_id"]} for p in selected]
    def group(rows):
        result = {"questions": len(rows)}
        for level in ("parent", "article"):
            measured = [metrics(ranked_units(predictions.get(r["id"], []), level), gold_units(r, level))
                        for r in rows]
            measured = [m for m in measured if m is not None]
            result[level] = {"labeled_questions": len(measured)}
            for key in ("hit@5", "recall@5", "recall@10", "mrr"):
                result[level][key] = sum(m[key] for m in measured) / len(measured) if measured else None
            if parents is not None:
                labeled = [r for r in rows if gold_units(r, level)]
                for budget in budgets:
                    recalls, hits = [], []
                    for row in labeled:
                        found = set(ranked_units(contexts[row["id"], budget], level))
                        gold = set(gold_units(row, level))
                        recalls.append(len(found & gold) / len(gold))
                        hits.append(float(bool(found & gold)))
                    result[level][f"recall@{budget}"] = sum(recalls) / len(recalls) if recalls else None
                    result[level][f"hit@{budget}"] = sum(hits) / len(hits) if hits else None
        blocks = [(ranked_units(predictions.get(r["id"], []), "article"), r["gold_blocks"])
                  for r in rows if r.get("gold_blocks")]
        if blocks:
            result["blocks"] = {"labeled_questions": len(blocks)}
            for k in (5, 10):
                result["blocks"][f"coverage@{k}"] = sum(block_coverage(u, b, k) for u, b in blocks) / len(blocks)
        times = [latency_ms[r["id"]] for r in rows if latency_ms and r["id"] in latency_ms]
        result["median_latency_ms"] = median(times) if times else None
        return result
    return {"all": group(gold_rows),
            "priority": group([r for r in gold_rows if r["priority"]]),
            "questions": group([r for r in gold_rows if "scenario_id" not in r]),
            "turns": group([r for r in gold_rows if "scenario_id" in r]),
            "categories": {c: group([r for r in gold_rows if r["category"] == c])
                           for c in sorted({r["category"] for r in gold_rows})}}
