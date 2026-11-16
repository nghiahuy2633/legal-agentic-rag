"""Quy tắc chunk, parent, dẫn chiếu trên dữ liệu giả và tiêu chí đạt trên file thật."""

import csv
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from legal_rag.ingestion.chunking import (
    MAX_CHARS,
    build_document,
    build_index,
    build_outputs,
    extract_references,
    is_delegation,
    split_text,
)
from legal_rag.ingestion.normalize import apply_corrections
from legal_rag.ingestion.parser import parse_articles


ROOT = Path(__file__).resolve().parents[2]
LAW = dict(document_id="luat", document_number="1/2025/QH15", document_title="Luật Mẫu",
           document_type="luat", effective_from="2026-01-01")
DECREE = dict(document_id="nd", document_number="2/2026/NĐ-CP",
              document_title="Nghị định hướng dẫn thi hành Luật Mẫu",
              document_type="nghi_dinh", effective_from="2026-02-01")
REGISTRY = [LAW, DECREE]


def article(number="1", intro="", clauses=(), **extra):
    return dict(document_id="luat", article=number, title=f"Tiêu đề {number}", chapter="II",
                chapter_title="TÊN CHƯƠNG", section=None, section_title=None, intro=intro,
                clauses=list(clauses), page_start=1, page_end=2, **extra)


def clause(number="1", lead_in="Nội dung.", points=(), page=1):
    return dict(clause=number, lead_in=lead_in, points=list(points), page=page)


def point(number="a", text="Điểm;", page=1):
    return dict(point=number, text=text, page=page)


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def by_id(rows, key="chunk_id"):
    return {row[key]: row for row in rows}


def test_units_levels_ids_and_parents():
    articles = [
        article("1", intro="Toàn bộ nội dung."),
        article("2", intro="Mở đầu:", clauses=[
            clause("1", "Khoản thường."),
            clause("2", "Câu dẫn:", [point("a", "Một;"), point("đ", "Hai.")]),
        ]),
    ]
    chunks, parents, split_count = build_document(LAW, articles)
    assert split_count == 0
    rows = by_id(chunks)
    assert {key: (row["level"], row["parent_id"]) for key, row in rows.items()} == {
        "luat_dieu-1": ("article", "luat_dieu-1"),
        "luat_dieu-2_mo-dau": ("article_intro", "luat_dieu-2"),
        "luat_dieu-2_khoan-1": ("clause", "luat_dieu-2"),
        "luat_dieu-2_khoan-2": ("clause", "luat_dieu-2"),
        "luat_dieu-2_khoan-2_diem-a": ("point", "luat_dieu-2_khoan-2"),
        "luat_dieu-2_khoan-2_diem-đ": ("point", "luat_dieu-2_khoan-2"),
    }
    leaf = rows["luat_dieu-2_khoan-2_diem-a"]
    assert (leaf["article"], leaf["clause"], leaf["point"]) == ("2", "2", "a")
    assert rows["luat_dieu-1"]["clause"] is None and rows["luat_dieu-1"]["point"] is None
    assert leaf["article_id"] == "luat_dieu-2"
    assert leaf["document_number"] == "1/2025/QH15" and leaf["effective_from"] == "2026-01-01"
    assert leaf["body"] == "Một;"
    assert leaf["context"].split("\n") == [
        "Luật Mẫu (số 1/2025/QH15)", "Chương II. TÊN CHƯƠNG", "Điều 2. Tiêu đề 2",
        "Mở đầu:", "Khoản 2: Câu dẫn:",
    ]
    assert leaf["index_text"] == leaf["context"] + "\n\nĐiều 2, Khoản 2, Điểm a: Một;"
    # Không lặp nội dung của chính chunk vào context.
    assert "Mở đầu:" not in rows["luat_dieu-2_mo-dau"]["context"]
    assert "Toàn bộ nội dung." not in rows["luat_dieu-1"]["context"]

    parent = by_id(parents, "parent_id")
    assert parent["luat_dieu-2_khoan-2"]["text"] == "2. Câu dẫn:\na) Một;\nđ) Hai."
    assert parent["luat_dieu-2_khoan-2"]["chunk_ids"] == [
        "luat_dieu-2_khoan-2", "luat_dieu-2_khoan-2_diem-a", "luat_dieu-2_khoan-2_diem-đ"]
    assert "Khoản 2:" not in parent["luat_dieu-2_khoan-2"]["context"]
    assert parent["luat_dieu-2"]["text"].startswith("Mở đầu:\n1. Khoản thường.\n2. Câu dẫn:\na) Một;")
    assert parent["luat_dieu-2"]["level"] == "article" and parent["luat_dieu-2"]["clause"] is None
    assert parent["luat_dieu-2"]["chunk_ids"] == [key for key in rows if key.startswith("luat_dieu-2")]
    assert parent["luat_dieu-1"]["chunk_ids"] == ["luat_dieu-1"]


