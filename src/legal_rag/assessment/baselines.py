"""Hai đối chứng không dùng bảng nghĩa vụ; không đọc nhãn đánh giá."""

import json

from legal_rag.assessment.status import PROMPTS, assess_status, payload


def _ask(chat, model, prompt, content):
    try:
        value = json.loads(chat.complete(payload(
            (PROMPTS / prompt).read_text(encoding="utf-8"),
            json.dumps(content, ensure_ascii=False), model, True)))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("JSON đối chứng không hợp lệ") from error
    if not isinstance(value, dict):
        raise ValueError("Đối chứng phải trả đối tượng JSON")
    return value


def _evidence(pipeline, parents):
    # Giữ nguyên đơn vị truy xuất/ngân sách parent, gắn E cho từng chunk nằm
    # trong parent đó để có thể trích riêng Điểm, không đánh đồng các Điểm.
    chunks = {c["chunk_id"]: c for c in pipeline.chunks}
    evidence, seen = [], set()
    for parent in parents:
        ids = parent.get("chunk_ids", [parent["parent_id"]])
        for cid in ids:
            if cid in seen:
                continue
            seen.add(cid)
            chunk = chunks.get(cid)
            evidence.append({"id": f"E{len(evidence) + 1}", "chunk_id": cid,
                "context": chunk.get("context", parent.get("context", "")) if chunk else parent.get("context", ""),
                "text": chunk["body"] if chunk else parent["text"]})
    return evidence


def _citations(ids, evidence):
    # Mã lạ bị bỏ, như cách luồng chính hạ từng tiêu chí, để đối chứng không mất cả kết quả vì một mã.
    lookup = {e["id"]: e["chunk_id"] for e in evidence}
    if not isinstance(ids, list):
        return []
    return list(dict.fromkeys(lookup[i] for i in ids if isinstance(i, str) and i in lookup))


def run_baseline(config, facts, description, statement, chat, model, pipeline_factory):
    if config not in ("b0", "b1"):
        raise ValueError("Đối chứng phải là b0 hoặc b1")
    pipeline = pipeline_factory()
    query = description + "\nDữ kiện: " + json.dumps(facts, ensure_ascii=False, sort_keys=True)
    content = {"facts": facts, "description": description, "statement": statement}
    calls = 0
    if config == "b0":
        parents = pipeline.context(query, budget=3000)
    else:
        planned = _ask(chat, model, "baseline_b1_plan_v1.txt", content)
        calls += 1
        queries = planned.get("queries")
        if (not isinstance(queries, list) or not 3 <= len(queries) <= 6
                or any(not isinstance(q, str) or not q.strip() for q in queries)
                or len(set(queries)) != len(queries)):
            raise ValueError("Cần 3 đến 6 truy vấn khác nhau")
        parents = pipeline.context_many(queries, query, budget=4500)
    evidence = _evidence(pipeline, parents)
    parsed = _ask(chat, model, f"baseline_{config}_v1.txt" if config == "b0"
                  else "baseline_b1_list_v1.txt", dict(content, evidence=evidence))
    calls += 1
    if not isinstance(parsed.get("obligations"), list):
        raise ValueError("Thiếu danh sách nghĩa vụ")
    warnings = _citations(parsed.get("prohibited", []), evidence)
    obligations, items, dropped = [], [], 0
    for index, entry in enumerate(parsed["obligations"], 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str) or not entry["text"].strip():
            dropped += 1
            continue
        ids = _citations(entry.get("evidence_ids"), evidence)
        if not ids:
            dropped += 1
            continue
        # Khóa không phụ thuộc thứ tự liệt kê, dùng tập mã căn cứ để đo lặp.
        key = "|".join(sorted(ids))
        obligation = {"key": key, "text": entry["text"], "chunk_ids": ids,
            "applicability": "ap_dung", "kind": "nghia_vu", "criteria": []}
        if config == "b0":
            obligation["status"] = entry["status"] if entry.get("status") in ("da", "chua", "chua_ro") else "chua_ro"
        else:
            criteria = entry.get("criteria")
            criteria = [c for c in criteria if isinstance(c, str) and c.strip()][:3] if isinstance(criteria, list) else []
            if not criteria:
                criteria = [entry["text"]]
            items.append({"row": {"id": f"b1-{index}", "kind": "nghia_vu",
                "obligation": entry["text"], "criteria": [
                    {"id": f"c{i}", "text": text} for i, text in enumerate(criteria, 1)]},
                "applicability": "ap_dung"})
        obligations.append(obligation)
    errors = []
    if config == "b1":
        assessed = assess_status(items, statement, description, chat, model)
        calls += assessed["llm_calls"]
        errors = assessed["errors"]
        for obligation, row in zip(obligations, assessed["rows"], strict=True):
            obligation.update(status=row["status"], criteria=row["criteria"])
    result = {"obligations": obligations, "warnings": warnings, "llm_calls": calls,
              "evidence": evidence, "dropped": dropped, "status_errors": errors}
    if any(e.get("error") == "LLMError" for e in errors):
        result["error"] = "Lỗi chấm hiện trạng"
        result["errors"] = errors
    return result
