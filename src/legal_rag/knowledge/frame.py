"""Khung căn cứ cố định và nhận biết câu hỏi nghĩa vụ tổng quát."""

import re

import yaml

from legal_rag.retrieval.exact import fold, parse_location


ALLOWED_WORDS = set("""mot cac nhung san pham ai tri tue nhan tao he thong ung dung app
minh toi ben cong ty cty can co phai lam thi ve theo phap luat nghia vu tuan thu
luu y gi nao vay nhu the ra sao ko khong""".split())
PHRASES = ("nghia vu", "tuan thu", "phai lam gi", "can lam gi", "luu y")


def is_broad_obligation_query(query: str) -> bool:
    if parse_location(query):
        return False
    words = re.findall(r"\w+", fold(query))
    text = " " + " ".join(words) + " "
    return (bool(words) and set(words) <= ALLOWED_WORDS
            and any(f" {phrase} " in text for phrase in PHRASES))


def load_frame(path, parents):
    """Trả các khối theo thứ tự YAML, thay mã bằng parent thật."""
    with open(path, encoding="utf-8") as stream:
        blocks = yaml.safe_load(stream)
    registry = parents if isinstance(parents, dict) else {p["parent_id"]: p for p in parents}
    result = []
    for block in blocks:
        units = []
        for parent_id in block["parents"]:
            if parent_id not in registry:
                raise ValueError(f"Khung {block['key']}: không có parent_id {parent_id}")
            units.append(registry[parent_id])
        result.append(dict(block, parents=units))
    return result
