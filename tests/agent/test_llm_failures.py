"""T30: HTTP, cache, đồ thị thật và API; chỉ dùng client/pipeline giả."""

from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import HTTPError

from fastapi.testclient import TestClient
import pytest

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.followup import NOTICE
from legal_rag.agent.graph import GraphDeps, LLM_ERROR_REPLY, build_graph, llm_error_reply, run_turn
from legal_rag.api.app import create_app
from legal_rag.api.service import ChatService
from legal_rag.config import LLMSettings
from legal_rag.evaluation.run import is_429
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError, QuotaExhaustedError
from test_agent_graph import analysis, fake_answer, fake_prepare, make_graph
from test_map_report import assessment, make_case


@pytest.mark.parametrize("array", [False, True])
@pytest.mark.parametrize("duration,seconds", [("5h6m6.39s", 18366.39), ("30s", 30),
    ("2h", 7200), ("4m", 240), ("later", None)])
def test_daily_quota_no_retry_or_sleep_and_redaction(array, duration, seconds):
    calls, waits = [], []
    def opener(request, **kwargs):
        calls.append(json.loads(request.data))
        body = {"error": {"message": f"secret Requests PER DAY limit exceeded; Please retry in {duration}."}}
        raise HTTPError(request.full_url, 429, "secret", {}, BytesIO(json.dumps([body] if array else body).encode()))
    client = HTTPChatClient("https://example.invalid", "secret", opener=opener, sleep=waits.append)
    payload = {"model": "main", "temperature": 0}
    with pytest.raises(QuotaExhaustedError) as caught:
        client.complete(payload)
    assert caught.value.status == 429 and caught.value.retry_after == seconds
    assert calls == [payload] and not waits and client.request_count == 1
    assert "secret" not in str(caught.value) and "[REDACTED]" in str(caught.value)
    assert is_429({"error": str(caught.value)})


@pytest.mark.parametrize("status", [400, 429, 503])
def test_array_detail_is_limited_and_other_429_still_retries(status):
    calls, waits = [], []
    def opener(request, **kwargs):
        calls.append(1)
        body = [{"error": {"message": "secret " + "x" * 2500}}]
        raise HTTPError(request.full_url, status, "secret", {}, BytesIO(json.dumps(body).encode()))
    client = HTTPChatClient("https://example.invalid", "secret", opener=opener,
                            sleep=waits.append, max_attempts=3)
    with pytest.raises(LLMError) as caught:
        client.complete({})
    assert not isinstance(caught.value, QuotaExhaustedError)
    assert len(calls) == (1 if status == 400 else 3)
    assert len(waits) == len(calls) - 1
    detail = str(caught.value).split("[REDACTED]", 1)[1]
    assert len("[REDACTED]" + detail) == 2000 and "secret" not in str(caught.value)


def test_fallback_skip_expiry_all_quota_and_cache_first(tmp_path):
    now, sent = [100.0], []
    payload = {"model": "main", "messages": [], "temperature": 0}
    def complete(data):
        sent.append(dict(data))
        raise QuotaExhaustedError(retry_after=30 if data["model"] == "main" else 60)
    cache = CachedChat(SimpleNamespace(complete=complete), tmp_path)
    chat = FallbackChat(cache, ("backup",), clock=lambda: now[0])
    with pytest.raises(QuotaExhaustedError) as caught:
        chat.complete(payload)
    assert caught.value.retry_after == 30
    assert sent == [payload, dict(payload, model="backup")]
    assert [a["status"] for a in chat.attempts] == [429, 429]
    now[0] += 10
    with pytest.raises(QuotaExhaustedError) as caught:
        chat.complete(payload)
    assert caught.value.retry_after == 20 and len(sent) == 2
    assert [a["status"] for a in chat.attempts] == ["skipped_quota", "skipped_quota"]
    assert is_429({"error": str(caught.value), "llm_attempts": chat.attempts})
    # Ghi bằng chính khóa cache cũ, không thêm dữ liệu cooldown vào payload.
    cache._path(dict(payload, model="backup")).write_text(json.dumps("đáp từ cache"), encoding="utf-8")
    assert chat.complete(payload) == "đáp từ cache"
    assert chat.last_model == "backup" and chat.attempts == [] and len(sent) == 2
    now[0] = 130
    with pytest.raises(QuotaExhaustedError):
        chat.complete(dict(payload, messages=[{"role": "user", "content": "mới"}]))
    assert len(sent) == 3 and sent[-1]["model"] == "main"
    assert [a["status"] for a in chat.attempts] == [429, "skipped_quota"]


def test_fallback_default_hour_and_successful_backup(tmp_path):
    now, sent = [0], []
    def complete(payload):
        sent.append(payload["model"])
        if payload["model"] == "main":
            raise QuotaExhaustedError()
        return "đáp"
    chat = FallbackChat(CachedChat(SimpleNamespace(complete=complete), tmp_path), ("backup",), clock=lambda: now[0])
    for turn in range(2):
        assert chat.complete({"model": "main", "turn": turn}) == "đáp"
    assert sent == ["main", "backup", "backup"]
    assert [a["status"] for a in chat.attempts] == ["skipped_quota", None]
    now[0] = 3600
    chat.complete({"model": "main", "turn": 3})
    assert sent[-2:] == ["main", "backup"]


