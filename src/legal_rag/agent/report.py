"""Ghép báo cáo sau kiểm chứng, luôn giữ câu kết ở cuối."""

import re

from legal_rag.agent.followup import CLOSING, before_closing
from legal_rag.generation.citations import format_citation, markdown_code_mask
from legal_rag.generation.evidence import build_evidence

LIST_ITEM_PREFIX = "33-2026-QD-TTg_linh-vuc-"
MARKERS = re.compile(r"\[(E\d+(?:\.[a-zđ])?(?:\s*,\s*E\d+(?:\.[a-zđ])?)*)\]", re.I)


def _codes_only(text):
    """Chỉ nhận toàn bộ đoạn là mã E, dấu ngăn cách và khoảng trắng."""
    matches = list(MARKERS.finditer(text))
    if not matches or re.sub(r"[\s,;.]", "", MARKERS.sub("", text)):
        return []
    return [code for match in matches for code in re.split(r"\s*,\s*", match[1])]


def tidy_citation_lines(body, citations):
    """Dọn dòng nguồn thuần; giữ nguyên câu nội dung và mọi nguồn chưa giải được."""
    available = {code.upper() for citation in citations
                 if (match := re.match(r"^\s*\[(E\d+(?:\.[a-zđ])?)\]", citation, re.I))
                 for code in [match[1]]}
    result, in_rules = [], False
    for line, masked in zip(body.splitlines(keepends=True), markdown_code_mask(body).splitlines(keepends=True)):
        heading = re.match(r"^##[ \t]+(.+?)\s*$", masked)
        if heading:
            in_rules = heading[1] == "Quy định áp dụng"
        if masked != line:
            result.append(line)
            continue
        bullet = re.match(r"^([ \t]*[-*][ \t]+)(.*?)(\r?\n)?$", line)
        content = bullet[2] if bullet else line.rstrip("\r\n")
        codes = _codes_only(content)
        if bullet and codes and all(code.upper() in available for code in codes):
            continue
        label, punctuation = "", ""
        if not codes and in_rules:
            first = MARKERS.search(content)
            if first:
                label, codes = content[:first.start()], _codes_only(content[first.start():])
        if in_rules and len(codes) > 3:
            last = list(MARKERS.finditer(content))[-1]
            punctuation = content[last.end():]
            ending = line[len(line.rstrip("\r\n")):]
            prefix = bullet[1] if bullet else ""
            for index in range(0, len(codes), 3):
                chunk = ", ".join(f"[{code}]" for code in codes[index:index + 3])
                final = index + 3 >= len(codes)
                lead = prefix + label if index == 0 else " " * len(prefix)
                result.append(lead + chunk + (punctuation if final else "")
                              + (ending if final else ending or "\n"))
        else:
            result.append(line)
    return "".join(result)


def assemble_report(reply, citations, high_risk, high_risk_items=(), parents=(), documents=()) -> str:
    citations = list(citations)
    body, closing = before_closing(reply)
    body = tidy_citation_lines(body, citations)
    if high_risk:
        title = ("## Đối chiếu Danh mục rủi ro cao" if high_risk.get("version") == "high_risk_v2"
                 and high_risk.get("status") == "chua_du_co_so" else
                 "## Gợi ý tham khảo: các mục Danh mục rủi ro cao có thể liên quan")
        section = title + "\n\n" + high_risk["text"]
        heading = "## Nghĩa vụ cần xem xét"
        lines = body.splitlines()
        if heading in lines:
            index = lines.index(heading)
            lines[index:index] = [section, ""]
            body = "\n".join(lines)
        else:
            body = "\n\n".join(filter(None, (body, section)))
    references = list(citations)
    if high_risk:
        items, fixed = {item["parent_id"]: item for item in high_risk_items}, []
        registry = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
        for key in high_risk.get("parent_ids", []):
            if key.startswith(LIST_ITEM_PREFIX):
                item = items.get(key)
                if item is None:
                    item = build_evidence([registry[key]], documents)[0]
                references.append(format_citation(item))
            elif key in registry:
                # Căn cứ cố định chỉ được nêu tên trong khối Danh mục; đường dẫn đặt ở đây (T57).
                try:
                    line = format_citation(build_evidence([registry[key]], documents)[0])
                except KeyError:  # thiếu văn bản trong sổ đăng ký: không bịa nguồn
                    continue
                if not any(ref.endswith(line) for ref in references):
                    fixed.append(line)
        references.extend(fixed)
    if references:
        body += "\n\n## Căn cứ pháp lý\n\n" + "\n".join(references)
    return "\n\n".join(filter(None, (body.strip(), closing.strip() or CLOSING)))
