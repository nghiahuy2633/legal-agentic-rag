"""Chỉ xuất dữ liệu quá trình xử lý đã cho phép cho giao diện."""

from legal_rag.agent.obligation_sources import public_coverage


def trace_view(trace) -> dict:
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key.lower() not in {"api_key", "authorization", "secret", "password",
                                           "token", "access_token", "prompt", "messages", "client", "settings"}}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    def pick(row, fields):
        return {key: clean(row[key]) for key in fields if key in row}

    def scores(rows):
        return [pick(row, ("chunk_id", "score")) for row in rows]

    def selected(rows):
        return [pick(row, ("parent_id", "source")) for row in rows]

    def check(row):
        return pick(row or {}, ("valid", "used", "used_points", "errors", "warnings", "missing_blocks"))

    nodes = []
    for row in trace.get("nodes", trace.get("trace", [])):
        node = pick(row, ("node", "ms", "llm_calls", "sub_queries", "status", "missing",
                          "question_type", "request_plan", "reason", "facts_source", "effective_question_type",
                          "effective_prompt_version", "presentation", "retrieval_count", "new_parent_count", "stop_reason",
                          "rewrite", "grade_ok", "grade_error", "rewrite_count", "verify_ok",
                          "issues", "verifier_mode", "verify_error", "repair_error", "verification", "field",
                          "high_risk", "high_risk_error", "assess_ok", "candidate_selection", "map_obligations",
                          "unreviewed_count", "rejected_count", "risk_level"))
        if "selected" in row:
            node["selected"] = (clean(row["selected"]) if row["node"] == "map_obligations"
                                else selected(row["selected"]))
        if "check" in row:
            node["check"] = check(row["check"])
        if "obligation_source_coverage" in row:
            node["obligation_source_coverage"] = clean(public_coverage(row["obligation_source_coverage"]))
        if "last_detail" in row:
            detail = row["last_detail"]
            node["last_detail"] = dict(queries=detail.get("queries", []),
                rerank_query=detail.get("rerank_query"),
                retrieval=[dict(query=q.get("query"), bm25=scores(q.get("bm25", [])),
                    dense={name: scores(rows) for name, rows in q.get("dense", {}).items()
                           if name in ("jina", "viet")}) for q in detail.get("retrieval", [])],
                **{key: scores(detail.get(key, [])) for key in ("rrf", "rerank", "exact")})
        nodes.append(node)
    return dict(nodes=nodes, evidence=[pick(row, ("id", "parent_id", "document_id", "document_number",
        "article", "clause", "article_title", "text", "source", "referenced_from", "external_refs"))
        for row in trace.get("evidence", [])], check=check(trace.get("check")))
