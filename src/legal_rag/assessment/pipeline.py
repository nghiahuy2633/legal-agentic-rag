"""Ghép lọc áp dụng, chấm tiêu chí và bản đánh giá."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.report import build_report, render_markdown, summarize
from legal_rag.assessment.status import assess_status
from legal_rag.knowledge.facts import validate_facts
from legal_rag.knowledge.obligations import load_obligations

TABLE = Path(__file__).resolve().parents[1] / "knowledge/obligations.yaml"


def prepare_assessment(messages, chat, model, previous=None, form=None, rows=None, prompt_version="facts_v2"):
    from legal_rag.assessment.facts_extract import extract_facts, merge_facts
    from legal_rag.assessment.questions import followup_questions, ready_for_assessment

    extracted = extract_facts(messages, chat, model, prompt_version=prompt_version)
    facts, changes = merge_facts(previous, extracted["facts"], form)
    result = {"facts": facts, "evidence": extracted["evidence"],
              "rejected": extracted["rejected"], "changes": changes,
              "questions": followup_questions(load_obligations(TABLE) if rows is None else rows, facts),
              "ready": ready_for_assessment(facts)}
    if "error" in extracted:
        result["error"] = extracted["error"]
    return result


def run_assessment(facts, statement, description, chat, model, rows=None, checks=None,
                   created=None, summarize_report=True, verify_da=True):
    if not isinstance(facts, dict) or not isinstance(statement, str) or not isinstance(description, str):
        raise ValueError("Dữ kiện phải là đối tượng; lời khai và mô tả phải là chuỗi")
    facts, errors = validate_facts(facts)
    if errors:
        raise ValueError("; ".join(errors))
    timing = {}
    start = perf_counter()
    if rows is None:
        table_bytes = TABLE.read_bytes()
        rows = load_obligations(TABLE)
        table_source = "file"
    else:
        table_bytes = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        table_source = "rows_json"
    applicable = applicable_obligations(rows, facts)
    timing["applicable_ms"] = (perf_counter() - start) * 1000
    start = perf_counter()
    status = assess_status(applicable["items"], statement, description, chat, model, checks, verify_da=verify_da)
    timing["status_ms"] = (perf_counter() - start) * 1000
    start = perf_counter()
    report = build_report(facts, applicable["items"], status, {
        "model": model, "table_sha256": hashlib.sha256(table_bytes).hexdigest(),
        "created": created if created is not None else datetime.now(timezone.utc).isoformat()})
    timing["report_ms"] = (perf_counter() - start) * 1000
    summary = {"llm_calls": 0}
    start = perf_counter()
    if summarize_report:
        summary = summarize(report, chat, model)
        report.update(narrative=summary["text"], summary_rejected=summary["summary_rejected"])
    timing["summary_ms"] = (perf_counter() - start) * 1000
    start = perf_counter()
    markdown = render_markdown(report)
    timing["render_ms"] = (perf_counter() - start) * 1000
    return {"report": report, "markdown": markdown, "trace": {
        "applicable": applicable, "status": status, "summary": summary,
        "llm_calls": status["llm_calls"] + summary["llm_calls"],
        "timing": timing, "table_source": table_source}}