def test_section_line_and_empty_chapter():
    item = article("1", intro="X.")
    item.update(chapter=None, chapter_title=None, section="2", section_title="Tên mục")
    context = build_document(LAW, [item])[0][0]["context"]
    assert context.split("\n") == ["Luật Mẫu (số 1/2025/QH15)", "Mục 2. Tên mục", "Điều 1. Tiêu đề 1"]


def test_article_without_content_is_an_error():
    with pytest.raises(ValueError, match="không có nội dung"):
        build_document(LAW, [article("1")])


def test_clause_pages_cover_until_next_clause():
    item = article("1", clauses=[clause("1", page=1), clause("2", page=2)])
    item["page_end"] = 3
    parents = by_id(build_document(LAW, [item])[1], "parent_id")
    assert parents["luat_dieu-1"]["pages"] == [1, 2, 3]
    assert parents["luat_dieu-1_khoan-1"]["pages"] == [1, 2]
    assert parents["luat_dieu-1_khoan-2"]["pages"] == [2, 3]


def test_split_only_above_limit_and_rejoins_exactly():
    short = "Câu một. Câu hai."
    assert split_text(short, max_chars=len(short)) == [short]
    text = "Câu một dài. Câu hai dài. Câu ba  có hai dấu cách. Câu bốn dài."
    parts = split_text(text, max_chars=30)
    assert len(parts) > 1 and all(len(part) <= 30 for part in parts)
    assert " ".join(parts) == text


def test_split_long_sentence_by_words():
    text = " ".join(["từ"] * 40) + "."
    parts = split_text(text, max_chars=20)
    assert all(len(part) <= 20 for part in parts) and " ".join(parts) == text


def test_split_overlap_repeats_sentences_within_limit():
    text = "Câu một. Câu hai. Câu ba. Câu bốn."
    assert split_text(text, max_chars=18, overlap_sentences=1) == [
        "Câu một. Câu hai.", "Câu hai. Câu ba.", "Câu ba. Câu bốn."]
    assert split_text(text, max_chars=18) == ["Câu một. Câu hai.", "Câu ba. Câu bốn."]


def test_split_rejects_bad_input():
    with pytest.raises(ValueError):
        split_text("a b", overlap_sentences=-1)
    with pytest.raises(ValueError):
        split_text("x" * 10, max_chars=5)


def test_long_unit_gets_part_ids_and_counts_once():
    body = " ".join(f"Câu số {i}." for i in range(800))
    assert len(body) > MAX_CHARS
    chunks, parents, split_count = build_document(LAW, [article("1", clauses=[clause("1", body)])])
    assert split_count == 1
    assert [row["chunk_id"] for row in chunks][:2] == ["luat_dieu-1_khoan-1", "luat_dieu-1_khoan-1_phan-2"]
    assert " ".join(row["body"] for row in chunks) == body
    assert all(len(row["body"]) <= MAX_CHARS for row in chunks)
    assert "(phần 2)" in chunks[1]["index_text"]
    assert by_id(parents, "parent_id")["luat_dieu-1_khoan-1"]["chunk_ids"] == [row["chunk_id"] for row in chunks]


@pytest.mark.parametrize("text", [
    "Chính phủ quy định chi tiết Điều này.",
    "Chính phủ quy định chi tiết về nội dung, trình tự, thủ tục.",
    "Thủ tướng Chính phủ quy định chi tiết khoản 2 Điều này.",
    "Bộ trưởng Bộ Khoa học và Công nghệ quy định chi tiết Điều này.",
    "Bộ Công an hướng dẫn chi tiết khoản này.",
    "Chính phủ quy định chi tiết Điều này. Bộ Tài chính hướng dẫn chi tiết khoản 1.",
])
def test_delegation_positive(text):
    assert is_delegation(text)


