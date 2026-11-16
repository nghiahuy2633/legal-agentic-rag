"""Sửa câu trả lời đúng một lời gọi với toàn bộ căn cứ của lượt."""

import json

from legal_rag.agent.verify import PROMPT_DIR, evidence_data
from legal_rag.agent.blocks import required_blocks, normalize_headings
from legal_rag.generation.citations import normalize_citation_markers
from legal_rag.agent.presentation import present_answer


def repair_answer(answer, errors, issues, items, chat, model,
                  version=None, question_type="khac", presentation_context=None, presentation_audit=None,
                  presentation_index=None, presentation_chunks=None) -> str:
    normalized = normalize_headings(normalize_citation_markers(answer), version, question_type)
    required = required_blocks(question_type)
    heading_errors = {f"Thiếu mục bắt buộc: {title}" for title in required}
    if (version in ("answer_v9", "answer_v10", "answer_v11") and errors and not issues
            and all(error in heading_errors for error in errors)
            and normalized != answer
            and all(f"## {title}" in normalized.splitlines() for title in required)):
        rendered, audit = present_answer(normalized, presentation_context, version)
        if presentation_audit is not None:
            presentation_audit.update(raw_reply=answer, presentation=audit)
        return rendered
    data = dict(answer=answer, errors=errors, issues=issues, evidence=evidence_data(items))
    prompt = ("repair_v5" if version == "answer_v12" else "repair_v4" if version == "answer_v11" else "repair_v3" if version == "answer_v10"
              else "repair_v2" if version == "answer_v9" else "repair_v1")
    if version in ("answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        data.update(question_type=question_type, required_blocks=required_blocks(question_type))
    if presentation_context is not None:
        data["Kết quả xử lý dùng để trình bày"] = presentation_context["data"]
    reply = chat.complete(dict(model=model, temperature=0,
        **({"response_format": {"type": "json_object"}} if version == "answer_v12" else {}), messages=[
        {"role": "system", "content": (PROMPT_DIR / f"{prompt}.txt").read_text(encoding="utf-8")},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]))
    if not isinstance(reply, str):
        return reply
    normalized = reply if version == "answer_v12" else normalize_headings(normalize_citation_markers(reply), version, question_type)
    rendered, audit = present_answer(normalized, presentation_context, version,
        **(dict(items=items, index=presentation_index, chunks=presentation_chunks) if version == "answer_v12" else {}))
    if presentation_audit is not None:
        presentation_audit.update(raw_reply=reply, presentation=audit)
    return rendered
