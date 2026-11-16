"""T42: store chung, bảng thật, mọi LLM đều giả và không nạp model."""
from copy import deepcopy
from math import ceil
import json
import unicodedata

from fastapi.testclient import TestClient
import pytest

from legal_rag.api.app import create_app
from legal_rag.api.service import ChatService
from legal_rag.api.assessment_service import AssessmentService, AssessmentError
from legal_rag.api.session_store import SessionStore
from legal_rag.assessment.claims import chat_claims, QUESTION_MARKERS, INTENTION_MARKERS
from legal_rag.assessment.groups import status_groups, GROUP_QUESTIONS
from legal_rag.assessment.profile_bridge import profile_override
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.config import AgentConfig
from legal_rag.config import LLMSettings
from legal_rag.llm import LLMError
from test_assessment_api import FakeChat, DESCRIPTION
from test_agent_graph import make_graph, analysis, fake_prepare, FakeChat as GraphChat

SETTINGS = LLMSettings("fake", "local", "PRIVATE")


class StatusChat(FakeChat):
    def __init__(self):
        super().__init__()
        self.quote = ""
        self.status = "chua"

    def complete(self, payload):
        content = payload["messages"][-1]["content"]
        if "NGHĨA VỤ VÀ TIÊU CHÍ:\n" in content and not self.fail:
            self.calls.append(deepcopy(payload))
            rows = json.loads(content.split("NGHĨA VỤ VÀ TIÊU CHÍ:\n")[1])
            return json.dumps({"results": [dict(obligation=r["id"], criterion=c["id"],
                status="khong_phat_hien" if r["kind"] == "cam" else self.status,
                quote=self.quote) for r in rows for c in r["criteria"]]})
        if content.startswith("[") and not self.fail:
            self.calls.append(deepcopy(payload))
            return json.dumps({"results": [dict(id=r["id"], verdict="ho_tro", reason="Có hỗ trợ")
                                          for r in json.loads(content)]})
        return super().complete(payload)


def assessment(tmp_path, store=None):
    chat = StatusChat()
    return AssessmentService(chat, SETTINGS, tmp_path / "assessment", store=store), chat


def group_calls(chat):
    return [json.loads(p["messages"][-1]["content"].split("NGHĨA VỤ VÀ TIÊU CHÍ:\n")[1])
            for p in chat.calls if "NGHĨA VỤ VÀ TIÊU CHÍ:\n" in p["messages"][-1]["content"]]


def test_shared_http_start_from_chat_and_empty_start(tmp_path):
    store = SessionStore()
    assess, chat = assessment(tmp_path, store)
    graph, llm, _ = make_graph(analysis(), "Đáp")
    chat_service = ChatService(graph, llm, SETTINGS, tmp_path / "chat")
    with TestClient(create_app(chat_service, assess, store=store)) as client:
        assert assess.store is chat_service.store is client.app.state.session_store is store
        assert client.post("/api/chat", json=dict(session_id="one", message=DESCRIPTION)).status_code == 200
        result = client.post("/api/assess/start", json=dict(session_id="one"))
        assert result.status_code == 200 and result.json()["ready"]
        assert result.json()["facts"]["roles"] == ["nha_cung_cap"]
        assert json.loads(chat.calls[0]["messages"][-1]["content"])["messages"] == [DESCRIPTION]
        before = len(chat.calls)
        empty = client.post("/api/assess/start", json=dict(session_id="empty")).json()
        assert not empty["ready"] and empty["questions"] and all(v is None for v in empty["facts"].values())
        assert before == len(chat.calls)
        assert client.get("/api/assess/state?session_id=one").json()["groups"] == result.json()["groups"]
        assert client.get("/api/assess/next?session_id=bad/key").status_code == 422
        assert client.get("/api/assess/state?session_id=missing").status_code == 404
        assert client.post("/api/assess/answer", json=dict(session_id="one", group="bad", unknown=True)).status_code == 422


