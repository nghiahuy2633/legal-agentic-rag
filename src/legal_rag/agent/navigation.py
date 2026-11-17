"""Tra mục lục văn bản bằng luật: liệt kê, đếm Điều; Khoản của một Điều; Điểm của một Khoản.

Chỉ đọc cấu trúc trong data/processed/articles, không gọi mô hình. Câu không khớp
hoặc không xác định được đúng một văn bản thì trả None để agent xử lý như thường.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from legal_rag.retrieval.exact import document_candidates, fold

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"
MAX_CHARS = 160
CLAUSE_PREVIEW = 140

_ARTICLE = re.compile(r"\bdieu\s+(\d+[a-z]?)\b")
_CLAUSE = re.compile(r"\bkhoan\s+(\d+[a-z]?)\b")
_HAS_CLAUSE_NUMBER = re.compile(r"\bkhoan\s+\d")
_ASK_CLAUSES = re.compile(
    r"\b(?:bao nhieu|may|nhung|cac)\s+khoan\b|\bkhoan\s+nao\b|\b(?:liet ke|danh sach)\b.*\bkhoan\b")
# "điểm mới", "điểm nào cần lưu ý"... là hỏi nội dung, không phải hỏi các Điểm a, b, c.
_NOT_POINT = r"(?!\s+(?:nao\s+)?(?:moi|chinh|quan trong|dang|can|noi bat|luu y|khac|gi)\b)"
_ASK_POINTS = re.compile(
    rf"\b(?:bao nhieu|may|nhung|cac)\s+diem\b{_NOT_POINT}|\bdiem\b{_NOT_POINT}\s+nao\b"
    rf"|\b(?:liet ke|danh sach)\b.*\bdiem\b{_NOT_POINT}")
_COUNT = re.compile(r"\b(?:bao nhieu|may)\s+(?:dieu|khoan|diem)\b")
_ASK_ARTICLES = re.compile(
    r"\b(?:liet ke|danh sach|muc luc)\b.*\bdieu\b|\bmuc luc\b|\b(?:bao nhieu|may)\s+dieu\b"
    r"|\b(?:gom|co)\s+(?:nhung\s+)?dieu\s+nao\b|\bcac\s+dieu\s+(?:cua|trong)\b")


@lru_cache(maxsize=None)
def _documents(data_dir=DATA_DIR):
    docs = {}
    with open(data_dir / "chunks.jsonl", encoding="utf-8") as handle:
        for line in handle:
            chunk = json.loads(line)
            docs.setdefault(chunk["document_id"], {key: chunk.get(key) for key in (
                "document_id", "document_number", "document_title")})
    return docs


@lru_cache(maxsize=None)
def _articles(document_id, data_dir=DATA_DIR):
    path = data_dir / "articles" / f"{document_id}.jsonl"
    if not path.exists():
        return ()
    with open(path, encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle)


def detect(message):
    """Trả loại câu hỏi mục lục hoặc None. Câu dài coi là câu hỏi nội dung."""
    text = fold(message.strip())
    if not text or len(text) > MAX_CHARS:
        return None
    count_only = bool(_COUNT.search(text))
    article = _ARTICLE.search(text)
    clause = _CLAUSE.search(text)
    if article and clause:
        if not _ASK_POINTS.search(text):
            return None
        return {"kind": "points", "article": article[1], "clause": clause[1], "count_only": count_only}
    if article:
        if _HAS_CLAUSE_NUMBER.search(text) or not _ASK_CLAUSES.search(text):
            return None
        return {"kind": "clauses", "article": article[1], "clause": None, "count_only": count_only}
    if _ASK_ARTICLES.search(text):
        return {"kind": "articles", "article": None, "clause": None, "count_only": count_only}
    return None


def _document_label(doc):
    return f"{doc['document_title']} ({doc['document_number']})"


def _preview(text):
    text = " ".join((text or "").split())
    return text if len(text) <= CLAUSE_PREVIEW else text[:CLAUSE_PREVIEW].rstrip() + "…"


def _clause_preview(clause):
    if not (clause.get("lead_in") or "").strip() and clause.get("points"):
        return _preview(clause["points"][0].get("text"))
    return _preview(clause.get("lead_in"))


def _list_articles(doc, articles, count_only):
    head = f"{_document_label(doc)} có {len(articles)} Điều."
    if count_only:
        return head
    lines, chapter = [head, ""], None
    for article in articles:
        if article.get("chapter") and article["chapter"] != chapter:
            chapter = article["chapter"]
            lines.append(f"Chương {chapter}. {article.get('chapter_title') or ''}".rstrip())
        lines.append(f"- Điều {article['article']}. {article['title']}")
    return "\n".join(lines)


def _list_clauses(doc, article, count_only):
    clauses = article.get("clauses") or []
    head = (f"Điều {article['article']}. {article['title']} của {_document_label(doc)} "
            f"có {len(clauses)} Khoản." if clauses else
            f"Điều {article['article']}. {article['title']} của {_document_label(doc)} không chia Khoản.")
    if count_only or not clauses:
        return head
    return "\n".join([head, ""] + [f"- Khoản {c['clause']}: {_clause_preview(c)}" for c in clauses])


def _list_points(doc, article, clause, count_only):
    points = clause.get("points") or []
    name = f"Khoản {clause['clause']} Điều {article['article']}. {article['title']} của {_document_label(doc)}"
    if not points:
        return f"{name} không chia Điểm."
    head = f"{name} có {len(points)} Điểm."
    if count_only:
        return head
    return "\n".join([head, ""] + [f"- Điểm {p['point']}: {_preview(p.get('text'))}" for p in points])


def navigate(message, data_dir=DATA_DIR):
    """Trả {"reply", "kind", "document_id"} khi trả lời được bằng mục lục, ngược lại None."""
    request = detect(message)
    if request is None:
        return None
    docs = _documents(data_dir)
    found, _ = document_candidates(message, list(docs.values()))
    if len(found) != 1:
        return None
    document_id = next(iter(found))
    articles = _articles(document_id, data_dir)
    if not articles:
        return None
    doc = docs[document_id]
    if request["kind"] == "articles":
        body = _list_articles(doc, articles, request["count_only"])
    else:
        match = [a for a in articles if fold(str(a["article"])) == request["article"]]
        if not match:
            return None
        if request["kind"] == "clauses":
            body = _list_clauses(doc, match[0], request["count_only"])
        else:
            clauses = [c for c in match[0].get("clauses") or []
                       if fold(str(c["clause"])) == request["clause"]]
            if not clauses:
                return None
            body = _list_points(doc, match[0], clauses[0], request["count_only"])
    reply = body + "\n\nNguồn: mục lục đọc trực tiếp từ văn bản trong kho luật, không qua mô hình."
    return {"reply": reply, "kind": request["kind"], "document_id": document_id}
