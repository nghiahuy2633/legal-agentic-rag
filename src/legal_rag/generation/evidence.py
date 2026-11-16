"""Chuẩn bị bằng chứng theo đúng thứ tự ngữ cảnh."""

import re


SCOPE_NOTE = 'Phạm vi của Thông tư 05: áp dụng đối với cơ quan quản lý nhà nước, tổ chức, cá nhân phục vụ hoạt động quản lý nhà nước hoặc cung cấp dịch vụ công; tổ chức, cá nhân khác được khuyến khích áp dụng.'

CONFORMITY_NOTE = re.compile(
    r"Đánh giá sự phù hợp theo điểm [ab], khoản 2 Điều 13 Luật Trí tuệ nhân tạo")

def build_evidence(units, documents, extra=()):
    registry = documents if isinstance(documents, dict) else {d["document_id"]: d for d in documents}
    items = []
    entries = [(unit, "frame" if "block" in unit else "retrieval") for unit in units]
    entries.extend((unit, "reference") for unit in extra)
    for unit, source in entries:
        document = registry[unit["document_id"]]
        items.append({
            "id": f"E{len(items) + 1}", "parent_id": unit["parent_id"],
            "document_id": unit["document_id"],
            "document_number": document["document_number"],
            "document_title": document["document_title"],
            "article": unit.get("article"), "article_title": unit["title"],
            "clause": unit.get("clause"), "text": unit["text"],
            "source_url": document["official_source_url"],
            "source": source,
        })
        if "referenced_from" in unit:
            items[-1]["referenced_from"] = unit["referenced_from"]
        if unit["document_id"] == "05-2026-TT-BKHCN":
            items[-1]["scope_note"] = SCOPE_NOTE
        if "block" in unit:
            items[-1]["block"] = unit["block"]
        if unit.get("level") == "list_item":
            lines = unit.get("context", "").splitlines()
            if not lines or not CONFORMITY_NOTE.fullmatch(lines[-1]):
                raise ValueError(f'Thiếu dòng đánh giá sự phù hợp: {unit["parent_id"]}')
            items[-1]["conformity_note"] = lines[-1]
    codes = {item["parent_id"]: item["id"] for item in items}
    for item in items:
        if "referenced_from" in item:
            item["referenced_from"] = codes.get(item["referenced_from"], item["referenced_from"])
    return items


def format_evidence(items):
    from legal_rag.generation.citations import format_citation
    return "\n\n".join(
        f'[{item["id"]}] {item["document_title"]}\n{format_citation(item)}\n'
        + (f'Nhóm: {item["block"]}\n' if "block" in item else "")
        + f'Tiêu đề: {item["article_title"]}\n'
        + (f'Được dẫn chiếu từ [{item["referenced_from"]}], kéo thêm để đủ ngữ cảnh.\n'
           if item.get("source") == "reference" and "referenced_from" in item else "")
        + ('Dẫn chiếu tới văn bản ngoài dữ liệu: ' + '; '.join(item["external_refs"]) + '.\n'
           if item.get("external_refs") else "")
        + (item["scope_note"] + "\n" if "scope_note" in item else "")
        + (item["conformity_note"] + "\n" if "conformity_note" in item else "")
        + item["text"] for item in items)


def append_evidence(items, parent_ids, parents, documents, source, budget):
    """Thêm nguyên parent trong ngân sách cứng; không lấy chỗ căn cứ đã có."""
    from legal_rag.retrieval.context import estimate_tokens
    registry = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
    result, seen, tokens = list(items), {item["parent_id"] for item in items}, 0
    for key in parent_ids:
        if key in seen:
            continue
        seen.add(key)
        parent = registry[key]
        cost = estimate_tokens(parent["text"])
        if tokens + cost > budget:
            continue
        item = build_evidence([parent], documents)[0]
        item.update(id=f"E{len(result) + 1}", source=source)
        result.append(item)
        tokens += cost
    return result, tokens
