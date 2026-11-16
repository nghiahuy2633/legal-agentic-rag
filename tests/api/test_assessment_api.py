"""T36: chat giả, bảng thật, không mạng và không model truy xuất."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from legal_rag.api import app as api
from legal_rag.api.assessment_service import AssessmentService, AssessmentError
from legal_rag.config import LLMSettings
from legal_rag.llm import CachedChat, LLMError

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTION = "Tôi là nhà cung cấp hệ thống AI rủi ro thấp."


class FakeChat:
    def __init__(self):
        self.calls = []
        self.fail = False

    def complete(self, payload):
        if self.fail:
            raise LLMError("PRIVATE")
        self.calls.append(deepcopy(payload))
        content = payload["messages"][-1]["content"]
        if content.startswith('{"messages":'):
            return json.dumps({"facts": {
                "roles": {"value": ["nha_cung_cap"], "quote": DESCRIPTION},
                "risk_level": {"value": "thap", "quote": DESCRIPTION}}})
        if "NGHĨA VỤ VÀ TIÊU CHÍ:\n" in content:
            rows = json.loads(content.split("NGHĨA VỤ VÀ TIÊU CHÍ:\n")[1])
            return json.dumps({"results": [dict(obligation=r["id"], criterion=c["id"],
                status="khong_phat_hien" if r["kind"] == "cam" else "chua_ro", quote="")
                for r in rows for c in r["criteria"]]})
        return "Cần tiếp tục tự rà soát."


def make_service(tmp_path, cached=False):
    chat = FakeChat()
    wrapped = CachedChat(chat, tmp_path / "cache") if cached else chat
    return AssessmentService(wrapped, LLMSettings("fake", "local", "PRIVATE"),
                             tmp_path / "traces", clock=lambda: "2026-11-07T00:00:00Z"), chat


def test_real_table_session_flow_trace_and_cache(tmp_path):
    service, chat = make_service(tmp_path, cached=True)
    prepared = service.describe("one", DESCRIPTION)
    assert prepared["ready"] and prepared["labels"]["roles"] == "vai trò"
    assert prepared["evidence"]["roles"] == DESCRIPTION
    prepared = service.set_facts("one", {"interacts_with_humans": True, "risk_level": "sai", "unknown": 1})
    assert len(prepared["errors"]) == 2
    assert prepared["facts"]["risk_level"] == "thap"
    assert "risk_level" not in service.sessions["one"]["form"]
    result = service.run("one", "Chúng tôi đang rà soát.")
    assert result["report"]["meta"]["table_sha256"] == hashlib.sha256(
        (ROOT / "src/legal_rag/knowledge/obligations.yaml").read_bytes()).hexdigest()
    task = next(t for t in result["report"]["todo"] if t["type"] == "tu_kiem")
    calls = len(chat.calls)
    result = service.check("one", task["row_id"], task["criterion_id"], "chua")
    row = next(r for r in result["report"]["obligations"] if r["id"] == task["row_id"])
    assert row["status"] == "chua"
    criterion = next(c for c in row["criteria"] if c["id"] == task["criterion_id"])
    assert criterion["source"] == "nguoi_dung"
    # Status payload giữ nguyên; chỉ bản tóm tắt thay đổi có thể gọi thêm một lần.
    assert len(chat.calls) <= calls + 1
    assert service.markdown("one") == result["markdown"]
    result = service.check("one", task["row_id"], task["criterion_id"], None)
    row = next(r for r in result["report"]["obligations"] if r["id"] == task["row_id"])
    assert next(c for c in row["criteria"] if c["id"] == task["criterion_id"])["status"] == "chua_ro"
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "traces").glob("*.json")]
    assert len(records) == 6
    assert all({"operation", "session_id", "input", "output", "total_ms", "time", "model"} <= r.keys() for r in records)
    assert "PRIVATE" not in json.dumps(records)
    assert all(p["temperature"] == 0 for p in chat.calls)


def test_errors_keep_session_and_trace(tmp_path):
    service, chat = make_service(tmp_path)
    service.describe("one", DESCRIPTION)
    original = deepcopy(service.sessions)
    for method in (lambda: service.run("one", "  "), lambda: service.check("one", "bad", "bad", "da")):
        with pytest.raises(AssessmentError):
            method()
    chat.fail = True
    for method in (lambda: service.describe("one", "thêm"), lambda: service.run("one", "Đang làm")):
        with pytest.raises(AssessmentError) as error:
            method()
        assert error.value.status_code == 503
        assert service.sessions == original
    with pytest.raises(AssessmentError) as error:
        service.markdown("missing")
    assert error.value.status_code == 404
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "traces").glob("*.json")]
    assert len(records) == 6 and sum("error" in r for r in records) == 5
    assert "PRIVATE" not in json.dumps(records)


def test_missing_facts_can_run_and_form_survives_extraction(tmp_path):
    service, _ = make_service(tmp_path)
    service.describe("one", DESCRIPTION)
    service.set_facts("one", {"roles": None, "risk_level": None})
    data = service.describe("one", DESCRIPTION)
    assert not data["ready"] and not data["evidence"]
    assert service.run("one", "Đang rà soát")["report"]
    assert service.sessions["one"]["description"] == DESCRIPTION + "\n" + DESCRIPTION


def test_failed_check_preserves_previous_report_and_session_isolation(tmp_path):
    service, chat = make_service(tmp_path)
    service.describe("one", DESCRIPTION)
    service.run("one", "Đang rà soát")
    task = next(t for t in service.sessions["one"]["report"]["todo"] if t["type"] == "tu_kiem")
    original = deepcopy(service.sessions["one"])
    with pytest.raises(AssessmentError) as error:
        service.check("one", "bad", "c1", "da")
    assert error.value.status_code == 422
    chat.fail = True
    with pytest.raises(AssessmentError) as error:
        service.check("one", task["row_id"], task["criterion_id"], "da")
    assert error.value.status_code == 503
    assert service.sessions["one"] == original
    assert service.markdown("one")
    chat.fail = False
    service.describe("two", "Một sản phẩm khác")
    assert service.sessions["one"] == original
    assert service.sessions["two"]["report"] is None


class FakeService:
    def describe(self, session_id, message):
        if message == "error":
            raise AssessmentError(503, "Dịch vụ LLM tạm thời lỗi. Vui lòng thử lại sau.")
        return {"facts": {}, "evidence": {}, "labels": {}, "questions": [], "ready": False, "changes": []}

    def set_facts(self, session_id, facts):
        if session_id == "missing":
            raise AssessmentError(404, "Không tìm thấy phiên đánh giá.")
        return self.describe(session_id, "")

    def run(self, session_id, statement):
        if not statement.strip():
            raise AssessmentError(422, "Vui lòng nhập lời khai hiện trạng trước khi đánh giá.")
        return {"report": {}, "markdown": "# Bản đánh giá\n"}

    def check(self, *args):
        return self.run("one", "ok")

    def markdown(self, session_id):
        return "# Bản đánh giá\n"


def test_endpoints_fake_service(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Không được nạp pipeline/model")
    monkeypatch.setattr(api, "load_service", forbidden)
    with TestClient(api.create_app(assessment_service=FakeService())) as client:
        for endpoint, payload in (
            ("describe", {"message": "Mô tả"}), ("facts", {"facts": {}}),
            ("run", {"statement": "Hiện trạng"}),
            ("check", {"row_id": "ob-001", "criterion_id": "c1", "value": None})):
            assert client.post(f"/api/assess/{endpoint}", json={"session_id": "one", **payload}).status_code == 200
        assert client.post("/api/assess/facts", json={"session_id": "missing", "facts": {}}).status_code == 404
        assert client.post("/api/assess/describe", json={"session_id": "one", "message": "error"}).status_code == 503
        for endpoint, payload in (("describe", {"message": "a" * 20001}),
                                  ("run", {"statement": "a" * 20001}), ("run", {"statement": ""}),
                                  ("check", {"row_id": "a", "criterion_id": "c1", "value": "yes"})):
            assert client.post(f"/api/assess/{endpoint}", json={"session_id": "one", **payload}).status_code == 422
        for path, payload in (("describe", {"message": "x"}), ("facts", {"facts": {}}),
                              ("run", {"statement": "x"}), ("check", {"row_id": "x", "criterion_id": "c1", "value": "da"})):
            assert client.post(f"/api/assess/{path}", json={"session_id": "../bad", **payload}).status_code == 422
        response = client.get("/api/assess/report.md?session_id=one")
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/markdown")
        assert "attachment" in response.headers["content-disposition"]
        assert client.get("/api/assess/report.md?session_id=bad/key").status_code == 422
        assert client.get("/api/health").json()["assessment"] is True


def test_assess_only_initializes_without_pipeline(monkeypatch, tmp_path):
    service, _ = make_service(tmp_path)
    monkeypatch.setenv("RAG_ASSESS_ONLY", "1")
    monkeypatch.setattr(api, "load_assessment_service", lambda: service)
    monkeypatch.setattr(api, "load_service", lambda: pytest.fail("Pipeline không được nạp"))
    with TestClient(api.create_app()) as client:
        response = client.post("/api/chat", json={"session_id": "one", "message": "x"})
        assert response.status_code == 503 and response.json()["detail"] == "Chế độ chỉ đánh giá"
        assert client.post("/api/assess/describe", json={"session_id": "one", "message": DESCRIPTION}).status_code == 200
        assert client.post("/api/assess/run", json={"session_id": "missing", "statement": "x"}).status_code == 404
        assert client.get("/api/health").json()["model_loaded"] is False


def test_static_chat_and_assessment_panel_and_no_inner_html():
    static = ROOT / "src/legal_rag/api/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'role="tab"' not in html
    assert 'id="open-assessment"' in html
    assert 'id="assessment-panel"' in html
    assert 'id="chat-panel"' in html
    assert "Rà soát sản phẩm" in html
    assessment_js = (static / "assessment.js").read_text(encoding="utf-8")
    assert "Hỏi về nghĩa vụ này" in assessment_js
    assert 'chua_ro: "Cần xác minh"' in assessment_js
    for path in static.glob("*.js"):
        assert "innerHTML" not in path.read_text(encoding="utf-8")