@pytest.mark.parametrize("text", [
    "Nghị định này quy định chi tiết một số điều của Luật:",
    "Nhà cung cấp phải báo cáo. Chính phủ quy định chi tiết Điều này.",
    "Chính phủ quy định chi tiết Điều này; nhà cung cấp phải báo cáo.",
    "Chính phủ thống nhất quản lý nhà nước.",
    "Nhiệm vụ khác do Chính phủ quy định.",
    "Thủ tướng Chính phủ quy định Danh mục.",
    "",
])
def test_delegation_negative(text):
    assert not is_delegation(text)


def references(body, document=LAW, target_clause="2", target_point=None, articles=None):
    index = build_index(articles or {
        "luat": [article("1", clauses=[clause("1"), clause("2", points=[point("a"), point("b")])]),
                 article("5", clauses=[clause("1")])],
        "nd": [article("1", clauses=[clause("1"), clause("2")])],
    })
    chunk = dict(chunk_id="src", document_id=document["document_id"], article="1", clause=target_clause,
                 point=target_point, body=body)
    return [(row["raw_text"], row["target_document_id"], row["target_article"], row["target_clause"],
             row["target_point"], row["resolved"])
            for row in extract_references(chunk, REGISTRY, index)]


def test_reference_named_document_from_other_document():
    assert references("theo khoản 1 Điều 5 của Luật Mẫu;", DECREE) == [
        ("khoản 1 Điều 5 của Luật Mẫu", "luat", "5", "1", None, True)]
    assert references("tại điểm b khoản 2 Điều 1 Luật Mẫu.", DECREE) == [
        ("điểm b khoản 2 Điều 1 Luật Mẫu", "luat", "1", "2", "b", True)]


def test_reference_longest_title_wins():
    rows = references("Theo Nghị định hướng dẫn thi hành Luật Mẫu.", LAW)
    assert rows == [("Nghị định hướng dẫn thi hành Luật Mẫu", "nd", None, None, None, True)]


def test_reference_self_forms_resolve_from_source():
    assert references("tại Điều này") == [("Điều này", "luat", "1", None, None, True)]
    assert references("tại khoản 1 Điều này") == [("khoản 1 Điều này", "luat", "1", "1", None, True)]
    assert references("tại khoản này") == [("khoản này", "luat", "1", "2", None, True)]
    assert references("tại điểm a khoản này") == [("điểm a khoản này", "luat", "1", "2", "a", True)]
    assert references("Luật này quy định") == [("Luật này", "luat", None, None, None, True)]
    assert references("Nghị định này quy định", DECREE) == [("Nghị định này", "nd", None, None, None, True)]
    assert references("Điều 5 của Luật này") == [("Điều 5 của Luật này", "luat", "5", None, None, True)]


def test_reference_registry_number():
    assert references("theo Nghị định số 2/2026/NĐ-CP.") == [
        ("Nghị định số 2/2026/NĐ-CP", "nd", None, None, None, True)]
    assert references("Điều 1 của Luật Mẫu số 1/2025/QH15;", DECREE) == [
        ("Điều 1 của Luật Mẫu số 1/2025/QH15", "luat", "1", None, None, True)]


def test_reference_lists_inherit_position_and_document():
    assert [row[1:] for row in references("điểm a và điểm b khoản này")] == [
        ("luat", "1", "2", "a", True), ("luat", "1", "2", "b", True)]
    assert [row[1:] for row in references("khoản 1 và khoản 2 Điều 1 Luật Mẫu", DECREE)] == [
        ("luat", "1", "1", None, True), ("luat", "1", "2", None, True)]
    assert [row[1:] for row in references("khoản 1, 2 và 3 Điều này")] == [
        ("luat", "1", "1", None, True), ("luat", "1", "2", None, True), ("luat", "1", "3", None, False)]
    assert [row[1:] for row in references("Điều 1 và Điều 5 của Luật Mẫu", DECREE)] == [
        ("luat", "1", None, None, True), ("luat", "5", None, None, True)]


def test_reference_outside_corpus_is_unresolved_even_in_list():
    rows = references("Bãi bỏ khoản 1 Điều 5, điểm a khoản 2 Điều 1 và Chương IV của Luật Khác số.")
    assert [row[1:] for row in rows] == [
        (None, "5", "1", None, False), (None, "1", "2", "a", False), (None, None, None, None, False)]
    assert references("theo Điều 1 của Luật Khoa học, công nghệ.") == [
        ("Điều 1 của Luật Khoa học, công nghệ", None, "1", None, None, False)]
    assert references("theo Nghị định số 9/2020/NĐ-CP.") == [
        ("Nghị định số 9/2020/NĐ-CP", None, None, None, None, False)]


