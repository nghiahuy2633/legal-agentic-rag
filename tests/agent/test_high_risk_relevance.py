"""Kiểm cổng ứng viên bằng phản hồi giả; không đặt nhãn pháp lý sản phẩm."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unicodedata

import pytest

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.report import assemble_report
from legal_rag.agent.trace_view import trace_view
from legal_rag.generation.evidence import build_evidence
from legal_rag.knowledge import high_risk as hr
from test_agent_graph import FakeChat, analysis
from test_high_risk import Chat, ROBOT, ITEMS, PARENTS, response
from test_map_report import fixture_data

DESCRIPTION = "Robot hỗ trợ thao tác, có nhân viên giám sát."


def match(status="phu_hop", basis="Robot hỗ trợ thao tác", missing_info=None):
    return dict(status=status, basis=basis, missing_info=missing_info or [])


def answer(object_match=None, statuses=("dap_ung", "chua_ro")):
    result = response(statuses)
    if object_match is not None:
        result["items"][0]["object_match"] = object_match
    return result


@pytest.mark.parametrize("obj,expected,reason", [
    (match(), "phu_hop", "matched"),
    (match("khong_phu_hop"), "khong_phu_hop", "not_matched"),
    (match("chua_ro"), "chua_ro", "unresolved"),
    (None, "chua_ro", "invalid_object_match"),
    ([], "chua_ro", "invalid_object_match"),
    (match("lạ"), "chua_ro", "invalid_status"),
    (match([]), "chua_ro", "invalid_status"),
    (match(basis=None), "chua_ro", "invalid_basis"),
    (match(basis="  "), "chua_ro", "invalid_basis"),
    (match(basis="Robot tự động phẫu thuật"), "chua_ro", "invalid_basis"),
    (match("khong_phu_hop", "không có dữ kiện này"), "chua_ro", "invalid_basis"),
    (match(basis="Robot hỗ trợ\n  thao tác"), "phu_hop", "matched"),
    (match(basis=unicodedata.normalize("NFD", "Robot hỗ trợ thao tác")), "phu_hop", "matched"),
    (match(basis="Robot ho tro thao tac"), "chua_ro", "invalid_basis"),
])
def test_normalize_object_match_and_basis(obj, expected, reason):
    chat = Chat(answer(obj))
    result = hr.assess_items(DESCRIPTION, [ROBOT], chat, "fake", version="high_risk_v2")
    decision = result["relevance"][0]
    assert result["version"] == "high_risk_v2" and result["assess_ok"]
    assert decision["status"] == expected and decision["reason"] == reason
    assert bool(result["items"]) is (expected == "phu_hop")
    assert (decision["basis"] is None) is (expected == "chua_ro")
    assert len(chat.payloads) == 1
    payload = chat.payloads[0]
    assert payload["temperature"] == 0 and payload["response_format"] == dict(type="json_object")
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["description"] == DESCRIPTION and sent["items"][0]["name"] == ROBOT["name"]
    assert sent["items"][0]["lead"] == hr.split_conditions(ROBOT)["lead"]
    assert payload["messages"][0]["content"].startswith("Phiên bản: high_risk_v2\n")


def test_missing_info_is_bounded_and_unknown_never_keeps_basis():
    obj = match("chua_ro", missing_info=[None, " ", " x ", "a" * 250, "y", "z"])
    obj["api_key"] = "not-a-setting"
    result = hr.assess_items(DESCRIPTION, [ROBOT], Chat(answer(obj)), "fake", version="high_risk_v2")
    decision = result["relevance"][0]
    assert decision["missing_info"] == ["x", "a" * 200, "y"]
    assert decision["basis"] is None
    assert set(decision) == {"item_id", "status", "basis", "missing_info", "reason"}


@pytest.mark.parametrize("value,reason,ok", [
    ("hỏng", "invalid_response", False), ("[]", "invalid_response", False),
    (dict(items=None), "invalid_response", False),
    (dict(items=[]), "missing_item", True),
    (dict(items=[dict(item_id="ngoài", object_match=match())]), "missing_item", True),
])
def test_invalid_response_and_unknown_ids_never_select(value, reason, ok):
    result = hr.assess_items(DESCRIPTION, [ROBOT], Chat(value), "fake", version="high_risk_v2")
    assert result["items"] == [] and result["assess_ok"] is ok
    assert result["relevance"][0]["reason"] == reason


def test_duplicate_ids_cannot_be_combined_into_a_match():
    value = answer(match())
    value["items"].append(deepcopy(value["items"][0]))
    result = hr.assess_items(DESCRIPTION, [ROBOT], Chat(value), "fake", version="high_risk_v2")
    assert result["items"] == []
    assert result["relevance"][0]["reason"] == "duplicate_item"


@pytest.mark.parametrize("statuses", [
    ("dap_ung", "dap_ung"), ("dap_ung", "khong_dap_ung"),
    ("chua_ro", "chua_ro"), ("khong_dap_ung", "khong_dap_ung"),
])
def test_eligible_keeps_condition_rules_and_legacy_call(statuses):
    value = answer(match(), statuses)
    old = hr.assess_items(DESCRIPTION, [ROBOT], Chat(value), "fake")
    new = hr.assess_items(DESCRIPTION, [ROBOT], Chat(value), "fake", version="high_risk_v2")
    assert new["items"] == old["items"]
    assert set(old) == {"items", "assess_ok"}
    rendered_old = hr.render_assessment(DESCRIPTION, old, ITEMS, PARENTS)
    rendered_new = hr.render_assessment(DESCRIPTION, new, ITEMS, PARENTS)
    assert rendered_new["status"] == rendered_old["status"]
    assert rendered_new["text"] == rendered_old["text"]
    assert rendered_new["parent_ids"] == rendered_old["parent_ids"]


@pytest.mark.parametrize("obj,reason", [
    (match("chua_ro"), "unresolved"),
    (match("khong_phu_hop"), "not_relevant"),
])
def test_no_eligible_is_neutral_even_if_conditions_all_satisfied(obj, reason):
    result = hr.assess_items(DESCRIPTION, [ROBOT], Chat(answer(obj, ("dap_ung", "dap_ung"))),
                             "fake", version="high_risk_v2")
    rendered = hr.render_assessment(DESCRIPTION, result, ITEMS, PARENTS)
    assert rendered["status"] == "chua_du_co_so" and rendered["selection_reason"] == reason
    assert rendered["parent_ids"] == list(hr.FIXED_PARENTS)
    assert ROBOT["name"] not in rendered["text"]
    assert "không phải kết luận sản phẩm không thuộc Danh mục" in rendered["text"]
    reply = assemble_report("Nội dung", [], rendered, [], PARENTS)
    assert "## Đối chiếu Danh mục rủi ro cao" in reply and "có thể liên quan" not in reply
    if reason == "unresolved":
        assert "chức năng chính, đầu ra và cách sử dụng" in rendered["text"]


def test_no_candidates_no_call_and_v2_header_validation(monkeypatch, tmp_path):
    chat = Chat("không gọi")
    result = hr.assess_items(DESCRIPTION, [], chat, "fake", version="high_risk_v2")
    assert result == dict(items=[], assess_ok=True, version="high_risk_v2", relevance=[])
    assert not chat.payloads
    rendered = hr.render_assessment(DESCRIPTION, result, ITEMS, PARENTS)
    assert rendered["status"] == "chua_du_co_so" and rendered["selection_reason"] == "no_candidates"
    path = tmp_path / "new.txt"
    path.write_text("Phiên bản: sai", encoding="utf-8")
    monkeypatch.setattr(hr, "PROMPT_V2_PATH", path)
    with pytest.raises(ValueError, match="high_risk_v2"):
        hr.assess_items(DESCRIPTION, [ROBOT], chat, "fake", version="high_risk_v2")
    assert not chat.payloads


def graph_fixture(statuses, *, pinned=False, hits=True):
    parents, documents, _, _ = fixture_data()
    items = [dict(item_id=hr.PREFIX + f"X_stt-{i}", name=f"Tên ứng viên riêng {i}", sector="Ví dụ", stt=str(i),
                  description="Chỉ áp dụng khi:\n- Điều kiện A\n- Điều kiện B") for i in range(len(statuses))]
    item_parents = [dict(parents[2], parent_id=i["item_id"], level="list_item", article=None,
                         title=i["name"], text=i["description"]) for i in items]
    parents += item_parents
    decisions = [dict(item_id=i["item_id"], object_match=match(s),
                     conditions=[dict(index=n, status="chua_ro", basis=None) for n in (1, 2)])
                 for i, s in zip(items, statuses)]
    replies = [analysis(request_kinds=["nghia_vu"], sub_queries=["truy vấn đầy đủ"],
                        profile_update=dict(product_description=DESCRIPTION))]
    if hits and items:
        replies.append(dict(items=decisions))
    replies.append("Nội dung [E1].")
    chat = FakeChat(*replies)
    def prepare(message, queries, **kwargs):
        units = [parents[0], *item_parents]
        return dict(evidence=build_evidence(units, documents), queries=queries, query_used=queries[0],
                    references_added=[], detail={}, timing={}, route="retrieval", prompt_version="answer_v8",
                    parents_used=[p["parent_id"] for p in units])
    graph = build_graph(GraphDeps(chat, "fake", prepare,
        config=AgentConfig(enable_obligations=False, enable_rewrite=False, enable_verifier=False),
        pipeline_factory=lambda: SimpleNamespace(search=lambda q: [dict(chunk_id=i["item_id"]) for i in items] if hits else []),
        parents=parents, documents=documents, high_risk_loader=lambda: items,
        chunks_loader=lambda: [dict(chunk_id=i["item_id"], parent_id=i["item_id"]) for i in items]))
    context = None
    if pinned:
        context = dict(assessment=dict(id="ob-x", applicability="ap_dung", conditions=[], status="chua_ro", criteria=[],
                                      citations=[dict(chunk_id=items[0]["item_id"])]))
    result = run_turn(graph, "s", "Nghĩa vụ AI?", context=context)
    return result, graph, chat, items


@pytest.mark.parametrize("statuses,eligible,displayed", [
    (["chua_ro", "khong_phu_hop", "phu_hop", "phu_hop", "phu_hop"], [2, 3, 4], [2, 3, 4]),
    (["phu_hop"] * 5, list(range(5)), [0, 1, 2]),
])
def test_graph_filters_before_cap_and_exposes_trace_without_source_leaks(statuses, eligible, displayed):
    result, graph, chat, items = graph_fixture(statuses)
    selection = next(n["candidate_selection"] for n in result["trace"] if n["node"] == "check_high_risk")
    ids = [i["item_id"] for i in items]
    assert selection["candidate_ids"] == ids
    assert selection["eligible_ids"] == [ids[n] for n in eligible]
    assert selection["displayed_ids"] == [ids[n] for n in displayed]
    assert len(selection["relevance"]) == 5
    assert next(n["candidate_selection"] for n in trace_view(result)["nodes"] if n["node"] == "check_high_risk") == selection
    assert result["high_risk"]["parent_ids"] == [ids[n] for n in displayed] + list(hr.FIXED_PARENTS)
    for n, item in enumerate(items):
        assert (item["name"] in result["reply"]) is (n in displayed)
        footer = result["reply"].split("## Căn cứ pháp lý\n\n", 1)[1]
        assert (item["name"] in footer) is (n in displayed)
    assert not any(e["parent_id"] in ids for e in result["evidence"])
    assert result["llm_calls"] == len(chat.payloads) == 3
    assert chat.payloads[-1]["messages"][1]["content"].count("Câu hỏi đầy đủ: truy vấn đầy đủ") == 1


def test_pinned_context_is_independent_of_discarded_candidate():
    result, graph, chat, items = graph_fixture(["khong_phu_hop", "chua_ro"], pinned=True)
    pinned = items[0]["item_id"]
    assert result["high_risk"]["status"] == "chua_du_co_so"
    assert result["high_risk"]["parent_ids"] == list(hr.FIXED_PARENTS)
    assert any(e["parent_id"] == pinned and e["source"] == "pinned" for e in result["evidence"])
    node = next(n for n in result["trace"] if n["node"] == "check_high_risk")
    assert pinned not in node["removed_list_items"]
    assert items[1]["item_id"] in node["removed_list_items"]
    assert graph.get_state({"configurable": {"thread_id": "s"}}).values["pinned_parents"] == [pinned]


def test_render_cannot_reintroduce_item_without_valid_relevance():
    forged = dict(answer(match()), version="high_risk_v2", relevance=[], assess_ok=True)
    rendered = hr.render_assessment(DESCRIPTION, forged, ITEMS, PARENTS)
    assert rendered["status"] == "chua_du_co_so"
    assert ROBOT["item_id"] not in rendered["parent_ids"]
