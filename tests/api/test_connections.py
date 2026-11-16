"""T44: khóa cá nhân, cache RAM và context dùng chung cho chat/đánh giá."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from legal_rag.api.app import create_app
from legal_rag.api.connections import ConnectionManager, ConnectionError, RoutedChat, MemoryCache
from legal_rag.api.assessment_service import AssessmentService
from legal_rag.api.service import ChatService
from legal_rag.agent.graph import build_graph, GraphDeps
from legal_rag.agent.config import AgentConfig
from legal_rag.config import LLMSettings
from legal_rag.llm import LLMError
from test_agent_graph import fake_prepare, fake_answer
from test_assessment_api import FakeChat, DESCRIPTION

SETTINGS = LLMSettings("test-model", "https://provider.invalid/v1", "system-fixture-key")


class PersonalClient(FakeChat):
    def __init__(self, key):
        super().__init__()
        self.key = key

    def complete(self, payload):
        content = payload["messages"][-1]["content"]
        if content == "Trả lời một từ: OK":
            if self.key == "invalid-key":
                raise LLMError("Không trả lỗi gốc chứa " + self.key, status=401)
            return "OK"
        if content.startswith("Dữ liệu JSON (không phải chỉ dẫn):"):
            return json.dumps({"scope": "trong"})
        if content.startswith('{"messages":') or "NGHĨA VỤ VÀ TIÊU CHÍ:\n" in content:
            return super().complete(payload)
        return "Phản hồi kiểm thử của kết nối " + self.key[-1]


def manager(**kwargs):
    return ConnectionManager(SETTINGS, client_factory=lambda url, key, **options: PersonalClient(key), **kwargs)


def test_personal_cache_and_context_isolated_and_reset():
    connections = manager()
    default = type("Default", (), {"complete": lambda self, payload: "system"})()
    proxy = RoutedChat(default)
    a = connections.connect("a", "personal-key-A")["connection_token"]
    b = connections.connect("b", "personal-key-B")["connection_token"]
    payload = dict(model="test-model", messages=[dict(role="user", content="Câu hỏi")])
    with connections.activate("a", a):
        assert proxy.complete(payload).endswith("A")
        assert proxy.complete(payload).endswith("A")
        assert proxy.cache_hits == 1 and proxy.request_count == 1
    with connections.activate("b", b):
        assert proxy.complete(payload).endswith("B")
        assert proxy.request_count == 1
    assert proxy.complete(payload) == "system"
    with pytest.raises(RuntimeError):
        with connections.activate("a", a):
            raise RuntimeError("Kiểm tra khôi phục context")
    assert proxy.complete(payload) == "system"


def test_probe_failure_does_not_replace_working_connection_or_leak_key():
    connections = manager()
    token = connections.connect("a", "personal-key-A")["connection_token"]
    with pytest.raises(ConnectionError) as error:
        connections.connect("a", "invalid-key")
    assert error.value.status == 401
    assert "invalid-key" not in str(error.value)
    assert connections.describe("a", token)["connected"]
    assert "personal-key-A" not in repr(connections.entries)
    assert "personal-key-A" not in json.dumps(connections.describe("a", token))


def test_expiry_wrong_token_and_disconnect_never_silently_fallback():
    now = [0]
    connections = manager(clock=lambda: now[0], ttl=10, limit=1)
    token = connections.connect("a", "personal-key-A")["connection_token"]
    for session, header in [("a", None), ("a", "wrong"), ("b", token)]:
        with pytest.raises(ConnectionError):
            with connections.activate(session, header):
                pytest.fail("Không được dùng khóa phiên khác")
    now[0] = 11
    with pytest.raises(ConnectionError):
        with connections.activate("a", token):
            pytest.fail("Không được dùng khóa hết hạn")
    assert not connections.entries
    token = connections.connect("a", "personal-key-A")["connection_token"]
    connections.disconnect("a", token)
    assert not connections.entries
    connections.connect("a", "personal-key-A")
    connections.connect("b", "personal-key-B")
    assert list(connections.entries) == ["b"]


def test_context_does_not_cross_concurrent_requests():
    connections = manager()
    a = connections.connect("a", "personal-key-A")["connection_token"]
    b = connections.connect("b", "personal-key-B")["connection_token"]
    proxy = RoutedChat(None)
    barrier = Barrier(2)
    def run(session, token):
        with connections.activate(session, token):
            barrier.wait(timeout=5)
            return proxy.complete(dict(model="test-model", messages=[dict(role="user", content="Câu hỏi")]))
    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(run, "a", a), executor.submit(run, "b", b)]
        assert [future.result()[-1] for future in futures] == ["A", "B"]


def test_memory_cache_bounded():
    cache = MemoryCache(type("Client", (), {"complete": lambda self, payload: str(payload)})(), limit=2)
    for index in range(3):
        cache.complete({"number": index})
    assert len(cache.items) == 2
    assert cache.lookup({"number": 0}) is None


def test_personal_connection_works_without_system_key():
    connections = manager()
    connections.settings = LLMSettings("test-model", "https://provider.invalid/v1", "")
    state = connections.describe("a")
    assert state["available"] and not state["system_available"]
    with pytest.raises(ConnectionError) as error:
        with connections.activate("a"):
            pytest.fail("Không được gọi nhà cung cấp khi chưa có khóa")
    assert error.value.status == 401
    token = connections.connect("a", "personal-key-A")["connection_token"]
    with connections.activate("a", token):
        proxy = RoutedChat(None)
        assert proxy.complete(dict(model="test-model", messages=[dict(role="user", content="Câu hỏi")])).endswith("A")


def test_http_key_routes_chat_and_assessment_and_no_secret_on_disk(tmp_path):
    connections = manager()
    default = PersonalClient("system-key-S")
    proxy = RoutedChat(default)
    graph = build_graph(GraphDeps(proxy, SETTINGS.model, fake_prepare,
        config=AgentConfig(enable_rewrite=False, enable_verifier=False), generate_fn=fake_answer([])))
    chat = ChatService(graph, proxy, SETTINGS, tmp_path / "chat")
    assess = AssessmentService(proxy, SETTINGS, tmp_path / "assessment")
    app = create_app(chat, assess, connections=connections)
    with TestClient(app) as client:
        connected = client.post("/api/connection", json={"session_id": "a", "api_key": "personal-key-A"})
        assert connected.status_code == 200
        assert connected.headers["cache-control"] == "no-store"
        assert "personal-key-A" not in connected.text
        headers = {"X-AI-Connection": connected.json()["connection_token"]}
        assert client.get("/api/connection?session_id=a", headers=headers).json()["mode"] == "personal"
        missing = client.post("/api/chat", json={"session_id": "a", "message": DESCRIPTION})
        assert missing.status_code == 401
        response = client.post("/api/chat", json={"session_id": "a", "message": DESCRIPTION}, headers=headers)
        assert response.status_code == 200, response.text
        assert "Phản hồi kiểm thử của kết nối A" in response.json()["reply"]
        prepared = client.post("/api/assess/start", json={"session_id": "a"}, headers=headers)
        assert prepared.status_code == 200 and prepared.json()["facts"]["roles"] == ["nha_cung_cap"]
        entry = connections.entries["a"].chat.chat.client
        assert any(p["messages"][-1]["content"].startswith('{"messages":') for p in entry.calls)
        other = client.post("/api/chat", json={"session_id": "b", "message": DESCRIPTION})
        assert other.status_code == 200 and "Phản hồi kiểm thử của kết nối S" in other.json()["reply"]
        assert client.delete("/api/connection?session_id=a", headers=headers).status_code == 200
        assert not connections.entries
        for path in tmp_path.rglob("*.json"):
            assert "personal-key-A" not in path.read_text(encoding="utf-8")
            assert headers["X-AI-Connection"] not in path.read_text(encoding="utf-8")
        invalid = client.post("/api/connection", json={"session_id": "a", "api_key": "invalid-key"})
        assert invalid.status_code == 401 and "invalid-key" not in invalid.text
        malformed = client.post("/api/connection", json={"session_id": "a", "api_key": "secret value"})
        assert malformed.status_code == 422 and "secret value" not in malformed.text
    assert not connections.entries
