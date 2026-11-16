"""Cùng bảng thật và facts thì chat dùng nguyên quyết định của bộ lọc chung."""
from copy import deepcopy
from pathlib import Path

import pytest

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.profile_bridge import facts_from_profile
from legal_rag.knowledge.facts import empty_facts
from legal_rag.knowledge.obligations import load_obligations
from test_agent_graph import FakeChat, fake_answer, fake_prepare

TABLE = Path(__file__).resolve().parents[2] / "src/legal_rag/knowledge/obligations.yaml"


def make_graph(rows, *analyses, config=None):
    counts = dict(table=0)
    def loader():
        counts["table"] += 1
        return rows
    responses = []
    for fields in analyses or ({},):
        # T55: câu xác nhận trả lời trực tiếp; test so khớp bảng dùng câu hỏi nghĩa vụ.
        responses.extend([dict(scope="trong", request_kinds=["nghia_vu"], question_type="nghia_vu", **fields), "Đáp"])
    chat = FakeChat(*responses)
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare,
                        config or AgentConfig(enable_rewrite=False, enable_high_risk=False),
                        fake_answer([]), obligations_loader=loader))
    return graph, chat, counts


@pytest.mark.parametrize("roles", [None, [], ["nha_cung_cap"], ["nha_cung_cap", "ben_trien_khai"]])
@pytest.mark.parametrize("risk", [None, "cao", "trung_binh", "thap", "chua_phan_loai"])
@pytest.mark.parametrize("public", [True, False, None])
def test_real_table_parity(roles, risk, public):
    rows = load_obligations(TABLE)
    facts = dict(empty_facts(), roles=roles, risk_level=risk, is_public_sector=public,
                 sectors=["y_te", "giao_duc"], generates_content=False, interacts_with_humans=False)
    graph, chat, counts = make_graph(rows)
    result = run_turn(graph, "s", "Có phải tôi cần làm việc này?", facts_override=facts)
    expected = applicable_obligations(rows, facts)
    mapped = result["map_obligations"]
    assert mapped["items"] == [dict(id=i["row"]["id"], **{k: i[k] for k in
        ("applicability", "conditions", "missing_facts")}) for i in expected["items"]]
    assert mapped["skipped"] == expected["skipped"]
    assert mapped["selected"] == [i["row"]["id"] for i in expected["items"] if i["applicability"] == "ap_dung"]
    assert counts["table"] == 1 and len(chat.payloads) == result["llm_calls"] == 2


def test_profile_adapter_preserves_unknown_false_and_does_not_infer():
    facts = facts_from_profile(dict(role="nha_cung_cap", sector="y_te", risk_level="trung_binh",
                                   is_public_sector=False, generates_content=False, product_description="tương tác con người"))
    assert facts["roles"] == ["nha_cung_cap"] and facts["sectors"] == ["y_te"]
    assert facts["risk_level"] == "trung_binh" and facts["is_public_sector"] is False
    assert facts["generates_content"] is False and facts["interacts_with_humans"] is None
    assert facts_from_profile({})["roles"] is None


def test_override_wins_llm_then_resets_next_turn_and_other_session():
    rows = load_obligations(TABLE)
    update = dict(profile_update=dict(role="nha_phat_trien", risk_level="cao"))
    graph, _, _ = make_graph(rows, update, update, update)
    facts = dict(empty_facts(), roles=["nha_cung_cap", "ben_trien_khai"], sectors=[],
                 risk_level="trung_binh", is_public_sector=False)
    original = deepcopy(facts)
    first = run_turn(graph, "s", "Tôi phải làm gì?", facts_override=facts)
    assert facts == original
    assert next(n for n in first["trace"] if n["node"] == "map_obligations")["facts_source"] == "assessment"
    second = run_turn(graph, "s", "Tôi cần thực hiện gì?")
    third = run_turn(graph, "other", "Tôi cần thực hiện gì?")
    for result in (second, third):
        assert next(n for n in result["trace"] if n["node"] == "map_obligations")["facts_source"] == "profile"
        assert result["map_obligations"]["items"] != first["map_obligations"]["items"]
    assert graph.get_state({"configurable": {"thread_id": "s"}}).values["facts_override"] is None


