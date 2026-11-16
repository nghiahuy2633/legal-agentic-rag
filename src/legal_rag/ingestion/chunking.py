"""Tạo chunk, parent và dẫn chiếu từ các Điều đã phân tích; toàn hàm thuần."""

from itertools import product
import re


MAX_CHARS = 3500

_SENTENCE_GAP = re.compile(r"(?<=[.!?…]) (?=\S)")

# Chỉ giao việc: chủ thể ban hành + "quy định/hướng dẫn chi tiết" + một câu trọn vẹn.
_DELEGATION = re.compile(
    r"(?:Chính phủ|Thủ tướng Chính phủ|Bộ trưởng Bộ [^.;:]+?|Bộ [^.;:]+?)"
    r" (?:quy định|hướng dẫn) chi tiết [^.;:!?]+\.(?:/\.)?"
)

_TYPE_LABELS = {"luat": "Luật", "nghi_dinh": "Nghị định",
                "thong_tu": "Thông tư", "quyet_dinh": "Quyết định"}
_DOC_TYPES = r"(?:Bộ luật|Luật|Pháp lệnh|Nghị định|Nghị quyết|Thông tư|Quyết định)"
_NUMBER = r"\d+/\d{4}/[\w-]*\w"
_LIST_GAP = r"(?:\s*,\s*|\s+(?:và|hoặc)\s+)"
_NUMS = rf"\d+(?!\w)(?:{_LIST_GAP}\d+(?!\w))*"
_LETTERS = rf"[a-zđ](?!\w)(?:{_LIST_GAP}[a-zđ](?!\w))*"
_GAP = r"(?:\s+của\s+|\s+)"
_POINT = rf"[Đđ]iểm\s+(?:{_LETTERS}|này(?!\w))"
_CLAUSE = rf"[Kk]hoản\s+(?:{_NUMS}|này(?!\w))"
_ARTICLE = rf"Điều\s+(?:{_NUMS}|này(?!\w))"
_CHAPTER = r"Chương\s+[IVXLCDM]+(?!\w)"
_ITEM = (rf"(?:{_POINT}(?:{_GAP}{_CLAUSE})?(?:{_GAP}{_ARTICLE})?"
         rf"|{_CLAUSE}(?:{_GAP}{_ARTICLE})?|{_ARTICLE}|{_CHAPTER})")
_ITEM_SEP = r"(?:\s*,\s*(?:(?:và|hoặc)\s+)?|\s+(?:và|hoặc)\s+)"
_ITEM_RE = re.compile(_ITEM)
_ITEM_POINT = re.compile(rf"[Đđ]iểm\s+({_LETTERS}|này)")
_ITEM_CLAUSE = re.compile(rf"[Kk]hoản\s+({_NUMS}|này)")
_ITEM_ARTICLE = re.compile(rf"Điều\s+({_NUMS}|này)")
_ITEM_CHAPTER = re.compile(_CHAPTER)
_JOINER = re.compile(r"(?<!\w)(?:và|hoặc)(?!\w)")


def split_text(text: str, max_chars: int = MAX_CHARS, overlap_sentences: int = 0) -> list[str]:
    """Tách theo câu khi vượt giới hạn; câu quá dài mới tách theo từ.

    Với overlap_sentences = 0, nối các phần bằng một dấu cách cho lại đúng text gốc.
    """
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences phải >= 0")
    if len(text) <= max_chars:
        return [text]
    tokens = []
    for sentence in _SENTENCE_GAP.split(text):
        tokens.extend([sentence] if len(sentence) <= max_chars else sentence.split(" "))
    if any(len(token) > max_chars for token in tokens):
        raise ValueError("Có từ dài hơn giới hạn, không tách được")
    parts = []
    current = []
    for token in tokens:
        if current and len(" ".join([*current, token])) > max_chars:
            parts.append(" ".join(current))
            current = current[-overlap_sentences:] if overlap_sentences else []
            while current and len(" ".join([*current, token])) > max_chars:
                current.pop(0)
        current.append(token)
    parts.append(" ".join(current))
    return parts


def is_delegation(text: str) -> bool:
    """Đúng khi mọi câu của nội dung đều chỉ giao cơ quan quy định chi tiết."""
    stripped = text.strip()
    return bool(stripped) and all(_DELEGATION.fullmatch(item) for item in _SENTENCE_GAP.split(stripped))


