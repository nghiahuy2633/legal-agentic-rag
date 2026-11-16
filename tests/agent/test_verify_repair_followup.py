"""T21: lời gọi giả, bao gồm toàn bộ luồng kiểm chứng và ngân sách."""

import importlib.util
import json
from pathlib import Path

import pytest

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.followup import CLOSING, NOTICE, QUESTIONS, ask_followup
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.agent.verify import verify_answer
from legal_rag.generation.citations import check_answer
from legal_rag.generation.prompt import DEFAULT_VERSION, BROAD_VERSION
from legal_rag.llm import LLMError
from test_agent_graph import FakeChat, analysis

ROOT = Path(__file__).resolve().parents[2]
ITEM = dict(id="E1", parent_id="p", document_id="134-2025-QH15", document_number="134/2025/QH15",
            article="1", clause=None, article_title="Tiêu đề", document_title="Luật", source="retrieval",
            text="Nội dung.", source_url="https://example.invalid", scope_note="Phạm vi", conformity_note="Đánh giá")
ISSUE = dict(sentence="Sai [E1].", type="sai_noi_dung", evidence="E1", reason="Khác căn cứ")


def prepare(message, queries, **kwargs):
    return dict(evidence=[ITEM], queries=queries, query_used=queries[0], references_added=[], detail={}, timing={},
                index=set(), chunks=[])


def generator(message, queries, profile, prepared, chat, model):
    reply = chat.complete(dict(model=model, messages=[dict(role="user", content=message)]))
    return dict(reply=reply, route="retrieval", evidence=[ITEM], check=check_answer(reply, [ITEM]),
                prompt_version="answer_v8", parents_used=["p"])


def case(*responses, enabled=True, request_kinds=()):
    chat = FakeChat(analysis(request_kinds=list(request_kinds)), *responses)
    graph = build_graph(GraphDeps(chat, "fake", prepare,
        AgentConfig(enable_rewrite=False, enable_verifier=enabled, verifier_mode="rule_llm"), generator))
    return run_turn(graph, "s", "Nghĩa vụ AI là gì?"), chat, graph


@pytest.mark.parametrize("response,ok,issues", [
    ("hỏng", False, []), ("[]", False, []), ({}, True, []), ({"issues": None}, True, []),
    ({"issues": "sai"}, False, []),
    ({"issues": [ISSUE, dict(ISSUE, type="lạ"), {"type": "sai_ma"}, dict(ISSUE, type=[])]}, True, [ISSUE]),
])
def test_verifier_parse_and_only_used_full_evidence(response, ok, issues):
    chat = FakeChat(response)
    result = verify_answer("Nội dung [E1.b] [E1, E3.đ].", [ITEM, dict(ITEM, id="E2")], chat, "fake")
    assert result == dict(issues=issues, verify_ok=ok)
    payload = chat.payloads[0]
    assert len(chat.payloads) == 1 and payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    items = json.loads(payload["messages"][1]["content"])["evidence"]
    assert len(items) == 1
    for key in ("text", "scope_note", "conformity_note", "article_title", "document_title"):
        assert items[0][key] == ITEM[key]


def test_no_issue_no_repair():
    result, chat, _ = case("Đúng [E1].", {})
    assert len(chat.payloads) == 3 and not result["verification"]["repaired"]
    assert "repair_answer" not in [n["node"] for n in result["trace"]]


@pytest.mark.parametrize("answer,issues", [("Sai [E99].", []), ("Sai [E1].", [ISSUE])])
def test_one_repair_then_rules_only(answer, issues):
    result, chat, _ = case(answer, dict(issues=issues), "Đúng [E1].\n\n" + CLOSING)
    assert result["verification"] == dict(issues=issues, repaired=True, final_valid=True)
    assert NOTICE not in result["reply"] and len(chat.payloads) == 4
    assert sum(n["node"] == "verify_citations" for n in result["trace"]) == 1
    assert result["check"]["used"] == ["E1"]


@pytest.mark.parametrize("repair", ["Sai [E99].\n\n" + CLOSING, "", LLMError("lỗi sửa")])
def test_repair_failure_notice_once_before_closing(repair):
    old = "Sai [E1].\n\n" + CLOSING
    result, chat, _ = case(old, dict(issues=[ISSUE]), repair)
    assert result["reply"].count(NOTICE) == 1 and result["reply"].endswith(CLOSING)
    if not isinstance(repair, str) or not repair:
        assert result["reply"].startswith("Sai [E1].")
        assert next(n for n in result["trace"] if n["node"] == "repair_answer")["repair_error"]
        assert not result["verification"]["repaired"]


def test_verify_error_and_disabled_verifier():
    result, chat, _ = case("Đúng [E1].", LLMError("lỗi kiểm"))
    assert result["error"] is None
    assert next(n for n in result["trace"] if n["node"] == "verify_citations")["verify_error"]
    result, chat, _ = case("Sai [E99].", "Đúng [E1].", enabled=False)
    assert len(chat.payloads) == 3 and result["verification"]["repaired"]


