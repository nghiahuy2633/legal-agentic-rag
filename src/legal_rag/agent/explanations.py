"""Liên kết giải thích với dòng đã quyết định; không tính lại điều kiện pháp lý."""

from copy import deepcopy
import json
import re

from legal_rag.generation.citations import check_answer, has_point, normalize_citation_markers
from legal_rag.generation.locations import sentences
from legal_rag.knowledge.facts import FACT_FIELDS


def with_rows(context):
    result = deepcopy(context)
    situations = result.get("situations", [])
    result["data"]["Dòng cần giải thích"] = [dict(row=i, **deepcopy(row),
        **({"Phạm vi theo bảng nghĩa vụ": situations[i - 1]} if i <= len(situations) and situations[i - 1] else {}))
        for i, row in enumerate(result["data"]["Nghĩa vụ có căn cứ hiện diện"], 1)]
    return result


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Khóa JSON bị trùng")
        value[key] = item
    return value


def bind_explanations(raw, context, items=(), index=None, chunks=None):
    rows = context["data"]["Dòng cần giải thích"]
    expected = [row["row"] for row in rows]
    audit = dict(schema="bound_explanations_v1", expected_keys=expected, received_keys=[],
                 accepted_keys=[], bindings=[], errors=[])
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"explanations"} or not isinstance(data["explanations"], list):
            raise ValueError("Cần JSON explanations đúng cấu trúc")
        entries = data["explanations"]
        if any(not isinstance(entry, dict) or set(entry) != {"row", "text"}
               or type(entry["row"]) is not int or not isinstance(entry["text"], str) for entry in entries):
            raise ValueError("Mỗi giải thích chỉ có row nguyên và text chuỗi")
        audit["received_keys"] = [entry["row"] for entry in entries]
        if audit["received_keys"] != expected:
            raise ValueError("Khóa giải thích thiếu, lạ, trùng hoặc sai thứ tự")
    except (ValueError, TypeError) as error:
        audit["errors"] = ["Giải thích chưa đúng giao thức liên kết: " + str(error)]
        return {}, audit
    evidence = {item["id"]: item for item in items}
    accepted = {}
    for row, entry in zip(rows, entries):
        text = normalize_citation_markers(entry["text"].strip())
        errors = []
        if not text or len(text) > 1200:
            errors.append("Giải thích phải là đoạn không rỗng, tối đa1200 ký tự")
        if re.search(r"[\r\n`]|\b[a-z][a-z0-9+.-]*:(?://|[^\s])|(?<!:)//|\bwww\.|\]\(|^\s*[#>]|<[^>]+>", text, re.I):
            errors.append("Giải thích cần văn xuôi thuần, không code/liên kết/tiêu đề")
        if re.search(r"\bob-\d+\b", text, re.I) or any(re.search(
                r"(?<![\w])" + re.escape(key) + r"(?![\w])", text) for key in FACT_FIELDS):
            errors.append("Giải thích chứa mã nội bộ")
        codes = row["Căn cứ"]
        own = [evidence[code] for code in codes if code in evidence]
        for marker in re.finditer(r"(?<![a-z0-9])E(\d+)(?:\.([a-zđ]|\d+))?(?![a-z0-9])", text, re.I):
            code = "E" + marker[1]
            if code not in codes:
                errors.append("Mã căn cứ ngoài dòng: " + marker[0])
            elif marker[2] and (code not in evidence or not has_point(evidence[code], marker[2].lower())):
                errors.append("Điểm không có trong căn cứ của dòng: " + marker[0])
        if len(own) != len(codes) or index is None or chunks is None:
            errors.append("Thiếu dữ liệu kiểm nguồn riêng của giải thích")
        else:
            markers = "".join(f"[{code}]" for code in codes)
            fragment = "\n".join(sentence + " " + markers for sentence in sentences(text))
            checked = check_answer(fragment, own, index, chunks)
            errors.extend(checked["errors"])
        audit["bindings"].append(dict(row=row["row"], evidence_ids=list(codes), valid=not errors,
                                      errors=list(dict.fromkeys(errors))))
        audit["errors"].extend(f'Giải thích dòng {row["row"]}: {error}' for error in errors)
        if not errors:
            accepted[row["row"]] = text
            audit["accepted_keys"].append(row["row"])
    audit["errors"] = list(dict.fromkeys(audit["errors"]))
    return accepted, audit
