"""Chèn câu lưu ý và câu hỏi thu hẹp bằng luật, giữ câu kết cuối cùng."""

import re

from legal_rag.retrieval.exact import parse_location

CLOSING = "Đây là hướng dẫn sơ bộ, không phải tư vấn pháp lý."
NOTICE = "Lưu ý: một số nội dung trong câu trả lời này chưa qua được kiểm tra tự động, cần đối chiếu nguyên văn căn cứ."
QUESTIONS = {
    "role": "Bạn là bên nào đối với hệ thống này: nhà phát triển, nhà cung cấp (đưa ra thị trường dưới tên mình), bên triển khai (dùng trong hoạt động nghề nghiệp, thương mại) hay người sử dụng?",
    "product_description": "Bạn mô tả ngắn giúp hệ thống này làm gì và ai sử dụng?",
    "sector": "Hệ thống này dùng trong lĩnh vực nào, ví dụ y tế, giáo dục, ngân hàng?",
}


def before_closing(answer):
    match = re.search(r"Đây là hướng dẫn sơ bộ,\s+không phải\s+tư vấn pháp lý\.\s*$", answer)
    return (answer[:match.start()].rstrip(), answer[match.start():]) if match else (answer.rstrip(), "")


def append_before_closing(answer, text):
    body, closing = before_closing(answer)
    return "\n\n".join(part for part in (body, text, closing) if part)


def ask_followup(state):
    if (state.get("analysis") or {}).get("question_type", "khac") not in ("nghia_vu", "khac"):
        return {}, None
    if (state.get("followup_asked", False) or state.get("route") not in ("retrieval", "broad_frame")
            or parse_location(state["message"])):
        return {}, None
    body, _ = before_closing(state["reply"])
    if body.endswith(NOTICE):
        body = body[:-len(NOTICE)].rstrip()
    if body.endswith("?"):
        return {"followup_asked": True}, None
    for field, question in QUESTIONS.items():
        if state["profile"].get(field) is None:
            return {"reply": append_before_closing(state["reply"], question), "followup_asked": True}, field
    return {}, None
