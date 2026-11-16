"""Agent: kiểm đầu vào, phân tích, phạm vi, chính sách nhu cầu và chọn nhánh."""

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unicodedata
import pytest
from legal_rag.agent import analyze
from legal_rag.agent.analyze import analyze_turn, decide
from legal_rag.agent.guard import MAX_INPUT_CHARS, check_input, scope_reply
from legal_rag.agent.profile import EMPTY_PROFILE, merge_profile, missing_fields
from legal_rag.evaluation.input_checks import load_input_checks, score_scope
from legal_rag.llm import LLMError
from types import SimpleNamespace
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.evaluation.input_checks import score_profile, score_scope
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.policy import request_plan
from test_agent_graph import FakeChat as FakeChat_answer_first_routing, fake_answer, fake_prepare
from legal_rag.agent.analyze import analyze_turn
from test_agent_graph import FakeChat as FakeChat_request_policy, fake_answer, fake_prepare
from legal_rag.agent.answer import prepare_evidence
from legal_rag.agent.config import MAX_QUERIES, AgentConfig
from legal_rag.agent.presentation import build_context, owned_bodies, prohibition_line
from test_agent_graph import FakeChat as FakeChat_scope_query_report
from test_basic_rag import chunks, parents, DOCUMENTS


ROOT = Path(__file__).resolve().parents[2]


class FakeChat:
    def __init__(self, answer):
        self.answer = answer
        self.payloads = []

    def complete(self, payload):
        self.payloads.append(payload)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def valid(**updates):
    return {"scope": "trong", "out_of_scope_part": None, "profile_update": {},
            "sub_queries": ["nghĩa vụ"], **updates}


@pytest.mark.parametrize("text,status", [
    (" \n ", "empty"), ("x" * 4001, "too_long"), ("???!!! 123", "garbage"),
    ("___ 12", "garbage"), ("cảm ơn bạn nhé!", "greeting"), ("Hi, admin ơi", "greeting"),
    ("xin chào 123", "ok"), ("a" * 4000, "ok"), ("asdfgh qwerty zxcv", "ok"),
])
def test_guard(text, status):
    result = check_input(text)
    assert result["status"] == status
    assert bool(result["reply"]) == (status != "ok")
    if status == "too_long":
        assert "4000" in result["reply"]


def test_guard_nfc_and_strip_before_length():
    assert check_input(unicodedata.normalize("NFD", "á" * 4000) + " \n")["status"] == "ok"
    assert check_input(unicodedata.normalize("NFD", "xin chào"))["status"] == "greeting"
    reply = scope_reply()
    for part in ("ngoài phạm vi", "134/2025/QH15", "142/2026/NĐ-CP", "05/2026/TT-BKHCN", "33/2026/QĐ-TTg"):
        assert part in reply


def test_dataset_and_rule_short_circuit():
    path = ROOT / "eval/input_checks.jsonl"
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = load_input_checks(path)
    assert len(rows) == 18
    by_id = {row["id"]: row for row in rows}
    assert len(by_id["i14"]["text"]) > MAX_INPUT_CHARS
    assert len(by_id["i15"]["text"]) < MAX_INPUT_CHARS
    assert check_input(by_id["i06"]["text"])["status"] == "ok"
    chat = FakeChat(AssertionError("Không được gọi LLM"))
    for ident in ("i01", "i03", "i04", "i05", "i14"):
        result = decide(by_id[ident]["text"], EMPTY_PROFILE, [], chat, "fake")
        assert result["source"] == "rule" and result["retrieve"] is False
    assert chat.payloads == []


def test_profile_merge():
    old = dict(EMPTY_PROFILE, role="nha_cung_cap", is_public_sector=True)
    snapshot = deepcopy(old)
    update = dict(role=None, sector="y_te", is_public_sector=False, generates_content=True,
                  product_description="x" * 350, surprise=None)
    result, ignored = merge_profile(old, update)
    assert old == snapshot
    assert result == dict(old, sector="y_te", is_public_sector=False, generates_content=True,
                          product_description="x" * 300)
    assert ignored == ["surprise"]
    result, ignored = merge_profile(result, {"role": "ben_trien_khai"})
    assert result["role"] == "ben_trien_khai" and ignored == []
    assert missing_fields(EMPTY_PROFILE) == list(EMPTY_PROFILE)
    assert missing_fields(result) == ["risk_level"]


@pytest.mark.parametrize("key,value", [
    ("role", "developer"), ("role", []), ("sector", "unknown"), ("sector", {}),
    ("is_public_sector", 1), ("generates_content", "false"),
    ("product_description", " \n"), ("product_description", 42),
])
def test_profile_invalid(key, value):
    profile, ignored = merge_profile(EMPTY_PROFILE, {key: value})
    assert profile == EMPTY_PROFILE and ignored == [key]


@pytest.mark.parametrize("fence", [False, True])
def test_analysis_payload_and_valid_json(fence):
    response = valid(scope="mot_phan", out_of_scope_part="phần khác", profile_update={"sector": "y_te"})
    answer = json.dumps(response)
    chat = FakeChat("```json\n" + answer + "\n```" if fence else answer)
    recent = [{"role": "user", "content": str(i) * 700} for i in range(6)]
    profile = EMPTY_PROFILE.copy()
    before = deepcopy((profile, recent))
    result = analyze_turn("câu hiện tại", profile, recent, chat, "fake")
    assert result == dict(response, analysis_ok=True, question_type="khac",
                          request_kinds=[], request_kinds_discarded=["missing_or_invalid_list"])
    assert (profile, recent) == before
    assert len(chat.payloads) == 1
    payload = chat.payloads[0]
    assert payload["model"] == "fake" and payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]
    data = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
    assert data == dict(profile=profile, message="câu hiện tại", recent_messages=[
        {"role": "user", "content": str(i) * 500} for i in range(2, 6)])


