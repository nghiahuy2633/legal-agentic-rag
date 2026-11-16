"""Độ phủ giả và kiểm tra bảng thật, chưa bắt buộc hoàn tất dữ liệu."""

COVERAGE_ENFORCED = True
CRITERIA_ENFORCED = True
POINT_COVERAGE_ENFORCED = True

import json
from pathlib import Path
import unicodedata

import pytest
import yaml

from legal_rag.knowledge.coverage import candidate_units, candidate_clauses, coverage_report, load_exclusions
from legal_rag.knowledge.obligations import load_obligations, missing_criteria


def chunk(clause, body, suffix="", article="7"):
    base = f"134-2025-QH15_dieu-{article}"
    return dict(chunk_id=f"{base}_khoan-{clause}{suffix}", parent_id=base,
                document_id="134-2025-QH15", article=article, body=body)


def test_candidates_and_coverage():
    chunks = [chunk("1", "PHẢI làm"), chunk("1", "có nghĩa vụ", "_diem-a"),
              chunk("2", unicodedata.normalize("NFD", "có trách nhiệm làm")),
              chunk("3", "nghiêm cấm"), chunk("4", "không được làm"),
              chunk("5", "bênphải"), chunk("6", "phải làm", article="1")]
    ids = [c["chunk_id"] for c in chunks if c["chunk_id"].endswith(tuple("1234"))]
    assert candidate_clauses(chunks) == ids
    rows = [dict(id="ob1", review_status="ai_draft", citations=[dict(chunk_id=chunks[1]["chunk_id"])]),
            dict(id="ob2", review_status="user_rejected", citations=[dict(chunk_id=ids[1])])]
    report = coverage_report(rows, chunks, [dict(clause_id=ids[2], reason="lý do")])
    assert report == dict(candidates=ids, covered=ids[:1], excluded=ids[2:3],
                          missing=[ids[1], ids[3]], rate=0.5)
    overlap = coverage_report(rows, chunks, [dict(clause_id=ids[0], reason="lý do")])
    assert overlap["rate"] == 0.25 and overlap["excluded"] == []
    assert coverage_report([], [], []) == dict(candidates=[], covered=[], excluded=[], missing=[], rate=1.0)


@pytest.mark.parametrize("items", [None, {}, [dict(clause_id="x", reason="")],
    [dict(clause_id="bad", reason="lý do")], [dict(clause_id="x", reason="a")]*2,
    [dict(clause_id="x", reason="a", extra=True)]])
def test_invalid_exclusions(tmp_path, items):
    path = tmp_path / "excluded.yaml"
    path.write_text(yaml.safe_dump(items), encoding="utf-8")
    with pytest.raises(ValueError):
        load_exclusions(path, ["x"])


def test_load_exclusions(tmp_path):
    path = tmp_path / "excluded.yaml"
    path.write_text('- clause_id: x\n  reason: không thuộc nghĩa vụ\n', encoding="utf-8")
    assert load_exclusions(path, ["x"]) == [dict(clause_id="x", reason="không thuộc nghĩa vụ")]


def test_real_coverage_and_criteria():
    root = Path(__file__).resolve().parents[2]
    rows = load_obligations(root / "src/legal_rag/knowledge/obligations.yaml")
    chunks = [json.loads(line) for line in (root / "data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    exclusions = load_exclusions(root / "src/legal_rag/knowledge/coverage_exclusions.yaml", candidate_units(chunks))
    report = coverage_report(rows, chunks, exclusions)
    assert isinstance(report["missing"], list)
    missing = missing_criteria(rows)
    assert isinstance(missing, list)
    if COVERAGE_ENFORCED:
        assert report["missing"] == []
    if CRITERIA_ENFORCED:
        assert missing == []


def test_real_point_coverage():
    root = Path(__file__).resolve().parents[2]
    chunks = [json.loads(line) for line in (root / "data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = load_obligations(root / "src/legal_rag/knowledge/obligations.yaml")
    exclusions = load_exclusions(root / "src/legal_rag/knowledge/coverage_exclusions.yaml", candidate_units(chunks))
    report = coverage_report(rows, chunks, exclusions, level="point")
    assert any("_diem-" in cid for cid in report["candidates"])
    if POINT_COVERAGE_ENFORCED:
        assert report["missing"] == []