def test_reference_without_document_is_not_guessed():
    assert references("Khoản 1 Điều 5 về nội dung") == [("Khoản 1 Điều 5", None, "5", "1", None, False)]
    assert references("tại Điều 1") == [("Điều 1", None, "1", None, None, False)]
    assert references("tại khoản 1 của Luật này") == [("khoản 1 của Luật này", "luat", None, "1", None, False)]
    assert references("Luật này", DECREE) == [("Luật này", None, None, None, None, False)]


def test_reference_to_missing_position_is_unresolved():
    assert references("Điều 99 của Luật này") == [("Điều 99 của Luật này", "luat", "99", None, None, False)]
    assert references("khoản 9 Điều này") == [("khoản 9 Điều này", "luat", "1", "9", None, False)]
    assert references("điểm z khoản 2 Điều này") == [("điểm z khoản 2 Điều này", "luat", "1", "2", "z", False)]


def test_self_clause_needs_a_source_clause():
    assert references("tại khoản này", target_clause=None)[0][-1] is False


def test_reference_ignores_ordinary_words():
    body = "Tại thời điểm xác nhận; đặc điểm yếu; khoản tiền bồi thường; điều này; Điều kiện; pháp luật này."
    assert references(body) == []


def test_document_in_registry_without_articles_is_unresolved():
    rows = references("Điều 1 của Nghị định số 2/2026/NĐ-CP", articles={"luat": [article("1", intro="X.")]})
    assert rows == [("Điều 1 của Nghị định số 2/2026/NĐ-CP", "nd", "1", None, None, False)]


def test_build_outputs_uses_registry_order_and_rejects_duplicates():
    decree_articles = [dict(article("1", intro="Nghị định này."), document_id="nd")]
    result = build_outputs(REGISTRY, {"nd": decree_articles, "luat": [article("1", intro="Luật này.")]})
    assert [row["chunk_id"] for row in result["chunks"]] == ["luat_dieu-1", "nd_dieu-1"]
    assert [row["source_chunk_id"] for row in result["references"]] == ["luat_dieu-1", "nd_dieu-1"]
    with pytest.raises(ValueError, match="Trùng"):
        build_outputs(REGISTRY, {"luat": [article("1", intro="A."), article("1", intro="B.")]})


def write_project(root, documents=("134-2025-QH15", "05-2026-TT-BKHCN")):
    (root / "data/source_registry").mkdir(parents=True)
    shutil.copy(ROOT / "data/source_registry/documents.csv", root / "data/source_registry/documents.csv")
    (root / "data/processed/articles").mkdir(parents=True)
    (root / "data/processed/text").mkdir(parents=True)
    for document in documents:
        shutil.copy(ROOT / f"data/processed/text/{document}.jsonl",
                    root / f"data/processed/text/{document}.jsonl")
    shutil.copy(ROOT / "data/processed/text_corrections.csv", root / "data/processed/text_corrections.csv")


def test_cli_parse_many_documents_all_or_nothing(tmp_path, capsys):
    parse = load_script("parse_articles")
    write_project(tmp_path)
    (tmp_path / "data/processed/text/hong.jsonl").write_text(
        json.dumps(dict(document_id="hong", page=1, text="Điều 2. Sai số")) + "\n", encoding="utf-8")
    folder = tmp_path / "data/processed/articles"
    assert parse.main(["--document", "134-2025-QH15", "--document", "hong"], tmp_path) == 1
    assert "hong" in capsys.readouterr().err
    assert list(folder.iterdir()) == []
    assert parse.main(["--document", "134-2025-QH15", "--document", "05-2026-TT-BKHCN"], tmp_path) == 0
    assert sorted(path.name for path in folder.iterdir()) == ["05-2026-TT-BKHCN.appendices.jsonl", "05-2026-TT-BKHCN.jsonl", "134-2025-QH15.jsonl"]