@pytest.mark.parametrize("answer", [
    "not json", "[]", "null", "{}", "42", None,
    *[json.dumps({key: value for key, value in valid().items() if key != missing})
      for missing in ("scope",)],
    *[json.dumps(valid(**change)) for change in (
        {"scope": "khac"}, {"scope": []}, {"out_of_scope_part": 42},
        {"profile_update": []}, {"sub_queries": "query"})],
])
def test_analysis_fallback(answer):
    chat = FakeChat(answer)
    result = decide("nội dung", EMPTY_PROFILE, [], chat, "fake")
    assert result["scope"] == "trong" and result["retrieve"] is True
    assert result["analysis_ok"] is False
    assert result["profile_update"] == {} and result["sub_queries"] == ["nội dung"]
    assert result["out_of_scope_part"] is None
    assert len(chat.payloads) == 1


@pytest.mark.parametrize("queries,expected", [
    ([" a ", "a", "", " \n", 2, None, "b", "c", "d"], ["a", "b", "c"]),
    ([], ["nội dung"]), ([" ", ""], ["nội dung"]),
])
def test_query_cleanup(queries, expected):
    result = analyze_turn("nội dung", EMPTY_PROFILE, [], FakeChat(json.dumps(valid(sub_queries=queries))), "fake")
    assert result["analysis_ok"] is True and result["sub_queries"] == expected


@pytest.mark.parametrize("scope", ["trong", "ngoai", "mot_phan"])
def test_decide_scopes(scope):
    chat = FakeChat(json.dumps(valid(scope=scope, out_of_scope_part="khác")))
    result = decide("nội dung", EMPTY_PROFILE, [], chat, "fake")
    assert result["source"] == "llm"
    assert result["retrieve"] == (scope != "ngoai")
    assert result["out_of_scope_part"] == ("khác" if scope == "mot_phan" else None)
    assert result["reply"] == (scope_reply() if scope == "ngoai" else None)


def test_analysis_llm_error_and_prompt_version(tmp_path, monkeypatch):
    chat = FakeChat(LLMError("lỗi giả"))
    with pytest.raises(LLMError, match="lỗi giả"):
        analyze_turn("nội dung", EMPTY_PROFILE, [], chat, "fake")
    assert len(chat.payloads) == 1
    path = tmp_path / "analyze_v7.txt"
    path.write_text("Phiên bản: sai", encoding="utf-8")
    monkeypatch.setattr(analyze, "PROMPT_DIR", tmp_path)
    chat = FakeChat("{}")
    with pytest.raises(ValueError, match="phiên bản"):
        analyze_turn("nội dung", EMPTY_PROFILE, [], chat, "fake")
    assert not chat.payloads


def test_score_scope():
    rows = [dict(id=str(i), kind="a" if i < 3 else "b", should_retrieve=i < 2)
            for i in range(5)]
    rows[0]["expected_scope"] = "mot_phan"
    rows[4]["expected_scope"] = "ngoai"
    results = [dict(id="0", retrieve=True, scope="mot_phan"), dict(id="1", retrieve=False),
               dict(id="2", retrieve=True), dict(id="3", retrieve=False), dict(id="4", error="lỗi")]
    before = deepcopy((rows, results))
    score = score_scope(rows, results)
    assert (rows, results) == before
    assert score["n"] == 5 and score["correct"] == 2 and score["incorrect"] == 3
    assert score["wrong_ids"] == ["1", "2", "4"]
    assert score["false_refusal_rate"] == 1 / 2
    assert score["false_accept_rate"] == 1 / 3
    assert score["errors"] == 1 and score["error_ids"] == ["4"]
    assert score["scope_match"] == {"n": 2, "correct": 1, "rate": 0.5}
    assert score["by_kind"]["b"]["false_refusal_rate"] is None
    empty = score_scope([], [])
    assert empty["n"] == 0 and empty["by_kind"] == {}
    assert empty["false_refusal_rate"] is None and empty["false_accept_rate"] is None
    assert empty["scope_match"]["rate"] is None
    assert score_scope(rows, [])["correct"] == 0