def test_default_rewrite_six_calls():
    chat = FakeChat(analysis(sub_queries=["gốc"]),
        dict(status="thieu_mot_phan", rewrite=["một"]),
        dict(status="thieu_mot_phan", rewrite=["hai"]),
        "Sai [E1].", dict(issues=[ISSUE]), "Đúng [E1].")
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(verifier_mode="rule_llm"), generate_fn=generator))
    result = run_turn(graph, "s", "Nghĩa vụ AI là gì?")
    assert result["llm_calls"] == len(chat.payloads) == 6
    assert result["verification"]["repaired"]
    assert sum(n["node"] == "recheck" for n in result["trace"]) == 1


def test_exhausted_repair_keeps_answer_and_records_error():
    def spend(message, qs, profile, prepared, chat, model):
        result = generator(message, qs, profile, prepared, chat, model)
        for _ in range(5):
            chat.complete(dict(model=model))
        return result
    chat = FakeChat(analysis(), "Sai [E1].", *(["phụ"] * 5), dict(issues=[ISSUE]))
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False, verifier_mode="rule_llm"), spend))
    result = run_turn(graph, "s", "Nghĩa vụ AI là gì?")
    assert result["llm_calls"] == len(chat.payloads) == 8
    assert NOTICE in result["reply"] and not result["verification"]["repaired"]
    assert next(n for n in result["trace"] if n["node"] == "repair_answer")["repair_error"]


@pytest.mark.parametrize("profile,field", [(EMPTY_PROFILE, "role"),
    (dict(EMPTY_PROFILE, role="nha_cung_cap"), "product_description"),
    (dict(EMPTY_PROFILE, role="nha_cung_cap", product_description="AI"), "sector")])
def test_followup_order(profile, field):
    update, asked = ask_followup(dict(message="Nghĩa vụ AI?", profile=profile,
        reply="Đúng [E1].\n\n" + CLOSING, route="retrieval"))
    assert asked == field and update["followup_asked"]
    assert update["reply"].endswith(QUESTIONS[field] + "\n\n" + CLOSING)


@pytest.mark.parametrize("extra,asked", [
    (dict(message="Điều 11 là gì?"), False), (dict(followup_asked=True), False),
    (dict(reply="Bạn làm gì?\n\n" + CLOSING), True), (dict(route="error"), False),
    (dict(reply="Bạn làm gì?\n\n" + NOTICE + "\n\n" + CLOSING), True),
    (dict(profile=dict(EMPTY_PROFILE, role="nha_cung_cap", product_description="AI", sector="y_te")), False),
])
def test_followup_skip(extra, asked):
    update, field = ask_followup(dict(message="Nghĩa vụ AI?", profile=EMPTY_PROFILE,
        reply="Đúng [E1].\n\n" + CLOSING, route="retrieval") | extra)
    assert field is None and update == ({"followup_asked": True} if asked else {})


@pytest.mark.parametrize("part", ["thời tiết", None])
def test_followup_persists_and_partial_scope_in_generation(part):
    chat = FakeChat(analysis("mot_phan", out_of_scope_part=part, request_kinds=["nghia_vu"]), "Đúng [E1].", {},
                    analysis(request_kinds=["nghia_vu"]), "Đúng [E1].", {})
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False, verifier_mode="rule_llm"), generator))
    first = run_turn(graph, "s", "Nghĩa vụ AI và thời tiết?")
    assert QUESTIONS["role"] in first["reply"]
    assert ("Không trả lời phần sau vì ngoài phạm vi: " + (part or "phần ngoài phạm vi của câu hỏi")) in chat.payloads[1]["messages"][0]["content"]
    second = run_turn(graph, "s", "Còn nghĩa vụ AI nào?")
    assert QUESTIONS["role"] not in second["reply"]


@pytest.mark.parametrize("phrase", ["pháp luật không quy định", "pháp luật hiện hành không quy định", "luật không quy định"])
def test_negative_warning_only(phrase):
    check = check_answer(phrase + " [E1].", [ITEM])
    assert check["valid"] and check["warnings"] == ["Khẳng định phủ định về pháp luật: " + phrase]


@pytest.mark.parametrize("phrase", ["không nêu", "không chứa thông tin"])
def test_new_refusal_phrases(phrase):
    assert check_answer("Bằng chứng " + phrase, [ITEM])["valid"]