def test_next_unknown_order_progress_and_replacement(tmp_path):
    service, chat = assessment(tmp_path)
    start = service.describe("s", DESCRIPTION)
    groups = start["groups"]
    assert groups and all(g["group"] in GROUP_QUESTIONS for g in groups)
    calls = len(chat.calls)
    for index, group in enumerate(groups):
        nxt = service.next("s")
        assert nxt["group"] == group["group"] and nxt["progress"] == dict(answered=index, total=len(groups))
        assert nxt["obligations"] and all(o["obligation"] in nxt["question"] for o in nxt["obligations"])
        result = service.answer("s", group["group"], "", True)
        rows = [r for r in result["report"]["obligations"] if r["group"] == group["group"]]
        assert all(c["status"] == "chua_ro" for r in rows for c in r["criteria"])
    assert len(chat.calls) == calls
    assert service.next("s")["group"] is None
    service.answer("s", groups[0]["group"], "thay thế", True)
    assert len(service.sessions["s"]["answers"]) == len(groups)
    assert service.sessions["s"]["answers"][groups[0]["group"]]["text"] == "thay thế"


def test_answer_calls_only_selected_obligations_and_keeps_other_groups(tmp_path):
    service, chat = assessment(tmp_path)
    groups = service.describe("s", DESCRIPTION)["groups"]
    for group in groups[:2]:
        service.answer("s", group["group"], "", True)
    selected = groups[0]
    before = len(chat.calls)
    chat.quote = "Chúng tôi chưa thực hiện các việc này."
    output = service.answer("s", selected["group"], chat.quote)
    batches = group_calls(type("Calls", (), {"calls": chat.calls[before:]})())
    obligations = [r for batch in batches for r in batch if r["kind"] == "nghia_vu"]
    assert {r["id"] for r in obligations} == {o["id"] for o in selected["obligations"]}
    assert len(batches) == ceil(len(selected["obligations"]) / 6) + ceil(
        sum(i["row"].get("kind") == "cam" for i in service._items(service.sessions["s"])) / 6)
    assert all(r["status"] == "chua_ro" for r in output["report"]["obligations"] if r["group"] != selected["group"])
    rows = [r for r in output["report"]["obligations"] if r["group"] == selected["group"]]
    assert all(c["evidence_source"] == "nhom:" + selected["group"] for r in rows for c in r["criteria"])
    snapshot = deepcopy(service.sessions["s"])
    chat.fail = True
    with pytest.raises(AssessmentError) as error:
        service.answer("s", selected["group"], "khác")
    assert error.value.status_code == 503 and service.sessions["s"] == snapshot


def test_chat_evidence_t40_check_and_stale(tmp_path):
    service, chat = assessment(tmp_path)
    group = service.describe("s", DESCRIPTION)["groups"][0]["group"]
    claim = "Chúng tôi đã hoàn tất quy trình."
    service.sessions["s"]["messages"].append(claim)
    chat.quote, chat.status = claim, "da"
    before = len(chat.calls)
    result = service.answer("s", group, "Đang rà soát.")
    rows = [r for r in result["report"]["obligations"] if r["group"] == group]
    assert all(c["status"] == "da" and c["evidence_source"] == "hoi_thoai" for r in rows for c in r["criteria"])
    assert any(p["messages"][-1]["content"].startswith("[") for p in chat.calls[before:])
    row, criterion = rows[0], rows[0]["criteria"][0]
    checked = service.check("s", row["id"], criterion["id"], "chua")
    c = next(r for r in checked["report"]["obligations"] if r["id"] == row["id"])["criteria"][0]
    assert c["evidence_source"] == "nguoi_dung" and c["status"] == "chua"
    version = service.sessions["s"]["facts_version"]
    service.set_facts("s", {"risk_level": "cao"})
    state = service.state("s")
    assert state["stale"] and state["report"] == checked["report"] and state["markdown"]
    assert service.sessions["s"]["facts_version"] == version + 1
    service.set_facts("s", {"risk_level": "cao"})
    assert service.sessions["s"]["facts_version"] == version + 1
    with pytest.raises(AssessmentError) as error:
        service.check("s", row["id"], criterion["id"], "da")
    assert error.value.status_code == 409
    result = service.answer("s", service.next("s")["group"] or group, "", True)
    assert not result["stale"]


@pytest.mark.parametrize("marker", QUESTION_MARKERS + INTENTION_MARKERS)
def test_claims_markers_nfc_case_and_questions(marker):
    text = "Chúng tôi " + marker.upper() + " thực hiện việc này."
    assert chat_claims([unicodedata.normalize("NFD", text)]) == ""