def load_cli():
    spec = importlib.util.spec_from_file_location("eval_scope", ROOT / "scripts/eval_scope.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_no_config(monkeypatch, capsys):
    module = load_cli()
    def forbidden():
        raise AssertionError("Không được đọc cấu hình")
    monkeypatch.setattr(module, "get_llm_settings", forbidden)
    assert module.main(["--dry-run"]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0] == dict(dataset="input_checks", n=18, rule=5, needs_llm=13)
    assert output[1]["dataset"] == "questions"
    scenarios = [json.loads(line) for line in (ROOT / "eval/scenarios.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    turns = [turn for scenario in scenarios for turn in scenario["turns"]]
    rule = sum(check_input(turn["user"])["status"] != "ok" for turn in turns)
    assert output[2] == dict(dataset="scenarios", n=len(turns), rule=rule, needs_llm=len(turns) - rule)
    assert len(output) == 3


def test_cli_fake_llm_errors_cache_and_models(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    module = load_cli()
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval/scenarios.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "eval/input_checks.jsonl").write_text(json.dumps(
        dict(id="i", kind="test", text="nội dung", should_retrieve=True)) + "\n", encoding="utf-8")
    (tmp_path / "eval/questions.jsonl").write_text("\n".join(json.dumps(row) for row in [
        dict(id="q1", question="nội dung", category="test", expected_behavior="tra_loi"),
        dict(id="q2", question="lỗi", category="test", expected_behavior="tra_loi"),
        dict(id="q3", question="xin chào", category="test", expected_behavior="tu_choi"),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(module, "get_llm_settings", lambda: SimpleNamespace(
        base_url="fake", api_key="secret", model="primary", fallback_models=("backup",)))
    calls = []
    class Client:
        def __init__(self, base_url, api_key, **kwargs):
            assert kwargs == {"max_attempts": 3}

        def complete(self, payload):
            calls.append(payload)
            data = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
            assert data["profile"] == EMPTY_PROFILE and data["recent_messages"] == []
            if data["message"] == "lỗi":
                raise LLMError("lỗi giả", status=400)
            if payload["model"] == "primary":
                raise LLMError("quá tải", status=503)
            return json.dumps(valid())
    output = tmp_path / "runs/scope.json"
    assert module.main(["--output", str(output)], root=tmp_path, client_factory=Client) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == 3  # primary + backup, cache cho q1, lỗi cho q2
    assert data["input_checks"]["results"][0]["model"] == "backup"
    questions = data["questions"]
    assert questions["results"][0]["model"] == "backup"
    assert questions["results"][1]["error"] == "lỗi giả"
    assert questions["results"][2]["model"] is None
    assert questions["score"]["correct"] == 2 and questions["score"]["errors"] == 1
    assert '"errors": 1' in capsys.readouterr().out
    assert "secret" not in output.read_text(encoding="utf-8")


def test_agent_does_not_depend_on_evaluation():
    for path in (ROOT / "src/legal_rag/agent").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("evaluation" not in alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert "evaluation" not in (node.module or "")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "eval/" not in node.value and "eval\\" not in node.value


def test_null_optional_keys_keep_out_of_scope_decision():
    from types import SimpleNamespace
    from legal_rag.agent.analyze import analyze_turn
    answer = '{"scope":"ngoai","out_of_scope_part":null,"profile_update":null,"sub_queries":null}'
    chat = SimpleNamespace(complete=lambda payload: answer)
    result = analyze_turn("câu hỏi", {}, [], chat, "m")
    assert result["scope"] == "ngoai" and result["analysis_ok"] is True
    assert result["profile_update"] == {} and result["sub_queries"] == ["câu hỏi"]


@pytest.mark.parametrize("answer,scope,ok", [
    ({"scope": "ngoai", "out_of_scope_part": "x", "sub_queries": []}, "ngoai", True),
    ({"scope": "trong"}, "trong", True),
    ({"profile_update": {}, "sub_queries": []}, "trong", False),
    ({"scope": "ngoai", "profile_update": "x"}, "trong", False),
    ({"scope": "ngoai", "profile_update": None}, "ngoai", True),
    ({"scope": "ngoai", "sub_queries": None}, "ngoai", True),
])
def test_optional_keys(answer, scope, ok):
    result = analyze.analyze_turn("câu hỏi", EMPTY_PROFILE, [], FakeChat(json.dumps(answer)), "fake")
    assert result == dict(scope=scope, analysis_ok=ok, out_of_scope_part=None,
                          profile_update={}, sub_queries=["câu hỏi"], question_type="khac",
                          request_kinds=[], request_kinds_discarded=["missing_or_invalid_list" if ok else "invalid_analysis"])


@pytest.mark.parametrize("version", ["analyze_v1", "analyze_v2"])
def test_prompt_selection(version):
    chat = FakeChat('{"scope":"trong"}')
    analyze.decide("câu hỏi", EMPTY_PROFILE, [], chat, "fake", version=version)
    assert chat.payloads[0]["messages"][0]["content"] == (
        ROOT / f"prompts/{version}.txt").read_text(encoding="utf-8")
    default = FakeChat('{"scope":"trong"}')
    analyze.decide("câu hỏi", EMPTY_PROFILE, [], default, "fake")
    assert default.payloads[0]["messages"][0]["content"].startswith("Phiên bản: analyze_v7\n")


def test_unknown_version_and_header(tmp_path, monkeypatch):
    chat = FakeChat("{}")
    for function in (analyze.analyze_turn, analyze.decide):
        with pytest.raises(ValueError, match="phiên bản"):
            function("câu hỏi", EMPTY_PROFILE, [], chat, "fake", version="../unknown")
    monkeypatch.setattr(analyze, "PROMPT_DIR", tmp_path)
    for version in ("analyze_v1", "analyze_v2"):
        (tmp_path / f"{version}.txt").write_text("Phiên bản: sai", encoding="utf-8")
        with pytest.raises(ValueError, match="phiên bản"):
            analyze.analyze_turn("câu hỏi", EMPTY_PROFILE, [], chat, "fake", version=version)
    assert chat.payloads == []


def test_profile_scoring():
    expected = dict(EMPTY_PROFILE, role="nha_cung_cap", sector="y_te", generates_content=False,
                    product_description="mô tả chuẩn")
    rows = [dict(id="a", expected_profile=expected), dict(id="b", expected_profile=EMPTY_PROFILE),
            dict(id="error", expected_profile=EMPTY_PROFILE)]
    results = [dict(id="a", profile=dict(EMPTY_PROFILE, role="ben_trien_khai", is_public_sector=False,
                                         generates_content=False, product_description="mô tả khác")),
               dict(id="b", profile=dict(EMPTY_PROFILE, product_description="đoán")),
               dict(id="error", error="lỗi", profile=EMPTY_PROFILE.copy())]
    before = deepcopy((rows, results))
    score = score_profile(rows, results)
    assert (rows, results) == before
    assert score["n"] == 2 and score["error_ids"] == ["error"] and score["errors"] == 1
    assert score["fields"]["role"] == dict(correct=1, wrong_value=1, guessed=0, missed=0, accuracy=.5)
    assert score["fields"]["sector"]["missed"] == 1
    assert score["fields"]["is_public_sector"]["guessed"] == 1
    assert score["fields"]["generates_content"]["correct"] == 2
    assert score["fields"]["product_description"] == dict(correct=1, guessed=1, missed=0, accuracy=.5)
    assert score["mistakes"] == [
        dict(id="a", field="role", expected="nha_cung_cap", predicted="ben_trien_khai"),
        dict(id="a", field="sector", expected="y_te", predicted=None),
        dict(id="a", field="is_public_sector", expected=None, predicted=False),
        dict(id="b", field="product_description", expected=None, predicted="đoán")]
    missed = score_profile([rows[0]], [dict(id="a", profile=EMPTY_PROFILE)])
    assert missed["fields"]["product_description"]["missed"] == 1
    for empty in (score_profile([], []), score_profile(rows, [])):
        assert empty["n"] == 0
        assert all(field["accuracy"] is None for field in empty["fields"].values())


def test_analysis_failed_is_separate():
    rows = [dict(id="a", kind="x", should_retrieve=True),
            dict(id="b", kind="x", should_retrieve=False)]
    score = score_scope(rows, [dict(id="a", retrieve=True, analysis_ok=False),
                               dict(id="b", retrieve=False, analysis_ok=None)])
    assert score["correct"] == 2 and score["errors"] == 0
    assert score["analysis_failed"] == 1 and score["analysis_failed_ids"] == ["a"]
    assert score["by_kind"]["x"]["analysis_failed_ids"] == ["a"]


@pytest.mark.parametrize("version", ["analyze_v1", "analyze_v2"])
def test_scenario_history_profiles_and_errors(tmp_path, monkeypatch, capsys, version):
    module = load_cli()
    directory = tmp_path / "eval"
    directory.mkdir()
    for name in ("input_checks", "questions"):
        (directory / f"{name}.jsonl").write_text("", encoding="utf-8")
    turns = [dict(turn=i, user=text, expected_behavior="tu_choi" if i == 2 else "tra_loi",
                  expected_profile=dict(EMPTY_PROFILE, sector="y_te"))
             for i, text in enumerate(["sản phẩm", "ngoài phạm vi", "lỗi", "tiếp tục"], 1)]
    scenarios = [dict(id="s", turns=turns), dict(id="next", turns=[dict(
        turn=1, user="kịch bản mới", expected_behavior="tra_loi", expected_profile=EMPTY_PROFILE)])]
    (directory / "scenarios.jsonl").write_text("\n".join(json.dumps(s) for s in scenarios), encoding="utf-8")
    monkeypatch.setattr(module, "get_llm_settings", lambda: SimpleNamespace(
        base_url="fake", api_key="secret", model="fake", fallback_models=()))
    calls = []

    class Client:
        def __init__(self, *args):
            pass

        def complete(self, payload):
            assert payload["messages"][0]["content"].startswith(f"Phiên bản: {version}\n")
            data = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
            calls.append(data)
            if data["message"] == "lỗi":
                raise LLMError("lỗi giả", status=400)
            outside = data["message"] == "ngoài phạm vi"
            update = {"sector": "giao_duc" if outside else "y_te"} if data["message"] != "kịch bản mới" else {}
            return json.dumps(dict(scope="ngoai" if outside else "trong", profile_update=update))

    assert module.main(["--prompt", version], root=tmp_path, client_factory=Client) == 0
    results = json.loads((tmp_path / f"runs/t18/scope-{version}.json").read_text(encoding="utf-8"))["scenarios"]
    assert [r["id"] for r in results["results"]] == ["s.t1", "s.t2", "s.t3", "s.t4", "next.t1"]
    for i, data in enumerate(calls[:4]):
        assert data["recent_messages"] == [turn["user"] for turn in turns[:i]]
        assert data["profile"] == (EMPTY_PROFILE if i == 0 else dict(EMPTY_PROFILE, sector="y_te"))
    assert calls[4]["recent_messages"] == [] and calls[4]["profile"] == EMPTY_PROFILE
    assert [r["profile"] for r in results["results"][:4]] == [dict(EMPTY_PROFILE, sector="y_te")] * 4
    assert results["results"][1]["retrieve"] is False
    assert results["results"][2]["error"] == "lỗi giả"
    assert results["profile_score"]["n"] == 4 and results["profile_score"]["errors"] == 1
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert printed[-1]["profile_score"] == results["profile_score"]


PRODUCT = dict(product_description="hệ thống AI cấp tín dụng", role="nha_cung_cap")


# Các ca lấy từ lượt kịch bản sai trong runs/eval/final-1 (analysis phát lại từ cache).
@pytest.mark.parametrize("kinds,question_type,report", [
    (["nghia_vu", "kien_thuc"], "xac_nhan", False),   # s004.t3: có phải tạm dừng không
    (["nghia_vu", "kien_thuc"], "su_kien", False),    # s005.t3: báo cáo theo mẫu nào
    (["kien_thuc", "nghia_vu"], "xac_nhan", False),   # s008.t3: có bị coi là nhận lỗi không
    (["kien_thuc", "nghia_vu"], "khac", False),       # s011.t2: vậy thay bằng quy định nào
    (["nghia_vu"], "xac_nhan", False),                # s002.t3: có phải báo Bộ KHCN không
    (["nghia_vu"], "dinh_nghia", False),
    (["nghia_vu", "kien_thuc"], "nghia_vu", False),   # s007.t3: lẫn kiến thức
    (["nghia_vu"], "nghia_vu", True),                 # cần tuân thủ những gì
    (["nghia_vu"], "khac", True),
    (["nghia_vu", "huong_dan"], "nghia_vu", True),
    (["kien_thuc"], "nghia_vu", False),
])
def test_report_only_for_pure_obligation_questions(kinds, question_type, report):
    plan = request_plan(dict(scope="trong", request_kinds=kinds, question_type=question_type),
                        PRODUCT, None, AgentConfig())
    assert plan["obligation_report"] is report
    assert plan["use_table"] is report and plan["use_high_risk"] is report
    assert plan["request_kinds"] == kinds  # nhu cầu model trả về vẫn được ghi nguyên
    if report:
        assert plan["effective_question_type"] == "nghia_vu"
    else:
        assert plan["effective_question_type"] == (
            question_type if question_type in ("su_kien", "dinh_nghia", "xac_nhan") else "khac")
        if "nghia_vu" in kinds:
            assert plan["table_reason"] == plan["high_risk_reason"] == "answer_first"


def test_resolved_assessment_context_keeps_report_for_obligation_question():
    plan = request_plan(dict(scope="trong", request_kinds=["nghia_vu"], question_type="nghia_vu"),
                        PRODUCT, dict(assessment={"id": "a"}), AgentConfig())
    assert plan["request_kinds"] == ["nghia_vu", "huong_dan"] and plan["obligation_report"]


def test_out_of_scope_never_reports():
    plan = request_plan(dict(scope="ngoai", request_kinds=["nghia_vu"], question_type="nghia_vu"),
                        PRODUCT, None, AgentConfig())
    assert not plan["obligation_report"] and not plan["use_table"]
    assert plan["table_reason"] == "not_requested"


@pytest.mark.parametrize("question_type,expected", [("nghia_vu", True), ("xac_nhan", False)])
def test_v4_compatibility_unchanged(question_type, expected):
    plan = request_plan(dict(scope="trong", question_type=question_type), PRODUCT, None,
                        AgentConfig(analyze_prompt="analyze_v4"))
    assert plan["obligation_report"] is expected and plan["use_table"] is expected


def test_graph_confirmation_question_skips_table_and_catalog_without_extra_calls():
    def forbidden():
        pytest.fail("Câu xác nhận không được tải bảng hoặc Danh mục")
    calls = []
    chat = FakeChat_answer_first_routing(dict(scope="trong", question_type="xac_nhan", request_kinds=["nghia_vu", "kien_thuc"],
                         profile_update=PRODUCT), "Đáp [E1].")
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare, AgentConfig(enable_rewrite=False),
                        fake_answer(calls), pipeline_factory=forbidden,
                        obligations_loader=forbidden, high_risk_loader=forbidden))
    result = run_turn(graph, "s", "trong lúc chuyển tiếp có phải tạm dừng hệ thống không")
    assert result["map_obligations"] is None and result["high_risk"] is None
    assert result["llm_calls"] == len(chat.payloads) == 2
    generated = next(n for n in result["trace"] if n["node"] == "generate")
    assert generated["effective_question_type"] == "xac_nhan"
    assert generated["effective_prompt_version"] not in ("answer_v10", "answer_v11", "answer_v12")


@pytest.mark.parametrize("kinds,table,high", [
    (["kien_thuc"], False, False), (["nghia_vu"], True, True),
    (["hien_trang"], False, False), (["huong_dan"], False, False),
    # T55: nhu cầu lẫn kiến thức được trả lời trực tiếp, không dựng báo cáo nghĩa vụ.
    (["kien_thuc", "nghia_vu", "huong_dan"], False, False), ([], False, False),
    (["nghia_vu", "huong_dan"], True, True),
])
def test_pure_policy(kinds, table, high):
    plan = request_plan(dict(request_kinds=kinds, scope="trong", question_type="nghia_vu"),
                        dict(product_description="sản phẩm"), None, AgentConfig())
    assert (plan["use_table"], plan["use_high_risk"]) == (table, high)
    assert plan["effective_question_type"] == ("nghia_vu" if table else "khac")


@pytest.mark.parametrize("value,expected", [
    (None, []), ("nghia_vu", []), (["bad"], []),
    (["bad", "nghia_vu", "nghia_vu", {}, "kien_thuc"], ["nghia_vu", "kien_thuc"]),
])
def test_v5_normalization_keeps_scope(value, expected):
    result = analyze_turn("Câu hỏi AI", {}, [], FakeChat_request_policy(dict(scope="ngoai", request_kinds=value)), "fake")
    assert result["scope"] == "ngoai" and result["analysis_ok"]
    assert result["request_kinds"] == expected
    assert result["request_kinds_discarded"]


@pytest.mark.parametrize("version,question,expected", [
    ("analyze_v2", "nghia_vu", False), ("analyze_v3", "nghia_vu", False),
    ("analyze_v4", "nghia_vu", True), ("analyze_v4", "xac_nhan", False),
    ("analyze_v5", "nghia_vu", False),
])
def test_compatibility(version, question, expected):
    plan = request_plan(dict(scope="trong", question_type=question), {}, None,
                        AgentConfig(analyze_prompt=version))
    assert plan["use_table"] is expected


def test_context_union_scope_and_flags():
    context = dict(assessment={"id": "exact"}, stale=True)
    for scope in ("trong", "ngoai"):
        plan = request_plan(dict(scope=scope, request_kinds=["nghia_vu"]),
                            dict(product_description="AI"), context,
                            AgentConfig(enable_obligations=False, enable_high_risk=False))
        assert plan["request_kinds"] == ["nghia_vu", "huong_dan"]
        assert not plan["use_table"] and not plan["use_high_risk"]
        assert plan["context_mode"] == ("blocked" if scope == "ngoai" else "assessment")


@pytest.mark.parametrize("message", ["Hệ thống AI là gì?", "Mức phạt bao nhiêu?", "Các mức rủi ro gồm những mức nào?",
                                     "Một sản phẩm AI cần có những nghĩa vụ gì?"])
@pytest.mark.parametrize("kind", ["kien_thuc", "hien_trang", "huong_dan"])
def test_non_g2_never_loads_resources_even_with_profile(message, kind):
    def forbidden():
        pytest.fail("Không được tải bảng/Danh mục")
    calls = []
    chat = FakeChat_request_policy(dict(scope="trong", question_type="nghia_vu", request_kinds=[kind],
                         profile_update=dict(product_description="AI y tế", role="nha_cung_cap")), "Đáp")
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare,
                        AgentConfig(enable_rewrite=False), fake_answer(calls),
                        pipeline_factory=forbidden, obligations_loader=forbidden, high_risk_loader=forbidden))
    result = run_turn(graph, "s", message)
    assert result["map_obligations"] is None and result["high_risk"] is None
    assert result["llm_calls"] == len(chat.payloads) == (1 if kind == "hien_trang" else 2)
    generated = next(n for n in result["trace"] if n["node"] == "generate")
    assert generated["effective_question_type"] == "khac"
    assert next(n for n in result["trace"] if n["node"] == "analyze")["question_type"] == "nghia_vu"
    assert next(n for n in result["trace"] if n["node"] == "plan_queries")["facts_source"] == "profile"
    assert not graph.get_state({"configurable": {"thread_id": "s"}}).values["followup_asked"]
    if kind == "hien_trang":
        assert "mở Rà soát" in result["reply"] and not calls


def test_v5_one_analysis_call_and_old_prompt_unchanged():
    from legal_rag.agent.analyze import PROMPT_DIR
    v4 = (PROMPT_DIR / "analyze_v4.txt").read_text(encoding="utf-8")
    v5 = (PROMPT_DIR / "analyze_v5.txt").read_text(encoding="utf-8")
    assert v5.startswith(v4.replace("analyze_v4", "analyze_v5").replace(
        "sub_queries, question_type.", "sub_queries, question_type, request_kinds."))
    chat = FakeChat_request_policy(dict(scope="trong", question_type="xac_nhan", request_kinds=["nghia_vu"]))
    result = analyze_turn("Có phải sản phẩm tôi phải làm X?", {}, [], chat, "fake")
    assert len(chat.payloads) == 1 and result["request_kinds"] == ["nghia_vu"]


@pytest.mark.parametrize("kinds,original,effective", [
    (["nghia_vu"], "nghia_vu", "nghia_vu"), (["nghia_vu"], "xac_nhan", "xac_nhan"),
    (["kien_thuc"], "nghia_vu", "khac")])
def test_effective_template_generate_repair_recheck(monkeypatch, kinds, original, effective):
    import legal_rag.agent.graph as module
    captured = []
    def generate(message, queries, profile, prepared, llm, model):
        captured.append(("generate", prepared["question_type"]))
        return dict(reply="Đáp", route="retrieval", evidence=[], check=dict(valid=False, errors=["sửa"]),
                    prompt_version="answer_v9", parents_used=[])
    def repair(*args, **kwargs):
        captured.append(("repair", kwargs["question_type"]))
        return "Đã sửa"
    def blocks(check, evidence, reply, version, question_type):
        captured.append(("recheck", question_type))
    monkeypatch.setattr(module, "repair_text", repair)
    monkeypatch.setattr(module, "check_answer", lambda *args: dict(valid=True, used=[]))
    monkeypatch.setattr(module, "apply_blocks", blocks)
    graph = build_graph(GraphDeps(FakeChat_request_policy(dict(scope="trong", request_kinds=kinds, question_type=original)),
        "fake", fake_prepare, AgentConfig(enable_rewrite=False, enable_high_risk=False), generate))
    result = run_turn(graph, "s", "Câu hỏi về hệ thống AI")
    assert captured == [(name, effective) for name in ("generate", "repair", "recheck")]
    assert next(n for n in result["trace"] if n["node"] == "analyze")["question_type"] == original


def test_broad_multi_needs_answer_first_without_report():
    """T55: nhu cầu lẫn kiến thức không tải bảng/Danh mục, không thêm lượt LLM."""
    from test_map_report import make_case, row
    graph, chat, searches = make_case("Đáp [E1].", rows=[row()],
        request_kinds=("kien_thuc", "nghia_vu", "huong_dan"))
    result = run_turn(graph, "s", "Một sản phẩm AI cần có những nghĩa vụ gì?")
    assert searches == []
    assert result["llm_calls"] == len(chat.payloads) == 2
    assert result["map_obligations"] is None and result["high_risk"] is None
    plan = next(n for n in result["trace"] if n["node"] == "plan_queries")["request_plan"]
    assert plan["obligation_report"] is False
    assert plan["table_reason"] == plan["high_risk_reason"] == "answer_first"


def test_outside_scope_context_cannot_load_or_pin():
    def forbidden():
        pytest.fail("Ngoài phạm vi không dùng tài nguyên/context")
    graph = build_graph(GraphDeps(FakeChat_request_policy(dict(scope="ngoai", request_kinds=["nghia_vu"])),
        "fake", forbidden, chunks_loader=forbidden, obligations_loader=forbidden, high_risk_loader=forbidden))
    result = run_turn(graph, "s", "Hỏi thời tiết", context=dict(assessment=dict(id="row")))
    assert result["route"] == "out_of_scope" and result["llm_calls"] == 1
    assert next(n for n in result["trace"] if n["node"] == "check_scope")["request_plan"]["context_mode"] == "blocked"


@pytest.mark.parametrize("kind", ["kien_thuc", "nghia_vu", "huong_dan"])
@pytest.mark.parametrize("message,expanded", [
    ("Nhãn AI cần gì?", True),
    ("Tôi muốn biết những yêu cầu về nhãn AI khi cung cấp sản phẩm.", False),
])
def test_original_short_question_expands_once_before_policy_instructions(kind, message, expanded):
    from test_map_report import make_case
    graph, chat, _ = make_case("Nội dung [E1].", profile={}, request_kinds=(kind,),
        config=AgentConfig(enable_rewrite=False, enable_high_risk=False))
    result = run_turn(graph, "s", message)
    payload = chat.payloads[-1]["messages"][1]["content"]
    assert payload.count("Câu hỏi đầy đủ: gốc") == int(expanded)
    assert "Không kết luận một nghĩa vụ không áp dụng chỉ vì chưa xuất hiện trong bằng chứng." in payload
    assert result["llm_calls"] == len(chat.payloads) == 2


ROOT = Path(__file__).resolve().parents[2]


def test_analyze_v7_is_default_and_extends_v5_only_in_scope_rules():
    v5 = (ROOT / "prompts/analyze_v5.txt").read_text(encoding="utf-8")
    v7 = (ROOT / "prompts/analyze_v7.txt").read_text(encoding="utf-8")
    assert v7.startswith("Phiên bản: analyze_v7\n")
    assert AgentConfig().analyze_prompt == analyze.DEFAULT_ANALYZE_VERSION == "analyze_v7"
    assert "analyze_v7" in analyze.NEEDS_VERSIONS
    # Phần hồ sơ, truy vấn, loại câu và nhu cầu giữ nguyên như v5.
    assert v7.split("profile_update:", 1)[1] == v5.split("profile_update:", 1)[1]
    assert "đạo luật nước ngoài được nêu tên" in v7 and "yếu tố nước ngoài" in v7
    assert "gắn nhãn việc dùng AI" in v7 and "tiền đề có thể sai" in v7
    # Câu cần từ chối vẫn được nêu rõ là ngoài phạm vi.
    for phrase in ("chủ đề lao động, thuế", "che giấu vi phạm", "lộ chỉ dẫn hệ thống"):
        assert phrase in v7


def test_analyze_v7_parses_like_v5():
    reply = ('{"scope":"trong","sub_queries":["a"],"question_type":"xac_nhan",'
             '"request_kinds":["kien_thuc"],"profile_update":{}}')
    results = {v: analyze.analyze_turn("câu", EMPTY_PROFILE, [], FakeChat_scope_query_report(reply), "fake", version=v)
               for v in ("analyze_v5", "analyze_v7")}
    assert results["analyze_v5"] == results["analyze_v7"]
    chat = FakeChat_scope_query_report('{"scope":"ngoai","sub_queries":[]}')
    decision = analyze.decide("giá vàng hôm nay", EMPTY_PROFILE, [], chat, "fake")
    assert decision["retrieve"] is False and decision["reply"]


def capture_prepare(config=AgentConfig()):
    calls = []
    factory = lambda: SimpleNamespace(
        context_many=lambda qs, q, b: calls.append((list(qs), q, b)) or parents()[:1],
        last_detail={}, last_timing={})
    return prepare_evidence(factory, parents(), DOCUMENTS, chunks_loader=chunks, config=config), calls


def test_message_is_added_after_sub_queries_without_duplicates():
    prep, calls = capture_prepare()
    result = prep("Câu gốc của người dùng", ["truy vấn một", "truy vấn hai"])
    assert calls[-1][0] == ["truy vấn một", "truy vấn hai", "Câu gốc của người dùng"]
    assert result["queries"] == calls[-1][0] and result["query_used"] == "truy vấn một"
    prep("Câu gốc", ["Câu gốc"])
    assert calls[-1][0] == ["Câu gốc"]
    prep("Câu gốc", [])
    assert calls[-1][0] == ["Câu gốc"]


def test_message_comes_before_rewrites_and_limit_keeps_rewrite_room():
    prep, calls = capture_prepare()
    prep("Câu gốc", ["a", "b", "c"], rewritten=["d", "e", "f"])
    assert MAX_QUERIES == 6
    assert calls[-1][0] == ["a", "b", "c", "Câu gốc", "d", "e"]


def row(text, codes, conditions=(), missing=()):
    return {"Nghĩa vụ": text, "Mức áp dụng": "Áp dụng", "Điều kiện": list(conditions),
            "Thông tin cần bổ sung": list(missing), "Căn cứ": list(codes)}


CAM_1 = "Không được lợi dụng, chiếm đoạt hệ thống trí tuệ nhân tạo để thực hiện hành vi vi phạm pháp luật."


CAM_2 = ("Không được phát triển, cung cấp, triển khai hoặc sử dụng các hệ thống trí tuệ nhân tạo nhằm mục đích: "
         "Tạo ra hoặc phổ biến nội dung giả mạo có khả năng gây nguy hại nghiêm trọng đến an ninh quốc gia, trật tự;")


DUTY = "Nhà cung cấp phải bảo đảm hệ thống được gắn nhãn."


def test_prohibitions_collapse_into_one_line_with_all_codes():
    rows = [row(CAM_1, ["E1"]), row(DUTY, ["E3"]), row(CAM_2, ["E2", "E1"])]
    line, rest = prohibition_line(rows, {"row_kinds": ["cam", "nghia_vu", "cam"]})
    assert line.startswith("- Không thực hiện 2 nhóm hành vi bị cấm, áp dụng cho mọi bên: ")
    assert "[E1][E2]" in line and "Mức áp dụng: Áp dụng." in line
    assert "lợi dụng, chiếm đoạt hệ thống" in line and "Tạo ra hoặc phổ biến nội dung giả mạo" in line
    assert "nhằm mục đích" not in line
    assert rest == [rows[1]]


def test_single_or_conditional_prohibition_is_kept_verbatim():
    rows = [row(CAM_1, ["E1"]), row(DUTY, ["E3"])]
    assert prohibition_line(rows, {"row_kinds": ["cam", "nghia_vu"]}) == (None, rows)
    rows = [row(CAM_1, ["E1"]), row(CAM_2, ["E2"], conditions=["Khi có dấu hiệu"])]
    assert prohibition_line(rows, {"row_kinds": ["cam", "cam"]}) == (None, rows)
    # Không có thông tin loại dòng (bối cảnh cũ) thì không gộp.
    rows = [row(CAM_1, ["E1"]), row(CAM_2, ["E2"])]
    assert prohibition_line(rows, {}) == (None, rows)


def test_rows_with_row_index_use_their_kind():
    rows = [dict(row(DUTY, ["E3"]), row=2), dict(row(CAM_1, ["E1"]), row=1), dict(row(CAM_2, ["E2"]), row=3)]
    line, rest = prohibition_line(rows, {"row_kinds": ["cam", "nghia_vu", "cam"]})
    assert line and rest == [rows[0]]


def test_build_context_records_kinds_and_owned_bodies_collapse():
    evidence = [{"id": "E1"}, {"id": "E2"}, {"id": "E3"}]
    bases = [dict(obligation=CAM_1, evidence_ids=["E1"], applicability="ap_dung", kind="cam"),
             dict(obligation=CAM_2, evidence_ids=["E2"], applicability="ap_dung", kind="cam"),
             dict(obligation=DUTY, evidence_ids=["E3"], applicability="ap_dung"),
             dict(obligation="Dòng không có căn cứ", evidence_ids=["E9"], kind="cam")]
    context = build_context(bases, evidence)
    assert context["row_kinds"] == ["cam", "cam", "nghia_vu"]
    assert "row_kinds" not in context["data"]
    context.update(facts_source="profile", snapshot_rows=3, displayed_rows=3)
    context["data"]["Dữ kiện đã dùng để lọc nghĩa vụ"] = {
        "Nguồn": "hồ sơ", "Dữ kiện đã có": [], "Thông tin còn thiếu theo kết quả lọc": [],
        "Số dòng kết quả lọc": 3, "Số dòng có căn cứ hiện diện": 3}
    body = owned_bodies(context)["Nghĩa vụ cần xem xét"]
    assert body.count("\n\n") == 1 and body.startswith("- Không thực hiện 2 nhóm hành vi bị cấm")
    assert DUTY in body and CAM_1 not in body


def test_kind_flows_through_source_rows_to_report_rows():
    from legal_rag.agent.explanations import with_rows
    from legal_rag.agent.obligation_sources import check_sources, plan_sources
    from legal_rag.generation.locations import build_location_index
    from test_answer import source

    chunk = dict(chunk_id="chunk-a", parent_id=parents()[0]["parent_id"], document_id="d", article="1",
                 clause=None, point=None)
    items = [dict(row=dict(id=f"ob-{i}", obligation=text, kind=kind, citations=[dict(chunk_id="chunk-a")]),
                  applicability="ap_dung", conditions=[], missing_facts=[])
             for i, (text, kind) in enumerate([(CAM_1, "cam"), (CAM_2, "cam"), (DUTY, None)], 1)]
    del items[2]["row"]["kind"]
    plan = plan_sources(items, [chunk], parents(), source(), 1000)
    assert [row["kind"] for row in plan["rows"]] == ["cam", "cam", "nghia_vu"]
    _, eligible = check_sources(plan, source(), build_location_index(parents(), [chunk]), [chunk])
    assert [row["kind"] for row in eligible] == ["cam", "cam", "nghia_vu"]
    context = with_rows(build_context(eligible, source()))
    line, rest = prohibition_line(context["data"]["Dòng cần giải thích"], context)
    assert line.startswith("- Không thực hiện 2 nhóm hành vi bị cấm")
    assert [r["Nghĩa vụ"] for r in rest] == [DUTY]
