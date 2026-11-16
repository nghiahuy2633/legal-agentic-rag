"""Rà soát: chấm hiện trạng, tiêu chí và độ phủ Điểm."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import pytest
from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.pipeline import TABLE, run_assessment
from legal_rag.assessment.report import (
    DISCLAIMER, build_report, citation_label, fallback_summary, render_markdown, summarize,
)
from legal_rag.assessment.status import assess_status as assess_status_current
from functools import partial
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.llm import LLMError
from legal_rag.assessment.status import assess_status as assess_status_assessment_points
from legal_rag.assessment.pipeline import prepare_assessment, run_assessment
from legal_rag.assessment.questions import FACT_QUESTIONS
from legal_rag.knowledge.facts import FACT_FIELDS, FACT_LABELS, validate_facts
from legal_rag.knowledge.coverage import candidate_units, coverage_report


assess_status = partial(assess_status_current, verify_da=False)


ROOT = Path(__file__).resolve().parents[2]


def row(id="ob-test", **changes):
    return dict({"id": id, "group": "minh_bach", "role": "moi_vai_tro",
        "risk_level": "moi_muc", "review_status": "ai_reviewed", "kind": "nghia_vu",
        "obligation": "Thông báo cho người dùng", "applies_when": None,
        "criteria": [{"id": "c1", "text": "Thông báo khi bắt đầu", "not_met": ["Thông báo sau khi dùng"]}],
        "citations": [{"chunk_id": "134-2025-QH15_dieu-11_khoan-1", "quote": "Thông báo"}]}, **changes)


def items(*rows, facts=None):
    return applicable_obligations(rows, facts or {})["items"]


def answer(*entries):
    return json.dumps({"results": [{"obligation": r, "criterion": c, "status": s, "quote": q}
                                    for r, c, s, q in entries]}, ensure_ascii=False)


class Chat:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.payloads = []

    def complete(self, payload):
        self.payloads.append(deepcopy(payload))
        value = self.answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("role,roles,public,expected", [
    ("moi_vai_tro", None, None, "ap_dung"),
    ("nha_phat_trien", None, None, "ap_dung_neu"),
    ("nha_cung_cap", None, None, "ap_dung_neu"),
    ("ben_trien_khai", None, None, "ap_dung_neu"),
    ("nguoi_su_dung", None, None, None),
    ("co_quan_nha_nuoc", None, True, "ap_dung"),
    ("co_quan_nha_nuoc", ["nha_cung_cap"], None, "ap_dung_neu"),
    ("co_quan_nha_nuoc", ["co_quan_nha_nuoc"], False, None),
    ("moi_vai_tro", [], False, "ap_dung"),
    ("nha_cung_cap", ["nha_cung_cap"], False, "ap_dung"),
    ("ben_trien_khai", ["nha_cung_cap"], False, None),
    ("nguoi_su_dung", ["nguoi_su_dung"], False, "ap_dung"),
    ("nha_cung_cap", [], False, None),
])
def test_roles(role, roles, public, expected):
    result = applicable_obligations([row(role=role)], {"roles": roles, "is_public_sector": public})
    assert ([i["applicability"] for i in result["items"]] == [expected]) if expected else not result["items"]
    assert result["skipped"]["role"] == (expected is None)


@pytest.mark.parametrize("actual", ["cao", "trung_binh", "thap", "chua_phan_loai", None])
@pytest.mark.parametrize("required", ["cao", "trung_binh", "thap", "moi_muc"])
def test_risk(actual, required):
    result = applicable_obligations([row(risk_level=required)], {"risk_level": actual})
    if actual in (None, "chua_phan_loai"):
        assert result["items"][0]["applicability"] == ("ap_dung" if required == "moi_muc" else "ap_dung_neu")
    elif required not in (actual, "moi_muc"):
        assert result["skipped"]["risk"] == 1
    else:
        assert result["items"][0]["applicability"] == "ap_dung"


def test_reviews_conditions_purity():
    expr = {"all": [{"fact": "interacts_with_humans", "op": "is_true"}] * 2}
    rows = [row("rejected", review_status="user_rejected"), row("draft", review_status="ai_draft"),
            row("reviewed", review_status="user_reviewed"), row("condition", applies_when=expr)]
    before = deepcopy(rows)
    result = applicable_obligations(rows, {}, accept=("user_reviewed", "ai_reviewed", "user_rejected"))
    assert result["skipped"] == {"rejected": 1, "not_accepted": 1, "role": 0, "risk": 0, "condition": 0}
    assert result["items"][1]["missing_facts"] == ["interacts_with_humans"]
    assert "tương tác trực tiếp" in result["items"][1]["conditions"][0]
    assert applicable_obligations(rows[-1:], {"interacts_with_humans": False})["skipped"]["condition"] == 1
    assert items(rows[-1], facts={"interacts_with_humans": True})[0]["applicability"] == "ap_dung"
    assert rows == before


def test_three_real_profiles():
    rows = load_obligations(TABLE)
    profile = {"roles": ["nha_cung_cap"], "risk_level": "trung_binh", "interacts_with_humans": True,
               "content_types": ["van_ban"]}
    found = {i["row"]["id"]: i for i in applicable_obligations(rows, profile)["items"]}
    assert "ob-016" not in found
    assert found["ob-015"]["applicability"] == "ap_dung"
    unknown = applicable_obligations(rows, {"roles": None})["items"]
    assert all(i["row"]["role"] == "moi_vai_tro" for i in unknown if i["applicability"] == "ap_dung")
    deployer = applicable_obligations(rows, {"roles": ["ben_trien_khai"], "risk_level": "chua_phan_loai"})["items"]
    assert any(i["row"]["risk_level"] == "cao" and i["applicability"] == "ap_dung_neu" for i in deployer)


def test_status_quotes_checks_and_conditional():
    criteria = [{"id": f"c{i}", "text": f"Tiêu chí {i}"} for i in range(1, 5)]
    chat = Chat(answer(("ob-test", "c1", "da", '“ĐÃ   THÔNG BÁO.”'),
                       ("ob-test", "c2", "chua", "Chưa lưu hồ sơ"),
                       ("ob-test", "c3", "da", "Chỉ trong mô tả"),
                       ("ob-test", "c4", "chua", "không có")))
    result = assess_status(items(row(criteria=criteria, role="nha_cung_cap")),
        unicodedata.normalize("NFD", "Đã thông báo. Chưa lưu hồ sơ"), "Chỉ trong mô tả", chat, "fake",
        checks={("ob-test", "c4"): "da"})
    assert [c["status"] for c in result["rows"][0]["criteria"]] == ["da", "chua", "chua_ro", "da"]
    assert result["rows"][0]["status"] == "chua"
    assert result["rows"][0]["criteria"][3]["source"] == "nguoi_dung"
    assert result["downgraded"] == 1
    assert chat.payloads[0]["temperature"] == 0
    assert chat.payloads[0]["response_format"] == {"type": "json_object"}
    assert "###\n" in chat.payloads[0]["messages"][1]["content"]


@pytest.mark.parametrize("replies,calls", [(('hỏng', 'hỏng'), 2), ((LLMError('lỗi'),), 1),
    (('{"results":{}}', '{"results":[]}'), 2),
    ((answer(("ob-test", "c1", "lạ", "")),), 1)])
def test_status_failures(replies, calls):
    chat = Chat(*replies)
    result = assess_status(items(row()), "", "", chat, "fake")
    assert result["rows"][0]["status"] == "chua_ro"
    assert result["llm_calls"] == calls
    assert result["errors"]
    if calls == 2:
        assert chat.payloads[0] != chat.payloads[1]


def test_retry_success_and_batches_continue_after_error():
    selected = items(row("a"), row("b", kind="thong_tin"), row("c"), row("d"))
    chat = Chat(LLMError("lỗi"), 'hỏng', answer(("d", "c1", "da", "Đã báo")))
    result = assess_status(selected, "Đã báo", "", chat, "fake", batch_size=2)
    assert [r["status"] for r in result["rows"]] == ["chua_ro", "chua_ro", "da"]
    assert result["llm_calls"] == 3
    first = json.loads(chat.payloads[0]["messages"][1]["content"].split("NGHĨA VỤ VÀ TIÊU CHÍ:\n")[1])
    assert len(first) == 2
    assert first[0]["criteria"][0]["Các trường hợp KHÔNG đạt"] == ["Thông báo sau khi dùng"]


@pytest.mark.parametrize("quote,status,downgraded", [("Mô phỏng để lừa", "co_dau_hieu", 0),
    ("bịa", "khong_phat_hien", 1), ("...", "khong_phat_hien", 1)])
def test_banned(quote, status, downgraded):
    r = row(kind="cam", criteria=[{"id": "c1", "text": "cấm"}, {"id": "c2", "text": "cấm khác"}])
    chat = Chat(answer((r["id"], "c1", "co_dau_hieu", quote), (r["id"], "c2", "khong_phat_hien", "")))
    result = assess_status(items(r), "", "Mô phỏng để lừa", chat, "fake")
    assert result["rows"][0]["status"] == status
    assert result["downgraded"] == downgraded


def test_no_criteria_duplicate_invalid_checks():
    chat = Chat(answer(("ob-test", "c1", "da", "Đã báo"), ("ob-test", "c1", "da", "Đã báo")))
    assert assess_status(items(row()), "Đã báo", "", chat, "fake")["rows"][0]["status"] == "chua_ro"
    assert assess_status(items(row(criteria=[])), "", "", Chat('{"results":[]}'), "fake")["rows"][0]["status"] == "chua_ro"
    with pytest.raises(ValueError):
        assess_status(items(row(kind="cam")), "", "", Chat(), "fake", checks={("ob-test", "c1"): "da"})
    with pytest.raises(ValueError):
        assess_status([], "", "", Chat(), "fake", batch_size=0)


def test_checks_survive_llm_error_and_summary_rate():
    selected = items(row("done"), row("unknown"), row("conditional", role="nha_cung_cap"))
    state = assess_status(selected, "", "", Chat(LLMError("lỗi")), "fake",
                          checks={("done", "c1"): "da", ("conditional", "c1"): "da"})
    assert [r["status"] for r in state["rows"]] == ["da", "chua_ro", "da"]
    report = build_report({}, selected, state, {})
    assert report["summary"] == {"total": 2, "da": 1, "chua": 0, "chua_ro": 1,
                                  "rate": 0.5, "conditional_total": 1}


def test_all_criteria_done_and_banned_statement():
    selected = items(row(criteria=[{"id": "c1", "text": "Một"}, {"id": "c2", "text": "Hai"}]),
                     row("ban", kind="cam"))
    chat = Chat(answer(("ob-test", "c1", "da", "Đã thông báo"),
                       ("ob-test", "c2", "da", "Đã lưu"),
                       ("ban", "c1", "co_dau_hieu", "Lừa dối")))
    result = assess_status(selected, "Đã thông báo. Đã lưu. Lừa dối", "", chat, "fake")
    assert [r["status"] for r in result["rows"]] == ["da", "co_dau_hieu"]


def test_pipeline_summary_and_fixed_input_bytes():
    def run():
        return run_assessment({}, "Đã thông báo", "", Chat(
            answer(("ob-test", "c1", "da", "Đã thông báo")), "Đã đáp ứng 1/1 nghĩa vụ."),
            "fake", rows=[row()], created="fixed", verify_da=False)
    first, second = run(), run()
    assert first["markdown"].encode() == second["markdown"].encode()
    assert first["report"] == second["report"]
    assert first["trace"]["llm_calls"] == 2
    assert first["report"]["summary_rejected"] is False
    assert first["report"]["summary"]["rate"] == 1


def report_fixture():
    rows = [row("late"), row("early", deadline="Trước khi đưa vào sử dụng"), row("unknown"),
            row("conditional", role="nha_cung_cap"), row("conditional2", risk_level="cao"),
            row("conditional3", role="nha_cung_cap"), row("banned", kind="cam"),
            row("info", kind="thong_tin", deadline="Hạn chuyển tiếp")]
    selected = items(*rows)
    status = {"rows": [{"row_id": r["id"], "status": ("co_dau_hieu" if r["kind"] == "cam" else
        "chua_ro" if r["id"] == "unknown" else "chua"), "criteria": [{"id": "c1", "text": "Thông báo khi bắt đầu",
        "status": "chua_ro" if r["id"] == "unknown" else "co_dau_hieu" if r["kind"] == "cam" else "chua",
        "quote": "" if r["id"] == "unknown" else "Chưa báo", "source": "llm"}]} for r in rows if r["kind"] != "thong_tin"]}
    return build_report({}, selected, status, {"created": "fixed", "model": "fake", "table_sha256": "abc"})


def test_report_counts_todo_labels_purity():
    report = report_fixture()
    assert report["summary"] == {"total": 3, "da": 0, "chua": 2, "chua_ro": 1, "rate": 0, "conditional_total": 3}
    assert [t.get("row_id", t.get("field")) for t in report["todo"]] == ["early", "late", "unknown", "roles", "risk_level"]
    assert report["todo"][2]["criterion_id"] == "c1"
    assert report["todo"][3]["affected_rows"] == 2
    assert report["warnings"][0]["quotes"] == ["Chưa báo"]
    assert report["info"][0]["deadline"] == "Hạn chuyển tiếp"
    assert citation_label("134-2025-QH15_dieu-11_khoan-1") == "Luật 134/2025/QH15, Điều 11, khoản 1"
    assert citation_label("142-2026-ND-CP_dieu-9_khoan-3_diem-đ") == "Nghị định 142/2026/NĐ-CP, Điều 9, khoản 3, điểm đ"
    assert citation_label("05-2026-TT-BKHCN_phu-luc-1_muc-2") == "Thông tư 05/2026/TT-BKHCN, Phụ lục 1, mục 2"
    assert build_report({}, [], {"rows": []}, {})["summary"]["rate"] is None


def test_markdown_expected():
    report = build_report({}, [], {"rows": []}, {"created": "fixed", "model": "fake", "table_sha256": "abc"})
    expected = (
        "# Bản đánh giá tuân thủ\n\n## Thông tin chung\n\nThời điểm: fixed\nModel: fake\n"
        "Phiên bản prompt: status_v1\nSHA-256 bảng nghĩa vụ: abc\nDữ kiện: {}\n\n"
        "Đã đáp ứng 0/0 nghĩa vụ áp dụng\n\nNghĩa vụ có điều kiện: 0\n\n"
        "## Cảnh báo hành vi bị cấm\n\nKhông phát hiện dấu hiệu từ thông tin đã cung cấp.\n\n"
        "## Nghĩa vụ áp dụng\n\nChưa có.\n\n## Nghĩa vụ áp dụng có điều kiện\n\nChưa có.\n\n"
        "## Việc cần làm\n\nChưa có.\n\n## Thông tin, hạn chuyển tiếp\n\nChưa có.\n\n"
        + DISCLAIMER + "\n")
    assert render_markdown(report) == expected
    populated = report_fixture()
    before = deepcopy(populated)
    rendered = render_markdown(populated)
    assert render_markdown(populated).encode() == rendered.encode()
    assert populated == before
    assert "| Thông báo cho người dùng | Luật 134/2025/QH15, Điều 11, khoản 1 | Chưa đáp ứng | Thông báo khi bắt đầu: Chưa báo |" in rendered
    assert "Đã đáp ứng chưa: Thông báo khi bắt đầu? [unknown/c1]" in rendered


@pytest.mark.parametrize("reply,rejected", [("Đã đáp ứng 0/3 nghĩa vụ.", False),
    ("Cần xem Điều 11 khoản 1.", False), ("Đã đáp ứng 999 nghĩa vụ.", True),
    ("Tỷ lệ 0.3.", True), (LLMError("lỗi"), True), ("", True),
    ("Một. Hai. Ba. Bốn. Năm. Sáu.", True)])
def test_summary(reply, rejected):
    report = report_fixture()
    chat = Chat(reply)
    result = summarize(report, chat, "fake")
    assert result["summary_rejected"] is rejected
    assert result["text"] == (fallback_summary(report) if rejected else reply)
    sent = json.loads(chat.payloads[0]["messages"][1]["content"])
    assert set(sent) == {"summary", "todo", "obligations"}


def test_pipeline_and_cli(tmp_path, monkeypatch, capsys):
    class EmptyChat:
        def complete(self, payload):
            return '{"results":[]}'

    result = run_assessment({}, "", "", EmptyChat(), "fake", created="fixed", summarize_report=False)
    assert result["report"]["meta"]["table_sha256"] == hashlib.sha256(TABLE.read_bytes()).hexdigest()
    assert result["trace"]["llm_calls"] == result["trace"]["status"]["llm_calls"]
    assert all(t >= 0 for t in result["trace"]["timing"].values())
    spec = importlib.util.spec_from_file_location("assess_cli", ROOT / "scripts/assess.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="fake", api_key="fake", offline=False))
    paths = {}
    for name, value in (("facts", '{}'), ("statement", "Đã báo"), ("description", "Sản phẩm")):
        paths[name] = tmp_path / name
        paths[name].write_text(value, encoding="utf-8")
    args = [v for k, p in paths.items() for v in ("--" + k, str(p))]
    out = tmp_path / "out"
    assert cli.main(args + ["--out", str(out), "--no-summary"], root=tmp_path,
                    client_factory=lambda *a: EmptyChat()) == 0
    assert {p.name for p in out.iterdir()} == {"report.md", "report.json", "trace.json"}
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert (out / "report.md").read_bytes() == render_markdown(report).encode("utf-8")
    assert "# Bản đánh giá tuân thủ" in capsys.readouterr().out
    paths["facts"].write_text('{"unknown":true}', encoding="utf-8")
    assert cli.main(args, root=tmp_path, client_factory=lambda *a: EmptyChat()) == 2
    paths["facts"].write_text('[]', encoding="utf-8")
    assert cli.main(args, root=tmp_path, client_factory=lambda *a: EmptyChat()) == 2
    paths["facts"].write_text('{}', encoding="utf-8")
    def missing_settings():
        raise ValueError("Thiếu biến môi trường: RAG_LLM_MODEL")
    monkeypatch.setattr(cli, "get_llm_settings", missing_settings)
    assert cli.main(args, root=tmp_path) == 2
    assert "Thiếu biến môi trường" in capsys.readouterr().err


def test_cli_checks_format(tmp_path):
    spec = importlib.util.spec_from_file_location("assess_checks", ROOT / "scripts/assess.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    path = tmp_path / "checks.json"
    entry = {"row_id": "ob-test", "criterion_id": "c1", "status": "da"}
    path.write_text(json.dumps([entry]), encoding="utf-8")
    assert cli.read_checks(path) == {("ob-test", "c1"): "da"}
    for invalid in ([entry, entry], {}, [{**entry, "status": "chua_ro"}], [{"extra": 1}]):
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError):
            cli.read_checks(path)


def verdicts(*entries):
    return json.dumps({"results": [dict(id=id, verdict=v, reason="Kiểm ý") for id, v in entries]})


@pytest.mark.parametrize("replies,calls", [
    ([verdicts(("ob-test/c1", "khong_ho_tro"))], 2), (['{"results":[]}'], 2),
    ([LLMError("private")], 2), (["bad", "bad"], 3), ([verdicts(("ob-test/c1", "wrong"))], 2),
    ([verdicts(("ob-test/c1", "ho_tro"), ("ob-test/c1", "ho_tro"))], 2),
])
def test_reject_missing_error_and_duplicate(replies, calls):
    quote = "Đã tự đánh giá sự phù hợp"
    chat = Chat(answer(("ob-test", "c1", "da", quote)), *replies)
    result = assess_status_assessment_points(items(row()), quote, "", chat, "fake")
    assert result["rows"][0]["status"] == "chua_ro"
    assert result["rows"][0]["criteria"][0]["quote"] == ""
    assert result["rejected_by_check"] == 1
    assert result["checks_log"][0]["id"] == "ob-test/c1"
    assert result["llm_calls"] == calls


def test_bad_json_retried_once_then_accepted():
    quote = "Đã thông báo"
    chat = Chat(answer(("ob-test", "c1", "da", quote)), "bad", verdicts(("ob-test/c1", "ho_tro")))
    result = assess_status_assessment_points(items(row()), quote, "", chat, "fake")
    assert result["rows"][0]["status"] == "da" and result["llm_calls"] == 3


@pytest.mark.parametrize("replies", [["bad", "bad"], [LLMError("private")], ['{"results":[]}']])
def test_banned_warning_kept_when_check_fails(replies):
    # Lỗi kỹ thuật ở bước kiểm lại không được làm mất dấu hiệu hành vi bị cấm.
    chat = Chat(answer(("ob-test", "c1", "co_dau_hieu", "Lừa dối")), *replies)
    result = assess_status_assessment_points(items(row(kind="cam")), "", "Lừa dối", chat, "fake")
    assert result["rows"][0]["status"] == "co_dau_hieu"
    assert result["rejected_by_check"] == 0
    assert result["checks_log"][0]["verdict"] == "giu_canh_bao"


def test_one_check_across_status_batches_excludes_user_and_bad_quotes():
    rows = [row(str(i)) for i in range(8)]
    chat = Chat(answer(*[(str(i), "c1", "da", "Đã báo") for i in range(6)]),
                answer(("6", "c1", "da", "bịa"), ("7", "c1", "da", "Đã báo")),
                verdicts(*[(f"{i}/c1", "ho_tro") for i in range(1, 6)], ("7/c1", "ho_tro")))
    result = assess_status_assessment_points(items(*rows), "Đã báo", "", chat, "fake", checks={("0", "c1"): "da"})
    sent = json.loads(chat.payloads[-1]["messages"][-1]["content"])
    assert [entry["id"] for entry in sent] == [f"{i}/c1" for i in [1, 2, 3, 4, 5, 7]]
    assert all({"id", "text", "not_met", "quote"} <= entry.keys() for entry in sent)
    assert result["llm_calls"] == 3
    assert result["rejected_by_check"] == 0
    assert result["rows"][0]["criteria"][0]["source"] == "nguoi_dung"


def test_check_batches_of_40():
    criteria = [dict(id=f"c{i}", text="Tiêu chí") for i in range(41)]
    chat = Chat(answer(*[("ob-test", c["id"], "da", "Đã báo") for c in criteria]),
                verdicts(*[(f"ob-test/c{i}", "ho_tro") for i in range(40)]),
                verdicts(("ob-test/c40", "ho_tro")))
    result = assess_status_assessment_points(items(row(criteria=criteria)), "Đã báo", "", chat, "fake")
    assert [len(json.loads(p["messages"][-1]["content"])) for p in chat.payloads[1:]] == [40, 1]
    assert result["rows"][0]["status"] == "da"


@pytest.mark.parametrize("verdict,expected", [("co_dau_hieu", "co_dau_hieu"), ("khong", "khong_phat_hien")])
def test_banned_check(verdict, expected):
    chat = Chat(answer(("ob-test", "c1", "co_dau_hieu", "Lừa dối")), verdicts(("ob-test/c1", verdict)))
    result = assess_status_assessment_points(items(row(kind="cam")), "", "Lừa dối", chat, "fake")
    assert result["rows"][0]["status"] == expected


def test_pipeline_default_and_legacy_switch():
    initial = answer(("ob-test", "c1", "da", "Đã báo"))
    result = run_assessment({}, "Đã báo", "", Chat(initial, verdicts(("ob-test/c1", "khong_ho_tro"))),
                            "fake", rows=[row()], summarize_report=False)
    assert result["report"]["summary"]["chua_ro"] == 1
    assert "status_check_v1" in result["report"]["meta"]["prompt_version"]
    legacy = run_assessment({}, "Đã báo", "", Chat(initial), "fake", rows=[row()],
                            summarize_report=False, verify_da=False)
    assert legacy["report"]["summary"]["da"] == 1
    assert legacy["trace"]["llm_calls"] == 1


def test_fact_labels_and_prompt_selection():
    assert list(FACT_FIELDS)[-1] == "content_may_mislead"
    assert list(FACT_LABELS) == list(FACT_FIELDS)
    assert set(FACT_QUESTIONS) == set(FACT_FIELDS)
    assert validate_facts({"content_may_mislead": True})[1] == []
    for version in [None, "facts_v1"]:
        chat = Chat('{"facts":{}}')
        kwargs = {} if version is None else {"prompt_version": version}
        prepare_assessment([], chat, "fake", rows=[], **kwargs)
        prompt = chat.payloads[0]["messages"][0]["content"]
        assert (version or "facts_v2") in prompt
        if version is None:
            assert all(text in prompt for text in ["dự kiến", "phần mềm", "chính họ", "content_may_mislead"])


def test_point_inherits_introduction_and_needs_own_citation():
    base = "134-2025-QH15_dieu-11_khoan-3"
    def chunk(suffix, body):
        return dict(chunk_id=base + suffix, parent_id="134-2025-QH15_dieu-11",
                    document_id="134-2025-QH15", article="11", body=body)
    chunks = [chunk("", "Bên triển khai có trách nhiệm sau đây:"),
              chunk("_diem-a", "Thông báo cho người dùng"), chunk("_diem-b", "Lưu hồ sơ")]
    assert candidate_units(chunks) == [base, base + "_diem-a", base + "_diem-b"]
    rows = [dict(id="x", review_status="ai_reviewed", citations=[dict(chunk_id=base)])]
    report = coverage_report(rows, chunks, [], level="point")
    assert report["missing"] == [base + "_diem-a", base + "_diem-b"]
    rows[0]["citations"].append(dict(chunk_id=base + "_diem-a"))
    assert coverage_report(rows, chunks, [], level="point")["missing"] == [base + "_diem-b"]
    assert coverage_report(rows, chunks, [dict(clause_id=base + "_diem-b", reason="Ngoài phạm vi")], level="point")["missing"] == []


def test_point_own_body_and_closing_is_not_introduction():
    base = "134-2025-QH15_dieu-11_khoan-3"
    chunks = [dict(chunk_id=base + suffix, parent_id="134-2025-QH15_dieu-11",
                   document_id="134-2025-QH15", article="11", level=level, body=body)
              for suffix, level, body in [("", "clause", "Danh sách"),
                  ("_cuoi", "clause_closing", "Phải lưu ý"),
                  ("_diem-a", "point", "Phải thông báo"),
                  ("_diem-b", "point", "Lưu hồ sơ")]]
    assert candidate_units(chunks) == [base, base + "_diem-a"]
    rows = [dict(id="x", review_status="user_rejected", citations=[dict(chunk_id=base + "_diem-a")])]
    assert coverage_report(rows, chunks, [], level="point")["covered"] == []


def test_js_visibility_table():
    source = (Path(__file__).resolve().parents[2] / "src/legal_rag/api/static/assessment.js").read_text(encoding="utf-8")
    assert "FACT_VISIBILITY_RULES" in source
    assert "uses_personal_data: () => false" in source
    assert "asked.has(name)" in source
    assert all(label in source for label in ["Bắt buộc", "Thông tin thêm", "Hiện tất cả"])
