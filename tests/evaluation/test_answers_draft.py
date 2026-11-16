"""T27: kiểm nhãn thật và nguồn nguyên văn, không gọi LLM hoặc tải model."""

import copy
import importlib.util
import json
from pathlib import Path
import unicodedata

import pytest

from legal_rag.evaluation.answers import load_answers, normalize_quote


ROOT = Path(__file__).resolve().parents[2]


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_real_answers_selection_schema_and_quotes():
    questions = [q for q in read_rows(ROOT / "eval/questions.jsonl")
                 if q.get("priority") is True and q["expected_behavior"] != "tu_choi"]
    gold = {r["id"]: r for r in read_rows(ROOT / "eval/retrieval.jsonl")}
    parents = {p["parent_id"]: p for p in read_rows(ROOT / "data/processed/parents.jsonl")}
    rows = load_answers(ROOT / "eval/answers.jsonl")
    assert len(rows) == len(questions) == 29
    assert [r["id"] for r in rows] == [q["id"] for q in questions]
    for row, question in zip(rows, questions):
        assert row["question"] == question["question"]
        assert row["expected_behavior"] == question["expected_behavior"]
        assert row["review_status"] == "user_reviewed"
        assert row["gold_parents"] == gold[row["id"]]["gold_parents"]
        assert 1 <= len(row["required_points"]) <= 8
        assert "pháp luật không quy định" not in row["reference_answer"].lower()
        assert "pháp luật không quy định" not in " ".join(row["required_points"]).lower()
        assert sorted(s["point"] for s in row["point_sources"]) == sorted(row["required_points"])
        for source in row["point_sources"]:
            # So khớp độc lập với helper của loader để tránh kiểm tra tự lặp.
            if source["parent_id"] is None:
                assert source["quote"] is None
                assert source["absence_reason"].strip()
                assert "Điều" in source["absence_reason"]
            else:
                quote = " ".join(unicodedata.normalize("NFC", source["quote"]).split())
                text = " ".join(unicodedata.normalize(
                    "NFC", parents[source["parent_id"]]["text"]).split())
                assert quote and quote in text
        # Phát hiện mất Unicode qua pipe PowerShell: câu hỏi là trường sao chép,
        # các trường soạn mới phải còn tiếng Việt có dấu.
        assert any(ord(c) > 127 for c in row["reference_answer"])


def fixture_files(tmp_path):
    parent = dict(parent_id="p", text="Một căn cứ pháp lý.")
    row = dict(id="draft-1", question="Hỏi", reference_answer="Đáp",
               required_points=["Một ý"], gold_parents=["p"], expected_behavior="tra_loi",
               review_status="ai_draft", point_sources=[dict(
                   point="Một ý", parent_id="p", quote="Một căn cứ")])
    parents_path = tmp_path / "parents.jsonl"
    parents_path.write_text(json.dumps(parent, ensure_ascii=False) + "\n", encoding="utf-8")
    return row, tmp_path / "answers.jsonl", parents_path


def write_row(path, row):
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.mark.parametrize("case", ["quote", "extra_point", "duplicate_point", "missing_point",
    "missing_reason", "empty_reason", "partial_null", "missing_field", "unknown_parent",
    "bad_type", "bad_point_type", "empty_quote", "bad_note"])
def test_invalid_point_sources_include_id(tmp_path, case):
    row, path, parents = fixture_files(tmp_path)
    source = row["point_sources"][0]
    if case == "quote":
        source["quote"] = "Không nằm trong parent"
    elif case == "extra_point":
        row["point_sources"].append(dict(source, point="Ý thừa"))
    elif case == "duplicate_point":
        row["required_points"].append("Ý thứ hai")
        row["point_sources"].append(copy.deepcopy(source))
    elif case == "missing_point":
        row["point_sources"] = []
    elif case in ("missing_reason", "empty_reason"):
        source.update(parent_id=None, quote=None)
        if case == "empty_reason":
            source["absence_reason"] = "  "
    elif case == "partial_null":
        source.update(parent_id=None, absence_reason="Đã tìm Điều 1")
    elif case == "missing_field":
        del source["quote"]
    elif case == "unknown_parent":
        source["parent_id"] = "missing"
    elif case == "bad_type":
        row["point_sources"] = {}
    elif case == "bad_point_type":
        source["point"] = []
    elif case == "empty_quote":
        source["quote"] = "  "
    elif case == "bad_note":
        row["review_note"] = []
    write_row(path, row)
    with pytest.raises(ValueError, match="id=draft-1.*(point_sources|review_note)"):
        load_answers(path, parents)


def test_optional_sources_legacy_null_and_normalization(tmp_path):
    row, path, parents = fixture_files(tmp_path)
    row["point_sources"][0]["quote"] = unicodedata.normalize("NFD", "Một\n căn\t cứ")
    row["review_note"] = "Cần người soát"
    write_row(path, row)
    assert load_answers(path, parents) == [row]
    assert normalize_quote("Một\n căn\t cứ") == "Một căn cứ"
    row["point_sources"][0].update(parent_id=None, quote=None, absence_reason="Đã tìm Điều 1")
    write_row(path, row)
    assert load_answers(path, parents) == [row]
    del row["point_sources"]
    del row["review_note"]
    write_row(path, row)
    assert load_answers(path, parents) == [row]


def test_review_deterministic_and_notes_first(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("make_answers_review", ROOT / "scripts/make_answers_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "answers-review.md"
    args = ["--output", str(output)]
    assert module.main(args) == 0
    content = output.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in content
    assert module.main(args) == 0
    assert output.read_bytes() == content
    text = content.decode("utf-8")
    rows = load_answers(ROOT / "eval/answers.jsonl")
    ordered = sorted(rows, key=lambda r: not bool(r.get("review_note")))
    headings = [line for line in text.splitlines() if line.startswith("## q")]
    assert headings == [f"## {row['id']}" for row in ordered]
    assert "Điều 11 — Khoản 1" in text
    assert "134/2025/QH15" in text
    assert "Phạm vi đã tìm" in text
    assert text.count("- [ ] Duyệt toàn câu") == len(rows)
    for row in rows:
        assert row["question"] in text and row["reference_answer"] in text
        for source in row["point_sources"]:
            if source["quote"] is not None:
                assert "\n".join("> " + line for line in source["quote"].splitlines()) in text
            else:
                assert source["absence_reason"] in text

