"""Tra vị trí pháp lý thuần túy trên các chunk được truyền vào."""

import re
import unicodedata


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
                   if unicodedata.category(c) != "Mn")


def parse_location(text: str) -> list[dict]:
    """Nhận từng vị trí riêng, gồm Khoản/Điểm trước hoặc sau Điều."""
    result = []
    for _, _, locations in _location_mentions(text):
        for location in locations:
            if location not in result:
                result.append(location)
    return result


def _location_mentions(text: str) -> list[tuple[int, int, list[dict]]]:
    """Giữ khoảng ký tự của cả cụm trước khi bung danh sách Khoản/Điểm."""
    original = unicodedata.normalize("NFC", text).lower()
    normalized = fold(original)
    clause = r"\d+[a-z]?"
    point = r"[a-z]"
    separator = r"(?:\s*,\s*|\s+v[aà]\s+)"
    clauses = clause + r"\b(?:" + separator + clause + r"\b)*"
    points = point + r"\b(?:" + separator + point + r"\b)*"
    pattern = re.compile(
        r"\b(?:diem\s+(?P<point>" + points + r")\s+)?"
        r"(?:khoan\s+(?P<clause>" + clauses + r")\s+)?"
        r"dieu\s+(?P<article>\d+[a-z]?)\b"
        r"(?:\s*,?\s*khoan\s+(?P<clause_after>" + clauses + r"))?"
        r"(?:\s*,?\s*diem\s+(?P<point_after>" + points + r"))?")
    result = []
    for match in pattern.finditer(normalized):
        point_group = "point_after" if match["point_after"] else "point"
        # fold giữ số ký tự sau NFC; đọc ký hiệu gốc để phân biệt đ và d.
        point_text = original[match.start(point_group):match.end(point_group)] if match[point_group] else None
        clause_text = match["clause_after"] or match["clause"]
        clause_values = re.split(separator, clause_text) if clause_text else [None]
        point_values = re.split(separator, point_text) if point_text else [None]
        locations = [{"article": match["article"], "clause": c, "point": p}
                     for c in clause_values for p in point_values]
        result.append((match.start(), match.end(), locations))
    return result


def document_candidates(text: str, chunks: list[dict]) -> tuple[set[str], bool]:
    """Nhận số hiệu đầy đủ, tên chính thức và tên viết tắt có số."""
    text = fold(text)
    docs = {c["document_id"]: c for c in chunks}
    found = set()
    explicit = bool(re.search(r"\b(?:luat|nghi dinh|nd|thong tu|tt|quyet dinh|qd)\s+\d", text)
                    or re.search(r"\b\d+/\d{4}/", text))
    for doc, chunk in docs.items():
        number = fold(chunk.get("document_number", doc.replace("-", "/", 2)))
        title = fold(chunk.get("document_title", ""))
        prefix = doc.split("-")[0]
        kind = ("luat" if "QH" in doc else "(?:nghi dinh|nd)" if "ND" in doc
                else "(?:thong tu|tt)" if "TT-B" in doc else "(?:quyet dinh|qd)")
        alias = re.search(r"\b" + kind + r"\s+" + re.escape(prefix) + r"\b(?!/)", text)
        if number in text or (title and title in text) or alias:
            found.add(doc)
        if "QH" in doc and re.search(r"\bluat\s+(?:ai|tri tue nhan tao)\b", text):
            found.add(doc)
    return found, explicit or bool(found)


def _document_mentions(text: str, chunks: list[dict]) -> list[tuple[int, int, set[str]]]:
    """Nhận cả văn bản ngoài corpus để không ghép sang văn bản lân cận."""
    normalized = fold(unicodedata.normalize("NFC", text))
    spans = [m.span() for m in re.finditer(
        r"\b(?:luat|nghi dinh|nd|thong tu|tt|quyet dinh|qd)\s+"
        r"\d+(?:/\d{4}/[\w-]+)?\b|\b\d+/\d{4}/[\w-]+\b",
        normalized)]
    for chunk in {c["document_id"]: c for c in chunks}.values():
        title = fold(chunk.get("document_title", ""))
        if title:
            spans.extend(m.span() for m in re.finditer(re.escape(title), normalized))
    spans.extend(m.span() for m in re.finditer(r"\bluat\s+(?:ai|tri tue nhan tao)\b", normalized))
    # Số hiệu nằm trong tên viết tắt là cùng một lần nhắc văn bản.
    merged = []
    for start, end in sorted(set(spans)):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return [(start, end, document_candidates(normalized[start:end], chunks)[0])
            for start, end in merged]


def exact_lookup(query: str, chunks: list[dict]) -> dict:
    mentions = _location_mentions(query)
    locations = [location for _, _, group in mentions for location in group]
    documents, explicit = document_candidates(query, chunks)
    document_mentions = _document_mentions(query, chunks)
    scoped_locations = []
    document_first = bool(mentions and document_mentions
                          and document_mentions[0][0] < mentions[0][0])
    for start, end, group in mentions:
        before = [d for d in document_mentions if d[1] <= start]
        after = [d for d in document_mentions if d[0] >= end]
        nearest = (before[-1] if before else None) if document_first else (
            after[0] if after else before[-1] if before else None)
        allowed = nearest[2] if nearest else documents if explicit else None
        scoped_locations.extend((location, allowed) for location in group)
    match_level = "article" if locations else "document" if explicit else None
    if match_level is None:
        return {"results": [], "ambiguous": False, "match_level": None}
    selected = []
    for chunk in chunks:
        if explicit and chunk["document_id"] not in documents:
            continue
        if locations and not any((allowed is None or chunk["document_id"] in allowed) and all(
                value is None or (str(chunk.get(key) or "").lower() if key == "point"
                                  else fold(str(chunk.get(key) or ""))) == value
                for key, value in location.items()) for location, allowed in scoped_locations):
            continue
        selected.append(chunk)
    selected.sort(key=lambda c: c["chunk_id"])
    return {"results": [{"chunk_id": c["chunk_id"], "parent_id": c["parent_id"],
                         "article_id": c.get("article_id"), "score": 1.0 if locations else 0.0,
                         "match_level": match_level} for c in selected],
            "match_level": match_level,
            "ambiguous": not explicit and len({c["document_id"] for c in selected}) > 1}