def test_cli_build_skips_missing_stable_bytes_and_no_temp(tmp_path, capsys):
    parse = load_script("parse_articles")
    build = load_script("build_chunks")
    write_project(tmp_path)
    assert build.main([], tmp_path) == 1
    assert parse.main(["--document", "134-2025-QH15", "--document", "05-2026-TT-BKHCN"], tmp_path) == 0
    assert build.main([], tmp_path) == 0
    output = capsys.readouterr().out
    assert "Bỏ qua 142-2026-ND-CP" in output and "Bỏ qua 33-2026-QD-TTg" in output
    folder = tmp_path / "data/processed"
    names = ["chunks.jsonl", "parents.jsonl", "references.jsonl"]
    first = {name: (folder / name).read_bytes() for name in names}
    assert all(first.values()) and all(b"\r" not in data for data in first.values())
    assert build.main([], tmp_path) == 0
    assert {name: (folder / name).read_bytes() for name in names} == first
    assert not list(folder.glob("*.tmp"))


def test_cli_build_failure_keeps_old_outputs(tmp_path):
    build = load_script("build_chunks")
    write_project(tmp_path)
    folder = tmp_path / "data/processed"
    (folder / "chunks.jsonl").write_text("cũ\n", encoding="utf-8")
    (folder / "articles/134-2025-QH15.jsonl").write_text(
        json.dumps(article("1")) + "\n", encoding="utf-8")
    assert build.main([], tmp_path) == 1
    assert (folder / "chunks.jsonl").read_text(encoding="utf-8") == "cũ\n"
    assert not list(folder.glob("*.tmp"))


# Tiêu chí đạt trên file thật.

def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


REAL_DOCUMENTS = {"134-2025-QH15": 35, "142-2026-ND-CP": 46, "05-2026-TT-BKHCN": 5, "33-2026-QD-TTg": 4}


