"""Kiểm tra truy xuất và phép đo bằng corpus giả; không gọi mạng hay LLM."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from legal_rag.evaluation.retrieval import clause_unit, evaluate, metrics, ranked_units, label_summary
from legal_rag.evaluation.retrieval_gold import build_gold
from legal_rag.evaluation.retrieval_experiment import run_experiments
from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever, tokenize
from legal_rag.retrieval.exact import exact_lookup, parse_location


def chunk(identifier, article="9", clause="1", point=None, body="nội dung", doc="134-2025-QH15"):
    article_id = f"{doc}_dieu-{article}" if article else None
    return {"chunk_id": identifier, "document_id": doc,
            "document_number": "134/2025/QH15" if doc.startswith("134") else "142/2026/NĐ-CP",
            "document_title": "Luật Trí tuệ nhân tạo" if doc.startswith("134") else "Nghị định hướng dẫn",
            "article": article, "clause": clause, "point": point,
            "article_id": article_id, "parent_id": f"{article_id}_khoan-{clause}" if clause else article_id,
            "body": body, "index_text": "Điều 9, phân loại rủi ro: " + body}


@pytest.fixture
def corpus():
    return [chunk("a", point="a"), chunk("d", point="d"), chunk("dd", point="đ"),
            chunk("b", clause="2"), chunk("c", doc="142-2026-ND-CP"),
            chunk("e", article="7", clause="2")]


@pytest.mark.parametrize("query,ids", [
    ("điểm a khoản 1 Điều 9 Luật 134", ["a"]),
    ("diem a khoan 1 dieu 9 luat 134", ["a"]),
    ("Điểm đ khoản 1 Điều 9 Luật AI", ["dd"]),
    ("Điểm d khoản 1 Điều 9 Luật AI", ["d"]),
    ("khoản 2 Điều 7", ["e"]),
    ("Điều 9 Nghị định 142/2026/NĐ-CP", ["c"]),
    ("dieu 9 nd 142", ["c"]),
    ("Điều 40 luật AI", []), ("Điều 999", []),
    ("Điều 9 Luật 999", []), ("Điều 9 Luật 134/2024/QH15", []),
    ("điểm z khoản 1 Điều 9", []), ("khoản 99 Điều 9", []),
    ("hệ thống rủi ro cao", []), ("134/2025/QH15", ["a", "b", "d", "dd", "e"]),
])
def test_exact(query, ids, corpus):
    before = deepcopy(corpus)
    assert [h["chunk_id"] for h in exact_lookup(query, corpus)["results"]] == ids
    assert corpus == before


def test_ambiguous(corpus):
    assert exact_lookup("dieu 9", corpus)["ambiguous"]
    assert not exact_lookup("Điều 9 Luật AI", corpus)["ambiguous"]
    assert not exact_lookup("Điều 999", corpus)["ambiguous"]


def test_hand_calculated_metrics():
    ranking = ["x", "a", "a", "y", "b", "z", "c"]
    assert metrics(ranking, ["a", "b", "c", "missing"]) == {
        "hit@5": 1, "recall@5": .5, "recall@10": .75, "mrr": .5}
    assert metrics([], ["a"]) == {"hit@5": 0, "recall@5": 0, "recall@10": 0, "mrr": 0}
    assert metrics(["a"], []) is None


def test_grouping_denominators_and_article_ranks():
    results = [{"parent_id": p} for p in ["d_dieu-1_khoan-1", "d_dieu-1_khoan-1",
                                          "d_dieu-1_khoan-2", "d_dieu-2", "d_phu-luc-1"]]
    assert ranked_units(results, "parent") == ["d_dieu-1_khoan-1", "d_dieu-1_khoan-2", "d_dieu-2", "d_phu-luc-1"]
    assert ranked_units(results, "article") == ["d_dieu-1", "d_dieu-2", "d_phu-luc-1"]
    rows = [{"id": "a", "category": "one", "priority": True, "gold_status": "auto",
             "gold_parents": ["d_dieu-1_khoan-1", "absent"], "gold_articles": ["d_dieu-2"]},
            {"id": "b", "category": "two", "priority": False, "gold_status": "auto",
             "gold_parents": [], "gold_articles": []},
            {"id": "c", "category": "one", "priority": True, "gold_status": "unresolved",
             "gold_parents": [], "gold_articles": []}]
    scored = evaluate(rows, {"a": results}, {"a": 2, "b": 4, "c": 6})
    assert scored["all"]["parent"] == {"labeled_questions": 1, "hit@5": 1,
                                       "recall@5": .5, "recall@10": .5, "mrr": 1}
    assert scored["all"]["article"]["mrr"] == .5
    assert scored["all"]["median_latency_ms"] == 4
    assert scored["priority"]["parent"]["labeled_questions"] == 1
    assert scored["categories"]["two"]["article"]["recall@5"] is None


def test_macro_average():
    rows = [{"id": str(i), "category": "one", "priority": True, "gold_status": "auto",
             "gold_parents": g, "gold_articles": []} for i, g in enumerate([["a"], ["a", "b"]])]
    scored = evaluate(rows, {"0": [{"parent_id": "a"}], "1": [{"parent_id": "b"}]})
    assert scored["all"]["parent"]["recall@5"] == .75


def test_stable_ranking_and_configuration():
    rows = [chunk("z", body="tín dụng"), chunk("a", body="tín dụng")]
    rows += [chunk(str(i), body="giáo dục học sinh") for i in range(4)]
    retriever = BM25Retriever(rows, BM25Config("syllable", "keep", "body"))
    assert [r["chunk_id"] for r in retriever.search("tín dụng")] == ["a", "z"]
    assert retriever.search("tín dụng") == BM25Retriever(list(reversed(rows)), retriever.config).search("tín dụng")
    assert retriever.search("tín dụng", limit=0) == []
    assert BM25Retriever([], retriever.config).search("test") == []
    assert BM25Retriever([chunk("a", body="")], retriever.config).search("test") == []
    with pytest.raises(ValueError):
        BM25Config(tokenizer="invalid")
    with pytest.raises(ValueError):
        BM25Config(accents="invalid")
    with pytest.raises(ValueError):
        BM25Config(source="invalid")


@pytest.mark.parametrize("tokenizer", ["syllable", "pyvi"])
def test_normalization_and_unaccented(tokenizer):
    config = BM25Config(tokenizer, "both", "body")
    assert tokenize("TÍN DỤNG", config) == tokenize("TI\u0301N DU\u0323NG", config)
    rows = [chunk("match", body="tín dụng ngân hàng")]
    rows += [chunk(str(i), body="giáo dục học sinh") for i in range(5)]
    assert BM25Retriever(rows, config).search("tin dung")[0]["chunk_id"] == "match"


def test_source_selection():
    rows = [chunk(str(i), body="bình thường") for i in range(5)]
    rows[0]["index_text"] = "đặc biệt"
    assert not BM25Retriever(rows, BM25Config("syllable", "keep", "body")).search("đặc biệt")
    assert BM25Retriever(rows, BM25Config("syllable", "keep", "index_text")).search("đặc biệt")[0]["chunk_id"] == "0"


def test_gold_resolution_and_overrides(corpus):
    parents = [{"parent_id": p} for p in {c["parent_id"] for c in corpus} | {"134-2025-QH15_dieu-9"}]
    base = {"id": "q", "question": "test", "category": "test", "priority": True,
            "in_corpus": "co", "expected_sources": ["Luật 134/2025/QH15, Điều 9, khoản 1, điểm a",
                                                       "Luật 134/2025/QH15, Điều 9"]}
    before = deepcopy(base)
    row = build_gold([base], parents, corpus)[0]
    assert row["gold_status"] == "auto"
    assert row["gold_parents"] == ["134-2025-QH15_dieu-9_khoan-1"]
    assert row["gold_articles"] == ["134-2025-QH15_dieu-9"]
    assert base == before
    override = {"id": "q", "gold_parents": ["134-2025-QH15_dieu-9_khoan-2"],
                "gold_status": "manual_ai", "notes": "căn cứ giả"}
    assert len(build_gold([base], parents, corpus, [override])[0]["gold_parents"]) == 2
    for source in ["Luật 134/2025/QH15, Điều 999", "Luật 134/2025/QH15, Điều 9, khoản 1, điểm z", "không rõ"]:
        row = build_gold([{**base, "expected_sources": [source]}], parents, corpus)[0]
        assert row["gold_status"] == "unresolved" and row["notes"]
    assert build_gold([{**base, "in_corpus": "khong"}], parents, corpus)[0]["gold_parents"]
    assert build_gold([{**base, "expected_behavior": "tu_choi"}], parents, corpus) == []
    with pytest.raises(ValueError):
        build_gold([base], parents, corpus, [{**override, "gold_parents": ["missing"]}])


def test_scenario_is_scored_per_turn(corpus):
    profile = {"role": "nha_cung_cap", "sector": "y_te", "is_public_sector": False,
               "generates_content": None, "product_description": "AI tư vấn"}
    empty = dict.fromkeys(profile)
    row = {"id": "s", "category": "nhieu_luot", "priority": True, "in_corpus": "co",
           "expected_sources": ["Luật 134/2025/QH15, Điều 9, khoản 1"],
           "turns": [{"turn": 1, "user": "giá vàng", "expected_behavior": "tu_choi", "expected_profile": empty, "expected_sources": []},
                     {"turn": 2, "user": "lượt hai", "expected_behavior": "tra_loi", "expected_profile": profile,
                      "expected_sources": ["Luật 134/2025/QH15, Điều 9, khoản 1"]}]}
    parents = [{"parent_id": "134-2025-QH15_dieu-9_khoan-1"}, {"parent_id": "134-2025-QH15_dieu-9_khoan-2"}]
    rows = build_gold([row], parents, corpus)
    assert [r["id"] for r in rows] == ["s.t2"]
    assert rows[0]["question"] == "lượt hai\nnhà cung cấp; y tế; AI tư vấn"
    assert rows[0]["turn_text"] == "lượt hai" and rows[0]["gold_status"] == "auto"
    override = {"id": "s", "gold_status": "ai_reviewed", "notes": "duyệt",
                "turns": {"2": {"gold_parents": ["134-2025-QH15_dieu-9_khoan-2"]}}}
    rows = build_gold([row], parents, corpus, [override])
    assert rows[0]["gold_status"] == "ai_reviewed_scenario" and len(rows[0]["gold_parents"]) == 2
    with pytest.raises(ValueError):
        build_gold([row], parents, corpus, [{**override, "turns": {"9": {}}}])


def test_override_removes_and_marks_secondary(corpus):
    parent = "134-2025-QH15_dieu-9_khoan-1"
    base = {"id": "q", "question": "test", "category": "test", "priority": True, "in_corpus": "co",
            "expected_sources": ["Luật 134/2025/QH15, Điều 9, khoản 1, điểm a"]}
    parents = [{"parent_id": parent}, {"parent_id": "134-2025-QH15_dieu-9"}]
    assert build_gold([base], parents, corpus)[0]["gold_points"] == [parent + "_diem-a"]
    override = {"id": "q", "gold_status": "ai_reviewed", "notes": "duyệt", "remove_parents": [parent],
                "secondary_parents": [parent]}
    row = build_gold([base], parents, corpus, [override])[0]
    assert row["gold_parents"] == [] and row["gold_secondary"] == [parent]
    assert row["gold_articles"] == ["134-2025-QH15_dieu-9"] and row["gold_status"] == "ai_reviewed"
    with pytest.raises(ValueError):
        build_gold([base], parents, corpus, [{**override, "remove_parents": ["134-2025-QH15_dieu-9_khoan-2"]}])
    with pytest.raises(ValueError):
        build_gold([{**base, "expected_behavior": "tu_choi"}], parents, corpus, [override])


def test_block_coverage_and_groups():
    row = {"id": "q", "category": "c", "priority": False, "gold_parents": [], "gold_articles": ["a_dieu-1"],
           "gold_blocks": {"x": ["a_dieu-1"], "y": ["a_dieu-2", "a_dieu-3"], "z": ["a_dieu-4"]}}
    turn = {"id": "s.t1", "scenario_id": "s", "category": "c", "priority": False, "gold_parents": [], "gold_articles": ["a_dieu-1"]}
    hits = [{"parent_id": f"a_dieu-{i}"} for i in (9, 3, 1)]
    scored = evaluate([row, turn], {"q": hits, "s.t1": hits})
    assert scored["questions"]["blocks"]["coverage@5"] == 2 / 3
    assert scored["questions"]["questions"] == 1 and scored["turns"]["questions"] == 1
    assert "blocks" not in scored["turns"]


def test_real_gold_follows_review_decisions():
    root = Path(__file__).resolve().parents[2]
    rows = {r["id"]: r for r in map(json.loads, (root / "eval/retrieval.jsonl").read_text(encoding="utf-8").splitlines())}
    for key in ("gold_parents", "gold_articles", "gold_secondary", "gold_blocks"):
        assert rows["q001"][key] == rows["q002"][key]
    assert rows["q046"]["priority"] and rows["q046"]["gold_parents"] == ["134-2025-QH15_dieu-29_khoan-1", "134-2025-QH15_dieu-29_khoan-5"]
    assert not {"q051", "q052", "q053", "q054", "q055", "s013.t1", "s005"} & set(rows)
    assert "134-2025-QH15_dieu-35_khoan-1" not in rows["q010"]["gold_parents"]
    assert "134-2025-QH15_dieu-14_khoan-1_diem-c" in rows["q028"]["gold_points"]
    assert all(r["gold_status"] == "auto" for i, r in rows.items() if i.startswith(("s011", "s012", "s014")))

def test_exact_circular_and_decision():
    rows = [chunk("tt", article="3", doc="05-2026-TT-BKHCN"),
            chunk("qd", article="4", doc="33-2026-QD-TTg")]
    rows[0].update(document_number="05/2026/TT-BKHCN", document_title="Thông tư Khung đạo đức")
    rows[1].update(document_number="33/2026/QĐ-TTg", document_title="Quyết định Danh mục")
    assert exact_lookup("Điều 3 TT 05", rows)["results"][0]["chunk_id"] == "tt"
    assert exact_lookup("dieu 4 qd 33", rows)["results"][0]["chunk_id"] == "qd"
    assert exact_lookup("Điều 3 Thông tư 05/2026/TT-BKHCN", rows)["results"][0]["chunk_id"] == "tt"


def test_experiments_use_all_configs_and_exact():
    rows = [chunk("match", body="tín dụng")]
    rows += [chunk(str(i), body="giáo dục học sinh") for i in range(5)]
    gold = [{"id": "q", "question": "Điều 9 Luật 134", "category": "tra_cuu_truc_tiep",
             "priority": True, "gold_status": "auto", "gold_parents": [rows[0]["parent_id"]],
             "gold_articles": [rows[0]["article_id"]]}]
    before = deepcopy(gold)
    result = run_experiments(rows, gold)
    assert set(result["runs"]) == {"A", "B", "C", "D", "exact", "best_exact", "best_turn_only"}
    assert result["best_bm25"] in "ABCD"
    assert result["runs"]["exact"]["metrics"]["all"]["parent"]["hit@5"] == 1
    assert gold == before


def test_document_match_is_not_promoted():
    rows = [chunk("a", body="khác"), chunk("z", body="minh bạch")]
    rows += [chunk(str(i), body="giáo dục") for i in range(5)]
    query = "Luật 134 quy định gì về minh bạch?"
    match = exact_lookup(query, rows)
    assert match["match_level"] == "document"
    assert match["results"] and all(h["match_level"] == "document" and h["score"] == 0 for h in match["results"])
    gold = [{"id": "q", "question": query, "category": "tra_cuu_truc_tiep", "priority": True,
             "gold_status": "auto", "gold_parents": [rows[0]["parent_id"]], "gold_articles": []}]
    result = run_experiments(rows, gold)
    best = result["best_bm25"]
    assert result["runs"]["best_exact"]["predictions"] == result["runs"][best]["predictions"]
    rows[0].update(document_id="05-2026-TT-BKHCN", document_number="05/2026/TT-BKHCN")
    assert exact_lookup("Phụ lục II Thông tư 05", rows)["match_level"] == "document"


@pytest.mark.parametrize("query,expected", [
    ("Điều 9 và Điều 10 Luật 134", ["nine", "ten", "wrong-clause"]),
    ("dieu 9 va dieu 10 luat 134", ["nine", "ten", "wrong-clause"]),
    ("khoản 1 Điều 9 và khoản 2 Điều 10 Luật 134", ["nine", "ten"]),
    ("Điều 9 khoản 1 và Điều 10 khoản 2 Luật 134", ["nine", "ten"]),
    ("điểm đ khoản 1 Điều 9 và điểm a khoản 2 Điều 10 Luật 134", ["nine", "ten"]),
    ("Điều 999 và Điều 10 Luật 134", ["ten", "wrong-clause"]),
    ("Điều 999 và Điều 1000 Luật 134", []),
])
def test_multiple_locations(query, expected):
    rows = [chunk("nine", article="9", clause="1", point="đ"),
            chunk("ten", article="10", clause="2", point="a"),
            chunk("wrong-clause", article="10", clause="3"),
            chunk("other-document", article="10", clause="2", doc="142-2026-ND-CP")]
    hits = exact_lookup(query, rows)
    assert [h["chunk_id"] for h in hits["results"]] == expected
    assert hits["match_level"] == "article"


@pytest.mark.parametrize("query,expected", [
    ("Khoản 1, 2 Điều 9 Luật 134", ["a", "b", "d", "dd", "point-b"]),
    ("khoản 1 và 2 Điều 9 Luật 134", ["a", "b", "d", "dd", "point-b"]),
    ("khoan 1 va 2 dieu 9 luat 134", ["a", "b", "d", "dd", "point-b"]),
    ("điểm a, b khoản 1 Điều 9 Luật 134", ["a", "point-b"]),
    ("diem a, b khoan 1 dieu 9 luat 134", ["a", "point-b"]),
    ("Điều 9, khoản 1, 2 Luật 134", ["a", "b", "d", "dd", "point-b"]),
    ("Điều 9, khoản 1, điểm d và đ Luật 134", ["d", "dd"]),
    ("điểm đ và a khoản 1 Điều 9 Luật 134", ["a", "dd"]),
    ("điểm d, b khoản 1 Điều 9 Luật 134", ["d", "point-b"]),
    ("khoản 99, 100 Điều 9 Luật 134", []),
    ("điểm x, z khoản 1 Điều 9 Luật 134", []),
])
def test_grouped_locations(query, expected, corpus):
    rows = corpus + [chunk("point-b", point="b"), chunk("wrong-clause", clause="3")]
    before = deepcopy(rows)
    result = exact_lookup(query, rows)
    assert [h["chunk_id"] for h in result["results"]] == expected
    assert result["match_level"] == "article" and not result["ambiguous"]
    assert rows == before


@pytest.mark.parametrize("query,expected", [
    ("Điều 9 Luật 134 và Điều 8 Nghị định 142", ["law-9-1", "law-9-2", "law-9-3", "nd-8"]),
    ("Luật 134 Điều 9 và Nghị định 142 Điều 8", ["law-9-1", "law-9-2", "law-9-3", "nd-8"]),
    ("Điều 9 và Điều 10 Luật 134", ["law-10", "law-9-1", "law-9-2", "law-9-3"]),
    ("Điều 8 Nghị định 142 và Quyết định 33", ["nd-8"]),
    ("Theo Nghị định 142, Điều 8 và Điều 9", ["nd-8", "nd-9"]),
    ("khoản 1, 2 Điều 9 Luật 134 và Điều 8 Nghị định 142", ["law-9-1", "law-9-2", "nd-8"]),
    ("Luật 134 khoản 1, 2 Điều 9 và Nghị định 142 Điều 8", ["law-9-1", "law-9-2", "nd-8"]),
    ("Điều 8 Nghị định 142 và Điều 10", ["nd-10", "nd-8"]),
    ("Điều 9 Luật 999 và Điều 8 Nghị định 142", ["nd-8"]),
    ("Điều 9 Luật 134/2024/QH15 và Điều 8 Nghị định 142", ["nd-8"]),
    ("Điều 9 134/2025/QH15 và Điều 8 142/2026/NĐ-CP", ["law-9-1", "law-9-2", "law-9-3", "nd-8"]),
    ("Luật AI Điều 9 và Nghị định hướng dẫn Điều 8", ["law-9-1", "law-9-2", "law-9-3", "nd-8"]),
    ("Điều 999 Luật 134 và Điều 1000 Nghị định 142", []),
])
def test_locations_are_scoped_to_documents(query, expected):
    rows = [chunk("law-9-1"), chunk("law-9-2", clause="2"), chunk("law-9-3", clause="3"),
            chunk("law-8", article="8"), chunk("law-10", article="10"),
            chunk("nd-8", article="8", doc="142-2026-ND-CP"),
            chunk("nd-9", article="9", doc="142-2026-ND-CP"),
            chunk("nd-10", article="10", doc="142-2026-ND-CP"),
            chunk("qd-8", article="8", doc="33-2026-QD-TTg")]
    rows[-1].update(document_number="33/2026/QĐ-TTg", document_title="Quyết định Danh mục")
    result = exact_lookup(query, rows)
    assert [h["chunk_id"] for h in result["results"]] == expected
    assert result["match_level"] == "article" and not result["ambiguous"]
    assert all(h["score"] == 1 and h["match_level"] == "article" for h in result["results"])
    assert exact_lookup(query, list(reversed(rows))) == result


def test_parse_grouped_locations_preserves_point_symbols_and_deduplicates():
    assert parse_location("điểm d, đ khoản 1, 2 Điều 9 và điểm đ khoản 2 Điều 9") == [
        {"article": "9", "clause": c, "point": p}
        for c in ("1", "2") for p in ("d", "đ")]


def test_list_item_preserves_article_rank_and_is_scored():
    item = "33_linh-vuc-I_stt-1"
    predictions = {"q": [{"parent_id": item}, {"parent_id": "law_dieu-9_khoan-1"}]}
    row = {"id": "q", "category": "test", "priority": True,
           "gold_status": "manual_ai", "gold_parents": [], "gold_articles": ["law_dieu-9"]}
    measured = evaluate([row], predictions)
    assert measured["all"]["article"]["mrr"] == .5
    five_items = [{"parent_id": f"item-{i}"} for i in range(5)]
    assert metrics(ranked_units(five_items + predictions["q"][1:], "article"), row["gold_articles"])["hit@5"] == 0
    row.update(gold_parents=[item], gold_articles=[])
    measured = evaluate([row], predictions)
    for level in ("parent", "article"):
        assert measured["all"][level]["mrr"] == 1
        assert measured["all"][level]["recall@5"] == 1


def test_partial_gold_keeps_resolved_sources_and_reports_missing(corpus):
    parent = "134-2025-QH15_dieu-9_khoan-1"
    base = {"id": "partial", "question": "test", "category": "test", "priority": True,
            "in_corpus": "co", "expected_sources": ["Luật 134, Điều 9, khoản 1", "Luật 134, Điều 999"]}
    row = build_gold([base], [{"parent_id": parent}], corpus)[0]
    assert row["gold_status"] == "unresolved"
    assert row["gold_parents"] == [parent] and row["unresolved_sources"]
    report = label_summary([row])
    assert report["partially_unresolved_count"] == 1
    assert report["partially_unresolved"][0]["id"] == "partial"
    assert evaluate([row], {"partial": [{"parent_id": parent}]})["all"]["parent"]["recall@5"] == 1


def test_recall_ceiling_per_level():
    rows = [{"id": "a", "gold_parents": [f"law_dieu-1_khoan-{i}" for i in range(10)], "gold_articles": ["law_dieu-1"]},
            {"id": "b", "gold_parents": ["item"], "gold_articles": [f"law_dieu-{i}" for i in range(5)]},
            {"id": "empty", "gold_parents": [], "gold_articles": []}]
    report = label_summary(rows)
    assert report["parent"] == {"labeled_questions": 2, "more_than_5": 1, "recall@5_ceiling": .75}
    assert report["article"]["labeled_questions"] == 2
    assert report["article"]["more_than_5"] == 1
    assert report["article"]["recall@5_ceiling"] == pytest.approx((1 + 5 / 6) / 2)


def test_clause_unit_uses_chunk_position():
    # Chunk Khoản có parent_id là Điều vẫn phải tính cho Khoản đó.
    clause = {"chunk_id": "d_dieu-1_khoan-2", "parent_id": "d_dieu-1"}
    point = {"chunk_id": "d_dieu-1_khoan-2_diem-a", "parent_id": "d_dieu-1_khoan-2"}
    closing = {"chunk_id": "d_dieu-1_khoan-2_cuoi", "parent_id": "d_dieu-1_khoan-2"}
    intro = {"chunk_id": "d_dieu-1_mo-dau", "parent_id": "d_dieu-1"}
    item = {"chunk_id": "d_linh-vuc-I_stt-1", "parent_id": "d_linh-vuc-I_stt-1"}
    assert {clause_unit(h) for h in (clause, point, closing)} == {"d_dieu-1_khoan-2"}
    assert clause_unit(intro) == "d_dieu-1"
    assert clause_unit(item) == "d_linh-vuc-I_stt-1"
    hits = [intro, clause, point, item]
    assert ranked_units(hits, "parent") == ["d_dieu-1", "d_dieu-1_khoan-2", "d_linh-vuc-I_stt-1"]
    assert ranked_units(hits, "article") == ["d_dieu-1", "d_linh-vuc-I_stt-1"]
    assert metrics(ranked_units([clause], "parent"), ["d_dieu-1_khoan-2"])["mrr"] == 1


def test_real_gold_labels_are_reachable():
    # Nhãn không chạm được thì Recall có trần giả dưới 1, phép đo mất nghĩa.
    root = Path(__file__).resolve().parents[2]
    def read(name):
        return [json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines()]
    chunks = read("data/processed/chunks.jsonl")
    hits = [{"chunk_id": c["chunk_id"], "parent_id": c["parent_id"]} for c in chunks]
    gold = read("eval/retrieval.jsonl")
    for level, field in (("parent", "gold_parents"), ("article", "gold_articles")):
        assert {g for row in gold for g in row[field]} <= set(ranked_units(hits, level))