def test_eval_dry_run_does_not_read_settings(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("eval_verifier", ROOT / "scripts/eval_verifier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_llm_settings", lambda: pytest.fail("không đọc LLM"))
    assert module.main(["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out) == dict(total=13, bat=7, dat=6)


def test_recheck_uses_location_index_and_blocks(monkeypatch):
    import legal_rag.agent.graph as module
    from legal_rag.generation.locations import build_location_index
    chunk = dict(document_id=ITEM["document_id"], article="1", clause=None, point=None)
    index = build_location_index([], [chunk])
    items = [dict(ITEM, block="một"), dict(ITEM, id="E2", block="hai")]
    def prep(message, qs, **kwargs):
        return dict(prepare(message, qs, **kwargs), evidence=items, index=index, chunks=[chunk])
    def gen(*args):
        return dict(generator(*args), evidence=items)
    original = module.check_answer
    seen = []
    def check(answer, evidence, passed_index, chunks):
        seen.append((passed_index, chunks))
        return original(answer, evidence, passed_index, chunks)
    monkeypatch.setattr(module, "check_answer", check)
    chat = FakeChat(analysis(), "Sai [E1].", dict(issues=[ISSUE]), "Khoản 9 Điều 1 [E1].")
    graph = build_graph(GraphDeps(chat, "fake", prep, AgentConfig(enable_rewrite=False, verifier_mode="rule_llm"), gen))
    result = run_turn(graph, "s", "Nghĩa vụ AI?")
    assert seen == [(index, [chunk])]
    assert result["check"]["errors"] and result["check"]["missing_blocks"] == ["hai"]
    assert not result["verification"]["final_valid"] and NOTICE in result["reply"]


def test_followup_without_closing_and_location_does_not_set_session_flag():
    result, _, graph = case("Đúng [E1].", {}, request_kinds=("nghia_vu",))
    assert result["answer"].endswith(QUESTIONS["role"])
    assert result["reply"].endswith(CLOSING)
    chat = FakeChat(analysis(), "Đúng [E1].", {})
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False), generator))
    run_turn(graph, "s", "Điều 11 là gì?")
    assert not graph.get_state({"configurable": {"thread_id": "s"}}).values["followup_asked"]


def test_eval_fake_errors_continue_and_cache(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("eval_verifier_fake", ROOT / "scripts/eval_verifier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("eval/verifier_traps.jsonl", "data/processed/parents.jsonl", "data/source_registry/documents.csv"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    monkeypatch.setattr(module, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://example.invalid", api_key="fake", model="fake", fallback_models=("backup",)))
    calls = []
    def client(url, key, **kwargs):
        assert kwargs == {"max_attempts": 3}
        def complete(payload):
            calls.append(payload)
            if len(calls) == 1:
                raise LLMError("lỗi giả")
            if len(calls) == 2:
                return "hỏng"
            return json.dumps(dict(issues=[]))
        return SimpleNamespace(complete=complete)
    assert module.main([], root=tmp_path, client_factory=client) == 0
    report = json.loads((tmp_path / "runs/t21/verifier.json").read_text(encoding="utf-8"))
    assert len(report["results"]) == 13 and report["errors"] == 2
    assert report["catch_rate"] == 0 and report["false_positive_rate"] == 0
    assert not report["results"][0]["correct"] and not report["results"][1]["correct"]
    assert (tmp_path / ".cache/llm").exists()
    assert all("issues" in r for r in report["mismatches"])
    assert "lỗi giả" in capsys.readouterr().out


def test_checkpoint_excludes_shared_chunks_and_index():
    from legal_rag.agent.config import AgentConfig
    from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
    from legal_rag.agent.profile import EMPTY_PROFILE
    item = dict(id="E1", parent_id="p", document_id="d", document_number="1/2026/X", document_title="t",
                article="1", article_title="t", clause=None, text="nội dung", source_url="u", source="retrieval")
    seen = {}

    def prepare(message, sub_queries, **kwargs):
        return dict(route="retrieval", evidence=[item], prompt_version="answer_v6", parents_used=["p"],
                    query_used=message, queries=[message], rerank_query=message, references_added=[],
                    detail={}, timing={}, index={("d", "1")}, chunks=[dict(chunk_id="c")])

    def generate(message, sub_queries, profile, prepared, chat, model):
        seen["index"], seen["chunks"] = prepared.get("index"), prepared.get("chunks")
        reply = chat.complete(dict(model=model, messages=[]))
        return dict(reply=reply, route="retrieval", evidence=[item], check=dict(valid=True, errors=[], used=["E1"], warnings=[]),
                    prompt_version="answer_v6", parents_used=["p"], query_used=message, references_added=[])

    class Chat:
        last_model, attempts = "m", []
        def __init__(self):
            self.answers = iter(['{"scope":"trong","sub_queries":["q"]}', '{"status":"du"}', "Nội dung [E1]", '{"issues":[]}'])
        def complete(self, payload):
            return next(self.answers)

    graph = build_graph(GraphDeps(Chat(), "m", prepare_fn=prepare, generate_fn=generate, config=AgentConfig()))
    run_turn(graph, "s", "Câu hỏi về nghĩa vụ")
    assert seen["index"] == {("d", "1")} and seen["chunks"] == [dict(chunk_id="c")]
    values = graph.get_state({"configurable": {"thread_id": "s"}}).values
    assert "chunks" not in (values.get("prepared") or {}) and "index" not in (values.get("prepared") or {})


def test_verify_v2_only_explains_point_citation():
    old = (ROOT / "prompts/verify_v1.txt").read_text(encoding="utf-8").splitlines()
    new = (ROOT / "prompts/verify_v2.txt").read_text(encoding="utf-8").splitlines()
    assert new[0] == "Phiên bản: verify_v2"
    added = [line for line in new[1:] if line not in old]
    assert len(added) == 1 and "[E3.b]" in added[0] and len(new) == len(old) + 1
