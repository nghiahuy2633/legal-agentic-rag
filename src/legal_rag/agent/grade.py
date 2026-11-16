"""Chấm mức đề cập của bằng chứng, một lần gọi và không thử lại JSON lỗi."""

import json
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts/grade_v1.txt"
STATUSES = ("du", "thieu_mot_phan", "khong_lien_quan")


def grade_evidence(message, queries, items, chat, model, version="grade_v3") -> dict:
    if version not in ("grade_v1", "grade_v2", "grade_v3"):
        raise ValueError("Sai phiên bản prompt chấm")
    path = PROMPT_PATH if version == "grade_v1" else PROMPT_PATH.with_name(f"{version}.txt")
    prompt = path.read_text(encoding="utf-8")
    if not prompt.splitlines() or prompt.splitlines()[0] != f"Phiên bản: {version}":
        raise ValueError(f"Sai phiên bản prompt: cần {version}")
    evidence = [{key: item.get(key) for key in
                 ("id", "document_number", "article", "clause", "article_title")}
                | {"text": item.get("text", "")[:400]} for item in items]
    data = dict(message=message, queries=list(queries), evidence=evidence)
    answer = chat.complete(dict(model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": prompt},
                  {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]))
    fallback = dict(status="du", missing=[], rewrite=[], grade_ok=False)
    try:
        result = json.loads(answer)
    except (TypeError, ValueError):
        return fallback
    if not isinstance(result, dict) or result.get("status") not in (STATUSES + (("khong_co_chi_tiet",) if version != "grade_v1" else ())):
        return fallback
    def strings(key):
        value = result.get(key)
        return list(dict.fromkeys(x.strip() for x in value if isinstance(x, str) and x.strip())) if isinstance(value, list) else []
    return dict(status=result["status"], missing=strings("missing"),
                rewrite=strings("rewrite")[:2] if result["status"] not in ("du", "khong_co_chi_tiet") else [], grade_ok=True)