@pytest.mark.parametrize("interacts", [True, False, None])
def test_real_conditions_payload_only_for_present_bases(interacts):
    from legal_rag.generation.evidence import build_evidence
    from legal_rag.retrieval.context import clause_unit
    rows = [r for r in load_obligations(TABLE) if r["id"] in ("ob-015", "ob-019", "ob-020")]
    chunks = [dict(chunk_id=c["chunk_id"], parent_id=c["chunk_id"])
              for row in rows for c in row["citations"]]
    keys = list(dict.fromkeys(clause_unit(c) for c in chunks))
    parents = [dict(parent_id=k, document_id="d", article="11", clause=str(i),
                    title="Minh bạch", text="Căn cứ " + k, context="Nguồn") for i, k in enumerate(keys)]
    documents = [dict(document_id="d", document_number="134/2025/QH15", document_title="Luật", official_source_url="https://example.invalid")]
    captured = []
    def prepare(message, queries, **kwargs):
        evidence = build_evidence(parents[1:2], documents)
        return dict(fake_prepare(message, queries, **kwargs), evidence=evidence)
    def generate(message, queries, profile, prepared, llm, model):
        captured.append((message, deepcopy(prepared)))
        return dict(reply=llm.complete(dict(model=model)), route="retrieval", evidence=prepared["evidence"],
                    check=dict(valid=True, used=[]), prompt_version="answer_v8", parents_used=prepared["parents_used"])
    chat = FakeChat(dict(scope="trong", request_kinds=["nghia_vu"]), "Đáp")
    graph = build_graph(GraphDeps(chat, "fake", prepare,
        AgentConfig(enable_rewrite=False, enable_high_risk=False), generate,
        parents=parents, documents=documents, chunks_loader=lambda: chunks, obligations_loader=lambda: rows))
    facts = dict(empty_facts(), roles=["nha_cung_cap", "ben_trien_khai"],
                 generates_content=False, interacts_with_humans=interacts)
    result = run_turn(graph, "s", "Cần thực hiện gì?", facts_override=facts)
    state = graph.get_state({"configurable": {"thread_id": "s"}}).values
    bases = state["applicability_bases"]
    if interacts is False:
        assert result["map_obligations"]["items"] == [] and not bases
    elif interacts is None:
        assert {b["id"] for b in bases} == {"ob-019", "ob-020"}
        assert all(b["applicability"] == "ap_dung_neu" and b["conditions"] for b in bases)
        assert not any(e["source"] == "obligation" for e in result["evidence"])
    else:
        assert {b["id"] for b in bases} == {"ob-015", "ob-019", "ob-020"}
        assert all(b["applicability"] == "ap_dung" for b in bases)
    by_id = {r["id"]: r for r in rows}
    projected = captured[0][1].get("presentation_context", {}).get("data", {}).get("Nghĩa vụ có căn cứ hiện diện", [])
    for basis in bases:
        assert basis["obligation"] == by_id[basis["id"]]["obligation"]
        rendered = next(row for row in projected if row["Nghĩa vụ"] == basis["obligation"])
        assert basis["evidence_ids"] and rendered["Căn cứ"] == basis["evidence_ids"]
        assert rendered["Điều kiện"] == basis["conditions"]
        assert basis["id"] not in str(projected) and "missing_facts" not in str(projected)
        assert all(code in {e["id"] for e in captured[0][1]["evidence"]} for code in basis["evidence_ids"])
    if interacts is None:
        assert bases[0]["evidence_ids"] == bases[1]["evidence_ids"]


@pytest.mark.parametrize("prepared", [True, False])
def test_service_full_snapshot_and_no_synthetic_product(tmp_path, prepared):
    from legal_rag.api.service import ChatService
    from legal_rag.api.session_store import SessionStore
    from legal_rag.config import LLMSettings
    store = SessionStore()
    session = store.get("s", create=True)
    facts = dict(empty_facts(), roles=["nha_cung_cap", "ben_trien_khai"], sectors=[],
                 risk_level="trung_binh", interacts_with_humans=False, generates_content=False)
    session.update(prepared=prepared, facts=deepcopy(facts))
    def forbidden():
        pytest.fail("Câu hỏi chung/lịch sử/Vai trò không phải mô tả sản phẩm")
    chat = FakeChat(dict(scope="trong", request_kinds=["nghia_vu"], profile_update=dict(role="nha_phat_trien")), "Đáp")
    graph = build_graph(GraphDeps(chat, "fake", fake_prepare,
        AgentConfig(enable_rewrite=False), fake_answer([]), pipeline_factory=forbidden,
        high_risk_loader=forbidden, obligations_loader=lambda: load_obligations(TABLE)))
    service = ChatService(graph, chat, LLMSettings("fake", "local", "PRIVATE"), tmp_path, store=store)
    result = service.chat("s", "Chúng tôi cần làm gì theo luật AI?")
    state = graph.get_state({"configurable": {"thread_id": "s"}}).values
    assert not state["profile"].get("product_description")
    assert state["facts_override"] == (facts if prepared else None)
    assert session["facts"] == facts
    if prepared:
        assert state["facts_override"] is not session["facts"]
        assert state["map_obligations"]["items"] == [dict(id=i["row"]["id"], **{k: i[k] for k in
            ("applicability", "conditions", "missing_facts")}) for i in applicable_obligations(load_obligations(TABLE), facts)["items"]]
    assert result["llm_calls"] == 2