def test_claims_split_and_not_substrings():
    assert chat_claims(["Chúng tôi đã thông báo. Có cần lưu nhật ký? Sẽ báo cáo. Chúng tôi chưa gắn nhãn!"]) == "Chúng tôi đã thông báo.\nChúng tôi chưa gắn nhãn!"
    assert "cố định" not in chat_claims(["Chúng tôi có kế hoạch cố định."])
    assert chat_claims(["Chúng tôi có quyền quyết định?", "Đã gửi thông báo?"]) == ""


def test_profile_bridge_priority_and_override_wins_and_resets():
    facts = dict(roles=["nha_phat_trien", "ben_trien_khai", "nha_cung_cap"],
                 sectors=["y_te", "giao_duc"], risk_level="cao", generates_content=False, is_public_sector=True)
    override = profile_override(facts, "Sản phẩm AI")
    assert override["role"] == "nha_cung_cap" and override["sector"] == "y_te"
    assert all(r in override["product_description"] for r in facts["roles"])
    graph, chat, _ = make_graph(analysis(profile_update=dict(role="nguoi_su_dung", sector="khac", risk_level="thap")), "Đáp",
                                analysis(profile_update=dict(role="ben_trien_khai")), "Đáp hai")
    result = run_turn(graph, "s", "Nghĩa vụ cho AI?", profile_override=override)
    assert result["profile"] == override
    payload = json.loads(chat.payloads[0]["messages"][-1]["content"].split("\n", 1)[1])
    assert payload["profile"] == override
    assert run_turn(graph, "s", "Hỏi tiếp về AI")["profile"]["role"] == "ben_trien_khai"


def test_store_lru_touches_and_capacity():
    store = SessionStore(2)
    store.get("a", True); store.get("b", True); store.get("a")
    store.get("c", True)
    assert list(store.sessions) == ["a", "c"] and store.get("b") is None
    store.put("a", deepcopy(store.get("a")))
    store.get("d", True)
    assert list(store.sessions) == ["a", "d"]
    for size in (0, -1, True):
        with pytest.raises(ValueError):
            SessionStore(size)


def test_context_pins_before_retrieval_separate_budget_and_instruction(tmp_path):
    from test_basic_rag import DOCUMENTS, parents
    from legal_rag.retrieval.context import estimate_tokens
    ps = parents()
    pinned, retrieved = ps[0], ps[1]
    chunk = dict(chunk_id=pinned["parent_id"] + "_diem-a", parent_id=pinned["parent_id"])
    calls = []
    chat = GraphChat(analysis(sub_queries=["truy vấn"]), "Đáp")
    def prepare(*args, **kwargs):
        from legal_rag.generation.evidence import build_evidence
        return dict(fake_prepare(*args, **kwargs), evidence=build_evidence([retrieved], DOCUMENTS))
    def generate(message, queries, profile, prepared, llm, model):
        calls.append((message, deepcopy(prepared)))
        return dict(reply=llm.complete({"model": model, "messages": [{"role": "user", "content": message}]}),
                    route="retrieval", evidence=prepared["evidence"], check=dict(used=[], valid=True),
                    prompt_version="answer_v2", parents_used=prepared["parents_used"])
    graph = build_graph(GraphDeps(chat, "fake", prepare,
        AgentConfig(enable_rewrite=False, enable_verifier=False, extra_budget=estimate_tokens(pinned["text"])),
        generate, parents=ps, documents=DOCUMENTS, chunks_loader=lambda: [chunk]))
    assess, _ = assessment(tmp_path)
    assess.describe("s", DESCRIPTION)
    group = assess.next("s")["group"]
    report = assess.answer("s", group, "", True)["report"]
    row = assess.sessions["s"]["report"]["obligations"][0]
    row["citations"] = [dict(chunk_id=chunk["chunk_id"])]
    service = ChatService(graph, chat, SETTINGS, tmp_path / "traces", store=assess.store)
    with TestClient(create_app(service, assess, store=assess.store)) as client:
        response = client.post("/api/chat", json=dict(session_id="s", message="Giải thích nghĩa vụ này",
                                                    context=dict(obligation_id=row["id"])))
        assert response.status_code == 200
        assert client.post("/api/chat", json=dict(session_id="s", message="AI", context={})).status_code == 422
    message, prepared = calls[0]
    assert prepared["evidence"][0]["parent_id"] == pinned["parent_id"]
    assert prepared["evidence"][0]["source"] == "pinned"
    assert prepared["evidence"][1]["parent_id"] == retrieved["parent_id"]
    assert len({e["id"] for e in prepared["evidence"]}) == 2
    assert "Kết quả đánh giá cho nghĩa vụ này:" in message and "Không kết luận ngược" in message
    state = graph.get_state({"configurable": {"thread_id": "s"}}).values
    assert state["extra_tokens"] == estimate_tokens(pinned["text"])
    record = json.loads(next((tmp_path / "traces").glob("*.json")).read_text(encoding="utf-8"))
    assert record["pinned_parents"] == [pinned["parent_id"]] and record["context"] == dict(obligation_id=row["id"])
    assert record["profile_override"]["role"] == "nha_cung_cap"


