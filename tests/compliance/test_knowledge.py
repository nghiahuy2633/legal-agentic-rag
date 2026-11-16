"""Bảng nghĩa vụ: điều kiện áp dụng và toán tử."""

from copy import deepcopy
import json
import pytest
import yaml
from legal_rag.knowledge.facts import FACT_FIELDS, empty_facts, validate_facts
from legal_rag.knowledge.conditions import validate_condition, evaluate, missing_facts, describe
from legal_rag.knowledge.obligations import load_obligations, missing_criteria
from legal_rag.knowledge.select import select_obligations
from test_obligations import TABLE, review_module
from pathlib import Path
from legal_rag.knowledge import high_risk as hr
from test_answer import DECISIONS, ITEM_ID, context_answer_content_fixes as context, render, section
from test_high_risk import ITEMS, PARENTS, ROBOT, response


def atom(name="generates_content", op="is_true", **kwargs):
    return dict(fact=name, op=op, **kwargs)


def test_facts_defaults_and_empty_lists():
    clean, errors = validate_facts({"roles": [], "sectors": ["y_te", "y_te", "khac"]})
    assert not errors
    assert clean["roles"] == [] and clean["content_types"] is None
    assert clean["sectors"] == ["y_te", "khac"]
    assert empty_facts() == dict.fromkeys(FACT_FIELDS)


@pytest.mark.parametrize("name,value", [("roles", "nha_cung_cap"), ("roles", ["khac"]),
    ("roles", [[]]), ("is_public_sector", 1), ("risk_level", []),
    ("sectors", ["unknown"]), ("operation_start_date", "2026-02-30"),
    ("operation_start_date", "2026-1-01"), ("content_types", [None])])
def test_invalid_facts(name, value):
    clean, errors = validate_facts({name: value, "unknown": True})
    assert clean[name] is None and len(errors) == 2 and "unknown" not in clean


@pytest.mark.parametrize("expr,actual,expected", [
    (atom(op="is_true"), True, True), (atom(op="is_true"), False, False),
    (atom(op="is_false"), False, True), (atom(op="is_false"), True, False),
    (atom(op="eq", value=False), False, True), (atom(op="ne", value=True), True, False),
    (atom(op="in", value=[True]), False, False),
    (atom("roles", "contains", value="nha_cung_cap"), [], False),
    (atom("roles", "contains", value="nha_cung_cap"), ["nha_cung_cap"], True),
    (atom("roles", "overlaps", value=["nha_cung_cap"]), [], False),
    (atom("roles", "overlaps", value=["nha_cung_cap"]), ["nha_cung_cap"], True),
    (atom("roles", "eq", value=[]), [], True),
    (atom("roles", "in", value=[[], ["nha_cung_cap"]]), [], True),
    *[(atom("operation_start_date", op, value="luat_134"), "2026-03-01", result)
      for op, result in [("lt", False), ("lte", True), ("gt", False), ("gte", True)]],
    (atom("operation_start_date", "lt", value="2026-05-01"), "2026-03-01", True),
    (atom("risk_level", "in", value=["cao"]), "cao", True),
])
def test_operators_and_unknown(expr, actual, expected):
    assert evaluate(expr, {expr["fact"]: actual}) is expected
    assert evaluate(expr, {}) is None
    assert missing_facts(expr, {}) == [expr["fact"]]
    assert describe(expr)


@pytest.mark.parametrize("left", [True, False, None])
@pytest.mark.parametrize("right", [True, False, None])
def test_nested_three_valued(left, right):
    a, b = atom(), atom("public_distribution")
    facts = dict(generates_content=left, public_distribution=right)
    conjunction = False if False in (left, right) else None if None in (left, right) else True
    disjunction = True if True in (left, right) else None if None in (left, right) else False
    assert evaluate({"all": [a, b]}, facts) is conjunction
    assert evaluate({"any": [a, b]}, facts) is disjunction
    assert evaluate({"not": {"all": [a, {"not": {"not": b}}]}}, facts) is (
        None if conjunction is None else not conjunction)


def test_missing_decisive_branches():
    a, b = atom(), atom("public_distribution")
    assert missing_facts({"all": [a, b]}, {"generates_content": False}) == []
    assert missing_facts({"any": [a, b]}, {"generates_content": True}) == []
    assert missing_facts({"all": [a, {"not": b}, a]}, {}) == ["generates_content", "public_distribution"]
    assert evaluate(None, {}) is True
    assert evaluate({"all": []}, {}) is True
    assert evaluate({"any": []}, {}) is False
    assert describe(atom("operation_start_date", "lt", value="luat_134")) == (
        "ngày đưa vào hoạt động trước 01/03/2026 (Luật 134 có hiệu lực)")


