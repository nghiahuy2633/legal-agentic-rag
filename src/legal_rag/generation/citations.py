"""Kiểm tra dấu trích dẫn và dữ kiện định danh; không chấm suy luận pháp lý."""

import re
import unicodedata

ARTICLE = re.compile(r"\bđiều\s+(\d+[a-zđ]?)\b")
DOCUMENT = re.compile(r"\b\d+/\d{4}/[a-zđ][a-zđ0-9]*(?:[-–][a-zđ0-9]+)*\b")
MONEY = re.compile(r"\b\d+(?:[.,]\d+)*(?:\s+(?:nghìn|ngàn|triệu|tỷ|tỉ))?\s+đồng\b")
MARKER_GROUP = re.compile(r"e\d+(?:\.[a-zđ])?(?:\s*,\s*e\d+(?:\.[a-zđ])?)*")
BRACKET = re.compile(r"\[([^\[\]]*)\]")
NUMERIC_MARKER_GROUP = re.compile(
    r"e\d+(?:\.(?:\d+|[a-zđ]))?(?:\s*,\s*e\d+(?:\.(?:\d+|[a-zđ]))?)*", re.I)
CONTEXT_PHRASE = re.compile(
    r"\b(?:điều này|khoản này|điểm này|luật này|nghị định này|thông tư này|quyết định này)\b")
INLINE_POINT_PARENTS = {
    f"05-2026-TT-BKHCN_phu-luc-1_muc-{n}" for n in (1, 2, 3)
}


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", str(text)).lower().split())


def markdown_code_mask(text):
    """Giữ vị trí ký tự/xuống dòng, che code fence và inline code bằng khoảng trắng."""
    masked = list(text)

    def hide(start, end):
        for position in range(start, end):
            if text[position] not in "\r\n":
                masked[position] = " "

    fence, offset = None, 0
    for line in text.splitlines(keepends=True):
        token = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        if fence:
            hide(offset, offset + len(line))
            if (token and token[1][0] == fence[0] and len(token[1]) >= len(fence)
                    and not token[2].strip()):
                fence = None
        elif token and not (token[1][0] == "`" and "`" in token[2]):
            fence = token[1]
            hide(offset, offset + len(line))
        offset += len(line)
    fence_mask = "".join(masked)
    ticks = list(re.finditer(r"`+", fence_mask))
    index = 0
    while index < len(ticks):
        opening = ticks[index]
        closing = next((i for i in range(index + 1, len(ticks))
                        if ticks[i][0] == opening[0]), None)
        if closing is None:
            index += 1
        else:
            hide(opening.start(), ticks[closing].end())
            index = closing + 1
    return "".join(masked)


def normalize_citation_markers(answer):
    """Hậu tố số không phải Điểm: đưa về cùng mã E trước khi kiểm, giữ cú pháp sai."""
    masked = markdown_code_mask(answer)
    urls = [(m.start(), m.end()) for m in re.finditer(r"\b[a-z][a-z0-9+.-]*://[^\s<>]+", masked, re.I)]
    replacements = []
    for match in BRACKET.finditer(masked):
        if (not NUMERIC_MARKER_GROUP.fullmatch(match[1].strip())
                or any(start <= match.start() < end for start, end in urls)):
            continue
        original = answer[match.start():match.end()]
        changed = re.sub(r"(e\d+)\.\d+", r"\1", original, flags=re.I)
        if changed != original:
            replacements.append((match.start(), match.end(), changed))
    for start, end, replacement in reversed(replacements):
        answer = answer[:start] + replacement + answer[end:]
    return answer


def has_point(item, point):
    text = unicodedata.normalize("NFC", item["text"]).lower()
    marker = re.escape(point) + r"\)"
    if re.search(r"^\s*" + marker, text, re.M):
        return True
    if item.get("parent_id") not in INLINE_POINT_PARENTS:
        return False
    # Ba mục này ghép tiêu đề và các Điểm vào một dòng trong corpus.
    heading = normalize(item.get("article_title", "")).removeprefix("mục ")
    body = normalize(text)
    return bool(re.search(r"\.\s+" + marker + r"\s+", body) or (
        point == "a" and heading and
        re.search(r"^" + re.escape(heading) + r"\s+" + marker + r"\s+", body)))


