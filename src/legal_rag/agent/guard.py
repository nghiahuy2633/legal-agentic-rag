"""Luật thuần cho những đầu vào chắc chắn không cần truy xuất."""

import re
import unicodedata

from legal_rag.retrieval.exact import fold

MAX_INPUT_CHARS = 4000
GREETING_WORDS = frozenset(
    "xin chao ban hello hi alo cam on nhe nha a ad admin oi thanks thank you ok oke tam biet".split()
)
GUIDANCE = "Bạn hãy mô tả sản phẩm AI hoặc đặt câu hỏi về nghĩa vụ pháp lý của sản phẩm AI tại Việt Nam."


def check_input(text):
    text = unicodedata.normalize("NFC", text).strip()
    if not text:
        return {"status": "empty", "reply": GUIDANCE}
    if len(text) > MAX_INPUT_CHARS:
        return {"status": "too_long", "reply": (
            f"Giới hạn đầu vào là {MAX_INPUT_CHARS} ký tự. "
            "Bạn hãy tóm tắt sản phẩm và câu hỏi."
        )}
    words = re.findall(r"\w+", text)
    if not any(any(char.isalpha() for char in word) for word in words):
        return {"status": "garbage", "reply": GUIDANCE}
    if words and all(fold(word) in GREETING_WORDS for word in words):
        return {"status": "greeting", "reply": "Xin chào! " + GUIDANCE}
    return {"status": "ok", "reply": None}


def scope_reply():
    return (
        "Câu hỏi ngoài phạm vi hỗ trợ. Hệ thống hỗ trợ nghĩa vụ pháp lý của sản phẩm AI "
        "theo Luật 134/2025/QH15, Nghị định 142/2026/NĐ-CP, "
        "Thông tư 05/2026/TT-BKHCN, Quyết định 33/2026/QĐ-TTg."
    )
