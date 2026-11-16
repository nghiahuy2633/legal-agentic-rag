"""Đơn vị Khoản dùng chung và lựa chọn ngữ cảnh theo ngân sách."""

import re
from math import ceil


def clause_unit(hit: dict) -> str:
    """Khoản chứa hit, kể cả Điểm, đoạn cuối và phần tách dài."""
    match = re.match(r"(.*_khoan-[^_]+)", hit.get("chunk_id", ""))
    return match[1] if match else hit["parent_id"]


def estimate_tokens(text: str) -> int:
    return ceil(len(text) / 3)


def select_context(hits, parents, budget, sibling_articles=0):
    if budget < 0:
        raise ValueError("budget phải không âm")
    if type(sibling_articles) is not int or sibling_articles < 0:
        raise ValueError("sibling_articles phải là số nguyên không âm")
    lookup = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
    selected, seen, tokens = [], set(), 0
    siblings, opened = {}, set()
    if sibling_articles:
        for parent in lookup.values():
            if parent.get("level") == "clause":
                key = (parent["document_id"], parent["article"])
                siblings.setdefault(key, []).append(parent["parent_id"])

    def candidates():
        for hit in hits:
            unit = clause_unit(hit)
            if unit in seen:
                continue
            yield unit
            if not sibling_articles:
                continue
            parent = lookup[unit]
            if parent.get("level") == "clause":
                key = (parent["document_id"], parent["article"])
                if key not in opened and len(opened) < sibling_articles:
                    opened.add(key)
                    yield from siblings[key]

    for unit in candidates():
        if unit in seen:
            continue
        seen.add(unit)
        if unit not in lookup:
            raise ValueError(f"Thiếu parent: {unit}")
        parent = lookup[unit]
        cost = estimate_tokens(parent["text"])
        if selected and tokens + cost > budget:
            break
        selected.append(parent)
        tokens += cost
    return selected, tokens
