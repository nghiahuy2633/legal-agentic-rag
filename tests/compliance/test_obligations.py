"""Kiểm tra bảng nháp thật và lỗi schema/căn cứ trước khi người dùng soát."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unicodedata

import pytest
import yaml

from legal_rag.knowledge.obligations import (
    GROUPS, REVIEW_STATUSES, RISK_LEVELS, ROLES, load_obligations, validate_citations,
)


ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "src/legal_rag/knowledge/obligations.yaml"


@pytest.fixture
def rows():
    return load_obligations(TABLE)


@pytest.fixture
def chunks():
    return {row["chunk_id"]: row for row in
            map(json.loads, (ROOT / "data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines())}


def test_real_table_schema_and_coverage(rows):
    assert 50 <= len(rows) <= 120
    assert len({row["id"] for row in rows}) == len(rows)
    assert {row["group"] for row in rows} == set(GROUPS)
    assert {row["role"] for row in rows} <= set(ROLES)
    assert {row["risk_level"] for row in rows} <= set(RISK_LEVELS)
    assert {row["review_status"] for row in rows} <= set(REVIEW_STATUSES)
    assert REVIEW_STATUSES == ("ai_draft", "ai_reviewed", "user_reviewed", "user_rejected")


def test_real_table_citations(rows, chunks):
    validate_citations(rows, chunks)


def test_obligations_have_explicit_references(rows):
    for row in rows:
        text = unicodedata.normalize("NFC", row["obligation"]).casefold()
        assert not any(term in text for term in ("điều này", "khoản này", "luật này")), row["id"]


def test_round_two_sources_and_review_notes(rows):
    sources = {c["chunk_id"] for row in rows for c in row["citations"]}
    expected = {
        "134-2025-QH15": {"10": ["2", "4"], "12": ["1"], "13": ["3"], "27": ["2"]},
        "142-2026-ND-CP": {"9": ["1", "2", "3"], "11": ["1", "2", "4", "5"],
                           "15": ["3", "4", "6"], "16": ["1", "2", "3", "4", "6"],
                           "17": ["4"], "18": ["3", "5"], "19": ["3"], "20": ["1", "2", "7"]},
        "33-2026-QD-TTg": {"4": ["1", "2", "3"]},
    }
    for document, articles in expected.items():
        for article, clauses in articles.items():
            for clause in clauses:
                assert f"{document}_dieu-{article}_khoan-{clause}" in sources
    for clause, points in [("1", "abcd"), ("2", "abc")]:
        for point in points:
            assert f"134-2025-QH15_dieu-15_khoan-{clause}_diem-{point}" in sources
    for row in rows:
        ids = {c["chunk_id"] for c in row["citations"]}
        if "142-2026-ND-CP_dieu-11_khoan-5" in ids or "142-2026-ND-CP_dieu-19_khoan-3" in ids:
            assert row["review_note"]
    assert "134-2025-QH15_dieu-27_khoan-2" not in {
        c["chunk_id"] for c in next(r for r in rows if r["id"] == "ob-039")["citations"]}


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", 1), ("role", "khong_ro"), ("role", []),
    ("risk_level", "rat_cao"), ("group", "khac"), ("review_status", "human"),
    ("condition", None), ("obligation", "  "), ("citations", []),
    ("review_note", None), ("review_note", " "), ("review_note", 1),
    ("obligation", "Theo Điều này"), ("obligation", "Theo khoản này"),
    ("obligation", "Theo Luật này"),
    ("citations", {}), ("citations", [{"chunk_id": "x"}]),
    ("citations", [{"chunk_id": "", "quote": "x"}]),
    ("citations", [{"chunk_id": "x", "quote": 2}]),
    ("citations", [{"chunk_id": "x", "quote": " "}]),
])
def test_invalid_fields_report_location(tmp_path, rows, field, value):
    rows[0][field] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=rf"Dòng 1\.{field}"):
        load_obligations(path)


@pytest.mark.parametrize("contents", ["", "{}", "[]", "- chuỗi", "[", "- id: ob-001"])
def test_invalid_top_level_or_yaml(tmp_path, contents):
    path = tmp_path / "invalid.yaml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        load_obligations(path)


def test_duplicate_ids_rejected(tmp_path, rows):
    rows[1]["id"] = rows[0]["id"]
    path = tmp_path / "duplicate.yaml"
    path.write_text(yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="Dòng 2.id: trùng"):
        load_obligations(path)


def test_unknown_field_rejected(tmp_path, rows):
    rows[0]["extra"] = "x"
    path = tmp_path / "extra.yaml"
    path.write_text(yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="Dòng 1: các trường"):
        load_obligations(path)


def test_missing_chunk_rejected(rows, chunks):
    rows[0]["citations"][0]["chunk_id"] = "khong-ton-tai"
    with pytest.raises(ValueError, match="ob-001: chunk_id không tồn tại"):
        validate_citations(rows, chunks)


def test_quote_from_context_is_not_body(rows, chunks):
    rows[0]["citations"][0]["quote"] = chunks[rows[0]["citations"][0]["chunk_id"]]["context"]
    with pytest.raises(ValueError, match="ob-001: quote không thuộc body"):
        validate_citations(rows, chunks)


def test_unicode_and_whitespace_normalization(rows, chunks):
    row = deepcopy(rows[0])
    quote = row["citations"][0]["quote"]
    row["citations"][0]["quote"] = unicodedata.normalize("NFD", quote).replace(" ", "\n\t  ")
    validate_citations([row], chunks)


def review_module():
    spec = importlib.util.spec_from_file_location("make_obligation_review", ROOT / "scripts/make_obligation_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_has_full_sources_and_checkboxes(rows, chunks):
    content = review_module().render_review(rows, chunks)
    for group in GROUPS:
        assert f"## {group}\n" in content
    for row in rows:
        assert f"### {row['id']}\n" in content
        assert row["obligation"] in content
        assert row["role"] in content
        assert row["risk_level"] in content
        for citation in row["citations"]:
            chunk = chunks[citation["chunk_id"]]
            assert chunk["document_number"] in content
            for field, label in (("article", "Điều"), ("clause", "Khoản"), ("point", "Điểm")):
                if chunk[field] is not None:
                    assert f"{label} {chunk[field]}" in content
            assert "\n".join("> " + line for line in chunk["body"].splitlines()) in content
    assert content.count("- [ ] Đã đối chiếu toàn bộ căn cứ") == len(rows)


def test_review_notes_appear_first_once(rows, chunks):
    content = review_module().render_review(rows, chunks)
    first_group = content.index(f"## {GROUPS[0]}\n")
    for row in rows:
        marker = f"### {row['id']}\n"
        assert content.count(marker) == 1
        if "review_note" in row:
            assert content.index(marker) < first_group
            assert row["review_note"] in content
        else:
            assert content.index(marker) > first_group


def test_review_cli_repeated_output_is_identical(tmp_path, rows, chunks, capsys):
    table = tmp_path / "src/legal_rag/knowledge/obligations.yaml"
    table.parent.mkdir(parents=True)
    table.write_bytes(TABLE.read_bytes())
    source = tmp_path / "data/processed/chunks.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks.values()), encoding="utf-8")
    module = review_module()
    assert module.main([], root=tmp_path) == 0
    output = tmp_path / "runs/obligations-review.md"
    first = output.read_bytes()
    assert module.main([], root=tmp_path) == 0
    assert output.read_bytes() == first
    assert first.decode("utf-8") == module.render_review(rows, chunks)


def test_review_rejects_invalid_corpus_before_writing(tmp_path, capsys):
    table = tmp_path / "src/legal_rag/knowledge/obligations.yaml"
    table.parent.mkdir(parents=True)
    table.write_bytes(TABLE.read_bytes())
    source = tmp_path / "data/processed/chunks.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text("", encoding="utf-8")
    assert review_module().main([], root=tmp_path) == 1
    assert "chunk_id không tồn tại" in capsys.readouterr().err
    assert not (tmp_path / "runs/obligations-review.md").exists()
