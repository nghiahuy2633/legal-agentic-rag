"""Đồ thị dẫn chiếu một bước, chỉ dùng dữ liệu được truyền vào."""

from legal_rag.retrieval.context import estimate_tokens


class ReferenceGraph:
    def __init__(self, references, parents, chunks):
        self.parents = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
        self.by_chunk = {}
        for row in references:
            self.by_chunk.setdefault(row["source_chunk_id"], []).append(row)
        self.articles = {}
        for parent in self.parents.values():
            if parent.get("level") in ("article", "clause"):
                key = (parent["document_id"], parent.get("article"))
                self.articles.setdefault(key, []).append(parent)

    def _rows(self, unit_id):
        for chunk_id in self.parents.get(unit_id, {}).get("chunk_ids", []):
            yield from self.by_chunk.get(chunk_id, ())

    def _target_ids(self, row):
        if not row["resolved"] or not row.get("target_article"):
            return []
        candidates = self.articles.get((row["target_document_id"], row["target_article"]), [])
        clauses = [p for p in candidates if p.get("level") == "clause"]
        if row.get("target_clause"):
            return [p["parent_id"] for p in clauses if p.get("clause") == row["target_clause"]]
        return [p["parent_id"] for p in (clauses or candidates)]

    def targets(self, unit_id):
        result, seen = [], {unit_id}
        unit = self.parents.get(unit_id, {})
        for row in self._rows(unit_id):
            # "Điều này" chỉ trỏ lại chính Điều chứa nó: không phải liên hệ mới, đã đo ở thí nghiệm kéo Khoản.
            if (not row.get("target_clause") and row.get("target_document_id") == unit.get("document_id")
                    and row.get("target_article") == unit.get("article")):
                continue
            for target in self._target_ids(row):
                if target not in seen:
                    seen.add(target)
                    result.append(dict(parent_id=target, raw_text=row["raw_text"],
                                       specific=bool(row.get("target_clause"))))
        return result

    def external(self, unit_id):
        return list(dict.fromkeys(row["raw_text"] for row in self._rows(unit_id)
                                  if not row["resolved"]))

    def articles_mentioned(self, unit_ids, article):
        return {row["target_document_id"] for unit in unit_ids for row in self._rows(unit)
                if row["resolved"] and row.get("target_article") == article}


def expand_references(units, graph, parents, budget, top_units):
    if budget < 0 or top_units < 0:
        raise ValueError("budget và top_units phải không âm")
    if not budget or not top_units:
        return []
    lookup = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
    seen = {p["parent_id"] for p in units}
    result, tokens = [], 0
    for unit in units[:top_units]:
        targets = sorted(graph.targets(unit["parent_id"]), key=lambda target: not target["specific"])
        for target in targets:
            pid = target["parent_id"]
            if pid in seen:
                continue
            parent = lookup[pid]
            cost = estimate_tokens(parent["text"])
            if tokens + cost > budget:
                continue
            seen.add(pid)
            tokens += cost
            result.append(dict(parent, referenced_from=unit["parent_id"]))
    return result