def _context(document: dict, article: dict, with_intro: bool, lead_in_of: dict | None = None) -> str:
    lines = [f"{document['document_title']} (số {document['document_number']})"]
    for label, number, title in (("Chương", article["chapter"], article["chapter_title"]),
                                 ("Mục", article["section"], article["section_title"])):
        if number:
            lines.append(f"{label} {number}. {title}" if title else f"{label} {number}")
    lines.append(f"Điều {article['article']}. {article['title']}")
    if with_intro and article["intro"]:
        lines.append(article["intro"])
    if lead_in_of is not None:
        lines.append(f"Khoản {lead_in_of['clause']}: {lead_in_of['lead_in']}")
    return "\n".join(lines)


def _label(article: dict, clause: dict | None, point: dict | None, level: str, part: int) -> str:
    label = f"Điều {article['article']}"
    if level == "article_intro":
        label += ", phần mở đầu"
    if clause is not None:
        label += f", Khoản {clause['clause']}"
    if point is not None:
        label += f", Điểm {point['point']}"
    if part > 1:
        label += f" (phần {part})"
    return label + ": "


def _clause_text(clause: dict) -> str:
    lines = [f"{clause['clause']}. {clause['lead_in']}"]
    lines.extend(f"{point['point']}) {point['text']}" for point in clause["points"])
    if clause.get("closing"):
        lines.append(clause["closing"])
    return "\n".join(lines)


def _clause_pages(article: dict, position: int) -> list[int]:
    # Đầu vào chỉ có trang bắt đầu của Khoản, nên lấy khoảng có thể chứa Khoản.
    clause = article["clauses"][position]
    following = article["clauses"][position + 1:]
    last = following[0]["page"] if following else article["page_end"]
    return list(range(clause["page"], last + 1))


def build_document(document: dict, articles: list[dict], overlap_sentences: int = 0,
                   max_chars: int = MAX_CHARS) -> tuple[list[dict], list[dict], int]:
    """Trả về chunks, parents và số đơn vị bị tách của một văn bản."""
    chunks = []
    parents = []
    split_count = 0
    document_id = document["document_id"]

    def add(article, clause, point, level, body, page, parent_id, base_id, context):
        nonlocal split_count
        parts = split_text(body, max_chars, overlap_sentences)
        split_count += len(parts) > 1
        delegates = is_delegation(body)
        ids = []
        for number, part in enumerate(parts, 1):
            chunk_id = base_id if number == 1 else f"{base_id}_phan-{number}"
            ids.append(chunk_id)
            chunks.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "document_number": document["document_number"],
                "document_title": document["document_title"],
                "article": article["article"],
                "clause": clause["clause"] if clause else None,
                "point": point["point"] if point else None,
                "level": level,
                "body": part,
                "context": context,
                "index_text": f"{context}\n\n{_label(article, clause, point, level, number)}{part}",
                "parent_id": parent_id,
                "article_id": f"{document_id}_dieu-{article['article']}",
                "page": page,
                "effective_from": document["effective_from"],
                "delegates": delegates,
            })
        return ids

    for article in articles:
        article_id = f"{document_id}_dieu-{article['article']}"
        if not article["intro"] and not article["clauses"]:
            raise ValueError(f"{article_id}: Điều không có nội dung")
        article_chunks = []
        clause_parents = []
        if not article["clauses"]:
            article_chunks += add(article, None, None, "article", article["intro"],
                                  article["page_start"], article_id, article_id,
                                  _context(document, article, with_intro=False))
        elif article["intro"]:
            article_chunks += add(article, None, None, "article_intro", article["intro"],
                                  article["page_start"], article_id, f"{article_id}_mo-dau",
                                  _context(document, article, with_intro=False))
        for position, clause in enumerate(article["clauses"]):
            clause_id = f"{article_id}_khoan-{clause['clause']}"
            # Câu dẫn của Khoản có Điểm cũng là một chunk để ghép body đủ nội dung Khoản.
            clause_chunks = add(article, clause, None, "clause", clause["lead_in"], clause["page"],
                                article_id, clause_id, _context(document, article, with_intro=True))
            for point in clause["points"]:
                clause_chunks += add(article, clause, point, "point", point["text"], point["page"],
                                     clause_id, f"{clause_id}_diem-{point['point']}",
                                     _context(document, article, with_intro=True, lead_in_of=clause))
            if clause.get("closing"):
                clause_chunks += add(article, clause, None, "clause_closing", clause["closing"],
                                     clause["closing_page"], clause_id, f"{clause_id}_cuoi",
                                     _context(document, article, with_intro=True, lead_in_of=clause))
            article_chunks += clause_chunks
            clause_parents.append({
                "parent_id": clause_id,
                "level": "clause",
                "document_id": document_id,
                "article": article["article"],
                "clause": clause["clause"],
                "title": article["title"],
                "pages": _clause_pages(article, position),
                "context": _context(document, article, with_intro=True),
                "text": _clause_text(clause),
                "chunk_ids": clause_chunks,
            })
        text_lines = [article["intro"]] if article["intro"] else []
        text_lines.extend(_clause_text(clause) for clause in article["clauses"])
        parents.append({
            "parent_id": article_id,
            "level": "article",
            "document_id": document_id,
            "article": article["article"],
            "clause": None,
            "title": article["title"],
            "pages": list(range(article["page_start"], article["page_end"] + 1)),
            "context": _context(document, article, with_intro=False),
            "text": "\n".join(text_lines),
            "chunk_ids": article_chunks,
        })
        parents.extend(clause_parents)
    return chunks, parents, split_count