def test_single_model_default_hour_no_requests_during_wait(tmp_path):
    now, sent = [0], []
    def complete(payload):
        sent.append(payload)
        raise QuotaExhaustedError()
    chat = FallbackChat(CachedChat(SimpleNamespace(complete=complete), tmp_path), clock=lambda: now[0])
    for moment, remaining in [(0, 3600), (100, 3500), (3599, 1), (3600, 3600)]:
        now[0] = moment
        with pytest.raises(QuotaExhaustedError) as caught:
            chat.complete({"model": "main"})
        assert caught.value.retry_after == remaining
    assert len(sent) == chat.request_count == 2


@pytest.mark.parametrize("quota_first", [False, True])
def test_mixed_fallback_failure_keeps_nonquota_error(tmp_path, quota_first):
    def complete(payload):
        if (payload["model"] == "main") == quota_first:
            raise QuotaExhaustedError(retry_after=60)
        raise LLMError("HTTP 503", status=503)
    chat = FallbackChat(CachedChat(SimpleNamespace(complete=complete), tmp_path), ("backup",))
    for _ in range(2):
        with pytest.raises(LLMError) as caught:
            chat.complete({"model": "main"})
        assert caught.value.status == 503


JSON_NODES = ("analyze", "grade_evidence", "check_high_risk", "verify_citations")
NODES = (*JSON_NODES, "generate", "repair_answer")
CASES = [(node, kind) for node in NODES for kind in
         (("json", "missing", "empty", "503", "429", "quota") if node in JSON_NODES
          else ("empty", "503", "429", "quota"))]


def failure(kind):
    if kind == "quota":
        return QuotaExhaustedError("PRIVATE C:/internal/key", retry_after=18366.39)
    if kind in ("503", "429"):
        return LLMError("PRIVATE C:/internal/key", status=int(kind))
    return {"json": "{broken", "missing": "{}", "empty": ""}[kind]


def responses(target=None, kind=None):
    values = {
        "analyze": analysis(request_kinds=["nghia_vu"]), "grade_evidence": dict(status="du"),
        "check_high_risk": assessment(basis="Robot y tế"), "generate": "Nội dung [E1].",
        "verify_citations": dict(issues=[]), "repair_answer": "Nội dung [E1]."}
    if target == "repair_answer":
        values["verify_citations"] = dict(issues=[dict(sentence="Nội dung [E1].", type="sai_muc_do",
                                                       evidence="E1", reason="Cần soát")])
    if target:
        values[target] = failure(kind)
    order = ["analyze", "grade_evidence", "check_high_risk", "generate", "verify_citations"]
    if target == "analyze" and kind in ("json", "missing", "empty"):
        # Phân tích hỏng dùng lookup, không tự đối chiếu Danh mục từ hồ sơ cũ.
        order.remove("check_high_risk")
    if target == "repair_answer":
        order.append(target)
    # Nút analyze/generate lỗi vận chuyển dừng lượt, không đọc thêm phản hồi.
    if target == "analyze" and kind in ("503", "429", "quota"):
        order = order[:1]
    if target == "generate" and kind in ("empty", "503", "429", "quota"):
        order = order[:4]
    return [values[node] for node in order]


def matrix_graph():
    graph, chat, searches = make_case(config=AgentConfig(enable_rewrite=True, enable_verifier=True, verifier_mode="rule_llm",
                                                        enable_obligations=False))
    return graph, chat


@pytest.mark.parametrize("node,kind", CASES, ids=[f"{n}-{k}" for n, k in CASES])
def test_graph_failure_matrix_and_same_session_recovery(node, kind):
    graph, chat = matrix_graph()
    # Thiết lập hồ sơ thật trong checkpoint trước lượt bị lỗi.
    chat.responses = iter([analysis(request_kinds=["nghia_vu"], profile_update={"role": "nha_cung_cap", "sector": "y_te",
        "product_description": "Robot y tế"}), dict(status="du"), assessment(basis="Robot y tế"), "Nội dung [E1].", dict(issues=[])])
    first = run_turn(graph, "s", "Robot có rủi ro cao không?")
    chat.responses = iter(responses(node, kind))
    result = run_turn(graph, "s", "Robot có rủi ro cao không?")
    assert node in [n["node"] for n in result["trace"]]
    expected_error = node in ("analyze", "generate") and kind in ("empty", "503", "429", "quota")
    if node == "analyze" and kind == "empty":
        expected_error = False
    assert result["route"] == ("error" if expected_error else "retrieval")
    assert result["profile"] == first["profile"]
    assert bool(result["error"]) == expected_error
    assert result["reply"]
    assert "[E99]" not in result["reply"] and "PRIVATE" not in result["reply"]
    if result["route"] == "retrieval":
        assert result["check"]["valid"] and result["check"]["used"] == ["E1"]
        assert (NOTICE in result["reply"]) == (node == "repair_answer")
    else:
        assert result["reply"] == llm_error_reply(failure(kind))
    if node == "analyze" and not expected_error:
        assert not next(n for n in result["trace"] if n["node"] == node)["analysis"]["analysis_ok"]
    if node == "grade_evidence":
        entry = next(n for n in result["trace"] if n["node"] == node)
        assert entry["status"] == "du" and not entry["grade_ok"]
    chat.responses = iter(responses())
    recovered = run_turn(graph, "s", "Robot có rủi ro cao không?")
    assert recovered["route"] == "retrieval" and not recovered["error"]
    assert recovered["profile"] == first["profile"] and recovered["check"]["valid"]
    state = graph.get_state({"configurable": {"thread_id": "s"}}).values
    assert len(state["messages"]) == 6


