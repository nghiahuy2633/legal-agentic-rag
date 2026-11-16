"""API T24: chỉ dùng đồ thị/LLM giả và không mở trình duyệt."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import inspect
import json
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest

from legal_rag.agent.graph import LLM_ERROR_REPLY
from legal_rag.agent.trace_view import trace_view
from legal_rag.api import app as api
from legal_rag.api import service as services
from legal_rag.api.service import ChatService
from legal_rag.config import LLMSettings
from legal_rag.llm import LLMError
from test_agent_graph import analysis, make_graph

ROOT = Path(__file__).resolve().parents[2]
RESPONSE_FIELDS = {"session_id", "reply", "route", "profile", "citations", "evidence",
                   "process", "llm_calls", "total_ms", "error"}


class FakeService:
    def __init__(self, error=None):
        self.error = error
        self.received = []

    def chat(self, session_id, message):
        self.received.append((session_id, message))
        if self.error:
            raise self.error
        return dict(session_id=session_id, reply="Trả lời [E1]", route="retrieval",
                    profile={}, citations=[], evidence=[], llm_calls=1, total_ms=12, error=None,
                    process={"nodes": [{"node": "generate", "prompt": "PRIVATE",
                             "messages": [{"content": "PRIVATE"}], "nested": {"api_key": "PRIVATE"}}],
                             "client": "PRIVATE", "settings": {"password": "PRIVATE"}})

    def health(self):
        return dict(status="ok", model="fake", fallback_models=["backup"], model_loaded=True,
                    api_key="PRIVATE", settings={"api_key": "PRIVATE"})


def forbidden(*args, **kwargs):
    raise AssertionError("Không được nạp runtime/model trong test này")


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(api, "build_agent", forbidden)
    monkeypatch.setattr(api, "RetrievalPipeline", forbidden)
    service = FakeService()
    with TestClient(api.create_app(service)) as client:
        yield client, service


def test_http_response_and_no_runtime_load(fake_client):
    client, service = fake_client
    response = client.post("/api/chat", json={"session_id": "demo-A_1", "message": "Nghĩa vụ AI"})
    assert response.status_code == 200
    assert set(response.json()) == RESPONSE_FIELDS
    assert service.received == [("demo-A_1", "Nghĩa vụ AI")]
    assert all(value not in response.text for value in ("PRIVATE", '"prompt"', '"messages"', '"api_key"'))


@pytest.mark.parametrize("payload", [
    {"session_id": "bad/key", "message": "a"}, {"session_id": "", "message": "a"},
    {"session_id": "a" * 65, "message": "a"}, {"session_id": "x"},
    {"session_id": "x", "message": "a" * 20001}, {"session_id": "x", "message": 12},
    {"session_id": None, "message": "a"},
])
def test_validation_in_vietnamese(fake_client, payload):
    client, service = fake_client
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 422
    assert not service.received
    assert all(any(word in item["msg"] for word in ("phải", "Thiếu", "không"))
               for item in response.json()["detail"])
    assert "input" not in response.text


def test_malformed_json_is_vietnamese(fake_client):
    client, _ = fake_client
    result = client.post("/api/chat", content="{", headers={"content-type": "application/json"})
    assert result.status_code == 422
    assert "Dữ liệu yêu cầu không đúng định dạng." in result.text


def test_unknown_error_hides_details():
    with TestClient(api.create_app(FakeService(RuntimeError("PRIVATE"))),
                    raise_server_exceptions=False) as client:
        response = client.post("/api/chat", json={"session_id": "x", "message": "a"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Không xử lý được yêu cầu. Vui lòng thử lại."}


def test_health_static_and_sync_routes(fake_client):
    client, _ = fake_client
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == dict(status="ok", model="fake", fallback_models=["backup"], model_loaded=True,
                                 assessment=False)
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200
    for route in client.app.routes:
        if getattr(route, "path", "") in ("/", "/api/chat", "/api/health"):
            assert not inspect.iscoroutinefunction(route.endpoint)


def make_service(tmp_path, *responses):
    graph, chat, _ = make_graph(*responses)
    return ChatService(graph, chat, LLMSettings("fake", "local", "PRIVATE", ("backup",)), tmp_path)


def test_interleaved_sessions_traces_and_public_process(tmp_path):
    service = make_service(tmp_path,
        analysis(profile_update={"role": "nha_cung_cap"}), "Đáp một [E1]",
        analysis(profile_update={"sector": "y_te"}), "Đáp hai [E1]",
        analysis(profile_update={"sector": "giao_duc"}), "Đáp ba [E1]")
    first = service.chat("first", "Tôi cung cấp AI")
    second = service.chat("second", "AI trong y tế")
    third = service.chat("first", "AI trong giáo dục")
    assert first["profile"]["role"] == "nha_cung_cap"
    assert second["profile"]["role"] is None and second["profile"]["sector"] == "y_te"
    assert third["profile"]["role"] == "nha_cung_cap" and third["profile"]["sector"] == "giao_duc"
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(tmp_path.glob("*.json"))]
    assert len(records) == 3
    for response, record in zip((first, second, third), records):
        assert set(response) == RESPONSE_FIELDS
        assert response["process"] == dict(trace_view(record), total_ms=record["total_ms"])
        assert "messages" in record and "conversation" in record and "llm_attempts" in record
        assert "parent_id" not in response["evidence"][0]
        assert response["citations"] == record["citations"] and response["citations"]
        assert response["total_ms"] >= 0
        assert "PRIVATE" not in json.dumps(response)
    assert service.health() == dict(status="ok", model="fake", fallback_models=["backup"], model_loaded=False)


@pytest.mark.parametrize("message", ["", "a" * 4001, "a" * 20000])
def test_guard_runs_for_empty_and_long_http_messages(tmp_path, message):
    service = make_service(tmp_path)
    with TestClient(api.create_app(service)) as client:
        result = client.post("/api/chat", json={"session_id": "x", "message": message})
    assert result.status_code == 200
    assert result.json()["route"] == "input_rejected" and result.json()["llm_calls"] == 0


def test_trace_write_failure_does_not_break_response(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    def fail(*args):
        raise OSError("PRIVATE")
    monkeypatch.setattr(services, "write_trace", fail)
    result = service.chat("x", "")
    assert result["reply"] and result["route"] == "input_rejected"


@pytest.mark.parametrize("error", [LLMError("PRIVATE"), RuntimeError("PRIVATE")])
def test_escaped_errors_are_traced_and_only_llm_is_handled(tmp_path, monkeypatch, error):
    service = make_service(tmp_path)
    def fail(*args):
        raise error
    monkeypatch.setattr(services, "run_turn", fail)
    if isinstance(error, LLMError):
        result = service.chat("x", "Nghĩa vụ AI")
        assert result["route"] == "error" and result["reply"] == LLM_ERROR_REPLY
        assert "PRIVATE" not in json.dumps(result)
    else:
        with pytest.raises(RuntimeError, match="PRIVATE"):
            service.chat("x", "Nghĩa vụ AI")
    record = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert record["route"] == "error" and record["error"]


def test_graph_handled_llm_error_is_traced(tmp_path):
    result = make_service(tmp_path, LLMError("PRIVATE")).chat("x", "Nghĩa vụ AI")
    assert result["route"] == "error" and result["reply"] == LLM_ERROR_REPLY
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_service_serializes_shared_graph(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    entered, release, second_started, second_entered = (Event() for _ in range(4))
    def run(graph, session, message):
        if session == "first":
            entered.set()
            assert release.wait(5)
        else:
            second_entered.set()
        return dict(route="input_rejected", reply="Đáp", trace=[], evidence=[], error=None)
    monkeypatch.setattr(services, "run_turn", run)
    def second():
        second_started.set()
        return service.chat("second", "")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.chat, "first", "")
        try:
            assert entered.wait(5)
            next_turn = pool.submit(second)
            assert second_started.wait(5)
            assert not second_entered.wait(.1)
        finally:
            release.set()
        assert first.result()["session_id"] == "first"
        assert next_turn.result()["session_id"] == "second"


def test_lifespan_loads_and_warms_once(monkeypatch):
    events = []
    class Pipeline:
        def __init__(self, chunks, parents):
            events.append("pipeline")
        def search(self, query):
            events.append("warm")
    def build(root, pipeline, chat_wrapper=None, settings=None):
        assert isinstance(pipeline, Pipeline) and events == ["pipeline", "warm"]
        assert chat_wrapper is api.RoutedChat
        events.append("graph")
        return object(), chat_wrapper(object()), LLMSettings("fake", "local", "PRIVATE")
    monkeypatch.setattr(api, "RetrievalPipeline", Pipeline)
    monkeypatch.setattr(api, "read_jsonl", lambda path: [])
    monkeypatch.setattr(api, "build_agent", build)
    monkeypatch.setattr(api, "get_llm_settings", lambda **kwargs: LLMSettings("fake", "local", "PRIVATE"))
    app = api.create_app()
    assert not events
    with TestClient(app) as client:
        for _ in range(2):
            assert client.get("/api/health").json()["model_loaded"] is True
    assert events == ["pipeline", "warm", "graph"]


def test_static_files_use_safe_local_assets():
    html = (api.STATIC / "index.html").read_text(encoding="utf-8")
    js = (api.STATIC / "app.js").read_text(encoding="utf-8")
    css = (api.STATIC / "style.css").read_text(encoding="utf-8")
    for content in (html, css):
        assert "http://" not in content and "https://" not in content
    assert 'name="viewport"' in html and 'for="message"' in html
    assert "function escapeHTML" in js and "return escapeHTML(text).replace" in js
    assert ".innerHTML =" not in js
    assert 'parseFromString(markdown(data.reply), "text/html")' in js
    assert 'link.rel = "noopener noreferrer"' in js
    assert "sessionStorage" in js and "setInterval(progress, 1000)" in js
    assert "min-height: 44px" in css and "minmax(0, 1fr)" in css


def test_serve_defaults_single_worker_and_overrides(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("serve_t24", ROOT / "scripts/serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    module.main([])
    module.main(["--host", "localhost", "--port", "8010"])
    assert calls[0] == (("legal_rag.api.app:create_app",), dict(factory=True, host="127.0.0.1", port=8000, workers=1))
    assert calls[1][1] == dict(factory=True, host="localhost", port=8010, workers=1)
    assert "http://127.0.0.1:8000" in capsys.readouterr().out
