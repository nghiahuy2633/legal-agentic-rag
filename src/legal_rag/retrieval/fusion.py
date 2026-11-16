"""Fusion thứ hạng và giới hạn mục Danh mục, không bỏ kết quả."""


def rrf(rankings, k=60):
    if k < 0:
        raise ValueError("k phải không âm")
    scores, hits = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit["chunk_id"]
            if key in seen:
                continue
            seen.add(key)
            hits.setdefault(key, hit)
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return [dict(hits[key], score=scores[key])
            for key in sorted(scores, key=lambda key: (-scores[key], key))]


def cap_list_items(hits, chunks, cap):
    if cap < 0:
        raise ValueError("cap phải không âm")
    lookup = chunks if isinstance(chunks, dict) else {c["chunk_id"]: c for c in chunks}
    head, tail, count = [], [], 0
    for hit in hits:
        is_item = lookup[hit["chunk_id"]].get("level") == "list_item"
        if is_item:
            count += 1
        (tail if is_item and count > cap else head).append(hit)
    return head + tail
