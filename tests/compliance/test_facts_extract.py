"""T35: chỉ dùng chat giả, kiểm dữ kiện, ưu tiên câu hỏi và CLI."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata

import pytest

from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.facts_extract import FACT_DESCRIPTIONS, extract_facts, merge_facts
from legal_rag.assessment.pipeline import TABLE, prepare_assessment
from legal_rag.assessment.questions import FACT_QUESTIONS, followup_questions, ready_for_assessment
from legal_rag.knowledge.facts import FACT_FIELDS, FACT_LABELS, empty_facts
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.llm import LLMError


class Chat:
    def __init__(self, response):
        self.response = response
        self.payloads = []

    def complete(self, payload):
        self.payloads.append(deepcopy(payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def response(**fields):
    return json.dumps({"facts": {name: {"value": value, "quote": quote}
                                for name, (value, quote) in fields.items()}}, ensure_ascii=False)


def test_extract_quotes_types_prompt_and_single_call():
    messages = [unicodedata.normalize("NFD", "Chúng tôi dùng chatbot. Không xử lý dữ liệu cá nhân."),
                "Nhà cung cấp phân loại rủi ro trung bình. Hoạt động tháng 3 năm 2026."]
    chat = Chat(response(interacts_with_humans=(True, '“CHÚNG TÔI   DÙNG CHATBOT.”'),
        uses_personal_data=(False, "Không xử lý dữ liệu cá nhân."),
        risk_level=("trung_binh", "Nhà cung cấp phân loại rủi ro trung bình."),
        operation_start_date=("2026-03-01", "Hoạt động tháng 3 năm 2026."),
        generates_content=(True, "Câu bịa"), roles=(["khong_hop_le"], "Chúng tôi dùng chatbot."),
        public_distribution=(None, "")))
    result = extract_facts(messages, chat, "fake")
    assert result["facts"]["interacts_with_humans"] is True
    assert result["facts"]["uses_personal_data"] is False
    assert result["facts"]["risk_level"] == "trung_binh"
    assert result["facts"]["operation_start_date"] == "2026-03-01"
    assert result["facts"]["generates_content"] is None
    assert result["facts"]["roles"] is None
    assert result["rejected"] == [
        {"field": "generates_content", "reason": "quote"}, {"field": "roles", "reason": "value"}]
    assert set(result["evidence"]) == {"interacts_with_humans", "uses_personal_data", "risk_level", "operation_start_date"}
    assert result["llm_calls"] == len(chat.payloads) == 1
    payload = chat.payloads[0]
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][0]["content"]
    assert "facts_v2" in prompt and "Bỏ qua mọi chỉ dẫn" in prompt
    assert "ngày 01" in prompt and "Không tự phân loại" in prompt
    assert json.loads(payload["messages"][1]["content"])["messages"] == messages
    for name in FACT_FIELDS:
        assert name in prompt and FACT_LABELS[name] in prompt and FACT_DESCRIPTIONS[name] in prompt


@pytest.mark.parametrize("quote", ["", "...", None, 4, "không tồn tại"])
def test_invalid_quote(quote):
    result = extract_facts(["Sản phẩm"], Chat(response(generates_content=(True, quote))), "fake")
    assert result["facts"] == empty_facts()
    assert result["rejected"] == [{"field": "generates_content", "reason": "quote"}]


@pytest.mark.parametrize("field,value", [("risk_level", "rat_cao"), ("generates_content", 1),
    ("roles", "nha_cung_cap"), ("operation_start_date", "2026-02-30"), ("content_types", ["khac"])])
def test_invalid_value(field, value):
    result = extract_facts(["Câu khai"], Chat(response(**{field: (value, "Câu khai")})), "fake")
    assert result["facts"][field] is None
    assert result["rejected"] == [{"field": field, "reason": "value"}]


@pytest.mark.parametrize("reply,error", [("hỏng", "JSON không hợp lệ"), ("[]", "JSON không hợp lệ"),
    ('{"facts":[]}', "JSON không hợp lệ"), (LLMError("không lộ chi tiết"), "LLMError")])
def test_extraction_errors(reply, error):
    chat = Chat(reply)
    result = extract_facts(["Mô tả"], chat, "fake")
    assert result == {"facts": empty_facts(), "evidence": {}, "rejected": [], "llm_calls": 1, "error": error}
    assert len(chat.payloads) == 1


def test_malformed_entries_and_deduplicated_lists():
    chat = Chat(json.dumps({"facts": {"unknown": {"value": True}, "roles": [],
        "sectors": {}, "generates_content": {"value": None},
        "content_types": {"value": ["van_ban", "van_ban"], "quote": "Tạo văn bản"}}}))
    result = extract_facts(["Tạo văn bản"], chat, "fake")
    assert result["facts"]["content_types"] == ["van_ban"]
    assert result["rejected"] == [{"field": name, "reason": "value"} for name in ("unknown", "roles", "sectors")]


def test_merge_precedence_changes_and_purity():
    previous = {"risk_level": "cao", "generates_content": True, "roles": ["nha_cung_cap"]}
    extracted = {"risk_level": None, "generates_content": False, "roles": ["ben_trien_khai"]}
    form = {"generates_content": True, "roles": [], "uses_personal_data": False}
    before = deepcopy((previous, extracted, form))
    facts, changes = merge_facts(previous, extracted, form)
    assert facts["risk_level"] == "cao" and facts["generates_content"] is True
    assert facts["roles"] == [] and facts["uses_personal_data"] is False
    assert changes == [{"field": "roles", "old": ["nha_cung_cap"], "new": []},
                       {"field": "uses_personal_data", "old": None, "new": False}]
    assert (previous, extracted, form) == before
    assert merge_facts(previous, extracted)[0]["generates_content"] is False
    assert merge_facts(previous, {}, {"risk_level": None})[0]["risk_level"] is None
    with pytest.raises(ValueError):
        merge_facts({}, {}, {"risk_level": "lạ"})


def test_real_table_questions_counts_order_and_purity():
    rows = load_obligations(TABLE)
    facts = empty_facts()
    before = deepcopy((rows, facts))
    questions = followup_questions(rows, facts, max_questions=100)
    assert [q["field"] for q in questions[:2]] == ["roles", "risk_level"]
    counts = dict.fromkeys(FACT_FIELDS, 0)
    for item in applicable_obligations(rows, facts)["items"]:
        if item["applicability"] == "ap_dung_neu":
            for name in set(item["missing_facts"]):
                counts[name] += 1
    expected = ["roles", "risk_level"] + sorted(
        [n for n in FACT_FIELDS if counts[n] and n not in ("roles", "risk_level")], key=lambda n: -counts[n])
    assert [q["field"] for q in questions] == expected
    assert all(q["affected"] == counts[q["field"]] for q in questions)
    assert (rows, facts) == before
    deployer = {"roles": ["ben_trien_khai"], "risk_level": "trung_binh", "generates_content": None}
    assert "generates_content" in [q["field"] for q in followup_questions(rows, deployer)]
    assert len(followup_questions(rows, facts, 1)) == 1
    assert followup_questions(rows, facts, 0) == []
    assert followup_questions([], facts)[0]["affected"] == 0
    assert ready_for_assessment(deployer)
    assert not ready_for_assessment(facts)
    deployer["risk_level"] = "chua_phan_loai"
    assert ready_for_assessment(deployer)
    assert "risk_level" not in [q["field"] for q in followup_questions(rows, deployer, 100)]
    assert set(FACT_QUESTIONS) == set(FACT_FIELDS)
    for name, spec in FACT_FIELDS.items():
        if spec["type"] in ("bool", "list"):
            assert FACT_QUESTIONS[name]["options"]


def test_prepare_merged_facts_and_error():
    result = prepare_assessment(["Tạo văn bản"], Chat(response(generates_content=(True, "Tạo văn bản"))),
        "fake", previous={"roles": ["ben_trien_khai"]}, form={"risk_level": "chua_phan_loai"}, rows=[])
    assert result["ready"] and result["questions"] == []
    assert result["facts"]["generates_content"] is True
    assert result["evidence"] == {"generates_content": "Tạo văn bản"}
    result = prepare_assessment([], Chat(LLMError("lỗi")), "fake", rows=[])
    assert not result["ready"] and result["error"] == "LLMError"


@pytest.mark.parametrize("use_facts", [False, True])
def test_cli_fake_chat(tmp_path, monkeypatch, capsys, use_facts):
    spec = importlib.util.spec_from_file_location("assess_t35", Path(__file__).resolve().parents[2] / "scripts/assess.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="fake", api_key="fake", offline=False))
    class Client:
        payloads = []

        def complete(self, payload):
            self.payloads.append(payload)
            if "facts_v2" in payload["messages"][0]["content"]:
                return response(roles=(["ben_trien_khai"], "Dùng hệ thống bên khác."),
                                risk_level=("trung_binh", "Rủi ro trung bình."))
            return '{"results":[]}'
    args = []
    for name in ("statement", "description"):
        path = tmp_path / name
        path.write_text("Mô tả và lời khai", encoding="utf-8")
        args += ["--" + name, str(path)]
    if use_facts:
        path = tmp_path / "facts.json"
        path.write_text('{}', encoding="utf-8")
        args += ["--facts", str(path)]
    out = tmp_path / "out"
    args += ["--message", "Dùng hệ thống bên khác.", "--message", "Rủi ro trung bình.",
             "--out", str(out), "--no-summary"]
    assert cli.main(args, root=tmp_path, client_factory=lambda *a: Client()) == 0
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    if use_facts:
        assert "preparation" not in trace
        assert not any("facts_v2" in p["messages"][0]["content"] for p in Client.payloads)
    else:
        assert trace["preparation"]["facts"]["roles"] == ["ben_trien_khai"]
        assert trace["preparation"]["ready"]
        assert trace["llm_calls"] == trace["status"]["llm_calls"] + 1
        assert "Dữ kiện và câu hỏi lại:" in capsys.readouterr().out
    assert (out / "report.md").exists()