def build_index(articles_by_document: dict[str, list[dict]]) -> dict:
    """Vị trí có thật: văn bản -> Điều -> Khoản -> tập Điểm."""
    return {
        document_id: {
            article["article"]: {clause["clause"]: {point["point"] for point in clause["points"]}
                                 for clause in article["clauses"]}
            for article in articles
        }
        for document_id, articles in articles_by_document.items()
    }


def reference_pattern(documents: list[dict]) -> re.Pattern:
    """Mẫu dẫn chiếu, lấy tên văn bản từ registry."""
    titles = sorted((re.escape(item["document_title"]) for item in documents), key=len, reverse=True)
    named = rf"(?:{'|'.join(titles)})(?!\w)(?:\s+số\s+{_NUMBER})?" if titles else r"(?!)"
    doc = (rf"(?:{_DOC_TYPES}\s+này(?!\w)"
           rf"|{named}"
           rf"|(?:{_DOC_TYPES}\s+)?(?:số\s+)?{_NUMBER}"
           rf"|{_DOC_TYPES}\s+[A-ZĐ][^.;:()]*?"
           r"(?=[.;:()]|$|\s+(?:theo|về|đối với|trong|khi|để|nhưng|thì|và pháp luật|và quy định)\s))")
    return re.compile(
        rf"(?<!\w)(?:(?P<items>{_ITEM}(?:{_ITEM_SEP}{_ITEM})*)(?:(?:\s+của)?\s+(?P<doc>{doc}))?"
        rf"|(?P<solo>{doc}))"
    )


def _resolve_document(phrase: str | None, source: dict, documents: list[dict]) -> str | None:
    """Mã văn bản đích; None nếu không nêu văn bản, ngoài corpus hoặc không chắc."""
    if phrase is None:
        return None
    phrase = " ".join(phrase.split())
    number = re.search(_NUMBER, phrase)
    if number:
        return next((item["document_id"] for item in documents
                     if item["document_number"] == number[0]), None)
    if phrase.endswith(" này"):
        own_label = _TYPE_LABELS.get(source["document_type"])
        return source["document_id"] if phrase == f"{own_label} này" else None
    return next((item["document_id"] for item in documents if item["document_title"] == phrase), None)


def _values(pattern: re.Pattern, text: str) -> list[str] | None:
    match = pattern.search(text)
    if not match:
        return None
    return [value for value in re.split(r"[,\s]+", _JOINER.sub(" ", match[1])) if value]


def _parse_items(text: str) -> list[dict]:
    items = [{"point": _values(_ITEM_POINT, match[0]), "clause": _values(_ITEM_CLAUSE, match[0]),
              "article": _values(_ITEM_ARTICLE, match[0]),
              "chapter": bool(_ITEM_CHAPTER.fullmatch(match[0]))}
             for match in _ITEM_RE.finditer(text)]
    # Thành phần thiếu lấy từ mục ngay sau trong cùng danh sách: "điểm a và điểm b khoản này".
    for position in range(len(items) - 2, -1, -1):
        current, following = items[position], items[position + 1]
        if current["point"] and not current["clause"] and following["point"]:
            current["clause"] = following["clause"]
            current["article"] = current["article"] or following["article"]
        if current["clause"] and not current["article"] and following["clause"]:
            current["article"] = following["article"]
    return items


