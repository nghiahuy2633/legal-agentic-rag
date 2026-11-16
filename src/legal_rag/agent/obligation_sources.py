"""Cấp nguồn theo gói và kiểm từng dòng, không quyết định tính áp dụng."""

from copy import deepcopy

from legal_rag.generation.citations import check_answer
from legal_rag.generation.locations import sentences
from legal_rag.retrieval.context import clause_unit, estimate_tokens


def _registry(rows, key):
    return rows if isinstance(rows, dict) else {row[key]: row for row in rows}


def requirements(items, chunks, parents):
    chunks, parents = _registry(chunks, "chunk_id"), _registry(parents, "parent_id")
    rows = []
    for item in items:
        row = item["row"]
        required, missing_chunks = [], []
        for citation in row["citations"]:
            key = citation["chunk_id"]
            if key not in chunks:
                missing_chunks.append(key)
            else:
                required.append(clause_unit(chunks[key]))
        required = list(dict.fromkeys(required))
        rows.append(dict(id=row["id"], obligation=row.get("obligation", ""), kind=row.get("kind", "nghia_vu"),
            situation=(row.get("condition") or "").strip(),
            **{key: deepcopy(item[key]) for key in ("applicability", "conditions", "missing_facts")},
            required_parents=required, missing_chunks=list(dict.fromkeys(missing_chunks)),
            missing_registry_parents=[key for key in required if key not in parents]))
    return rows


def plan_sources(items, chunks, parents, evidence, budget, blocked_prefix=None):
    """Chọn nguyên gói thiếu; không làm thay đổi đầu vào hoặc cấp mã E."""
    parents = _registry(parents, "parent_id")
    rows = requirements(items, chunks, parents)
    seen = {row["parent_id"] for row in evidence}
    added, tokens, allocations = [], 0, {}
    ordered = [row for status in ("ap_dung", "ap_dung_neu") for row in rows
               if row["applicability"] == status]
    for row in ordered:
        missing = [key for key in row["required_parents"] if key not in seen]
        if not row["required_parents"] or row["missing_chunks"] or row["missing_registry_parents"]:
            allocations[row["id"]] = "invalid_sources"
            continue
        if blocked_prefix and any(key.startswith(blocked_prefix) for key in missing):
            allocations[row["id"]] = "separate_list_item"
            continue
        cost = sum(estimate_tokens(parents[key]["text"]) for key in missing)
        if tokens + cost > budget:
            allocations[row["id"]] = "budget"
            continue
        seen.update(missing)
        added.extend(missing)
        tokens += cost
        allocations[row["id"]] = "added" if missing else "already_present"
    return dict(rows=rows, added_parent_ids=added, added_tokens=tokens, allocations=allocations)


def check_sources(plan, evidence, index=None, chunks=None):
    """Nguồn của dòng khác không được dùng để làm hợp lệ fragment này."""
    available = {item["parent_id"]: item for item in evidence}
    rows, eligible = [], []
    counts = dict(core=len(plan["rows"]), complete=0, partial=0, none=0, eligible=0, withheld=0)
    for original in plan["rows"]:
        row = deepcopy(original)
        required = row["required_parents"]
        row["present_parents"] = [key for key in required if key in available]
        row["missing_parents"] = [key for key in required if key not in available]
        own_evidence = [available[key] for key in row["present_parents"]]
        row["evidence_ids"] = [item["id"] for item in own_evidence]
        complete = bool(required) and not any(row[key] for key in
            ("missing_chunks", "missing_registry_parents", "missing_parents"))
        row["source_status"] = "complete" if complete else "partial" if own_evidence else "none"
        counts[row["source_status"]] += 1
        # Bộ kiểm vị trí chỉ bind nguồn ở câu có marker: mỗi câu audit dùng đúng E của dòng.
        # Đây là fragment kiểm riêng, không đổi nguyên văn quyết định hoặc văn bản hiển thị.
        markers = "".join(f"[{code}]" for code in row["evidence_ids"])
        fragment = "\n".join(sentence + " " + markers for sentence in
                             sentences(row["obligation"] + "\n" + "\n".join(row["conditions"])))
        if complete and index is not None and chunks is not None:
            checked = check_answer(fragment, own_evidence, index, chunks)
            reason = "ready" if checked["valid"] else "fragment_errors"
        else:
            reason = "missing_location_data" if complete else "incomplete_sources"
            checked = dict(valid=False, errors=[], used=[], warnings=[])
        row.update(fragment_check=checked, eligible=complete and checked["valid"], reason=reason,
                   allocation=plan["allocations"].get(row["id"], "invalid_sources"))
        if row["eligible"]:
            eligible.append({key: deepcopy(row[key]) for key in
                ("id", "obligation", "kind", "situation", "applicability", "conditions", "missing_facts", "evidence_ids")})
        rows.append(row)
    counts.update(eligible=len(eligible), withheld=len(rows) - len(eligible))
    return dict(version="obligation_sources_v1", rows=rows, counts=counts,
                added_parent_ids=list(plan["added_parent_ids"]), added_tokens=plan["added_tokens"]), eligible


def public_coverage(coverage):
    """Chỉ chiếu quá trình nguồn; nguyên văn quyết định giữ ở trace gốc."""
    fields = ("id", "required_parents", "present_parents", "missing_parents", "missing_chunks",
              "missing_registry_parents", "source_status", "evidence_ids", "fragment_check",
              "eligible", "reason", "allocation")
    return {**{key: deepcopy(coverage[key]) for key in
                ("version", "counts", "added_parent_ids", "added_tokens")},
            "rows": [{key: deepcopy(row[key]) for key in fields} for row in coverage["rows"]]}
