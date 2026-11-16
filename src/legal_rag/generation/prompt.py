"""Payload chat dùng prompt có kiểm tra phiên bản."""

from pathlib import Path
import json

from legal_rag.generation.evidence import format_evidence

PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"
DEFAULT_VERSION = "answer_v9"
BROAD_VERSION = "answer_v7"


def build_messages(question, items, version=DEFAULT_VERSION, question_type="khac", presentation_context=None):
    if version not in ("answer_v1", "answer_v2", "answer_v3", "answer_v4", "answer_v5", "answer_v6", "answer_v7", "answer_v8", "answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        raise ValueError("Sai phiên bản prompt")
    prompt = (PROMPT_DIR / f"{version}.txt").read_text(encoding="utf-8")
    if not prompt.splitlines() or prompt.splitlines()[0] != f"Phiên bản: {version}":
        raise ValueError(f"Sai phiên bản prompt: cần {version}")
    if version in ("answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        question += f"\nLoại câu hỏi: {question_type}"
    if presentation_context is not None:
        question += "\nKết quả xử lý dùng để trình bày:\n" + json.dumps(presentation_context["data"], ensure_ascii=False)
    return {"temperature": 0, **({"response_format": {"type": "json_object"}} if version == "answer_v12" else {}), "messages": [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Câu hỏi:\n{question}\n\nBằng chứng:\n{format_evidence(items)}"},
    ]}
