"""T62: số token từ trường usage, qua cache, model dự phòng, ngân sách lượt và trace."""

from io import BytesIO
import json

import pytest

from legal_rag.agent.budget import BudgetChat, sum_tokens
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError, normalize_usage
from test_agent_graph import FakeChat, analysis, fake_answer, fake_prepare

USAGE = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 170}


def body(text="đáp", usage=USAGE):
    data = {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
    if usage is not None:
        data["usage"] = usage
    return BytesIO(json.dumps(data).encode())


def test_normalize_usage_keeps_only_integer_fields():
    assert normalize_usage(USAGE) == USAGE
    assert normalize_usage({"prompt_tokens": 5, "completion_tokens": "x", "total_tokens": True}) == {"prompt_tokens": 5}
    assert normalize_usage(None) is None and normalize_usage({}) is None and normalize_usage([1]) is None


def test_http_client_reads_usage_and_resets_per_call():
    responses = [body(), body(usage=None)]
    client = HTTPChatClient("https://fake.invalid", "fake-secret", opener=lambda *a, **k: responses.pop(0))
    assert client.complete({}) == "đáp" and client.last_usage == USAGE
    assert client.complete({}) == "đáp" and client.last_usage is None


class UsageClient:
    def __init__(self, usage=USAGE, fail=False):
        self.usage, self.fail, self.calls = usage, fail, 0
        self.last_usage = None

    def complete(self, payload):
        self.calls += 1
        if self.fail:
            raise LLMError("lỗi giả", status=500)
        self.last_usage = self.usage
        return "đáp " + payload["model"]


def test_cache_stores_usage_beside_answer_and_reads_it_back(tmp_path):
    chat = CachedChat(UsageClient(), tmp_path)
    assert chat.complete({"model": "m"}) == "đáp m" and chat.last_usage == USAGE
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 2 and any(name.endswith(".usage.json") for name in files)
    again = CachedChat(UsageClient(), tmp_path)
    assert again.complete({"model": "m"}) == "đáp m" and again.client.calls == 0
    assert again.last_usage == USAGE and again.cache_hits == 1


def test_old_cache_without_usage_file_gives_none(tmp_path):
    CachedChat(UsageClient(usage=None), tmp_path).complete({"model": "m"})
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]
    chat = CachedChat(UsageClient(), tmp_path)
    assert chat.complete({"model": "m"}) == "đáp m" and chat.last_usage is None


def test_fallback_and_budget_pass_usage_of_successful_call(tmp_path):
    chat = BudgetChat(FallbackChat(CachedChat(UsageClient(), tmp_path), ("du-phong",)))
    chat.complete({"model": "chinh"})
    assert chat.history[-1]["usage"] == USAGE
    failing = BudgetChat(FallbackChat(CachedChat(UsageClient(fail=True), tmp_path / "x")))
    with pytest.raises(LLMError):
        failing.complete({"model": "chinh"})
    assert failing.history[-1]["usage"] is None


def test_sum_tokens_counts_known_calls():
    assert sum_tokens([USAGE, None, {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}]) == dict(
        input=130, output=32, total=182, calls_with_usage=2)
    assert sum_tokens([]) == dict(input=0, output=0, total=0, calls_with_usage=0)


class UsageFakeChat(FakeChat):
    """FakeChat có usage cố định cho mỗi lượt."""
    last_usage = USAGE


def test_trace_nodes_and_turn_report_tokens():
    chat = UsageFakeChat(analysis(), "Nội dung [E1]")
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare, AgentConfig(enable_rewrite=False, enable_verifier=False),
                                  fake_answer([])))
    result = run_turn(graph, "s", "Nhãn AI có yêu cầu gì?")
    calls = result["llm_calls"]
    assert calls >= 2
    assert result["tokens"] == dict(input=120 * calls, output=30 * calls, total=170 * calls, calls_with_usage=calls)
    assert all("tokens" in node for node in result["trace"])
    assert sum(node["tokens"]["calls_with_usage"] for node in result["trace"]) == calls
    plain = run_turn(build_graph(GraphDeps(FakeChat(analysis(), "Nội dung [E1]"), "fake", fake_prepare,
                                           AgentConfig(enable_rewrite=False, enable_verifier=False), fake_answer([]))),
                     "s2", "Nhãn AI?")
    assert plain["tokens"]["calls_with_usage"] == 0