@pytest.mark.parametrize("expr", [[], {}, {"fact": "unknown", "op": "eq", "value": 1},
    atom("roles", "is_true"), atom("risk_level", "eq", value="unknown"),
    atom(op="is_true", value=True), atom(op="eq"), atom(op="lt", value="2026-01-01"),
    atom("roles", "overlaps", value="nha_cung_cap"),
    atom("roles", "contains", value="unknown"), atom("operation_start_date", "gt", value="2026-02-30"),
    {"all": [], "extra": 1}, {"any": True}, {"not": None, "value": 1},
    atom(op="eq", value=True, extra=1), atom(op="in", value=[1])])
def test_invalid_conditions_have_path(expr):
    with pytest.raises(ValueError, match=r"\$\.all\[0\]"):
        validate_condition({"all": [expr]})


def write_rows(tmp_path, rows):
    path = tmp_path / "table.yaml"
    path.write_text(yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")
    return path


def test_old_table_only_adds_kind():
    original = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    assert load_obligations(TABLE) == [{"kind": "nghia_vu", **row} for row in original]


def test_criteria_audit_and_schema(tmp_path):
    row = deepcopy(load_obligations(TABLE)[0])
    for key in ("criteria", "applies_when", "deadline", "review_by", "review_note"):
        row.pop(key, None)
    row.update(review_status="ai_reviewed", kind="nghia_vu")
    assert missing_criteria([row]) == [row["id"]]
    assert load_obligations(write_rows(tmp_path, [row])) == [row]
    row["kind"] = "thong_tin"
    assert missing_criteria([row]) == []
    row.update(kind="cam", criteria=[dict(id="c1", text="Đã kiểm tra", not_met=["Chưa kiểm tra"])],
               applies_when=atom(), deadline="trước khi dùng", review_by="ai")
    assert missing_criteria(load_obligations(write_rows(tmp_path, [row]))) == []


@pytest.mark.parametrize("field,value", [("kind", "x"), ("review_by", "x"), ("deadline", ""),
    ("applies_when", atom("unknown")), ("criteria", None), ("criteria", [dict(id="c0", text="x")]),
    ("criteria", [dict(id="c1", text="x"), dict(id="c1", text="y")]),
    ("criteria", [dict(id="c1", text="")]), ("criteria", [dict(id="c1", text="x", extra=True)]),
    ("criteria", [dict(id="c1", text="x", not_met="x")]),
    ("criteria", [dict(id="c1", text="x", not_met=[None])])])
def test_optional_schema_rejected(tmp_path, field, value):
    row = deepcopy(load_obligations(TABLE)[0])
    row[field] = value
    with pytest.raises(ValueError, match=rf"Dòng 1\.{field}"):
        load_obligations(write_rows(tmp_path, [row]))


def test_accept_review_statuses():
    rows = [dict(id=str(i), review_status=status, role="moi_vai_tro", risk_level="moi_muc")
            for i, status in enumerate(("ai_draft", "ai_reviewed", "user_reviewed", "user_rejected"))]
    assert select_obligations(rows, {}) == dict(selected=[rows[2]], unreviewed_count=2, rejected_count=1)
    assert select_obligations(rows, {}, accept=("user_reviewed", "ai_reviewed")) == dict(
        selected=rows[1:3], unreviewed_count=1, rejected_count=1)


@pytest.mark.parametrize("enabled", [False, True])
def test_graph_passes_accept_flag(enabled):
    from legal_rag.agent.config import AgentConfig
    from legal_rag.agent.graph import run_turn
    from test_map_report import make_case, row
    rows = [row(review_status="ai_reviewed")]
    graph, _, _ = make_case("Nội dung [E1].", rows=rows,
        config=AgentConfig(accept_ai_reviewed=enabled, enable_high_risk=False,
                           enable_rewrite=False, enable_verifier=False))
    result = run_turn(graph, "s", "Nghĩa vụ AI là gì?")
    mapped = result["map_obligations"]
    assert mapped["selected"] == (["A"] if enabled else [])
    assert mapped["unreviewed_count"] == (0 if enabled else 1)
    assert mapped["rejected_count"] == 0


def test_review_knowledge_fields_deterministic():
    from pathlib import Path
    row = deepcopy(load_obligations(TABLE)[0])
    row.update(kind="cam", criteria=[dict(id="c1", text="Tiêu chí", not_met=["Chưa đạt"])],
               applies_when=atom(), deadline="trước khi dùng", review_by="ai")
    chunks = {c["chunk_id"]: c for c in map(json.loads,
        Path("data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines())}
    module = review_module()
    result = module.render_review([row], chunks)
    assert result == module.render_review([row], chunks)
    for text in ("`cam`", "1. `c1`: Tiêu chí", "Không đạt: Chưa đạt", "trước khi dùng", "Người soát: ai", describe(atom())):
        assert text in result


ROOT = Path(__file__).resolve().parents[2]


ROWS = {r["id"]: r for r in yaml.safe_load(
    (ROOT / "src/legal_rag/knowledge/obligations.yaml").read_text(encoding="utf-8"))}


APPROVED = {
    "ob-072": "Hệ thống phải phân loại lại thành rủi ro cao khi Danh mục hệ thống trí tuệ nhân tạo có rủi ro cao được sửa đổi, bổ sung",
    "ob-074": "Hệ thống phải phân loại lại thành rủi ro cao khi Danh mục hệ thống trí tuệ nhân tạo có rủi ro cao được sửa đổi, bổ sung",
    "ob-018": "Âm thanh, hình ảnh, video mô phỏng người thật hoặc tái hiện sự kiện thực tế; trừ các trường hợp tại khoản 4 Điều 18 Nghị định 142/2026/NĐ-CP",
    "ob-067": "Hệ thống rủi ro trung bình theo khoản 1 Điều 9 Nghị định 142/2026/NĐ-CP, trừ các trường hợp tại khoản 3 Điều 9",
    "ob-080": "Hệ thống thuộc khoản 1 Điều 20 Nghị định 142/2026/NĐ-CP",
    "ob-063": "Khi hệ thống xảy ra sự cố nghiêm trọng",
    "ob-064": "Khi hệ thống xảy ra sự cố nghiêm trọng",
    "ob-075": "Hệ thống đã được đánh giá sự phù hợp",
    "ob-059": "", "ob-060": "", "ob-061": "", "ob-062": ""}


def test_table_has_approved_conditions_and_no_internal_notes():
    assert {key: ROWS[key]["condition"] for key in APPROVED} == APPROVED
    for row in ROWS.values():
        text = row["condition"]
        assert "người soát" not in text and "được giữ trong căn cứ" not in text
        assert "khoản 7 xác định" not in text and "áp dụng đồng thời điều kiện" not in text
    # Nguyên văn nghĩa vụ và trích dẫn giữ "điểm a" như văn bản gốc.
    assert "điểm a khoản 1 Điều 11" in ROWS["ob-072"]["obligation"]


@pytest.mark.parametrize("statuses,expected", [
    (["dap_ung", "dap_ung", "dap_ung"], "khop"),
    (["dap_ung", "chua_ro", "dap_ung"], "co_the_khop"),
    (["dap_ung", "khong_dap_ung", "dap_ung"], "khong_khop"),
    (["chua_ro", "chua_ro", "khong_dap_ung"], "khong_khop")])
def test_one_unmet_condition_excludes_item(statuses, expected):
    assert hr.item_status(response(statuses)["items"][0]) == expected


def test_render_names_the_unmet_condition_and_states_reading():
    text = hr.render_assessment("sản phẩm", response(["dap_ung", "khong_dap_ung"]), ITEMS, PARENTS)["text"]
    assert "Mục này không khớp vì điều kiện 2 không đáp ứng theo mô tả sản phẩm." in text
    # T57: cách đọc đồng thời vẫn áp dụng trong item_status nhưng không chèn vào câu trả lời (không gắn nguồn).
    assert "phải đáp ứng đồng thời" in hr.CONNECTOR_NOTE and hr.CONNECTOR_NOTE not in text
    assert "không tự kết luận" not in text
    unclear = hr.render_assessment("sản phẩm", response(["dap_ung", "chua_ro"]), ITEMS, PARENTS)["text"]
    assert "Mục này không khớp" not in unclear
    assert len(hr.split_conditions(ROBOT)["conditions"]) == 2


def test_excluded_item_unclear_conditions_not_asked():
    excluded = [dict(DECISIONS[0], conditions=[dict(c) for c in DECISIONS[0]["conditions"]])]
    excluded[0]["conditions"][0]["status"] = "khong_dap_ung"
    text, audit = render(context(decisions=excluded))
    missing = section(text, "Thông tin còn thiếu và giới hạn")
    assert "Điều kiện Danh mục chưa rõ" not in missing
    assert "Giao dịch có mức giá trị cao" not in missing
    assert not audit["errors"]
    kept, _ = render(context())
    assert "Giao dịch có mức giá trị cao" in section(kept, "Thông tin còn thiếu và giới hạn")
    assert ITEM_ID