@pytest.mark.parametrize("seconds,hours", [(18366.39, 6), (30, 1), (None, 1), (3600, 1), (3601, 2)])
@pytest.mark.parametrize("escaped", [False, True])
def test_api_quota_safe_message_and_http(tmp_path, monkeypatch, seconds, hours, escaped):
    graph, chat, _ = make_graph(QuotaExhaustedError("PRIVATE C:/internal/key", retry_after=seconds))
    service = ChatService(graph, chat, LLMSettings("fake", "local", "PRIVATE"), tmp_path)
    if escaped:
        def fail(*args):
            raise QuotaExhaustedError("PRIVATE C:/internal/key", retry_after=seconds)
        monkeypatch.setattr("legal_rag.api.service.run_turn", fail)
    with TestClient(create_app(service)) as client:
        response = client.post("/api/chat", json={"session_id": "s", "message": "Nghĩa vụ AI"})
    assert response.status_code == 200
    result = response.json()
    assert result["route"] == "error"
    assert result["reply"] == result["error"] == f"Dịch vụ AI đã hết lượt trong ngày, vui lòng thử lại sau khoảng {hours} giờ."
    assert "PRIVATE" not in response.text and "C:/internal" not in response.text
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize("status", [429, 503])
def test_api_normal_llm_errors_keep_t24_response(tmp_path, status):
    graph, chat, _ = make_graph(LLMError("PRIVATE C:/internal/key", status=status))
    service = ChatService(graph, chat, LLMSettings("fake", "local", "PRIVATE"), tmp_path)
    with TestClient(create_app(service)) as client:
        response = client.post("/api/chat", json={"session_id": "s", "message": "Nghĩa vụ AI"})
    assert response.status_code == 200
    assert response.json()["reply"] == response.json()["error"] == LLM_ERROR_REPLY
    assert "PRIVATE" not in response.text and "C:/internal" not in response.text


@pytest.mark.parametrize("graph_handled", [False, True])
def test_eval_still_stops_on_five_daily_quotas(tmp_path, graph_handled):
    from legal_rag.evaluation import run
    from test_eval_runner import dataset, Executor
    rows = [dict(id=f"q{i}", question="Hỏi AI", expected_behavior="tra_loi") for i in range(8)]
    dataset(tmp_path, questions=rows)
    if graph_handled:
        # Bao gồm lần đầu gọi bị 429 và những lần sau bỏ qua mọi model.
        def complete(payload):
            raise QuotaExhaustedError(retry_after=30)
        chat = FallbackChat(CachedChat(SimpleNamespace(complete=complete), tmp_path / "cache"), clock=lambda: 0)
        graph = build_graph(GraphDeps(chat, "fake", fake_prepare,
            AgentConfig(enable_rewrite=False, enable_verifier=False), fake_answer([])))
        class GraphExecutor(Executor):
            def execute(self, entry, session):
                return run_turn(graph, entry["id"], entry["question"])
        executor = GraphExecutor()
    else:
        executor = Executor({row["id"]: QuotaExhaustedError(retry_after=30) for row in rows})
    assert run.main(["--run-id", "t30", "--configs", "full", "--layers", "behavior"],
                    tmp_path, lambda _: executor) == 3
    saved = run.latest(tmp_path / "runs/eval/t30/full.behavior.jsonl")
    assert len(saved) == 5 and all(is_429(row) for row in saved.values())
    if graph_handled:
        assert chat.request_count == 1 and chat.attempts == [{"model": "fake", "status": "skipped_quota"}]


@pytest.mark.parametrize("node", ["grade_evidence", "check_high_risk", "verify_citations", "repair_answer"])
def test_api_degraded_nodes_do_not_expose_internal_errors(tmp_path, node):
    graph, chat = matrix_graph()
    initial = responses()
    initial[0] = analysis(request_kinds=["nghia_vu"], profile_update={"product_description": "Robot y tế"})
    chat.responses = iter(initial)
    run_turn(graph, "s", "Robot có rủi ro cao không?")
    chat.responses = iter(responses(node, "503"))
    service = ChatService(graph, chat, LLMSettings("fake", "local", "PRIVATE"), tmp_path)
    with TestClient(create_app(service)) as client:
        response = client.post("/api/chat", json={"session_id": "s", "message": "Robot có rủi ro cao không?"})
    assert response.status_code == 200 and response.json()["route"] == "retrieval"
    assert "PRIVATE" not in response.text and "C:/internal" not in response.text
