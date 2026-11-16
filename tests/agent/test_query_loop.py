"""Agent: nhiều truy vấn, chấm bằng chứng, viết lại truy vấn, sửa câu trả lời."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from legal_rag.agent.answer import prepare_evidence, generate_answer
from legal_rag.agent.budget import LLMBudgetExceeded
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.grade import grade_evidence
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.agent.trace_view import trace_view
from legal_rag.llm import LLMError
from legal_rag.retrieval.pipeline import RetrievalPipeline
from legal_rag.retrieval.fusion import rrf
from test_basic_rag import chunks, parents, config, Encoder, DOCUMENTS
from test_agent_graph import FakeChat, analysis, state
from legal_rag.agent.followup import NOTICE
from legal_rag.agent.profile import EMPTY_PROFILE, merge_profile
from test_agent_graph import FakeChat, analysis
from test_verify_repair_followup import prepare, generator, ISSUE
from legal_rag.agent.analyze import analyze_turn, QUESTION_TYPES
from legal_rag.agent.answer import generate_answer
from legal_rag.agent.blocks import check_blocks, OBLIGATION_BLOCKS
from legal_rag.agent.followup import ask_followup, CLOSING
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.prompt import build_messages
from test_basic_rag import parents, DOCUMENTS
from legal_rag.agent.blocks import required_blocks
from legal_rag.agent.repair import repair_answer
from legal_rag.retrieval.rerank import ScoreLRU, rerank
from test_basic_rag import chunks, parents, config, DOCUMENTS


ROOT = Path(__file__).resolve().parents[2]


def make_pipeline():
    calls, encoder = [], Encoder()
    def score(pairs):
        calls.append(pairs)
        return list(range(len(pairs)))
    pipeline = RetrievalPipeline(chunks(), parents(), config(dense=("jina",), rerank_pool=3, exact_first=True),
        encoders={"jina": encoder}, vectors={"jina": np.array([[1., 0.], [0., 1.], [.5, .5]])}, scorer=score)
    return pipeline, calls, encoder


def test_single_multi_equivalent_and_duplicate_queries_rerank_once():
    p, calls, encoder = make_pipeline()
    query = "Điều 2 Luật 134/2025/QH15"
    expected = p.search(query)
    assert p.search_many([query], query) == expected
    assert p.search_many([query, query], query) == expected
    assert len(calls) == 1 and encoder.queries == [query]
    assert p.context_many([query], query, 3000) == p.context(query, 3000)
    assert p.last_detail["exact"][0]["chunk_id"] == "b"


def test_many_fuses_every_source_once_and_exact_order(monkeypatch):
    import legal_rag.retrieval.pipeline as module
    p, calls, _ = make_pipeline()
    rankings = []
    def fusion(rows):
        rankings.extend(rows)
        return rrf(rows)
    monkeypatch.setattr(module, "rrf", fusion)
    result = p.search_many(["Điều 2", "Điều 1"], "nhãn")
    assert len(rankings) == 4 and len(calls) == 1
    assert all(pair[0] == "nhãn" for pair in calls[0])
    assert [h["chunk_id"] for h in result[:2]] == ["b", "a"]
    detail = p.last_detail
    assert detail["queries"] == ["Điều 2", "Điều 1"] and len(detail["retrieval"]) == 2
    for query in detail["retrieval"]:
        assert set(query) == {"query", "bm25", "dense"}
        for rows in [query["bm25"], *query["dense"].values()]:
            assert len(rows) <= 10 and all(set(h) == {"chunk_id", "score"} for h in rows)
    assert "index_text" not in json.dumps(detail) and "body" not in json.dumps(detail)
    assert all(set(h) == {"chunk_id", "score"} for key in ("rrf", "rerank", "exact") for h in detail[key])


@pytest.mark.parametrize("response,status,ok,rewrites", [
    ("oops", "du", False, []), ([], "du", False, []), ({}, "du", False, []),
    ({"status": "strange"}, "du", False, []), ({"status": None}, "du", False, []),
    ({"status": "du", "rewrite": ["q"]}, "du", True, []),
    ({"status": "thieu_mot_phan", "rewrite": [" q ", "q", "", None, "r", "s"]}, "thieu_mot_phan", True, ["q", "r"]),
    ({"status": "khong_lien_quan", "rewrite": None}, "khong_lien_quan", True, []),
    ({"status": "thieu_mot_phan"}, "thieu_mot_phan", True, []),
])
def test_grade_parse_and_compact_payload(response, status, ok, rewrites):
    chat = FakeChat(response)
    item = dict(id="E1", document_number="134/2025/QH15", article="1", clause=None,
                article_title="Tiêu đề", text="x" * 900)
    result = grade_evidence("Câu hỏi", ["q"], [item], chat, "fake")
    assert result["status"] == status and result["grade_ok"] == ok and result["rewrite"] == rewrites
    assert len(chat.payloads) == 1
    payload = chat.payloads[0]
    assert payload["temperature"] == 0 and payload["response_format"] == {"type": "json_object"}
    assert json.loads(payload["messages"][1]["content"])["evidence"][0]["text"] == "x" * 400


def test_grade_checks_prompt_version(monkeypatch, tmp_path):
    import legal_rag.agent.grade as module
    path = tmp_path / "grade.txt"
    path.write_text("Phiên bản: sai", encoding="utf-8")
    monkeypatch.setattr(module, "PROMPT_PATH", path)
    chat = FakeChat()
    with pytest.raises(ValueError, match="grade_v1"):
        grade_evidence("q", [], [], chat, "fake", version="grade_v1")
    assert not chat.payloads


def grade(status="thieu_mot_phan", rewrite=None):
    return dict(status=status, missing=["khía cạnh"], rewrite=rewrite if rewrite is not None else ["truy vấn bổ sung"])


def graph_case(grades, config=AgentConfig(enable_verifier=False), generator=generate_answer, message="Nhãn AI cần gì?"):
    calls = []
    pipeline = SimpleNamespace(last_detail={}, last_timing={})
    def context_many(queries, rerank_query, budget):
        calls.append((list(queries), rerank_query, budget))
        pipeline.last_detail = dict(queries=list(queries), rerank_query=rerank_query, retrieval=[], rrf=[], rerank=[], exact=[])
        return parents()[:1]
    pipeline.context_many = context_many
    chat = FakeChat(analysis(sub_queries=["truy vấn độc lập", "truy vấn thứ hai", "truy vấn thứ ba"]),
                    *grades, "Nội dung [E1]")
    prepare = prepare_evidence(lambda: pipeline, parents(), DOCUMENTS,
                               chunks_loader=chunks, config=config)
    original_prepare = prepare
    def prepare(*args, **kwargs):
        result = original_prepare(*args, **kwargs)
        result["prompt_version"] = "answer_v8"
        return result
    graph = build_graph(GraphDeps(chat, "fake", prepare, config, generator))
    result = run_turn(graph, "s", message)
    return result, calls, chat, graph


@pytest.mark.parametrize("grades,rounds,rewrites", [
    ([grade("du")], 1, 0),
    ([grade(rewrite=["một"]), grade("du")], 2, 1),
    ([grade(rewrite=["một"]), grade(rewrite=["hai"])], 2, 1),
    ([grade(rewrite=[])], 1, 0),
    ([grade(rewrite=["truy vấn độc lập"])], 1, 0),
    (["JSON hỏng"], 1, 0),
    ([LLMError("lỗi chấm")], 1, 0),
])
def test_graph_loops_bounded_generates_once(grades, rounds, rewrites):
    result, calls, chat, graph = graph_case(grades)
    names = [n["node"] for n in result["trace"]]
    assert names.count("retrieve") == names.count("grade_evidence") == rounds
    assert names.count("rewrite_query") == rewrites and names.count("generate") == 1
    assert result["llm_calls"] == rounds + 2 and result["reply"].startswith("Nội dung [E1]")
    assert len(calls) == rounds and all(len(qs) <= 6 for qs, _, _ in calls)
    assert len(state(graph)["last_parents"]) == 1
    prompt = chat.payloads[-1]["messages"][1]["content"]
    assert "Câu hỏi đầy đủ: truy vấn độc lập" in prompt
    if isinstance(grades[0], LLMError):
        assert next(n for n in result["trace"] if n["node"] == "grade_evidence")["grade_error"] == "lỗi chấm"
    if grades[0] == "JSON hỏng":
        assert not next(n for n in result["trace"] if n["node"] == "grade_evidence")["grade_ok"]
    assert state(graph)["llm_messages"] == chat.payloads[-1]["messages"]


def test_query_limit_skips_extra_loop_and_uses_config_budget():
    result, calls, _, _ = graph_case([grade(rewrite=["một", "hai"]), grade(rewrite=["ba"])],
                                    AgentConfig(enable_verifier=False, budget=123, rerank_mode="joined"))
    assert len(calls) == 2 and len(calls[-1][0]) == 6
    assert calls[-1][1] == " ".join(calls[-1][0]) and all(c[2] == 123 for c in calls)
    assert sum(n["node"] == "rewrite_query" for n in result["trace"]) == 1


def test_disabled_grade_no_llm():
    result, calls, chat, _ = graph_case([], AgentConfig(enable_rewrite=False, enable_verifier=False))
    assert len(chat.payloads) == 2 and len(calls) == 1
    entry = next(n for n in result["trace"] if n["node"] == "grade_evidence")
    assert entry["status"] == "bo_qua" and entry["llm_calls"] == 0


def test_broad_skips_retrieve_and_grade():
    from test_broad_frame import real_parents
    prepare = prepare_evidence(lambda: pytest.fail("Không tạo pipeline"), real_parents(),
                               {"134-2025-QH15": DOCUMENTS[0]}, chunks_loader=chunks)
    chat = FakeChat(analysis(request_kinds=["nghia_vu"]), "Nội dung [E1]")
    result = run_turn(build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_verifier=False))), "s", "Một sản phẩm AI cần có những nghĩa vụ gì?")
    names = [n["node"] for n in result["trace"]]
    assert "retrieve" not in names and "grade_evidence" not in names and result["llm_calls"] == 2
    assert all(i["source"] == "frame" for i in result["evidence"])


@pytest.mark.parametrize("extra,expected", [(3, "retrieval"), (4, "error")])
def test_worst_case_budget_reserves_two_future_calls(extra, expected):
    def generate(message, queries, profile, prepared, chat, model):
        result = generate_answer(message, queries, profile, prepared, chat, model)
        for _ in range(extra):
            chat.complete({"model": model})
        if extra == 3:
            with pytest.raises(LLMBudgetExceeded):
                chat.complete({"model": model})
        return result
    # Cần hai phản hồi giả cho hai lời gọi dành cho bước sau.
    prep = prepare_evidence(lambda: SimpleNamespace(context_many=lambda qs, *args: parents()[:len(qs)],
        last_detail={}, last_timing={}), parents(), DOCUMENTS, chunks_loader=chunks)
    chat = FakeChat(analysis(), grade(rewrite=["một"]), grade(rewrite=["hai"]), grade("du"),
                    "Nội dung [E1]", "kiểm", "sửa", "phụ")
    original_prep = prep
    def prep(*args, **kwargs):
        result = original_prep(*args, **kwargs)
        result["prompt_version"] = "answer_v8"
        return result
    graph = build_graph(GraphDeps(chat, "fake", prep, AgentConfig(max_rewrites=2), generate_fn=generate))
    result = run_turn(graph, "s", "Nhãn AI cần gì?")
    assert result["llm_calls"] == len(chat.payloads) == 8 and result["route"] == expected


def test_trace_view_omits_prompt_secret_and_preserves_all_rounds():
    result, _, _, _ = graph_case([grade(rewrite=["một"]), grade("du")])
    raw = dict(nodes=result["trace"], evidence=result["evidence"], check=result["check"],
               messages=[{"content": "PROMPT_SENTINEL"}], api_key="SECRET_SENTINEL")
    raw["nodes"][0].update(prompt="PROMPT_SENTINEL", api_key="SECRET_SENTINEL")
    view = trace_view(raw)
    text = json.dumps(view)
    assert "PROMPT_SENTINEL" not in text and "SECRET_SENTINEL" not in text and "messages" not in text
    assert len(view["nodes"]) == len(result["trace"])
    assert sum("last_detail" in n for n in view["nodes"]) == 2
    assert all(i["source"] == "retrieval" for i in view["evidence"])


def eval_module():
    spec = importlib.util.spec_from_file_location("eval_multiquery", ROOT / "scripts/eval_multiquery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runs(values):
    return {name: dict(metrics=dict(questions=dict(recall=v), turns=dict(recall=.5264)))
            for name, v in zip(("base", "first", "multi_message", "multi_joined"), values)}


@pytest.mark.parametrize("values,chosen,accepted", [
    ([.7, .71, .71, .71], "first", True), ([.7, .6, .72, .73], "multi_joined", True),
    ([.7, .6, .6, .6], "multi_message", False), ([.7, .68, .67, .67], "first", True)])
def test_selection_rule(values, chosen, accepted):
    result = eval_module().choose_multiquery(runs(values))
    assert result["candidate"] == chosen and result["accepted"] == accepted


def test_eval_settings_turn_text_fallback_and_macro(capsys):
    module = eval_module()
    gold = [dict(id="q1", question="gốc", gold_parents=["a", "b"]),
            dict(id="q2", question="khác", gold_parents=["a"]),
            dict(id="s001.t1", scenario_id="s001", turn_text="câu tiếp", question="câu ghép", gold_parents=["b"])]
    analysis_data = dict(questions=dict(results=[dict(id="q1", sub_queries=["một", "hai"])]),
                         scenarios=dict(results=[dict(id="s001.t1", sub_queries=["độc lập"])]))
    settings, fallback = module.query_settings(gold[-1], analysis_data)
    assert not fallback and settings["base"] == (["câu ghép"], "câu ghép")
    assert settings["multi_message"] == (["độc lập"], "câu tiếp")
    pipeline = SimpleNamespace(context_many=lambda qs, rq, budget: [dict(parent_id="a")])
    result, fallbacks = module.measure(gold, analysis_data, pipeline)
    assert result["base"]["metrics"]["questions"]["recall"] == .75
    assert fallbacks == dict(questions=1, turns=0)
    result = runs([.6952, .7, .7, .7])
    module.validate_baseline(result)
    result["base"]["metrics"]["questions"]["recall"] = .5
    with pytest.raises(ValueError, match="dừng"):
        module.validate_baseline(result)


def test_eval_main_exits_nonzero_on_baseline_drift(tmp_path, monkeypatch):
    module = eval_module()
    (tmp_path / "data/processed").mkdir(parents=True)
    (tmp_path / "eval").mkdir()
    for name, rows in (("chunks", chunks()), ("parents", parents())):
        (tmp_path / f"data/processed/{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / "eval/retrieval.jsonl").write_text(json.dumps(dict(id="q1", question="gốc", gold_parents=["a"], gold_articles=[])), encoding="utf-8")
    path = tmp_path / "analysis.json"
    path.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    assert module.main(["--analysis", str(path), "--output", str(output)], root=tmp_path,
        pipeline_factory=lambda *args: SimpleNamespace(context_many=lambda *args: [])) == 1
    assert not output.exists()


@pytest.mark.parametrize("rounds", [1, 2])
def test_graph_duplicate_queries_use_real_pipeline_and_scorer_once_per_round(rounds):
    pipeline, scorer_calls, _ = make_pipeline()
    prep = prepare_evidence(lambda: pipeline, parents(), DOCUMENTS, chunks_loader=chunks)
    grades = [grade(rewrite=["một"]), grade(rewrite=["hai"])] if rounds == 2 else [grade("du")]
    chat = FakeChat(analysis(sub_queries=["nhãn", "nhãn"]), *grades, "Nội dung [E1]")
    original_prep = prep
    def prep(*args, **kwargs):
        result = original_prep(*args, **kwargs)
        result["prompt_version"] = "answer_v8"
        return result
    result = run_turn(build_graph(GraphDeps(chat, "fake", prep, AgentConfig(enable_verifier=False, max_rewrites=2))), "s", "Nhãn AI có yêu cầu gì?")
    assert len(scorer_calls) == 1
    retrievals = [n for n in result["trace"] if n["node"] == "retrieve"]
    assert len(retrievals) == rounds and retrievals[0]["last_detail"]["queries"] == ["nhãn", "Nhãn AI có yêu cầu gì?"]
    assert all(len(n["last_detail"]["queries"]) == i + 1 for i, n in enumerate(retrievals, 1))


def test_trace_view_filters_nested_secret_fields():
    detail = dict(queries=["q"], rerank_query="q", retrieval=[dict(query="q", bm25=[dict(
        chunk_id="a", score=1, text="PROMPT_SENTINEL", api_key="SECRET_SENTINEL")], dense={})])
    raw = dict(nodes=[dict(node="retrieve", last_detail=detail)], check=dict(
        valid=False, errors=[dict(api_key="SECRET_SENTINEL", prompt="PROMPT_SENTINEL", reason="lỗi")]))
    view = trace_view(raw)
    assert "SECRET_SENTINEL" not in json.dumps(view) and "PROMPT_SENTINEL" not in json.dumps(view)
    assert view["check"]["errors"] == [dict(reason="lỗi")]


def test_eval_reachability_stops_before_pipeline_creation(tmp_path, monkeypatch):
    module = eval_module()
    (tmp_path / "data/processed").mkdir(parents=True)
    (tmp_path / "eval").mkdir()
    for name, rows in (("chunks", chunks()), ("parents", parents())):
        (tmp_path / f"data/processed/{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / "eval/retrieval.jsonl").write_text(json.dumps(dict(id="q1", question="gốc", gold_parents=["không tồn tại"], gold_articles=[])), encoding="utf-8")
    assert module.main([], root=tmp_path, pipeline_factory=lambda *args: pytest.fail("Không tạo pipeline")) == 1


def test_eval_drift_stops_before_candidate_queries():
    module = eval_module()
    calls = []
    pipeline = SimpleNamespace(context_many=lambda qs, q, b: calls.append(q) or [])
    gold = [dict(id="q1", question="base", gold_parents=["a"])]
    with pytest.raises(ValueError, match="dừng"):
        module.measure(gold, dict(questions=dict(results=[dict(id="q1", sub_queries=["candidate"])])),
                       pipeline, enforce_baseline=True)
    assert calls == ["base"]


def test_defaults():
    config = AgentConfig()
    assert config.analyze_prompt == "analyze_v7"
    assert config.verifier_mode == "rule"
    assert config.accept_ai_reviewed is True


def test_default_accepts_ai_reviewed_rows():
    from test_map_report import make_case, row
    graph, _, _ = make_case("Nội dung [E1].", rows=[row(review_status="ai_reviewed")],
                            config=AgentConfig(enable_rewrite=False, enable_high_risk=False))
    result = run_turn(graph, "s", "Nghĩa vụ AI là gì?")
    assert result["map_obligations"]["selected"] == ["A"]
    assert result["map_obligations"]["unreviewed_count"] == result["map_obligations"]["rejected_count"] == 0


def test_declared_risk_survives_next_turn():
    chat = FakeChat(analysis(profile_update={"risk_level": "cao"}), "Nội dung [E1].",
                    analysis(profile_update={"risk_level": None}), "Nội dung [E1].")
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False), generator))
    assert run_turn(graph, "s", "Tôi tự phân loại AI rủi ro cao")["profile"]["risk_level"] == "cao"
    assert run_turn(graph, "s", "Nhãn AI cần gì?")["profile"]["risk_level"] == "cao"


@pytest.mark.parametrize("field,value", [
    ("analyze_prompt", "analyze_v1"), ("analyze_prompt", None),
    ("verifier_mode", "llm"), ("verifier_mode", None)])
def test_config_rejects_unknown_modes(field, value):
    with pytest.raises(ValueError, match=field):
        AgentConfig(**{field: value})


@pytest.mark.parametrize("version", ["analyze_v2", "analyze_v3"])
def test_graph_uses_configured_prompt(version):
    chat = FakeChat(analysis(), "Nội dung [E1].")
    config = AgentConfig(analyze_prompt=version, enable_rewrite=False)
    graph = build_graph(GraphDeps(chat, "fake", prepare, config, generator))
    result = run_turn(graph, "s", "Nghĩa vụ AI?")
    assert chat.payloads[0]["messages"][0]["content"].startswith(f"Phiên bản: {version}\n")
    assert result["profile"]["risk_level"] is None


@pytest.mark.parametrize("risk", ["cao", "trung_binh", "thap", "chua_phan_loai"])
def test_merge_declared_risk(risk):
    profile, ignored = merge_profile(EMPTY_PROFILE, {"risk_level": risk})
    assert profile["risk_level"] == risk and ignored == []
    assert merge_profile(profile, {"risk_level": None}) == (profile, [])
    assert merge_profile(profile, {"risk_level": "khop"}) == (profile, ["risk_level"])


@pytest.mark.parametrize("mode,enabled,calls", [
    ("rule", True, 2), ("rule_llm", True, 3), ("rule_llm", False, 2)])
def test_verifier_calls_and_trace(mode, enabled, calls):
    chat = FakeChat(analysis(), "Nội dung [E1].", {"issues": [ISSUE]}, "Nội dung [E1].")
    config = AgentConfig(verifier_mode=mode, enable_verifier=enabled, enable_rewrite=False)
    graph = build_graph(GraphDeps(chat, "fake", prepare, config, generator))
    result = run_turn(graph, "s", "Nhãn AI cần gì?")
    uses_llm = mode == "rule_llm" and enabled
    assert len(chat.payloads) == calls + int(uses_llm)  # thêm một lần sửa khi có cờ LLM
    assert result["verification"]["repaired"] is uses_llm
    node = next(n for n in trace_view(result)["nodes"] if n["node"] == "verify_citations")
    assert node["verifier_mode"] == mode
    assert node["llm_calls"] == int(uses_llm)


@pytest.mark.parametrize("repair,valid", [("Đúng [E1].", True), ("Vẫn sai [E99].", False)])
def test_rule_mode_keeps_repair_final_valid_and_notice(repair, valid):
    chat = FakeChat(analysis(), "Sai [E99].", repair)
    graph = build_graph(GraphDeps(chat, "fake", prepare,
        AgentConfig(enable_rewrite=False), generator))
    result = run_turn(graph, "s", "Nhãn AI cần gì?")
    assert result["llm_calls"] == 3
    assert result["verification"] == dict(issues=[], repaired=True, final_valid=valid)
    assert (NOTICE in result["reply"]) is (not valid)
    assert next(n for n in result["trace"] if n["node"] == "verify_citations")["llm_calls"] == 0


def test_v3_only_changes_profile_rules_and_adds_declared_risk():
    root = Path(__file__).resolve().parents[2]
    old = (root / "prompts/analyze_v2.txt").read_text(encoding="utf-8")
    new = (root / "prompts/analyze_v3.txt").read_text(encoding="utf-8")
    restored = new.replace("Phiên bản: analyze_v3", "Phiên bản: analyze_v2", 1)
    restored = restored.replace(
        "profile_update: với role, sector, is_public_sector, generates_content, product_description, chỉ điền khi người dùng nói rõ hoặc suy ra trực tiếp từ một câu cụ thể; nếu không thì null. Không đoán.",
        "profile_update: chỉ ghi điều người dùng nói rõ hoặc suy ra trực tiếp từ lời họ; không đoán, không rõ thì bỏ khóa.")
    restored = restored.replace("true, false hoặc null", "true hoặc false")
    restored = "\n".join(line for line in restored.split("\n") if not line.startswith("- risk_level:"))
    assert restored == old


SHORT = "## Trả lời ngắn\nBằng chứng được cung cấp không nêu mức tiền cụ thể [E1]."


ANSWER = SHORT + "\n\n## Căn cứ\nQuy định liên quan [E1].\n\n" + CLOSING


@pytest.mark.parametrize("value,expected", [(x, x) for x in QUESTION_TYPES] + [
    ("la", "khac"), (None, "khac"), ([], "khac"), ({}, "khac")])
def test_question_type(value, expected):
    result = analyze_turn("Mức phạt AI?", {}, [], FakeChat(analysis(question_type=value)), "fake")
    assert result["question_type"] == expected


def test_missing_and_broken_analysis():
    for response in (analysis(), "bad", [], {}):
        assert analyze_turn("AI?", {}, [], FakeChat(response), "fake")["question_type"] == "khac"


@pytest.mark.parametrize("version", ["analyze_v2", "analyze_v3"])
def test_legacy_analyze_ignores_new_key(version):
    result = analyze_turn("AI?", {}, [], FakeChat(analysis(question_type="su_kien")),
                          "fake", version=version)
    assert result["question_type"] == "khac"


@pytest.mark.parametrize("kind", QUESTION_TYPES)
def test_payload_type_only_in_user_message(kind):
    payload = build_messages("AI?", [], question_type=kind)
    assert f"Loại câu hỏi: {kind}" in payload["messages"][1]["content"]
    assert f"Loại câu hỏi: {kind}" not in payload["messages"][0]["content"]
    assert "Loại câu hỏi:" not in build_messages("AI?", [], "answer_v8")["messages"][1]["content"]


@pytest.mark.parametrize("kind", QUESTION_TYPES)
def test_required_blocks(kind):
    check = {"used": []}
    expected = ["Trả lời ngắn"] + (list(OBLIGATION_BLOCKS) if kind == "nghia_vu" else ["Căn cứ"])
    assert check_blocks(check, [], "", "answer_v9", kind) == expected
    answer = "\n".join("## " + title + "\nNội dung" for title in expected)
    assert check_blocks(check, [], answer, "answer_v9", kind) == []
    for title in expected:
        assert check_blocks(check, [], answer.replace("## " + title, "### " + title),
                            "answer_v9", kind) == [title]
    assert check_blocks(check, [], "", "answer_v8", kind) == []


@pytest.mark.parametrize("kind", QUESTION_TYPES)
def test_followup_by_type(kind):
    update, field = ask_followup(dict(analysis={"question_type": kind}, profile=EMPTY_PROFILE,
                                     message="Nhãn AI?", reply=ANSWER, route="retrieval"))
    assert bool(update) == (kind in ("nghia_vu", "khac"))
    assert field == ("role" if kind in ("nghia_vu", "khac") else None)


def run_case(statuses, *, max_rewrites=1, parent_sets=None, kind="su_kien",
             grade_prompt="grade_v2"):
    parent_sets = parent_sets or [["a"]] * (len(statuses))
    calls = []
    items = build_evidence(parents()[:1], DOCUMENTS)

    def prepare(message, queries, *, rewritten, **kwargs):
        ids = parent_sets[len(calls)]
        evidence = [dict(items[0], id=f"E{i+1}", parent_id=key) for i, key in enumerate(ids)]
        calls.append(list(rewritten))
        return dict(route="retrieval", prompt_version="answer_v9", evidence=evidence,
                    parents_used=ids, queries=[*queries, *rewritten], query_used=queries[0],
                    references_added=[], detail={}, timing={})

    chat = FakeChat(analysis(question_type=kind, sub_queries=["goc"]), *statuses, ANSWER)
    config = AgentConfig(max_rewrites=max_rewrites, grade_prompt=grade_prompt,
                         enable_high_risk=False, enable_obligations=False)
    graph = build_graph(GraphDeps(chat, "fake", prepare, config))
    result = run_turn(graph, "s", "Không gắn nhãn video deepfake thì bị phạt bao nhiêu tiền?")
    return result, calls, chat, graph


def grade_qa_focus_speed(status="thieu_mot_phan", queries=("moi",)):
    return dict(status=status, missing=[], rewrite=list(queries))


@pytest.mark.parametrize("statuses,limit,sets,reason,count", [
    ([grade_qa_focus_speed("khong_co_chi_tiet")], 1, None, "khong_co_chi_tiet", 1),
    ([grade_qa_focus_speed("du")], 1, None, "du", 1),
    ([grade_qa_focus_speed()], 0, None, "max_rewrites", 1),
    ([grade_qa_focus_speed(), grade_qa_focus_speed(queries=["khac"])], 1, [["a"], ["a", "b"]], "max_rewrites", 2),
    ([grade_qa_focus_speed(), grade_qa_focus_speed(queries=["khac"])], 2, [["a"], ["a"]], "no_new_parents", 2),
    ([grade_qa_focus_speed(), grade_qa_focus_speed(queries=["khac"]), grade_qa_focus_speed(queries=["nua"])], 2,
     [["a"], ["a", "b"], ["b", "c"]], "max_rewrites", 3),
    ([grade_qa_focus_speed(queries=["goc"])], 2, None, "no_new_queries", 1),
    ([grade_qa_focus_speed(queries=[])], 2, None, "no_new_queries", 1),
])
def test_stop_conditions(statuses, limit, sets, reason, count):
    result, calls, chat, graph = run_case(statuses, max_rewrites=limit, parent_sets=sets)
    assert len(calls) == count
    assert state(graph)["rewrites"] == count - 1
    assert state(graph)["rewrite_stop_reason"] == reason
    retrieved = [n for n in trace_view(result)["nodes"] if n["node"] == "retrieve"]
    assert [n["retrieval_count"] for n in retrieved] == list(range(1, count+1))
    expected = []
    previous = set()
    for ids in (sets or [["a"]] * count):
        expected.append(len(set(ids) - previous))
        previous = set(ids)
    assert [n["new_parent_count"] for n in retrieved] == expected
    grades = [n for n in trace_view(result)["nodes"] if n["node"] == "grade_evidence"]
    assert grades[-1]["stop_reason"] == reason
    assert result["verification"]["final_valid"]
    assert result["reply"].startswith("## Trả lời ngắn")
    assert "Bạn là bên nào" not in result["reply"]
    assert "Loại câu hỏi: su_kien" in chat.payloads[-1]["messages"][1]["content"]
    assert next(n for n in trace_view(result)["nodes"] if n["node"] == "analyze")["question_type"] == "su_kien"


@pytest.mark.parametrize("value", [-1, 3, True, 1.5, None])
def test_invalid_rewrite_limit(value):
    with pytest.raises(ValueError, match="max_rewrites"):
        AgentConfig(max_rewrites=value)


def test_grade_version_and_terminal_rewrite():
    for version in ("grade_v1", "grade_v2"):
        chat = FakeChat(grade_qa_focus_speed("khong_co_chi_tiet"))
        result = grade_evidence("AI?", [], [], chat, "fake", version=version)
        assert result["rewrite"] == []
        assert result["grade_ok"] == (version == "grade_v2")
        assert chat.payloads[0]["messages"][0]["content"].startswith(f"Phiên bản: {version}")


def test_old_answer_generation_unchanged():
    item = build_evidence(parents()[:1], DOCUMENTS)
    prepared = dict(evidence=item, prompt_version="answer_v8", route="retrieval",
                    parents_used=["a"], query_used="AI?", references_added=[])
    result = generate_answer("AI?", [], EMPTY_PROFILE, prepared, FakeChat("Nội dung [E1]"), "fake")
    assert result["check"]["valid"]
    assert result["prompt_version"] == "answer_v8"


def test_repair_rechecks_new_blocks():
    item = build_evidence(parents()[:1], DOCUMENTS)
    def prepare(*args, **kwargs):
        return dict(evidence=item, prompt_version="answer_v9", route="retrieval",
                    parents_used=["a"], queries=["AI?"], query_used="AI?",
                    references_added=[], detail={}, timing={})
    for repaired, valid in [(ANSWER, True), ("Nội dung [E1]", False)]:
        chat = FakeChat(analysis(question_type="su_kien"), "Nội dung [E1]", repaired)
        graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False)))
        result = run_turn(graph, "s", "Hỏi mức phạt AI?")
        assert result["verification"]["repaired"]
        assert result["verification"]["final_valid"] is valid


def test_v9_headings_tolerate_colon_and_bold():
    from legal_rag.agent.blocks import check_blocks
    answer = "## Trả lời ngắn:\nA [E1].\n## **Căn cứ**:\nB [E1]."
    check = {"valid": True, "errors": [], "used": ["E1"], "warnings": [], "used_points": []}
    assert check_blocks(check, [], answer, "answer_v9", "su_kien") == []


@pytest.mark.parametrize('kind', ['su_kien','dinh_nghia','xac_nhan','nghia_vu','khac'])
def test_repair_prompt_by_type(kind):
    chat=FakeChat(ANSWER)
    repair_answer('sai', ['thiếu'], [], [], chat, 'fake', 'answer_v9', kind)
    payload=chat.payloads[0]
    assert payload['messages'][0]['content'].startswith('Phiên bản: repair_v2')
    data=json.loads(payload['messages'][1]['content'])
    assert data['question_type']==kind
    assert data['required_blocks']==list(required_blocks(kind))
    assert payload['temperature']==0
    chat=FakeChat(ANSWER)
    repair_answer('sai', [], [], [], chat, 'fake', 'answer_v8', kind)
    assert chat.payloads[0]['messages'][0]['content'].startswith('Phiên bản: repair_v1')
    assert 'required_blocks' not in json.loads(chat.payloads[0]['messages'][1]['content'])


def test_heading_normalization_does_not_call_repair():
    items=build_evidence(parents()[:1], DOCUMENTS)
    def prepare(*args, **kwargs):
        return dict(evidence=items,prompt_version='answer_v9',route='retrieval',parents_used=['a'],
                    queries=['AI?'],query_used='AI?',references_added=[],detail={},timing={})
    chat=FakeChat(analysis(question_type='su_kien'),
                  ANSWER.replace('## Trả lời ngắn','## **trả   LỜI ngắn**:')
                        .replace('## Căn cứ','## CĂN CỨ.'))
    graph=build_graph(GraphDeps(chat,'fake',prepare,AgentConfig(enable_rewrite=False,
        enable_high_risk=False,enable_obligations=False)))
    result=run_turn(graph,'s','Mức phạt AI?')
    assert result['reply'].startswith(ANSWER.split('\n\n'+ 'Đây là')[0])
    assert '## **' not in result['reply'] and '## CĂN CỨ.' not in result['reply']
    assert len(chat.payloads)==2
    assert result['verification']['final_valid']
    assert not result['verification']['repaired']


def test_grade_v3_default_terminal():
    assert AgentConfig().grade_prompt=='grade_v3'
    chat=FakeChat(dict(status='khong_co_chi_tiet',missing=['mức tiền'],rewrite=['thử lại']))
    result=grade_evidence('Phạt bao nhiêu?',[],[],chat,'fake')
    assert result['grade_ok'] and result['rewrite']==[]
    assert chat.payloads[0]['messages'][0]['content'].startswith('Phiên bản: grade_v3')


def test_direct_repair_skips_only_heading_errors():
    original=ANSWER.replace('## Căn cứ', '## __CĂN  CỨ__：')
    errors=['Thiếu mục bắt buộc: Căn cứ']
    chat=FakeChat()
    assert repair_answer(original,errors,[],[],chat,'fake','answer_v9','su_kien')==ANSWER
    assert not chat.payloads
    # Có lỗi nội dung hoặc thiếu tiêu đề thực thì vẫn cần bước sửa.
    for text,problems,issues in [(original,errors+['Sai mã trích dẫn'],[]),
                                (original,errors,[{'type':'sai_noi_dung'}]),
                                (original.replace('## Trả lời ngắn',''),errors,[])]:
        chat=FakeChat(ANSWER)
        assert repair_answer(text,problems,issues,[],chat,'fake','answer_v9','su_kien')==ANSWER
        assert len(chat.payloads)==1


class Encoder_qa_repair_speed:
    def __init__(self): self.calls=[]
    def encode_queries(self, texts):
        self.calls.append(list(texts))
        return np.array([[len(q),1.] for q in texts])


class Scorer:
    def __init__(self): self.calls=[]
    def score(self,pairs):
        self.calls.append(list(pairs))
        return [float(len(q)+len(t)) for q,t in pairs]


def pipeline(enabled=True, **kw):
    encoder=Encoder_qa_repair_speed(); scorer=Scorer()
    p=RetrievalPipeline(chunks(),parents(),config(dense=('jina',),rerank_pool=3),
        {'jina':encoder},{'jina':np.array([[1.,0.],[0.,1.],[1.,1.]])},scorer,
        cache_enabled=enabled,**kw)
    return p,encoder,scorer


def test_cache_and_batch_only_new_work():
    p,e,s=pipeline()
    p.search_many(['aa','bbb','aa'],'rq')
    assert e.calls==[['aa','bbb']]
    assert len(s.calls)==1 and len(s.calls[0])==3
    p.search_many(['aa','bbb','cccc'],'rq')
    assert e.calls==[['aa','bbb'],['cccc']]
    assert len(s.calls)==1
    assert p.last_timing['rerank']['new_pairs']==0
    assert p.last_timing['rerank']['cached_pairs']==3
    p.search_many(['aa'],'other')
    assert len(s.calls)==2


@pytest.mark.parametrize('batch', [True,False])
def test_cache_and_no_cache_identical(batch):
    on,_,_=pipeline(batch_queries=batch); off,_,_=pipeline(False,batch_queries=batch)
    for queries in [['aa','bbb'],['aa','bbb','cccc'],['aa','bbb']]:
        assert on.search_many(queries,'rq')==off.search_many(queries,'rq')
        assert on.context_many(queries,'rq')==off.context_many(queries,'rq')


def test_lru_eviction_and_refresh():
    cs=chunks(); lookup={c['chunk_id']:c for c in cs}
    cache=ScoreLRU(2); scorer=Scorer()
    def run(ids):
        return rerank('q',[dict(chunk_id=i) for i in ids],lookup,scorer,len(ids),cache)
    run(['a','b']);run(['a']);run(['c'])
    assert list(cache.entries)==[('q','a'),('q','c')]
    run(['b'])
    assert scorer.calls[-1]==[('q',lookup['b']['index_text'])]
    assert len(cache.entries)==2
    # Một lô lớn hơn sức chứa vẫn trả đủ điểm trước khi loại mục cũ.
    assert len(run(['a','b','c']))==3


def test_cache_zero_and_isolation():
    a,e,s=pipeline(rerank_cache_size=0)
    a.search('q');a.search('q')
    assert len(s.calls)==2 and not a.score_cache.entries
    b,other,_=pipeline();b.search('q')
    assert other.calls==[['q']]
    assert e.calls==[['q']]