def _target(point, clause, article, is_chapter, phrase_document, chunk, index) -> dict:
    uses_self = "này" in (point, clause, article)
    document_id = chunk["document_id"] if uses_self else phrase_document
    certain = not is_chapter
    if point == "này":
        point, clause = chunk["point"], clause or "này"
        certain = certain and point is not None
    if clause == "này":
        certain = certain and article in (None, "này") and chunk["clause"] is not None
        clause, article = chunk["clause"], "này"
    if article == "này":
        article = chunk["article"]
    if (point is not None and clause is None) or (clause is not None and article is None):
        certain = False
    known = index.get(document_id)
    exists = known is not None and certain
    if exists and article is not None:
        exists = article in known
        if exists and clause is not None:
            exists = clause in known[article]
            if exists and point is not None:
                exists = point in known[article][clause]
    return {"target_document_id": document_id, "target_article": article,
            "target_clause": clause, "target_point": point, "resolved": exists}


def extract_references(chunk: dict, documents: list[dict], index: dict,
                       pattern: re.Pattern | None = None) -> list[dict]:
    """Mỗi vị trí được nêu rõ trong body một dòng; không có căn cứ thì resolved = false."""
    pattern = pattern or reference_pattern(documents)
    source = next(item for item in documents if item["document_id"] == chunk["document_id"])
    rows = []
    for match in pattern.finditer(chunk["body"]):
        document_id = _resolve_document(match["doc"] or match["solo"], source, documents)
        if match["items"] and not match["doc"] and chunk.get("level") in ("point", "clause_closing"):
            lead = next((line for line in chunk['context'].splitlines() if line.startswith('Khoản ')), '')
            # Câu dẫn liệt kê phải nêu duy nhất một văn bản đích có tên/số hiệu.
            # Không bỏ qua văn bản ngoài corpus để rồi chọn nhầm văn bản còn lại.
            if lead.endswith(':'):
                named = [m['doc'] or m['solo'] for m in pattern.finditer(lead)
                         if (m['doc'] or m['solo']) and not (m['doc'] or m['solo']).endswith(' này')]
                candidates = {_resolve_document(name, source, documents) for name in named}
                if len(candidates) == 1 and None not in candidates:
                    document_id = candidates.pop()
        items = _parse_items(match["items"]) if match["items"] else [
            {"point": None, "clause": None, "article": None, "chapter": False}]
        for item in items:
            for point, clause, article in product(item["point"] or [None], item["clause"] or [None],
                                                  item["article"] or [None]):
                rows.append({"source_chunk_id": chunk["chunk_id"], "raw_text": match[0],
                             **_target(point, clause, article, item["chapter"], document_id,
                                       chunk, index)})
    return rows


def build_outputs(documents: list[dict], articles_by_document: dict[str, list[dict]],
                  overlap_sentences: int = 0, max_chars: int = MAX_CHARS,
                  supplements: dict[str, list[dict]] | None = None,
                  high_risk_items: list[dict] | None = None) -> dict:
    """Ghép đầu ra theo thứ tự registry; `documents` là toàn bộ registry."""
    chunks = []
    parents = []
    split_count = 0
    from legal_rag.ingestion.supplements import build_supplement
    for document in documents:
        if document["document_id"] in articles_by_document:
            result = build_document(document, articles_by_document[document["document_id"]],
                                    overlap_sentences, max_chars)
            chunks += result[0]
            parents += result[1]
            split_count += result[2]
        for level, items in (("appendix_item", (supplements or {}).get(document['document_id'], [])),
                             ("list_item", high_risk_items or [] if document['document_id'] == '33-2026-QD-TTg' else [])):
            result = build_supplement(document, items, level, max_chars, overlap_sentences)
            chunks += result[0]
            parents += result[1]
            split_count += result[2]
    for key, rows in (("chunk_id", chunks), ("parent_id", parents)):
        values = [row[key] for row in rows]
        if len(values) != len(set(values)):
            raise ValueError(f"Trùng {key}")
    index = build_index(articles_by_document)
    pattern = reference_pattern(documents)
    references = [row for chunk in chunks
                  for row in extract_references(chunk, documents, index, pattern)]
    return {"chunks": chunks, "parents": parents, "references": references,
            "split_count": split_count}
