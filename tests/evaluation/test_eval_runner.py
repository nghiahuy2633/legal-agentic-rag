"""T23: kiểm tra bằng phản hồi và pipeline giả, không gọi mạng."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from legal_rag.agent.config import DEFAULT_CONTEXT_BUDGET

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.runtime import build_agent
from legal_rag.evaluation import answers, run
from legal_rag.evaluation.behavior import score_behavior
from legal_rag.llm import LLMError
from test_basic_rag import cli_root
from test_agent_graph import analysis, draft_obligations, FakeChat


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def answer_row(ident="a"):
    return dict(id=ident, question="Hỏi AI", reference_answer="Nội dung",
                required_points=["Nội dung"], gold_parents=["p"],
                expected_behavior="tra_loi", review_status="draft")


def good_judge():
    return dict(meaning_ok=True, points=[dict(point="Nội dung", covered=True)],
                citations_relevant=True, citation_issues=[], unsupported_claims=0, reason="Đủ ý")


def good_result(ident="a", **changes):
    return dict(dict(id=ident, answer="Nội dung [E1]", check={"valid": True}, error=None,
                     route="retrieval", evidence=[], profile={}, llm_calls=3, latency_ms=10,
                     model="fake", llm_attempts=[]), **changes)


def dataset(root, questions=(), scenarios=(), checks=(), answer_rows=None):
    for name, rows in (("questions", questions), ("scenarios", scenarios), ("input_checks", checks)):
        write_rows(root / f"eval/{name}.jsonl", rows)
    if answer_rows is not None:
        write_rows(root / "eval/answers.jsonl", answer_rows)
        write_rows(root / "data/processed/parents.jsonl", [dict(parent_id="p")])


@pytest.mark.parametrize("field,value", [("id", 1), ("question", ""), ("reference_answer", None),
    ("required_points", "x"), ("required_points", [3]), ("gold_parents", [None]),
    ("expected_behavior", 1), ("review_status", []), ("gold_parents", ["không tồn tại"])])
def test_load_schema_and_reachable_parents(tmp_path, field, value):
    row = answer_row()
    row[field] = value
    dataset(tmp_path, answer_rows=[row])
    with pytest.raises(ValueError, match=f"id=.*{field}"):
        answers.load_answers(tmp_path / "eval/answers.jsonl")


def test_load_valid_duplicate_and_bad_json(tmp_path):
    dataset(tmp_path, answer_rows=[answer_row()])
    path = tmp_path / "eval/answers.jsonl"
    assert answers.load_answers(path) == [answer_row()]
    write_rows(path, [answer_row(), answer_row()])
    with pytest.raises(ValueError, match="id=a.*id"):
        answers.load_answers(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="id=.*JSON"):
        answers.load_answers(path)


def test_judge_prompt_schema_payload_and_malformed(monkeypatch):
    row, result = answer_row(), good_result()
    result["evidence"] = [dict(id="E1", text="Nội dung"), dict(id="E2", text="Không trích")]
    chat = FakeChat(good_judge(), "[]", dict(good_judge(), meaning_ok=1), LLMError("HTTP 429", 429))
    judgment = answers.judge_answer(row, result, chat, "judge")
    assert judgment["meaning_ok"] and judgment["key"] == answers.judgment_key(row, result, "judge")
    payload = chat.payloads[0]
    assert payload["temperature"] == 0 and payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][0]["content"].startswith("Phiên bản: judge_v2\n")
    assert json.loads(payload["messages"][1]["content"])["evidence"] == result["evidence"][:1]
    for _ in range(3):
        assert answers.judge_answer(row, result, chat, "judge")["judge_error"]


@pytest.mark.parametrize("condition", ["meaning", "code", "check", "relevance", "good"])
def test_all_four_correctness_conditions(condition):
    row, result, judgment = answer_row(), good_result(), good_judge()
    if condition == "meaning":
        judgment["meaning_ok"] = False
    if condition == "code":
        result["answer"] = "Không trích dẫn"
    if condition == "check":
        result["check"]["valid"] = False
    if condition == "relevance":
        judgment["citations_relevant"] = False
    scores = answers.score_answers([row], [result], {answers.judgment_key(row, result): judgment})
    assert scores["correct_rate"] == (1 if condition == "good" else 0)


def test_errors_missing_and_same_denominator():
    rows = [answer_row(str(i)) for i in range(4)]
    results = [good_result("0"), good_result("1", error="lỗi"), good_result("2")]
    judgments = {answers.judgment_key(rows[0], results[0]): good_judge()}
    scores = answers.score_answers(rows, results, judgments)
    # Câu 2 có cùng nội dung với câu 0 nên dùng lại đúng khóa phán quyết.
    assert scores["n"] == 4 and scores["correct_rate"] == .5
    assert scores["errors"] == 1 and scores["missing_results"] == 1
    other = answers.score_answers(rows, results[:1], judgments)
    assert other["n"] == scores["n"] and other["correct_rate"] == .25
    assert answers.score_answers([], [], {})["correct_rate"] is None
    assert scores == answers.score_answers(rows, results, judgments)


def test_missing_broken_judgment_and_paired_intervals():
    row, result = answer_row(), good_result()
    assert answers.score_answers([row], [result], {})["missing_judgments"] == 1
    assert answers.score_answers([row], [result], {answers.judgment_key(row, result): {}})["correct_rate"] == 0
    a = dict(samples={str(i): dict(correct=1, correct_covered=1, required_points=1) for i in range(10)})
    b = dict(samples={str(i): dict(correct=0, correct_covered=0, required_points=0) for i in range(10)})
    assert answers.compare(a, b)["confidence_interval"] == [1, 1]
    assert answers.compare(a, b)["overlaps_zero"] is False
    assert answers.compare(a, a)["conclusion"] == "chưa đủ để kết luận"
    assert answers.compare(a, b) == answers.compare(a, b)
    with pytest.raises(ValueError):
        answers.compare(a, dict(samples={}))


def test_behavior_known_fields_errors_and_profile_denominator():
    scenarios = [dict(id="s", turns=[
        dict(turn=1, user="AI", expected_behavior="hoi_lai", expected_profile={"role": "nha_cung_cap"}),
        dict(turn=2, user="AI", expected_behavior="tra_loi", expected_profile={"role": "nha_cung_cap"})])]
    questions = [dict(id="refuse", expected_behavior="tu_choi"),
                 dict(id="number", expected_behavior="tra_loi", category="thieu_can_cu")]
    results = [good_result("s.t1", answer="Bạn có vai trò nào?", profile={"role": "nha_cung_cap"}),
               good_result("s.t2", error="lỗi", profile={"role": "nha_cung_cap"}),
               good_result("refuse", route="out_of_scope"),
               good_result("number", route="input_rejected", check={"errors": ["Số tiền ngoài bằng chứng"]})]
    score = score_behavior(scenarios, questions, [], results)
    assert score["asked_known_fields"]["ids"] == ["s.t1"]
    assert score["profile"]["fields"]["role"]["accuracy"] == .5
    assert score["profile"]["n"] == 2 and score["errors"] == 1
    assert score["correct_refusal"]["rate"] == 1
    assert score["false_refusal"]["count"] == 1
    assert score["fabricated_numbers"]["count"] == 1
    assert score_behavior([], [], [], [])["followup"]["rate"] is None


class Executor:
    def __init__(self, responses=None):
        self.calls, self.restores = [], []
        self.responses = responses or {}
        self.chat = FakeChat(good_judge())
        self.settings = SimpleNamespace(model="fake")

    def execute(self, entry, session):
        assert not any(key.startswith("expected_") for key in entry)
        self.calls.append((entry, session))
        response = self.responses.get(entry["id"], {})
        if isinstance(response, Exception):
            raise response
        return good_result(entry["id"], **response)

    def restore(self, session, result):
        self.restores.append((session, result))


def test_resume_skips_success_and_retries_error(tmp_path):
    plan = {"behavior": [dict(id="q1", question="AI"), dict(id="q2", question="AI") ]}
    first = Executor({"q2": LLMError("HTTP 500", 500)})
    assert run.run_config(tmp_path, "full", plan, lambda _: first)[0] == 0
    second = Executor()
    run.run_config(tmp_path, "full", plan, lambda _: second)
    assert [e[0]["id"] for e in second.calls] == ["q2"]
    assert len(run.read_jsonl(tmp_path / "full.behavior.jsonl")) == 3
    assert run.latest(tmp_path / "full.behavior.jsonl")["q2"]["error"] is None


def test_five_429_exit_three_preserves_success_stops_configs(tmp_path, capsys):
    rows = [dict(id=f"q{i}", question="Hỏi AI", expected_behavior="tra_loi") for i in range(8)]
    dataset(tmp_path, questions=rows)
    executor = Executor({f"q{i}": LLMError("HTTP 429", 429) for i in range(1, 7)})
    created = []
    def factory(name):
        created.append(name)
        return executor
    args = ["--run-id", "r", "--configs", "full,basic", "--layers", "behavior"]
    assert run.main(args, tmp_path, factory) == 3
    assert created == ["basic"]  # Thứ tự cấu hình cố định, không phụ thuộc thứ tự CLI.
    saved = run.latest(tmp_path / "runs/eval/r/basic.behavior.jsonl")
    assert len(saved) == 6 and saved["q0"]["error"] is None
    assert "--run-id r" in capsys.readouterr().out


def test_scenarios_isolated_ordered_restore_and_continue_error(tmp_path):
    scenarios = [dict(id="s", turns=[dict(turn=2, user="hai", expected_profile={}),
                                     dict(turn=3, user="ba"),
                                     dict(turn=1, user="một", expected_behavior="hoi_lai")]),
                 dict(id="t", turns=[dict(turn=1, user="khác")])]
    dataset(tmp_path, scenarios=scenarios)
    _, plan = run.load_datasets(tmp_path, ["behavior"], None)
    assert [r["id"] for r in plan["behavior"]] == ["s.t1", "s.t2", "s.t3", "t.t1"]
    first = Executor({"s.t2": LLMError("HTTP 503", 503)})
    assert run.run_config(tmp_path, "full", plan, lambda _: first)[:3] == (0, 2, 0)
    assert [e[0]["id"] for e in first.calls] == ["s.t1", "s.t2", "t.t1"]
    assert first.calls[0][1] == first.calls[1][1] != first.calls[2][1]
    skipped = run.latest(tmp_path / "full.behavior.jsonl")["s.t3"]
    assert skipped["error"] == "Bỏ qua vì lượt s.t2 lỗi"
    assert skipped["http_status"] is None and "llm_attempts" not in skipped
    assert skipped["llm_calls"] == 0 and skipped["latency_ms"] == 0
    second = Executor()
    assert run.run_config(tmp_path, "full", plan, lambda _: second)[:3] == (0, 2, 0)
    assert [e[0]["id"] for e in second.calls] == ["s.t2", "s.t3"]
    assert len(second.restores) == 1 and second.restores[0][1]["id"] == "s.t1"
    assert second.restores[0][0] == second.calls[0][1] == second.calls[1][1]
    assert all(not row["error"] for row in run.latest(tmp_path / "full.behavior.jsonl").values())


def scenario_plan(*names, turns=3):
    return {"behavior": [dict(id=f"{name}.t{turn}", scenario_id=name, turn=turn, question="Hỏi AI")
                         for name in names for turn in range(1, turns + 1)]}


@pytest.mark.parametrize("failure", ["error", "missing"])
def test_resume_invalidates_old_success_after_retry(tmp_path, failure):
    plan = scenario_plan("s", turns=4)
    for entry in plan["behavior"]:
        if entry["turn"] == 3 and failure == "missing":
            continue
        run.append_jsonl(tmp_path / "full.behavior.jsonl", good_result(
            entry["id"], error="HTTP 503" if entry["turn"] == 3 and failure == "error" else None))
    executor = Executor()
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[:3] == (0, 2, 0)
    assert [e[0]["id"] for e in executor.calls] == ["s.t3", "s.t4"]
    assert len(executor.restores) == 1 and executor.restores[0][1]["id"] == "s.t2"
    # Một kịch bản đã thành công hoàn toàn không cần dựng hoặc restore executor.
    run.run_config(tmp_path, "full", plan, lambda _: pytest.fail("Đã giữ mọi lượt"))


def test_legacy_t2_error_retries_t3_success(tmp_path):
    plan = scenario_plan("s")
    for entry in plan["behavior"]:
        run.append_jsonl(tmp_path / "full.behavior.jsonl", good_result(
            entry["id"], error="HTTP 503" if entry["turn"] == 2 else None))
    executor = Executor()
    run.run_config(tmp_path, "full", plan, lambda _: executor)
    assert [e[0]["id"] for e in executor.calls] == ["s.t2", "s.t3"]
    assert [r[1]["id"] for r in executor.restores] == ["s.t1"]


def test_scenario_skips_preserve_429_streak_and_stop_at_five(tmp_path):
    plan = scenario_plan("a", "b", "c", "d", "e", "f")
    executor = Executor({f"{name}.t1": LLMError("HTTP 429", 429) for name in "abcdef"})
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[:3] == (3, 0, 5)
    assert [e[0]["id"] for e in executor.calls] == [f"{name}.t1" for name in "abcde"]
    records = run.read_jsonl(tmp_path / "full.behavior.jsonl")
    assert len(records) == 13  # Bốn kịch bản có hai lượt bỏ qua, dừng ngay lỗi thứ năm.
    skipped = [r for r in records if r["error"].startswith("Bỏ qua")]
    assert len(skipped) == 8 and all("llm_attempts" not in r for r in skipped)


def test_retry_first_turn_clean_on_reused_agent_executor(tmp_path, monkeypatch):
    root = cli_root(tmp_path)
    draft_obligations(monkeypatch)
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="fake", api_key="secret"))
    replies = FakeChat(analysis(profile_update={"role": "nha_cung_cap"}), LLMError("HTTP 503", 503),
                       analysis(), "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]", analysis(), "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]")
    units = run.read_jsonl(root / "data/processed/parents.jsonl")
    pipe = SimpleNamespace(context_many=lambda *a: units[:1], last_detail={}, last_timing={})
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph, executor.chat, executor.settings = build_agent(root,
        AgentConfig(enable_rewrite=False, enable_verifier=False), lambda *a: replies, pipeline=pipe)
    # Quan sát đầu vào phân tích ở cả hai lần chạy, kể cả khi prompt trùng cache.
    monkeypatch.setattr(executor.chat.chat, "lookup", lambda payload: None)
    restores = []
    monkeypatch.setattr(executor, "restore", lambda *args: restores.append(args))
    plan = scenario_plan("s", turns=2)
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[:3] == (0, 0, 0)
    old = run.latest(tmp_path / "full.behavior.jsonl")["s.t1"]
    assert old["profile"]["role"] == "nha_cung_cap" and old["session_state"]["messages"]
    assert run.run_config(tmp_path, "full", plan, lambda _: executor)[:3] == (0, 2, 0)
    assert not restores
    analyses = [payload for payload in replies.payloads if "response_format" in payload]
    data = json.loads(analyses[1]["messages"][1]["content"].split("\n", 1)[1])
    assert data["profile"]["role"] is None and data["recent_messages"] == []
    assert all(not r["error"] for r in run.latest(tmp_path / "full.behavior.jsonl").values())


def test_missing_answers_behavior_runs_dry_no_config_and_score_bytes(tmp_path, monkeypatch, capsys):
    dataset(tmp_path, questions=[dict(id="q", question="Hỏi AI", expected_behavior="tra_loi")])
    def forbidden(*args, **kwargs):
        pytest.fail("Không được đọc cấu hình hoặc gọi LLM")
    monkeypatch.setattr(run, "get_llm_settings", forbidden)
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", forbidden)
    args = ["--run-id", "r", "--configs", "full,basic"]
    assert run.main([*args, "--dry-run"], tmp_path, forbidden) == 0
    output = capsys.readouterr().out
    assert "Thiếu" in output and "còn lại=1" in output and "LLM tối đa còn lại=8" in output
    assert not (tmp_path / "runs").exists()
    executor = Executor()
    assert run.main(args, tmp_path, lambda _: executor) == 0
    assert len(executor.calls) == 2
    assert run.main([*args, "--score-only"], tmp_path, forbidden) == 0
    path = tmp_path / "runs/eval/r/summary.json"
    before = path.read_bytes()
    assert run.main([*args, "--score-only"], tmp_path, forbidden) == 0
    assert before == path.read_bytes()


def test_judgments_cached_same_model_configured_model_and_score_only_missing(tmp_path, monkeypatch):
    dataset(tmp_path, answer_rows=[answer_row()])
    executor = Executor()
    monkeypatch.delenv("RAG_JUDGE_MODEL", raising=False)
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers"]
    assert run.main([*args, "--score-only"], tmp_path, lambda _: pytest.fail("LLM")) == 4
    directory = tmp_path / "runs/eval/r"
    run.append_jsonl(directory / "full.answers.jsonl", good_result())
    assert run.main([*args, "--score-only"], tmp_path, lambda _: pytest.fail("LLM")) == 4
    assert json.loads((directory / "summary.json").read_text(encoding="utf-8"))["configs"]["full"]["answers"]["missing_judgments"] == 1
    assert run.main(args, tmp_path, lambda _: executor) == 0
    judgment = run.read_jsonl(directory / "full.judgments.jsonl")[0]
    assert judgment["judge_same_model"] is True
    assert run.main(args, tmp_path, lambda _: pytest.fail("Đã cache")) == 0
    assert len(executor.chat.payloads) == 1
    run.append_jsonl(directory / "full.answers.jsonl", good_result(answer="Đổi [E1]"))
    monkeypatch.setenv("RAG_JUDGE_MODEL", "other-judge")
    another = Executor()
    assert run.main(args, tmp_path, lambda _: another) == 0
    assert run.read_jsonl(directory / "full.judgments.jsonl")[-1]["judge_same_model"] is False
    assert another.chat.payloads[0]["model"] == "other-judge"


def test_basic_pins_prompt_no_graph_and_budget(tmp_path, monkeypatch):
    root = cli_root(tmp_path)
    seen = []
    pipeline = SimpleNamespace(context=lambda q, budget: seen.append((q, budget)) or
                               run.read_jsonl(root / "data/processed/parents.jsonl")[:1])
    chat = FakeChat("Nội dung [E1]")
    monkeypatch.setattr(run, "build_agent", lambda *a, **kw: pytest.fail("Không dựng graph"))
    executor = run.BasicExecutor(root, pipeline, chat, SimpleNamespace(model="fake"))
    result = executor.execute(dict(question="Hỏi AI"), "s")
    # T58: basic dùng cùng ngân sách ngữ cảnh với full.
    assert seen == [("Hỏi AI", DEFAULT_CONTEXT_BUDGET)] and result["llm_calls"] == 1
    assert chat.payloads[0]["messages"][0]["content"].startswith("Phiên bản: answer_v2\n")
    assert not any("verify" in p["messages"][0]["content"] for p in chat.payloads)


def test_runtime_shared_pipeline_no_obligations_and_restored_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("legal_rag.agent.answer.load_frame", lambda path, parents: [dict(label="khung", parents=parents[:1])])
    root = cli_root(tmp_path)
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="fake", api_key="secret", fallback_models=()))
    replies = []
    def client(*args):
        def complete(payload):
            replies.append(payload)
            return json.dumps(analysis(request_kinds=["nghia_vu"], profile_update={"role": "nha_cung_cap"})) if "response_format" in payload else "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]"
        return SimpleNamespace(complete=complete)
    units = run.read_jsonl(root / "data/processed/parents.jsonl")
    calls = []
    pipeline = SimpleNamespace(context_many=lambda qs, q, b: calls.append(q) or units[:1],
                               last_detail={}, last_timing={})
    config = AgentConfig(enable_obligations=False, enable_rewrite=False, enable_verifier=False)
    graph, chat, settings = build_agent(root, config, client, lambda *a: pytest.fail("Dùng pipeline sẵn"), pipeline)
    executor = run.AgentExecutor.__new__(run.AgentExecutor)
    executor.graph, executor.chat, executor.settings = graph, chat, settings
    result = executor.execute(dict(question="Một sản phẩm AI cần có những nghĩa vụ gì?"), "s")
    assert result["route"] == "broad_frame" and not calls
    graph2, chat2, settings2 = build_agent(root, config, client, lambda *a: pytest.fail("Dùng pipeline sẵn"), pipeline)
    executor.graph, executor.chat, executor.settings = graph2, chat2, settings2
    executor.restore("s", result)
    state = graph2.get_state({"configurable": {"thread_id": "s"}}).values
    assert state["profile"]["role"] == "nha_cung_cap" and len(state["messages"]) == 2
    result2 = executor.execute(dict(question="Hỏi tiếp AI"), "s")
    assert result2["profile"]["role"] == "nha_cung_cap" and len(calls) == 1


def test_shared_pipeline_constructed_once():
    calls = []
    shared = run.SharedPipeline(Path(__file__).resolve().parents[2],
                                lambda chunks, parents: calls.append(1) or SimpleNamespace(context=lambda q, b: []))
    assert calls == []
    shared.context("a", 3000)
    shared.context("b", 3000)
    assert calls == [1]


@pytest.mark.parametrize("marker", ["[E1.đ]", "[E1, E2]", "[e1]"])
def test_valid_citation_marker_forms(marker):
    row, result = answer_row(), good_result(answer="Nội dung " + marker)
    score = answers.score_answers([row], [result], {answers.judgment_key(row, result): good_judge()})
    assert score["correct_rate"] == 1
    assert "E1" in answers.cited_codes(result["answer"])


def test_basic_broad_prompt_pinned_v3(tmp_path, monkeypatch):
    root = cli_root(tmp_path)
    calls = []
    monkeypatch.setattr(run, "load_frame", lambda path, parents: calls.append(path) or
                        [dict(label="khung", parents=parents[:1])])
    pipeline = SimpleNamespace(context=lambda *a: pytest.fail("Khung không truy xuất"))
    chat = FakeChat("Nội dung [E1]")
    executor = run.BasicExecutor(root, pipeline, chat, SimpleNamespace(model="fake"))
    result = executor.execute(dict(question="Một sản phẩm AI cần có những nghĩa vụ gì?"), "s")
    assert result["route"] == "broad_frame" and calls
    assert chat.payloads[0]["messages"][0]["content"].startswith("Phiên bản: answer_v3\n")


def test_429_streak_reset_and_terminal_status():
    assert run.is_429(dict(error="HTTP 500", llm_attempts=[{"status": 429}, {"status": 500}])) is False
    assert run.is_429(dict(error="HTTP 429", llm_attempts=[])) is True
    assert run.is_429(dict(error=None, llm_attempts=[{"status": 429}])) is False


def test_judge_429_stop_retry_then_cached(tmp_path, monkeypatch):
    rows = [dict(answer_row(str(i)), reference_answer=f"Ý {i}") for i in range(6)]
    for row in rows:
        run.append_jsonl(tmp_path / "full.answers.jsonl", good_result(row["id"]))
    executor = Executor()
    executor.chat = FakeChat(*[LLMError("HTTP 429", 429) for _ in range(5)])
    assert run.collect_judgments(tmp_path, "full", rows, lambda _: executor)[0] == 3
    assert len(run.read_jsonl(tmp_path / "full.judgments.jsonl")) == 5
    retry = Executor()
    retry.chat = FakeChat(*[good_judge() for _ in rows])
    assert run.collect_judgments(tmp_path, "full", rows, lambda _: retry)[0] == 0
    assert len(retry.chat.payloads) == 6
    assert len(run.latest(tmp_path / "full.judgments.jsonl", "key")) == 6
    assert run.collect_judgments(tmp_path, "full", rows, lambda _: pytest.fail("Cache"))[0] == 0


def test_dry_run_latest_error_and_limit_counts(tmp_path, capsys):
    dataset(tmp_path, questions=[dict(id=f"q{i}", question="AI") for i in range(3)])
    directory = tmp_path / "runs/eval/r"
    run.append_jsonl(directory / "full.behavior.jsonl", good_result("q0"))
    run.append_jsonl(directory / "full.behavior.jsonl", good_result("q1"))
    run.append_jsonl(directory / "full.behavior.jsonl", good_result("q1", error="lỗi mới"))
    assert run.main(["--run-id", "r", "--configs", "full", "--layers", "behavior", "--limit", "2", "--dry-run"],
                    tmp_path, lambda _: pytest.fail("Không dựng agent")) == 0
    output = capsys.readouterr().out
    assert "đã xong=1; còn lại=1" in output
    assert "tối đa còn lại=8" in output and "phổ biến=3" in output


def test_run_cli_real_graph_fake_llm_and_pipeline(tmp_path, monkeypatch):
    root = cli_root(tmp_path)
    draft_obligations(monkeypatch)
    dataset(root, scenarios=[dict(id="s", turns=[
        dict(turn=1, user="Tôi cung cấp AI", expected_behavior="hoi_lai", expected_profile={"role": "nha_cung_cap"}),
        dict(turn=2, user="Hỏi tiếp AI", expected_behavior="tra_loi", expected_profile={"role": "nha_cung_cap"})])])
    monkeypatch.setattr("legal_rag.agent.runtime.get_llm_settings", lambda: SimpleNamespace(
        model="fake", base_url="fake", api_key="secret"))
    replies = FakeChat(analysis(profile_update={"role": "nha_cung_cap"}), "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]",
                       analysis(), "## Trả lời ngắn\nNội dung [E1]\n\n## Căn cứ\nNội dung [E1]")
    units = run.read_jsonl(root / "data/processed/parents.jsonl")
    pipe = SimpleNamespace(context_many=lambda *a: units[:1], last_detail={}, last_timing={})
    def factory(name):
        value = run.AgentExecutor.__new__(run.AgentExecutor)
        value.graph, value.chat, value.settings = build_agent(root,
            AgentConfig(enable_rewrite=False, enable_verifier=False), lambda *a: replies, pipeline=pipe)
        return value
    args = ["--run-id", "r", "--configs", "full", "--layers", "behavior"]
    assert run.main([*args, "--limit", "1"], root, factory) == 0
    assert run.main(args, root, factory) == 0
    records = run.read_jsonl(root / "runs/eval/r/full.behavior.jsonl")
    assert len(records) == 2 and len(replies.payloads) == 4
    assert records[1]["profile"]["role"] == "nha_cung_cap"
    data = json.loads(replies.payloads[2]["messages"][1]["content"].split("\n", 1)[1])
    assert data["profile"]["role"] == "nha_cung_cap"
    assert len(data["recent_messages"]) == 2


def test_score_only_with_judgments_same_bytes_no_llm(tmp_path):
    rows = [answer_row(str(i)) for i in range(3)]
    dataset(tmp_path, answer_rows=rows)
    directory = tmp_path / "runs/eval/r"
    for name in ("full", "basic"):
        for row in rows[:1 if name == "basic" else 2]:
            result = good_result(row["id"])
            run.append_jsonl(directory / f"{name}.answers.jsonl", result)
            run.append_jsonl(directory / f"{name}.judgments.jsonl",
                             dict(good_judge(), key=answers.judgment_key(row, result)))
    args = ["--run-id", "r", "--layers", "answers", "--score-only"]
    def forbidden(*args):
        pytest.fail("Không được gọi LLM")
    assert run.main(args, tmp_path, forbidden) == 4
    before = (directory / "summary.json").read_bytes()
    assert run.main(args, tmp_path, forbidden) == 4
    assert before == (directory / "summary.json").read_bytes()
    summary = json.loads(before)
    assert summary["configs"]["full"]["answers"]["n"] == summary["configs"]["basic"]["answers"]["n"] == 3


def test_limit_does_not_mix_ids_between_layers(tmp_path):
    dataset(tmp_path, answer_rows=[answer_row("q2"), answer_row("q1")],
            questions=[dict(id="q1", question="AI"), dict(id="q2", question="AI")])
    data, plan = run.load_datasets(tmp_path, ["answers", "behavior"], 1)
    assert [r["id"] for r in data["answers"]] == ["q2"]
    assert [r["id"] for r in data["questions"]] == ["q1"]
    assert len(plan["answers"]) == len(plan["behavior"]) == 1