def check_answer(answer, items, index=None, chunks=None):
    text = normalize(answer)
    available = {normalize(item["id"]) for item in items}
    used = []
    used_points = []
    errors = []
    for content in BRACKET.findall(text):
        if not re.search(r"\be\d+", content):
            continue
        if not MARKER_GROUP.fullmatch(content.strip()):
            errors.append(f"Lỗi định dạng trích dẫn: [{content.upper()}]")
            continue
        for marker, point in re.findall(r"(e\d+)(?:\.([a-zđ]))?", content):
            if point and {"id": marker.upper(), "point": point} not in used_points:
                used_points.append({"id": marker.upper(), "point": point})
            if marker not in used:
                used.append(marker)
    for marker in used:
        if marker not in available:
            errors.append(f"Trích dẫn không tồn tại: [{marker.upper()}]")
    for entry in used_points:
        item = next((i for i in items if normalize(i["id"]) == normalize(entry["id"])), None)
        if item is None or not has_point(item, entry["point"]):
            errors.append(f'Điểm không có trong bằng chứng: [{entry["id"]}.{entry["point"]}]')
    refusal = any(phrase in text for phrase in (
        "không có căn cứ", "ngoài phạm vi", "không liên quan", "không có thông tin", "không chứa thông tin", "không nêu"))
    if not used and (not refusal or ARTICLE.search(text) or DOCUMENT.search(text)):
        errors.append("Câu trả lời thiếu trích dẫn [En]")
    articles, numbers, amounts = set(), set(), set()
    for item in items:
        if item.get("article") is not None:
            articles.add(normalize(item["article"]))
        body = normalize("\n".join(item.get(key, "") for key in
                                   ("text", "conformity_note", "scope_note")))
        articles.update(ARTICLE.findall(body))
        numbers.update(DOCUMENT.findall(body))
        numbers.update(DOCUMENT.findall(normalize(item["document_number"])))
        note = normalize(item.get("conformity_note", ""))
        articles.update(ARTICLE.findall(note))
        numbers.update(DOCUMENT.findall(note))
        amounts.update(MONEY.findall(body))
    for article in (dict.fromkeys(ARTICLE.findall(text)) if index is None or chunks is None else ()):
        if article not in articles:
            errors.append(f"Điều ngoài bằng chứng: Điều {article}")
    for number in dict.fromkeys(DOCUMENT.findall(text)):
        if number not in numbers:
            errors.append(f"Số hiệu ngoài bằng chứng: {number}")
    for amount in dict.fromkeys(MONEY.findall(text)):
        if amount not in amounts:
            errors.append(f"Số tiền ngoài bằng chứng: {amount}")
    if index is not None and chunks is not None:
        from legal_rag.generation.locations import check_locations, check_numbers
        errors.extend(check_locations(answer, items, index, chunks))
        errors.extend(check_numbers(answer, items))
    errors = list(dict.fromkeys(errors))
    warnings = [f"Cụm mất ngữ cảnh: {phrase}"
                for phrase in dict.fromkeys(CONTEXT_PHRASE.findall(text))]
    warnings.extend(f"Khẳng định phủ định về pháp luật: {phrase}" for phrase in
                    dict.fromkeys(re.findall(r"pháp luật hiện hành không quy định|pháp luật không quy định|(?<!pháp )luật không quy định", text)))
    result = {"valid": not errors, "errors": errors, "used": [m.upper() for m in used],
              "warnings": warnings}
    if used_points or (index is not None and chunks is not None):
        result["used_points"] = used_points
    return result


def check_blocks(check, items):
    """Liệt kê nhóm chưa có bằng chứng nào được trích, giữ thứ tự đầu vào."""
    used = {normalize(marker) for marker in check["used"]}
    blocks = dict.fromkeys(item["block"] for item in items if "block" in item)
    covered = {item["block"] for item in items
               if "block" in item and normalize(item["id"]) in used}
    return [block for block in blocks if block not in covered]


def format_citation(item, point=None):
    parts = [item["document_number"]]
    if item.get("article"):
        parts.append(f'Điều {item["article"]}')
        if item.get("clause"):
            parts.append(f'Khoản {item["clause"]}')
    else:
        parts.append(item["article_title"])
    if point is not None:
        parts.append(f"Điểm {point}")
    parts.append(item["source_url"])
    return ", ".join(parts)


def citation_list(check, items):
    """Hiển thị vị trí đầy đủ cho các mã đã dùng, theo thứ tự xuất hiện."""
    result = []
    by_id = {item["id"].upper(): item for item in items}
    for marker in check.get("used", []):
        if marker not in by_id:
            continue
        points = [p["point"] for p in check.get("used_points", []) if p["id"] == marker]
        for point in points or [None]:
            suffix = f".{point}" if point else ""
            result.append(f"[{marker}{suffix}] {format_citation(by_id[marker], point)}")
    return result
