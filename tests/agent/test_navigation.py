"""Tra mục lục bằng luật: không gọi mô hình, chỉ bắt câu hỏi mục lục rõ ràng.

Số Điều, Khoản, Điểm mong đợi được đọc lại từ data/processed/articles, không ghi cứng.
"""

import json
from pathlib import Path

import pytest

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.navigation import DATA_DIR, MAX_CHARS, detect, navigate

ARTICLES_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "articles"
LAW, DECREE, CIRCULAR, DECISION = "134-2025-QH15", "142-2026-ND-CP", "05-2026-TT-BKHCN", "33-2026-QD-TTg"
SOURCE_NOTE = "Nguồn: mục lục đọc trực tiếp từ văn bản trong kho luật, không qua mô hình."


def load_articles(document_id):
    with open(ARTICLES_DIR / f"{document_id}.jsonl", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def article_of(document_id, number):
    return next(a for a in load_articles(document_id) if a["article"] == str(number))


def clause_of(document_id, article, number):
    return next(c for c in article_of(document_id, article)["clauses"] if c["clause"] == str(number))


def test_data_dir_points_at_repo_data():
    assert DATA_DIR == ARTICLES_DIR.parent
    assert (DATA_DIR / "chunks.jsonl").exists()
    for document_id in (LAW, DECREE, CIRCULAR, DECISION):
        assert (DATA_DIR / "articles" / f"{document_id}.jsonl").exists()


# ---- Nhận dạng câu hỏi ----

@pytest.mark.parametrize("message, kind, count_only", [
    ("Liệt kê các điều của Luật trí tuệ nhân tạo", "articles", False),
    ("liet ke cac dieu cua luat tri tue nhan tao", "articles", False),
    ("luat AI co bao nhieu dieu", "articles", True),
    ("Luật AI có mấy điều?", "articles", True),
    ("Luật 134 có tất cả bao nhiêu điều", "articles", True),
    ("Nghị định 142 gồm những điều nào?", "articles", False),
    ("NĐ 142 có những điều nào", "articles", False),
    ("Danh sách các điều trong Nghị định 142", "articles", False),
    ("Mục lục thông tư 05", "articles", False),
    ("muc luc quyet dinh 33", "articles", False),
    ("Cho tôi xem mục lục của Luật 134/2025/QH15", "articles", False),
    ("Các điều của Quyết định 33 là gì", "articles", False),
    ("Điều 11 Luật 134 có những khoản nào?", "clauses", False),
    ("liet ke cac khoan dieu 18 nghi dinh 142", "clauses", False),
    ("Danh sách khoản của Điều 3 Thông tư 05", "clauses", False),
    ("Điều 18 Nghị định 142 có mấy khoản", "clauses", True),
    ("dieu 4 quyet dinh 33 co bao nhieu khoan", "clauses", True),
    ("Điều 5 luật AI gồm các khoản nào", "clauses", False),
    ("Liệt kê các điểm của khoản 2 điều 7 luật 134", "points", False),
    ("liet ke cac diem khoan 2 dieu 7 luat 134", "points", False),
    ("khoản 2 điều 18 nghị định 142 có mấy điểm", "points", True),
    ("Khoản 1 Điều 3 Thông tư 05 có bao nhiêu điểm?", "points", True),
    ("Khoản 1 Điều 4 Quyết định 33 gồm những điểm nào", "points", False),
    ("Danh sách điểm của khoản 3 điều 18 NĐ 142", "points", False),
    ("Điều 14 khoản 1 Luật AI có các điểm nào?", "points", False),
])
def test_detects_navigation_questions(message, kind, count_only):
    request = detect(message)
    assert request["kind"] == kind and request["count_only"] is count_only


def test_detect_returns_article_and_clause_numbers():
    assert detect("Điều 11 Luật 134 có những khoản nào?")["article"] == "11"
    request = detect("khoản 2 điều 18 nghị định 142 có mấy điểm")
    assert (request["article"], request["clause"]) == ("18", "2")
    assert detect("Luật AI có mấy điều")["article"] is None


@pytest.mark.parametrize("message", [
    "Điều 11 là gì?",
    "Điều 11 Luật 134 quy định gì?",
    "Khoản 2 Điều 7 luật AI nói gì",
    "Khoản 2 Điều 7 Luật 134 quy định gì?",
    "Nội dung điểm a khoản 2 điều 7 luật 134",
    "Điểm a khoản 2 Điều 7 Luật 134 nói gì?",
    "Khoản 2 Điều 7 Luật 134 có điểm gì mới?",
    "Khoản 2 Điều 7 Luật 134 có những điểm mới nào?",
    "Khoản 2 Điều 7 Luật 134 có điểm nào cần lưu ý?",
    "Các điểm quan trọng của khoản 2 điều 7 luật 134",
    "Khoản 3 Điều 11 Luật 134 áp dụng cho ai?",
    "Bên triển khai hệ thống trí tuệ nhân tạo là gì?",
    "Không gắn nhãn video deepfake thì bị phạt bao nhiêu tiền?",
    "Hệ thống rủi ro cao phải đáp ứng những điều kiện nào?",
    "Viết giúp tôi một bài thơ về mùa thu",
    "",
    "   ",
])
def test_content_questions_are_not_detected(message):
    assert detect(message) is None
    assert navigate(message) is None


@pytest.mark.parametrize("message", [
    "Liệt kê các khoản của Điều 11 có liên quan tới gắn nhãn video, ảnh do AI tạo ra cho một nền tảng "
    "mạng xã hội có hàng triệu người dùng và tự phát triển mô hình ngôn ngữ lớn",
    "Liệt kê các điều của Luật trí tuệ nhân tạo mà một doanh nghiệp khởi nghiệp cung cấp chatbot chăm sóc "
    "khách hàng cho ngân hàng cần đặc biệt quan tâm khi triển khai tại Việt Nam",
    "Liệt kê các điểm của khoản 2 điều 7 luật 134 và giải thích từng điểm áp dụng thế nào cho công ty tôi "
    "đang phát triển hệ thống chấm điểm tín dụng dùng trí tuệ nhân tạo",
])
def test_long_questions_fall_back_to_agent(message):
    assert len(message) > MAX_CHARS
    assert navigate(message) is None


@pytest.mark.parametrize("message", [
    "Liệt kê các điều của luật",
    "Có bao nhiêu điều?",
    "Mục lục",
    "Điều 11 có những khoản nào?",
    "Khoản 2 điều 7 có mấy điểm?",
    "Liệt kê các điều của nghị định",
])
def test_question_without_document_falls_back(message):
    assert detect(message) is not None
    assert navigate(message) is None


@pytest.mark.parametrize("message", [
    "Luật 999 có bao nhiêu điều",
    "Liệt kê các điều của Luật An ninh mạng",
    "Nghị định 13 gồm những điều nào?",
    "Mục lục thông tư 99",
    "Điều 5 Nghị định 13 có những khoản nào",
    "Khoản 1 điều 2 Luật 24 có mấy điểm",
])
def test_document_outside_corpus_falls_back(message):
    assert navigate(message) is None


def test_two_documents_in_one_question_fall_back():
    assert navigate("Luật 134 và Nghị định 142 có bao nhiêu điều") is None


@pytest.mark.parametrize("message", [
    "Điều 99 Luật 134 có những khoản nào?",
    "Điều 47 Nghị định 142 có mấy khoản",
    "Điều 6 Thông tư 05 có những khoản nào",
    "Khoản 2 Điều 99 Luật 134 có mấy điểm",
    "Khoản 9 Điều 7 Luật 134 có những điểm nào",
    "Liệt kê các điểm của khoản 8 điều 18 nghị định 142",
    "Khoản 1 Điều 4 Thông tư 05 có mấy điểm",
])
def test_missing_article_or_clause_falls_back(message):
    assert detect(message) is not None
    assert navigate(message) is None


# ---- Cấp Điều ----

@pytest.mark.parametrize("message, document_id", [
    ("Liệt kê các điều của Luật trí tuệ nhân tạo", LAW),
    ("liet ke cac dieu cua luat AI", LAW),
    ("Luật 134 gồm những điều nào", LAW),
    ("Mục lục Luật 134/2025/QH15", LAW),
    ("Nghị định 142 gồm những điều nào?", DECREE),
    ("Danh sách các điều trong NĐ 142", DECREE),
    ("muc luc nghi dinh 142/2026/NĐ-CP", DECREE),
    ("Mục lục thông tư 05", CIRCULAR),
    ("Liệt kê các điều của TT 05", CIRCULAR),
    ("Quyết định 33 có những điều nào", DECISION),
    ("danh sach cac dieu cua QĐ 33", DECISION),
])
def test_lists_every_article_of_each_document(message, document_id):
    articles = load_articles(document_id)
    result = navigate(message)
    assert result["kind"] == "articles" and result["document_id"] == document_id
    lines = result["reply"].splitlines()
    assert lines[0].endswith(f"có {len(articles)} Điều.")
    assert [line for line in lines if line.startswith("- Điều ")] == [
        f"- Điều {a['article']}. {a['title']}" for a in articles]
    assert lines[-1] == SOURCE_NOTE


@pytest.mark.parametrize("message, document_id", [
    ("luat AI co bao nhieu dieu", LAW),
    ("Luật trí tuệ nhân tạo có mấy điều?", LAW),
    ("Nghị định 142 có bao nhiêu điều", DECREE),
    ("ND 142 co may dieu", DECREE),
    ("Thông tư 05 có mấy điều", CIRCULAR),
    ("Quyết định 33 có bao nhiêu điều?", DECISION),
])
def test_counts_articles_without_listing(message, document_id):
    result = navigate(message)
    assert result["document_id"] == document_id
    assert f"có {len(load_articles(document_id))} Điều." in result["reply"]
    assert "- Điều" not in result["reply"]


def test_article_list_shows_chapters_only_when_document_has_them():
    law = navigate("Liệt kê các điều của Luật trí tuệ nhân tạo")["reply"]
    chapters = []
    for article in load_articles(LAW):
        if article["chapter"] not in chapters:
            chapters.append(article["chapter"])
    assert [line.split(".")[0] for line in law.splitlines() if line.startswith("Chương ")] == [
        f"Chương {chapter}" for chapter in chapters]
    assert "Chương" not in navigate("Mục lục thông tư 05")["reply"]


def test_reply_names_document_title_and_number():
    reply = navigate("Mục lục quyết định 33")["reply"]
    assert reply.startswith("Quyết định ban hành Danh mục hệ thống trí tuệ nhân tạo có rủi ro cao (33/2026/QĐ-TTg) có")


# ---- Cấp Khoản ----

@pytest.mark.parametrize("message, document_id, number", [
    ("Điều 11 Luật 134 có những khoản nào?", LAW, 11),
    ("Liệt kê các khoản của Điều 5 luật AI", LAW, 5),
    ("liet ke cac khoan dieu 18 nghi dinh 142", DECREE, 18),
    ("Điều 41 NĐ 142 gồm các khoản nào", DECREE, 41),
    ("Danh sách khoản của Điều 3 Thông tư 05", CIRCULAR, 3),
    ("Điều 4 Quyết định 33 có những khoản nào", DECISION, 4),
])
def test_lists_clauses_of_one_article(message, document_id, number):
    article = article_of(document_id, number)
    result = navigate(message)
    assert result["kind"] == "clauses" and result["document_id"] == document_id
    lines = result["reply"].splitlines()
    assert lines[0].startswith(f"Điều {number}. {article['title']} của ")
    assert lines[0].endswith(f"có {len(article['clauses'])} Khoản.")
    assert [line.split(":")[0] for line in lines if line.startswith("- Khoản ")] == [
        f"- Khoản {c['clause']}" for c in article["clauses"]]


@pytest.mark.parametrize("message, document_id, number", [
    ("Điều 18 Nghị định 142 có mấy khoản", DECREE, 18),
    ("dieu 11 luat 134 co bao nhieu khoan", LAW, 11),
    ("Điều 3 TT 05 có mấy khoản?", CIRCULAR, 3),
    ("Điều 1 QĐ 33 có bao nhiêu khoản", DECISION, 1),
])
def test_counts_clauses_without_listing(message, document_id, number):
    reply = navigate(message)["reply"]
    assert f"có {len(article_of(document_id, number)['clauses'])} Khoản." in reply
    assert "- Khoản" not in reply


def test_clause_line_previews_lead_in():
    reply = navigate("Điều 11 Luật 134 có những khoản nào?")["reply"]
    lead_in = " ".join(clause_of(LAW, 11, 4)["lead_in"].split())
    assert f"- Khoản 4: {lead_in[:40]}" in reply


@pytest.mark.parametrize("message, document_id, number", [
    ("Điều 2 Luật 134 có những khoản nào", LAW, 2),
    ("Điều 45 Nghị định 142 có mấy khoản", DECREE, 45),
    ("Liệt kê các khoản của Điều 4 Thông tư 05", CIRCULAR, 4),
])
def test_article_without_clauses_says_so(message, document_id, number):
    assert not article_of(document_id, number)["clauses"]
    reply = navigate(message)["reply"]
    assert "không chia Khoản." in reply and "- Khoản" not in reply


# ---- Cấp Điểm ----

@pytest.mark.parametrize("message, document_id, article, clause", [
    ("Liệt kê các điểm của khoản 2 điều 7 luật 134", LAW, 7, 2),
    ("liet ke cac diem khoan 1 dieu 14 luat AI", LAW, 14, 1),
    ("Khoản 2 Điều 7 Luật trí tuệ nhân tạo có những điểm nào?", LAW, 7, 2),
    ("Khoản 3 điều 18 nghị định 142 gồm các điểm nào", DECREE, 18, 3),
    ("Danh sách điểm của khoản 1 điều 1 NĐ 142", DECREE, 1, 1),
    ("Liệt kê các điểm khoản 1 Điều 3 Thông tư 05", CIRCULAR, 3, 1),
    ("Khoản 1 Điều 4 Quyết định 33 có những điểm nào", DECISION, 4, 1),
])
def test_lists_points_of_one_clause(message, document_id, article, clause):
    points = clause_of(document_id, article, clause)["points"]
    assert points
    result = navigate(message)
    assert result["kind"] == "points" and result["document_id"] == document_id
    lines = result["reply"].splitlines()
    assert lines[0].startswith(f"Khoản {clause} Điều {article}. {article_of(document_id, article)['title']} của ")
    assert lines[0].endswith(f"có {len(points)} Điểm.")
    assert [line.split(":")[0] for line in lines if line.startswith("- Điểm ")] == [
        f"- Điểm {p['point']}" for p in points]
    assert lines[-1] == SOURCE_NOTE


@pytest.mark.parametrize("message, document_id, article, clause", [
    ("khoản 2 điều 18 nghị định 142 có mấy điểm", DECREE, 18, 2),
    ("Khoản 2 điều 7 luật 134 có bao nhiêu điểm?", LAW, 7, 2),
    ("khoan 1 dieu 3 thong tu 05 co may diem", CIRCULAR, 3, 1),
    ("Khoản 1 Điều 4 QĐ 33 có mấy điểm", DECISION, 4, 1),
])
def test_counts_points_without_listing(message, document_id, article, clause):
    reply = navigate(message)["reply"]
    assert f"có {len(clause_of(document_id, article, clause)['points'])} Điểm." in reply
    assert "- Điểm" not in reply


def test_point_line_previews_point_text():
    point = clause_of(DECREE, 18, 3)["points"][-1]
    reply = navigate("Liệt kê các điểm của khoản 3 điều 18 nghị định 142")["reply"]
    assert f"- Điểm {point['point']}: {' '.join(point['text'].split())[:40]}" in reply


@pytest.mark.parametrize("message, document_id, article, clause", [
    ("Khoản 1 Điều 11 Luật 134 có những điểm nào", LAW, 11, 1),
    ("Liệt kê các điểm của khoản 1 điều 18 nghị định 142", DECREE, 18, 1),
    ("Khoản 2 Điều 1 Thông tư 05 có mấy điểm", CIRCULAR, 1, 2),
    ("khoản 1 điều 1 quyết định 33 có bao nhiêu điểm", DECISION, 1, 1),
])
def test_clause_without_points_says_so(message, document_id, article, clause):
    assert not clause_of(document_id, article, clause)["points"]
    result = navigate(message)
    assert result["kind"] == "points"
    assert f"Khoản {clause} Điều {article}." in result["reply"]
    assert "không chia Điểm." in result["reply"] and "- Điểm" not in result["reply"]


# ---- Trong đồ thị agent ----

class NoChat:
    calls = 0

    def complete(self, payload):
        raise AssertionError("navigation must not call the model")


def fail(*args, **kwargs):
    raise AssertionError("navigation must not retrieve or generate")


@pytest.mark.parametrize("message, kind, document_id", [
    ("Luật trí tuệ nhân tạo có bao nhiêu điều?", "articles", LAW),
    ("Điều 18 Nghị định 142 có mấy khoản", "clauses", DECREE),
    ("Liệt kê các điểm của khoản 1 điều 3 thông tư 05", "points", CIRCULAR),
])
def test_graph_answers_navigation_without_llm(message, kind, document_id):
    graph = build_graph(GraphDeps(NoChat(), "fake", fail, AgentConfig(), fail))
    result = run_turn(graph, "s", message)
    assert result["route"] == "navigation" and result["llm_calls"] == 0
    assert result["reply"] == navigate(message)["reply"]
    assert [node["node"] for node in result["trace"]] == ["check_input", "respond"]
    entry = result["trace"][0]
    assert (entry["status"], entry["kind"], entry["document_id"]) == ("navigation", kind, document_id)


def test_graph_passes_content_question_on_to_agent():
    graph = build_graph(GraphDeps(NoChat(), "fake", fail, AgentConfig(), fail))
    with pytest.raises(AssertionError):
        run_turn(graph, "s", "Khoản 2 Điều 7 luật AI nói gì")


def test_switch_is_on_by_default_and_off_keeps_old_behaviour():
    assert AgentConfig().enable_navigation is True
    graph = build_graph(GraphDeps(NoChat(), "fake", fail, AgentConfig(enable_navigation=False), fail))
    with pytest.raises(AssertionError):
        run_turn(graph, "s", "Luật trí tuệ nhân tạo có bao nhiêu điều?")