@pytest.mark.parametrize("has_report,reason", [(False, "no_report"), (True, "obligation_not_in_report")])
def test_invalid_context_is_ignored_traced_and_message_kept_on_error(tmp_path, has_report, reason):
    graph, chat, calls = make_graph(analysis(), "Đáp", RuntimeError("Lỗi giả"))
    service = ChatService(graph, chat, SETTINGS, tmp_path)
    session = service.store.get("s", True)
    if has_report:
        session["report"] = dict(obligations=[])
    service.chat("s", "Hỏi về AI", context=dict(obligation_id="missing"))
    assert "Kết quả đánh giá" not in calls[0][0]
    record = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert record["context_ignored"] == reason and record["pinned_parents"] == []
    with pytest.raises(RuntimeError):
        service.chat("s", "Lượt bị lỗi")
    assert session["messages"] == ["Hỏi về AI", "Lượt bị lỗi"]


def test_banned_claims_all_answers_unknown_removes_old_quote(tmp_path):
    class BannedChat(StatusChat):
        def complete(self, payload):
            content = payload["messages"][-1]["content"]
            result = super().complete(payload)
            if "NGHĨA VỤ VÀ TIÊU CHÍ:\n" in content:
                rows = json.loads(content.split("NGHĨA VỤ VÀ TIÊU CHÍ:\n")[1])
                if rows and rows[0]["kind"] == "cam":
                    data = json.loads(result)
                    for entry in data["results"]:
                        entry.update(status="co_dau_hieu", quote=self.quote)
                    return json.dumps(data)
            if content.startswith("["):
                return json.dumps({"results": [dict(id=r["id"], verdict="co_dau_hieu", reason="Có dấu hiệu")
                                              for r in json.loads(content)]})
            return result
    chat = BannedChat()
    service = AssessmentService(chat, SETTINGS, tmp_path)
    groups = service.describe("s", DESCRIPTION)["groups"]
    text = "Chúng tôi đang thực hiện hành vi này."
    chat.quote = text
    result = service.answer("s", groups[0]["group"], text)
    assert result["report"]["warnings"]
    assert all(c["evidence_source"] == "nhom:" + groups[0]["group"]
               for r in result["report"]["warnings"] for c in r["criteria"])
    before = len(chat.calls)
    result = service.answer("s", groups[0]["group"], "", True)
    assert not result["report"]["warnings"] and len(chat.calls) == before


def test_unknown_overrides_chat_claims_and_previous_check(tmp_path):
    service, chat = assessment(tmp_path)
    group = service.describe("s", DESCRIPTION)["groups"][0]["group"]
    chat.quote = DESCRIPTION
    result = service.answer("s", group, DESCRIPTION)
    row = next(r for r in result["report"]["obligations"] if r["group"] == group)
    service.check("s", row["id"], row["criteria"][0]["id"], "da")
    before = len(chat.calls)
    result = service.answer("s", group, "", True)
    assert before == len(chat.calls)
    assert all(c["status"] == "chua_ro" and c["evidence_source"] is None
               for r in result["report"]["obligations"] if r["group"] == group for c in r["criteria"])