@pytest.fixture(scope="module")
def real():
    with (ROOT / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as source:
        documents = list(csv.DictReader(source))
    articles = {key: read_jsonl(ROOT / f"data/processed/articles/{key}.jsonl") for key in REAL_DOCUMENTS}
    return dict(
        documents=documents, articles=articles,
        chunks=read_jsonl(ROOT / "data/processed/chunks.jsonl"),
        parents=read_jsonl(ROOT / "data/processed/parents.jsonl"),
        references=read_jsonl(ROOT / "data/processed/references.jsonl"),
    )


def test_real_outputs_match_code(real):
    result = build_outputs(real["documents"], real["articles"],
                           supplements={"05-2026-TT-BKHCN": read_jsonl(ROOT / "data/processed/articles/05-2026-TT-BKHCN.appendices.jsonl")},
                           high_risk_items=read_jsonl(ROOT / "data/processed/high_risk_list.jsonl"))
    assert result["chunks"] == real["chunks"]
    assert result["parents"] == real["parents"]
    assert result["references"] == real["references"]
    assert result["split_count"] == 0


def test_real_articles_match_text(real):
    for key, articles in real["articles"].items():
        pages = read_jsonl(ROOT / f"data/processed/text/{key}.jsonl")
        pages = apply_corrections(pages, ROOT / "data/processed/text_corrections.csv")
        assert parse_articles(pages) == articles


def test_real_article_counts_and_unique_ids(real):
    for key, count in REAL_DOCUMENTS.items():
        assert [item["article"] for item in real["articles"][key]] == [str(i) for i in range(1, count + 1)]
        assert sum(row["document_id"] == key and row["level"] == "article" for row in real["parents"]) == count
    for rows, name in ((real["chunks"], "chunk_id"), (real["parents"], "parent_id")):
        values = [row[name] for row in rows]
        assert len(values) == len(set(values))


def test_real_thong_tu_uses_points_without_d_stroke(real):
    letters = [item["point"] for item in real["articles"]["05-2026-TT-BKHCN"][2]["clauses"][0]["points"]]
    assert letters == list("abcde")


def test_real_context_has_title_and_lead_in(real):
    chunks = by_id(real["chunks"])
    for key, articles in real["articles"].items():
        for item in articles:
            heading = f"Điều {item['article']}. {item['title']}"
            for chunk in real["chunks"]:
                if chunk["article_id"] == f"{key}_dieu-{item['article']}":
                    assert heading in chunk["context"].split("\n")
            for section in item["clauses"]:
                for leaf in section["points"]:
                    chunk = chunks[f"{key}_dieu-{item['article']}_khoan-{section['clause']}_diem-{leaf['point']}"]
                    assert f"Khoản {section['clause']}: {section['lead_in']}" in chunk["context"].split("\n")
                    assert chunk["level"] == "point"


def test_real_bodies_rebuild_every_clause_and_cover_every_position(real):
    chunks = by_id(real["chunks"])
    expected_ids = set()
    for key, articles in real["articles"].items():
        for item in articles:
            article_id = f"{key}_dieu-{item['article']}"
            if not item["clauses"]:
                expected_ids.add(article_id)
                assert chunks[article_id]["body"] == item["intro"]
            elif item["intro"]:
                expected_ids.add(f"{article_id}_mo-dau")
                assert chunks[f"{article_id}_mo-dau"]["body"] == item["intro"]
            for section in item["clauses"]:
                clause_id = f"{article_id}_khoan-{section['clause']}"
                ids = [clause_id] + [f"{clause_id}_diem-{leaf['point']}" for leaf in section["points"]]
                if section.get("closing"):
                    ids.append(f"{clause_id}_cuoi")
                expected_ids.update(ids)
                rebuilt = " ".join(chunks[value]["body"] for value in ids)
                assert rebuilt == " ".join([section["lead_in"]] + [leaf["text"] for leaf in section["points"]] + ([section["closing"]] if section.get("closing") else []))
    assert {key for key, row in chunks.items() if row["article_id"] is not None} == expected_ids


def test_real_every_parent_exists_and_lists_chunks(real):
    parents = by_id(real["parents"], "parent_id")
    chunks = by_id(real["chunks"])
    for chunk in real["chunks"]:
        assert chunk["parent_id"] in parents
        if chunk["article_id"] is None:
            continue
        assert chunk["article_id"] in parents
        assert chunk["chunk_id"] in parents[chunk["article_id"]]["chunk_ids"]
        assert chunk["index_text"].startswith(chunk["context"] + "\n\n")
        assert chunk["index_text"].endswith(chunk["body"])
    for parent in real["parents"]:
        assert parent["chunk_ids"] and all(value in chunks for value in parent["chunk_ids"])
        assert parent["pages"] == sorted(parent["pages"]) and parent["pages"]


def test_real_parent_of_risk_clause(real):
    parent = by_id(real["parents"], "parent_id")["134-2025-QH15_dieu-9_khoan-1"]
    lines = parent["text"].split("\n")
    assert lines[0] == "1. Hệ thống trí tuệ nhân tạo được phân loại theo các mức độ rủi ro sau đây:"
    assert [line[:2] for line in lines[1:]] == ["a)", "b)", "c)"]
    assert "rủi ro cao" in lines[1] and "rủi ro trung bình" in lines[2] and "rủi ro thấp" in lines[3]


def test_real_delegates(real):
    chunks = by_id(real["chunks"])
    chunk = chunks["134-2025-QH15_dieu-9_khoan-3"]
    assert chunk["body"] == "Chính phủ quy định chi tiết Điều này." and chunk["delegates"] is True
    assert chunks["134-2025-QH15_dieu-9_khoan-2"]["delegates"] is False
    article_seven = [row for row in real["chunks"] if row["article_id"] == "134-2025-QH15_dieu-7"]
    assert article_seven
    assert all(row["delegates"] for row in article_seven if "Chính phủ quy định chi tiết" in row["body"])


def test_real_reference_from_decree_to_law(real):
    assert any(row["source_chunk_id"].startswith("142-2026-ND-CP_") and row["resolved"]
               and row["raw_text"] == "khoản 4 Điều 13 của Luật Trí tuệ nhân tạo"
               and row["target_document_id"] == "134-2025-QH15"
               and (row["target_article"], row["target_clause"], row["target_point"]) == ("13", "4", None)
               for row in real["references"])


def test_real_references_are_verbatim_and_point_to_real_positions(real):
    chunks = by_id(real["chunks"])
    index = build_index(real["articles"])
    for row in real["references"]:
        assert row["raw_text"] in chunks[row["source_chunk_id"]]["body"]
        if not row["resolved"]:
            continue
        known = index[row["target_document_id"]]
        if row["target_article"] is not None:
            assert row["target_article"] in known
        if row["target_clause"] is not None:
            assert row["target_clause"] in known[row["target_article"]]
        if row["target_point"] is not None:
            assert row["target_point"] in known[row["target_article"]][row["target_clause"]]


def test_real_repealed_law_list_does_not_resolve_to_source(real):
    rows = [row for row in real["references"] if row["source_chunk_id"] == "134-2025-QH15_dieu-33"]
    assert len(rows) == 5 and not any(row["resolved"] or row["target_document_id"] for row in rows)
