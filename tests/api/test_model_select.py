"""Chọn model theo phiên: danh sách cho phép, đổi model ở lớp RoutedChat, header HTTP."""
import json

from fastapi.testclient import TestClient
import pytest

from legal_rag.api.app import create_app
from legal_rag.api.assessment_service import AssessmentService
from legal_rag.api.connections import ConnectionError, ConnectionManager, RoutedChat, active_model
from legal_rag.api.service import ChatService
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import build_graph, GraphDeps
from legal_rag.config import LLMSettings, get_llm_settings
from test_agent_graph import fake_prepare, fake_answer
from test_assessment_api import DESCRIPTION
from test_connections import PersonalClient

SETTINGS = LLMSettings("model-a", "https://provider.invalid/v1", "system-fixture-key", models=("model-b",))
PAYLOAD = dict(model="model-a", messages=[dict(role="user", content="Câu hỏi")])


class RecordingClient(PersonalClient):
    """Ghi model của mọi lời gọi, kể cả lời gọi chat không qua FakeChat."""
    def __init__(self, key):
        super().__init__(key)
        self.models = []

    def complete(self, payload):
        self.models.append(payload["model"])
        return super().complete(payload)


class Recorder:
    def __init__(self):
        self.models = []

    def complete(self, payload):
        self.models.append(payload["model"])
        return "OK"


def test_settings_list_default_first_without_duplicates_or_blanks():
    settings = LLMSettings("model-a", "url", "key", models=(" model-b ", "", "model-a", "model-b"))
    assert settings.models == ("model-a", "model-b")
    assert LLMSettings("model-a", "url", "key").models == ("model-a",)


def test_settings_read_model_list_from_environment(monkeypatch):
    monkeypatch.setenv("RAG_LLM_MODEL", "model-a")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("RAG_LLM_API_KEY", "fixture-key")
    monkeypatch.setenv("RAG_LLM_MODELS", "model-b, model-c")
    assert get_llm_settings().models == ("model-a", "model-b", "model-c")
    monkeypatch.setenv("RAG_LLM_MODELS", "")
    assert get_llm_settings().models == ("model-a",)


def test_selected_model_replaces_payload_model_only_inside_request():
    connections = ConnectionManager(SETTINGS)
    recorder = Recorder()
    proxy = RoutedChat(recorder)
    with connections.activate("a", model="model-b"):
        proxy.complete(PAYLOAD)
        assert active_model("model-a") == "model-b"
    with connections.activate("a"):
        proxy.complete(PAYLOAD)
        assert active_model("model-a") == "model-a"
    proxy.complete(PAYLOAD)
    assert recorder.models == ["model-b", "model-a", "model-a"]
    assert PAYLOAD["model"] == "model-a"


def test_model_outside_allowed_list_is_rejected_before_any_call():
    connections = ConnectionManager(SETTINGS)
    with pytest.raises(ConnectionError) as error:
        with connections.activate("a", model="model-x"):
            pytest.fail("Không được chạy thao tác với model ngoài danh sách")
    assert error.value.status == 400
    assert connections.describe("a")["models"] == ["model-a", "model-b"]


def test_http_header_selects_model_for_chat_and_assessment(tmp_path):
    connections = ConnectionManager(SETTINGS, client_factory=lambda url, key, **options: PersonalClient(key))
    default = RecordingClient("system-key-S")
    proxy = RoutedChat(default)
    graph = build_graph(GraphDeps(proxy, SETTINGS.model, fake_prepare,
        config=AgentConfig(enable_rewrite=False, enable_verifier=False), generate_fn=fake_answer([])))
    chat = ChatService(graph, proxy, SETTINGS, tmp_path / "chat")
    assess = AssessmentService(proxy, SETTINGS, tmp_path / "assessment")
    app = create_app(chat, assess, connections=connections)
    with TestClient(app) as client:
        assert client.get("/api/connection?session_id=a").json()["models"] == ["model-a", "model-b"]
        bad = client.post("/api/chat", json={"session_id": "a", "message": DESCRIPTION}, headers={"X-AI-Model": "model-x"})
        assert bad.status_code == 400 and not default.models
        header = {"X-AI-Model": "model-b"}
        assert client.post("/api/chat", json={"session_id": "a", "message": DESCRIPTION}, headers=header).status_code == 200
        assert client.post("/api/assess/start", json={"session_id": "a"}, headers=header).status_code == 200
        assert default.models and set(default.models) == {"model-b"}
        before = len(default.models)
        assert client.post("/api/chat", json={"session_id": "b", "message": DESCRIPTION}).status_code == 200
        assert set(default.models[before:]) == {"model-a"}
    traces = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "assessment").rglob("*.json")]
    assert traces and all(trace["model"] == "model-b" for trace in traces if trace.get("session_id") == "a")
