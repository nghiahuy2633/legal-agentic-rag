"""Lọc lời khai hiện tại khỏi câu hỏi và dự định."""
import re
import unicodedata

QUESTION_MARKERS = ("có cần", "có phải", "phải không", "được không", "là gì",
                    "bao nhiêu", "thế nào", "như nào", "làm sao", "không ạ")
INTENTION_MARKERS = ("dự kiến", "sẽ", "định", "sắp", "kế hoạch")


def chat_claims(messages):
    claims = []
    for message in messages:
        for sentence in re.findall(r"[^.!?;\n]+[.!?;]?", unicodedata.normalize("NFC", message)):
            sentence = sentence.strip()
            lower = sentence.lower()
            if (not re.search(r"\w", sentence) or sentence.endswith("?") or any(
                    re.search(r"(?<!\w)" + re.escape(marker) + r"(?!\w)", lower)
                    for marker in QUESTION_MARKERS + INTENTION_MARKERS)):
                continue
            claims.append(sentence)
    return "\n".join(claims)
