"""T19: hội thoại với LLM giả, không tải model hay gọi mạng."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from answer_support import composed_answer
from legal_rag.agent.answer import AGENT_ANSWER_VERSION
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.budget import BudgetChat, LLMBudgetExceeded
from legal_rag.agent.graph import GraphDeps, LLM_ERROR_REPLY, build_graph, run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError
from test_basic_rag import DOCUMENTS, cli_root, parents
from test_broad_frame import real_parents
from test_llm import response

ROOT = Path(__file__).resolve().parents[2]
FULL_PATH = ["check_input", "analyze", "check_scope", "update_profile", "plan_queries", "retrieve", "grade_evidence", "check_high_risk", "map_obligations", "generate", "verify_citations", "ask_followup", "respond"]


class FakeChat:
    api_key = "t19-secret"

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.payloads = []
        self.last_model = None
        self.attempts = []

    def complete(self, payload):
        self.payloads.append(payload)
        self.last_model = None
        self.attempts = [{"model": payload["model"], "status": None}]
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        self.last_model = payload["model"]
        return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result


def analysis(scope="trong", **kwargs):
    return dict(scope=scope, **kwargs)


def fake_answer(calls):
    def answer(message, sub_queries, profile, prepared, chat, model):
        calls.append((message, sub_queries, dict(profile), chat.calls))
        reply = chat.complete({"model": model, "messages": [{"role": "user", "content": message}]})
        return dict(reply=reply, route="retrieval", evidence=[{"id": "E1", "parent_id": "parent", "source": "retrieval", "document_number": "1/2026", "article_title": "Tiêu đề", "source_url": "https://example.invalid"}],
                    check={"used": ["E1"], "valid": True}, prompt_version="answer_v2",
                    parents_used=["parent"], query_used=sub_queries[0], references_added=[])
    return answer


def fake_prepare(message, queries, **kwargs):
    return dict(evidence=[], queries=queries, query_used=queries[0], references_added=[], detail={}, timing={})


def make_graph(*responses):
    chat, calls = FakeChat(*responses), []
    return build_graph(GraphDeps(chat, "fake", fake_prepare, AgentConfig(enable_rewrite=False, enable_verifier=False), fake_answer(calls))), chat, calls


def state(graph, session="s"):
    return graph.get_state({"configurable": {"thread_id": session}}).values


def assert_trace(result, nodes):
    assert [item["node"] for item in result["trace"]] == nodes
    assert all(item["ms"] >= 0 and item["llm_calls"] >= 0 for item in result["trace"])
    assert sum(item["llm_calls"] for item in result["trace"]) == result["llm_calls"]
    raw = json.dumps(result["trace"])
    assert all(secret not in raw for secret in ("api_key", "t19-secret", "client", "settings"))


@pytest.mark.parametrize("message", ["", "xin chào", "123 !!!", "a" * 4001])
def test_guard_never_calls_llm_or_answer(message):
    graph, chat, calls = make_graph()
    result = run_turn(graph, "s", message)
    assert result["route"] == "input_rejected" and result["llm_calls"] == 0
    assert not chat.payloads and not calls
    assert result["profile"] == EMPTY_PROFILE
    assert len(state(graph)["messages"]) == 2
    assert_trace(result, ["check_input", "respond"])


def test_outside_scope_preserves_profile_and_skips_answer():
    graph, chat, calls = make_graph(analysis(profile_update={"role": "nha_cung_cap"}), "Trả lời",
                                     analysis("ngoai", profile_update={"role": "nguoi_su_dung"}))
    first = run_turn(graph, "s", "Tôi cung cấp AI")
    result = run_turn(graph, "s", "Hỏi thời tiết")
    assert result["route"] == "out_of_scope" and result["llm_calls"] == 1
    assert result["profile"] == first["profile"] and len(calls) == 1
    assert result["evidence"] == [] and result["check"] is None
    assert len(chat.payloads) == 3
    assert_trace(result, ["check_input", "analyze", "check_scope", "respond"])


def test_partial_scope_prefix_and_profile_trace():
    graph, _, calls = make_graph(analysis("mot_phan", out_of_scope_part="dự báo thời tiết",
        profile_update={"sector": "y_te", "unknown": True}, sub_queries=["truy vấn"]), "Trả lời [E1]")
    result = run_turn(graph, "s", "Nghĩa vụ AI y tế và thời tiết")
    assert result["reply"].startswith("Phần ngoài phạm vi (dự báo thời tiết) không được trả lời.\n\n")
    assert result["reply"].count("không được trả lời") == 1
    assert calls[0][1] == ["truy vấn"] and result["llm_calls"] == 2
    update = result["trace"][3]
    assert update["before"] == EMPTY_PROFILE
    assert update["after"]["sector"] == "y_te" and update["ignored"] == ["unknown"]
    assert result["trace"][4]["sub_queries"] == ["truy vấn"]
    assert_trace(result, FULL_PATH)


def test_history_profile_sessions_last_four_and_budget_reset():
    graph, chat, calls = make_graph(
        analysis(profile_update={"role": "nha_cung_cap"}), "đáp một",
        analysis(profile_update={"sector": "giao_duc"}), "đáp hai",
        analysis(), "đáp ba", analysis(), "đáp khác", analysis(), "đáp bốn")
    run_turn(graph, "s", "Tôi cung cấp AI")
    second = run_turn(graph, "s", "Trong giáo dục")
    data = json.loads(chat.payloads[2]["messages"][1]["content"].split("\n", 1)[1])
    assert data["recent_messages"] == [
        {"role": "user", "content": "Tôi cung cấp AI"},
        {"role": "assistant", "content": state(graph)["messages"][1]["content"]}]
    assert second["profile"]["role"] == "nha_cung_cap" and second["profile"]["sector"] == "giao_duc"
    run_turn(graph, "s", "Câu hỏi ba")
    other = run_turn(graph, "other", "Câu hỏi khác")
    assert other["profile"] == EMPTY_PROFILE
    other_data = json.loads(chat.payloads[6]["messages"][1]["content"].split("\n", 1)[1])
    assert other_data["recent_messages"] == []
    fourth = run_turn(graph, "s", "Câu hỏi bốn")
    data = json.loads(chat.payloads[8]["messages"][1]["content"].split("\n", 1)[1])
    assert data["recent_messages"] == state(graph)["messages"][2:6]
    assert len(data["recent_messages"]) == 4
    assert fourth["llm_calls"] == 2 and all(call[3] == 1 for call in calls)
    assert_trace(fourth, FULL_PATH)


def test_llm_errors_are_recorded_history_retained_and_session_reusable():
    graph, _, calls = make_graph(analysis(profile_update={"role": "nha_cung_cap"}), "đáp",
                                 LLMError("lỗi phân tích"), analysis(), LLMError("lỗi trả lời"),
                                 analysis(), "thử lại thành công")
    first = run_turn(graph, "s", "Tôi cung cấp AI")
    failed = run_turn(graph, "s", "Hỏi tiếp")
    assert failed["route"] == "error" and failed["reply"] == LLM_ERROR_REPLY
    assert failed["profile"] == first["profile"] and failed["error"] == "lỗi phân tích"
    assert failed["evidence"] == [] and failed["check"] is None
    assert len(state(graph)["messages"]) == 4 and len(calls) == 1
    assert_trace(failed, ["check_input", "analyze", "respond"])
    failed = run_turn(graph, "s", "Hỏi lần nữa")
    assert failed["route"] == "error" and failed["error"] == "lỗi trả lời"
    assert_trace(failed, FULL_PATH[:-3] + ["respond"])
    success = run_turn(graph, "s", "Thử lại")
    assert success["error"] is None and success["check"]["valid"]
    assert state(graph)["prompt_version"] == "answer_v2"
    rejected = run_turn(graph, "s", "xin chào")
    assert rejected["error"] is None and rejected["check"] is None and rejected["evidence"] == []
    assert state(graph)["analysis"] is None and state(graph)["prompt_version"] is None
    assert rejected["llm_calls"] == 0 and len(state(graph)["messages"]) == 10


def test_other_errors_still_raise():
    graph, _, _ = make_graph(ValueError("lỗi lập trình"))
    with pytest.raises(ValueError, match="lỗi lập trình"):
        run_turn(graph, "s", "Nghĩa vụ AI")


def test_budget_counts_cache_fallback_and_reset(tmp_path):
    client_calls = []
    def complete(payload):
        client_calls.append(payload)
        if payload["model"] == "primary":
            raise LLMError("quá tải", status=503)
        return "đáp"
    fallback = FallbackChat(CachedChat(SimpleNamespace(complete=complete), tmp_path), ("backup",))
    chat = BudgetChat(fallback)
    for _ in range(8):
        assert chat.complete({"model": "primary"}) == "đáp"
    assert chat.calls == 8 and len(client_calls) == 2 and fallback.cache_hits == 7
    assert chat.last_model == "backup" and chat.attempts == []
    assert chat.history[0]["attempts"] == [{"model": "primary", "status": 503},
                                            {"model": "backup", "status": None}]
    with pytest.raises(LLMBudgetExceeded):
        chat.complete({"model": "primary"})
    assert len(client_calls) == 2 and chat.calls == 8
    chat.reset()
    assert chat.calls == 0 and chat.history == []
    chat.complete({"model": "primary"})
    assert chat.calls == 1


def test_graph_budget_exhaustion_is_error_and_next_turn_starts_fresh():
    chat = FakeChat(analysis(), *(["đáp"] * 7), analysis(), *(["đáp"] * 7))
    def too_many(message, queries, profile, prepared, chat, model):
        for _ in range(8):
            chat.complete({"model": model})
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare, AgentConfig(enable_rewrite=False, enable_verifier=False), too_many))
    for _ in range(2):
        result = run_turn(graph, "s", "Nghĩa vụ AI")
        assert result["route"] == "error" and result["llm_calls"] == 8
        assert result["trace"][-2]["llm_calls"] == 7
    assert len(chat.payloads) == 16


def test_composed_answer_query_profile_and_lazy_reuse():
    created, contexts = [], []
    def factory():
        created.append(1)
        return SimpleNamespace(context_many=lambda qs, q, b: contexts.append((qs, q, b)) or parents()[:1], last_detail={}, last_timing={})
    answer = composed_answer(factory, parents(), DOCUMENTS, budget=123)
    chat = FakeChat("Nội dung [E1]", "Nội dung [E1]")
    profile = dict(EMPTY_PROFILE, role="nha_cung_cap", is_public_sector=False)
    for _ in range(2):
        result = answer("Câu hỏi gốc", ["truy vấn đầu", "truy vấn sau"], profile, chat, "fake")
        assert result["route"] == "retrieval" and result["prompt_version"] == AGENT_ANSWER_VERSION == "answer_v2"
        assert result["check"]["valid"]
    assert created == [1] and contexts == [(["truy vấn đầu", "truy vấn sau", "Câu hỏi gốc"], "Câu hỏi gốc", 123)] * 2
    question = chat.payloads[0]["messages"][1]["content"]
    assert question.startswith("Câu hỏi:\nCâu hỏi gốc\n\nThông tin đã biết về tình huống:")
    assert "Vai trò: nhà cung cấp" in question and "Thuộc khu vực công: không" in question
    assert "Câu hỏi đầy đủ: truy vấn đầu" in question


def test_basic_broad_answer_skips_pipeline_and_checks_blocks():
    def forbidden():
        pytest.fail("không tạo pipeline")
    documents = {"134-2025-QH15": DOCUMENTS[0]}
    chat = FakeChat("Nội dung [E1]")
    result = composed_answer(forbidden, real_parents(), documents, budget=0)(
        "Một sản phẩm AI cần có những nghĩa vụ gì?", ["truy vấn"], EMPTY_PROFILE, chat, "fake")
    assert result["route"] == "broad_frame" and result["prompt_version"] == "answer_v7"
    assert len(result["evidence"]) == 22
    assert result["check"]["valid"] is False and len(result["check"]["missing_blocks"]) == 3
    assert "Thông tin đã biết" not in chat.payloads[0]["messages"][1]["content"]


def load_chat():
    spec = importlib.util.spec_from_file_location("chat_t19", ROOT / "scripts/chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_error_then_guard_then_recovery_default_session(tmp_path, monkeypatch, capsys):
    draft_obligations(monkeypatch)
    module = load_chat()
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="https://example.invalid", api_key="t19-secret"))
    replies = iter([json.dumps(analysis()), "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]", LLMError("lỗi tạm thời"),
                    json.dumps(analysis()), "## Trả lời ngắn\nThử lại [E1]\n\n## Căn cứ\nThử lại [E1]"])
    def client(url, key):
        def complete(payload):
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return result
        return SimpleNamespace(complete=complete)
    def pipeline(chunks, units):
        return SimpleNamespace(context_many=lambda queries, query, budget: units[:1], last_detail={}, last_timing={})
    root = cli_root(tmp_path)
    assert module.main(["--no-verifier", "--no-rewrite", "--message", "Câu hỏi AI", "--message", "Câu hỏi lỗi",
                        "--message", "xin chào", "--message", "Thử lại AI"], root, pipeline, client) == 0
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((root / "runs/traces").glob("*.json"))]
    assert [r["route"] for r in records] == ["retrieval", "error", "input_rejected", "retrieval"]
    assert all(r["session_id"] == "demo" for r in records)
    assert records[1]["model"] is None and records[1]["error"] == "lỗi tạm thời"
    assert records[2]["model"] is None and records[2]["llm_attempts"] == []
    assert records[2]["evidence"] == [] and records[2]["check"] is None
    assert records[2]["prompt_version"] is None and records[3]["error"] is None
    assert "t19-secret" not in capsys.readouterr().out + json.dumps(records)


def draft_obligations(monkeypatch):
    """Kho dữ liệu giả không có chunk của bảng thật: dùng bảng thật ở trạng thái toàn nháp."""
    from legal_rag.agent import runtime
    real = runtime.load_obligations
    monkeypatch.setattr(runtime, "load_obligations",
                        lambda path: [dict(row, review_status="ai_draft") for row in real(path)])


@pytest.mark.parametrize("interactive", [False, True])
def test_chat_cli_two_messages_fake_client_pipeline(tmp_path, monkeypatch, capsys, interactive):
    from io import StringIO
    module, created, payloads = load_chat(), [], []
    draft_obligations(monkeypatch)
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="https://example.invalid", api_key="t19-secret", fallback_models=("backup",)))
    def client(url, key, **kwargs):
        assert kwargs == {"max_attempts": 3}
        def complete(payload):
            payloads.append(payload)
            if "response_format" in payload:
                return json.dumps(analysis(profile_update={"role": "nha_cung_cap"}))
            return "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]"
        return SimpleNamespace(complete=complete)
    def pipeline(chunks, units):
        created.append(1)
        return SimpleNamespace(context_many=lambda queries, query, budget: units[:1], last_detail={}, last_timing={})
    root = cli_root(tmp_path)
    trace_dir = root / "runs/custom"
    args = ["--no-verifier", "--no-rewrite", "--session", "test-session", "--trace-dir", str(trace_dir)]
    if interactive:
        monkeypatch.setattr(module.sys, "stdin", StringIO("Câu hỏi AI\nHỏi tiếp AI\n"))
    else:
        args += ["--no-rewrite", "--message", "Câu hỏi AI", "--message", "Hỏi tiếp AI"]
    assert module.main(args, root, pipeline, client) == 0
    assert created == [1] and len(payloads) == 4
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(trace_dir.glob("*.json"))]
    assert len(records) == 2
    for record in records:
        assert record["session_id"] == "test-session" and record["llm_calls"] == 2
        assert record["conversation"] == [{"role": "user", "content": record["query"]},
                                       {"role": "assistant", "content": record["reply"]}]
        assert len(record["llm_attempts"]) == 2 and record["model"] == "fake"
        assert [n["node"] for n in record["nodes"]] == FULL_PATH
    history = json.loads(payloads[2]["messages"][1]["content"].split("\n", 1)[1])["recent_messages"]
    assert history == records[0]["conversation"]
    raw = json.dumps(records) + capsys.readouterr().out
    assert "t19-secret" not in raw and "api_key" not in raw


@pytest.mark.parametrize("error_type", [URLError, OSError, TimeoutError])
@pytest.mark.parametrize("recover", [False, True])
def test_connection_retries_hide_secret_and_stop(error_type, recover):
    attempts, waits = [], []
    def opener(*args, **kwargs):
        attempts.append(1)
        if recover and len(attempts) == 3:
            return response("đáp")
        raise error_type("t19-secret")
    client = HTTPChatClient("https://example.invalid", "t19-secret", opener=opener,
                            sleep=waits.append, max_attempts=3)
    if recover:
        assert client.complete({}) == "đáp"
    else:
        with pytest.raises(LLMError) as caught:
            client.complete({})
        assert caught.value.status is None
        assert str(caught.value) == "Không kết nối được endpoint LLM."
        assert caught.value.__suppress_context__
    assert client.request_count == len(attempts) == 3 and len(waits) == 2
    assert all(base <= wait <= base + 1 for base, wait in zip([1, 2], waits))
