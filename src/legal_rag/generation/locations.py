"""Kiểm vị trí và con số thuần túy; không xác nhận nội dung pháp lý."""

import re
from decimal import Decimal
import unicodedata

from legal_rag.retrieval.exact import _location_mentions, document_candidates, parse_location


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", str(text)).lower().split())


def evidence_text(item):
    return "\n".join(item.get(key, "") for key in ("text", "conformity_note", "scope_note"))


def sentences(answer):
    """Giữ dấu chấm trong số, số hiệu, ngày tháng và mã Điểm."""
    return [s.strip() for s in re.split(r"[;:\n]+|(?<!\d)\.(?!\d)|(?<=\d)\.(?![\w/])", unicodedata.normalize("NFC", answer)) if s.strip()]


def sentence_items(sentence, items):
    ids = {m.upper() for group in re.findall(r"\[([^\[\]]*)\]", sentence)
           for m in re.findall(r"\bE\d+", group, re.I)}
    return [item for item in items if item["id"].upper() in ids] if ids else items


def build_location_index(parents, chunks):
    index = set()
    parents = parents.values() if isinstance(parents, dict) else parents
    for row in [*parents, *chunks]:
        if row.get("article") is None:
            continue
        key = (row["document_id"], normalize(row["article"]))
        index.add(key)
        if row.get("clause") is not None:
            key += (normalize(row["clause"]),)
            index.add(key)
            if row.get("point") is not None:
                index.add(key + (normalize(row["point"]),))
    return index


def location_label(location):
    return " ".join(f"{label} {location[key]}" for key, label in
                    (("point", "Điểm"), ("clause", "Khoản"), ("article", "Điều")) if location.get(key))


def check_locations(answer, items, index, chunks):
    answer = unicodedata.normalize("NFC", answer)
    errors = []
    for sentence in sentences(answer):
        explicit_docs, _ = document_candidates(sentence, chunks)
        selected = sentence_items(sentence, items)
        sentence_docs = explicit_docs if len(explicit_docs) == 1 else {i["document_id"] for i in selected}
        has_marker = bool(re.search(r"\[\s*E\d+", sentence, re.I))
        mentions = _location_mentions(sentence)
        for mention_index, (start, end, _) in enumerate(mentions):
            # Chỉ phân tích vị trí bằng cùng parser của truy xuất.
            for location in parse_location(sentence[start:end]):
                next_start = mentions[mention_index + 1][0] if mention_index + 1 < len(mentions) else len(sentence)
                tail = sentence[end:next_start]
                external = re.search(r"\b(?:của|theo)\s+(?:Bộ luật|Luật|Nghị định|Thông tư|Quyết định)\b", tail[:40], re.I)
                if external and not document_candidates(tail[external.start():], chunks)[0]:
                    continue
                # Văn bản nêu ngay sau vị trí thắng văn bản chung của câu: một câu có thể dẫn nhiều văn bản.
                nearby = document_candidates(tail[:40], chunks)[0]
                docs = nearby if len(nearby) == 1 else sentence_docs
                label = location_label(location)
                def exists(entry):
                    if entry[0] not in docs or entry[1] != location["article"]:
                        return False
                    if location["clause"] is not None and (len(entry) < 3 or entry[2] != location["clause"]):
                        return False
                    return location["point"] is None or (len(entry) == 4 and entry[3] == location["point"])

                if not any(exists(entry) for entry in index):
                    errors.append(f"Vị trí không tồn tại: {label}")
                if has_marker:
                    matched = False
                    for item in selected:
                        same = (item["document_id"] in docs and
                                normalize(item.get("article")) == location["article"] and
                                (location["clause"] is None or normalize(item.get("clause")) == location["clause"]))
                        body = normalize(evidence_text(item))
                        phrase = normalize(sentence[start:end])
                        reference = bool(re.search(re.escape(phrase) + r"(?!\w)", body))
                        if item["document_id"] not in docs:
                            reference = reference or bool(re.search(
                                re.escape(normalize(f'Điều {location["article"]}')) + r"(?!\w)", body))
                        same_article_reference = (
                            item["document_id"] in docs and
                            normalize(item.get("article")) == location["article"] and
                            location["clause"] is not None and location["point"] is None and
                            bool(re.search(
                                r"\bkhoản\s+" + re.escape(location["clause"]) + r"\s+điều này\b",
                                normalize(item["text"]))))
                        if same or reference or same_article_reference:
                            matched = True
                    if not matched:
                        errors.append(f"Vị trí không khớp bằng chứng: {label}")
    # Số hiệu viết tắt cũng phải có trong corpus hoặc nguyên văn bằng chứng.
    body = normalize("\n".join(evidence_text(i) for i in items))
    for match in re.finditer(r"\b(?:Luật|Nghị định|Thông tư|Quyết định)\s+\d+(?:/\d{4}/[\w-]+)?\b", answer, re.I):
        if not document_candidates(match[0], chunks)[0] and normalize(match[0]) not in body:
            errors.append(f"Số hiệu ngoài bằng chứng: {match[0]}")
    return list(dict.fromkeys(errors))


DATE = re.compile(r"\b(?:(\d{1,2})/(\d{1,2})/(\d{4})|ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4}))\b", re.I)
DATE_WITHOUT_YEAR = re.compile(
    r"\bngày\s+(?:0?[1-9]|[12]\d|3[01])\s+tháng\s+(?:0?[1-9]|1[0-2])\b", re.I)
PERCENT = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:%|phần trăm)", re.I)
DURATION = re.compile(r"\b(\d+)\s+(ngày|tháng|năm|giờ)\b", re.I)


def number_mentions(text):
    text = unicodedata.normalize("NFC", text)
    dates = list(DATE.finditer(text))
    date_spans = [*dates, *DATE_WITHOUT_YEAR.finditer(text)]
    result = [("Ngày", tuple(int(v) for v in (m.groups()[:3] if m[1] else m.groups()[3:])), m[0]) for m in dates]
    result += [("Tỷ lệ", Decimal(m[1].replace(",", ".")), m[0]) for m in PERCENT.finditer(text)]
    result += [("Thời hạn", (int(m[1]), m[2].lower()), m[0]) for m in DURATION.finditer(text)
               if not any(a.start() <= m.start() < a.end() for a in date_spans)]
    return result


def check_numbers(answer, items):
    answer = unicodedata.normalize("NFC", answer)
    errors = []
    for sentence in sentences(answer):
        available = {(kind, value) for item in sentence_items(sentence, items)
                     for kind, value, _ in number_mentions(evidence_text(item))}
        for kind, value, raw in number_mentions(sentence):
            if (kind, value) not in available:
                errors.append(f"{kind} ngoài bằng chứng: {raw}")
    return list(dict.fromkeys(errors))
