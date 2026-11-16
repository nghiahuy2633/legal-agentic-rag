"""T31: cache trên đồ thị thật, không gọi mạng hoặc tải model."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from legal_rag.agent.graph import run_turn
from legal_rag.agent.runtime import build_agent
from legal_rag.config import get_llm_settings
from legal_rag.evaluation import run
from legal_rag.llm import CacheMissError, CachedChat, FallbackChat, OfflineClient, LLMError
from test_basic_rag import cli_root
from test_eval_runner import write_rows
from test_llm_failures import matrix_graph, responses as node_responses

ROOT = Path(__file__).resolve().parents[2]
MESSAGE = "Robot có rủi ro cao không?"
DEMO_ERROR = "Câu này chưa có sẵn trong chế độ trình diễn. Vui lòng chọn câu đã chuẩn bị."


def responses(*args):
    values = node_responses(*args)
    values[0] = dict(scope="trong", request_kinds=["nghia_vu"], profile_update={"product_description": "Robot y tế"})
    return values


def demo_module():
    spec = importlib.util.spec_from_file_location("check_demo_t31", ROOT / "scripts/check_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Không được mở mạng")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("legal_rag.llm.urlopen", forbidden)


def settings_env(monkeypatch, offline):
    monkeypatch.setattr("legal_rag.config.load_dotenv", lambda *a, **kw: None)
    for key, value in {"RAG_LLM_MODEL": "fake", "RAG_LLM_OFFLINE": offline,
                       "RAG_LLM_BASE_URL": "", "RAG_LLM_API_KEY": "",
                       "RAG_LLM_FALLBACK_MODELS": "backup"}.items():
        monkeypatch.setenv(key, value)


def test_offline_settings_runtime_and_basic_without_credentials(tmp_path, monkeypatch):
    settings_env(monkeypatch, "1")
    assert get_llm_settings().offline
    root = cli_root(tmp_path)
    graph, chat, _ = build_agent(root, client_factory=lambda *a, **kw: pytest.fail("HTTP client"))
    assert isinstance(chat.chat.client, OfflineClient)
    assert run_turn(graph, "s", MESSAGE)["reply"] == DEMO_ERROR
    basic = run.BasicExecutor(root, None)
    assert isinstance(basic.chat.chat.client, OfflineClient)
    monkeypatch.setenv("RAG_LLM_MODEL", "")
    with pytest.raises(ValueError, match="RAG_LLM_MODEL"):
        get_llm_settings()
    settings_env(monkeypatch, "0")
    with pytest.raises(ValueError, match="RAG_LLM_BASE_URL, RAG_LLM_API_KEY"):
        get_llm_settings()


def test_offline_all_models_cache_first_no_fallback_or_quota(tmp_path):
    cache = CachedChat(OfflineClient(), tmp_path)
    chat = FallbackChat(cache, ("backup", "third"))
    payload = {"model": "fake"}
    seen = []
    lookup = cache.lookup
    cache.lookup = lambda data: seen.append(data["model"]) or lookup(data)
    for _ in range(2):
        with pytest.raises(CacheMissError) as caught:
            chat.complete(payload)
        assert caught.value.status is None
        assert chat._quota_until == {} and len(chat.attempts) == 1
    assert seen[:3] == ["fake", "backup", "third"]
    cache._path(dict(payload, model="third")).write_text(json.dumps("đáp"), encoding="utf-8")
    before = cache.request_count
    assert chat.complete(payload) == "đáp" and chat.last_model == "third"
    assert cache.request_count == before and not chat.attempts


def replay_graph(tmp_path, missing=None):
    graph, fake = matrix_graph()
    fake.responses = iter(responses())
    recorded = []
    complete = fake.complete
    def record(payload):
        answer = complete(payload)
        recorded.append((payload, answer))
        return answer
    fake.complete = record
    original = run_turn(graph, "record", MESSAGE)
    nodes = [n["node"] for n in original["trace"] if n["llm_calls"]]
    cache = CachedChat(OfflineClient(), tmp_path)
    for node, (payload, answer) in zip(nodes, recorded):
        if node != missing:
            cache._path(payload).write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    graph, fake = matrix_graph()
    chat = FallbackChat(cache)
    fake.complete = chat.complete
    return graph, chat


@pytest.mark.parametrize("missing", [None, "analyze", "generate", "grade_evidence", "verify_citations"])
def test_demo_real_graph_cached_and_auxiliary_misses(tmp_path, monkeypatch, capsys, missing):
    graph, chat = replay_graph(tmp_path, missing)
    module = demo_module()
    write_rows(tmp_path / "eval/demo_scenarios.jsonl", [dict(id="d", note="test", turns=[MESSAGE])])
    def factory(root):
        assert get_llm_settings().offline
        assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
        return graph, chat, None
    settings_env(monkeypatch, "0")
    assert module.main([], tmp_path, factory) == int(missing is not None)
    out = capsys.readouterr().out
    assert ("sẵn sàng" if missing is None else f"thiếu cache ở nút {missing}") in out
    assert "retrieval" in out if missing in (None, "grade_evidence", "verify_citations") else "error" in out
    assert not chat._quota_until
    assert os.environ["RAG_LLM_OFFLINE"] == "0"
    if missing == "generate":
        assert run_turn(graph, "check", MESSAGE)["reply"] == DEMO_ERROR


@pytest.mark.parametrize("node", ["grade_evidence", "check_high_risk", "verify_citations", "repair_answer"])
def test_evaluation_marks_degraded_nodes_keeps_answer(node, tmp_path):
    graph, chat = matrix_graph()
    values = responses(node, "429")
    values[0] = dict(scope="trong", request_kinds=["nghia_vu"], profile_update={"product_description": "Robot y tế"})
    values = [LLMError("HTTP 429; per day", 429) if isinstance(v, LLMError) else v for v in values]
    chat.responses = iter(values)
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph = graph
    result = executor.execute(dict(question=MESSAGE), "s")
    assert result["degraded_nodes"] == [node]
    assert result["error"] == f"Nút {node} lỗi LLM: HTTP 429; per day"
    assert result["answer"] and result["route"] == "retrieval" and run.is_429(result)


def test_degraded_resume_skips_later_turn_and_retries(tmp_path):
    graph, chat = matrix_graph()
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph = graph
    plan = {"behavior": [dict(id=f"s.t{i}", scenario_id="s", turn=i, question=MESSAGE) for i in (1, 2)]}
    first = responses("verify_citations", "429")
    chat.responses = iter(first)
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[1] == 0
    saved = run.latest(tmp_path / "full.behavior.jsonl")
    assert saved["s.t1"]["degraded_nodes"] == ["verify_citations"]
    assert saved["s.t2"]["error"] == "Bỏ qua vì lượt s.t1 lỗi"
    chat.responses = iter([*responses(), *responses()])
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[1] == 2
    assert all(not row["error"] for row in run.latest(tmp_path / "full.behavior.jsonl").values())


def test_malformed_grade_json_not_degraded():
    graph, chat = matrix_graph()
    chat.responses = iter(responses("grade_evidence", "json"))
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph = graph
    result = executor.execute(dict(question=MESSAGE), "s")
    assert result["error"] is None and result["degraded_nodes"] == []


def test_multiple_degraded_nodes_keep_all_errors_and_429():
    graph, chat = matrix_graph()
    values = responses()
    values[1] = LLMError("HTTP 503", 503)
    values[-1] = LLMError("HTTP 429", 429)
    chat.responses = iter(values)
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph = graph
    result = executor.execute(dict(question=MESSAGE), "s")
    assert result["degraded_nodes"] == ["grade_evidence", "verify_citations"]
    assert result["error"] == "Nút grade_evidence lỗi LLM: HTTP 503; Nút verify_citations lỗi LLM: HTTP 429"
    assert run.is_429(result)


def test_dry_run_does_not_build_agent(capsys):
    assert demo_module().main(["--dry-run"], ROOT,
        lambda *a: pytest.fail("Không tải model")) == 0
    rows = [json.loads(line) for line in (ROOT / "eval/demo_scenarios.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    turns = sum(len(row["turns"]) for row in rows)
    assert f"{len(rows)} kịch bản, {turns} lượt." in capsys.readouterr().out
