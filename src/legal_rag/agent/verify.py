"""Kiểm chứng nội dung bằng một lời gọi, không thử lại phản hồi hỏng."""

import json
from pathlib import Path
import re

PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"
TYPES = {"sai_noi_dung", "sai_chu_the", "sai_muc_do", "khong_co_can_cu", "sai_ma"}


def evidence_data(items):
    return [{key: item.get(key) for key in (
        "id", "document_number", "document_title", "article", "clause", "article_title",
        "text", "scope_note", "conformity_note")} for item in items]


def verify_answer(answer, items, chat, model) -> dict:
    used = {m.upper() for m in re.findall(r"\bE\d+\b", " ".join(
        re.findall(r"\[([^\[\]]*)\]", answer)), re.I)}
    data = dict(answer=answer, evidence=evidence_data(
        [item for item in items if item["id"].upper() in used]))
    response = chat.complete(dict(model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": (PROMPT_DIR / "verify_v2.txt").read_text(encoding="utf-8")},
                  {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]))
    try:
        result = json.loads(response)
        if not isinstance(result, dict):
            raise ValueError
        issues = result.get("issues")
        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise ValueError
    except (TypeError, ValueError):
        return dict(issues=[], verify_ok=False)
    return dict(issues=[{key: issue.get(key, "") for key in ("sentence", "type", "evidence", "reason")}
                        for issue in issues if isinstance(issue, dict)
                        and isinstance(issue.get("type"), str) and issue["type"] in TYPES
                        and isinstance(issue.get("sentence"), str) and issue["sentence"].strip()],
                verify_ok=True)
