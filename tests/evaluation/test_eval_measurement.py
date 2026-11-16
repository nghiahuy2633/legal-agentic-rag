"""T32: phép đo, tiếp tục chấm và HTTP chỉ dùng dữ liệu/client giả."""

import importlib.util
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from legal_rag.evaluation import answers, run
from legal_rag.llm import HTTPChatClient, LLMError, QuotaExhaustedError
from test_agent_graph import FakeChat
from test_basic_rag import cli_root
from test_eval_runner import answer_row, dataset, Executor, good_judge, good_result, write_rows
from test_llm import response


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RAG_JUDGE_MODEL", "RAG_LLM_MODEL", "RAG_LLM_FALLBACK_MODELS", "RAG_LLM_RATE_WAIT_MAX"):
        monkeypatch.setenv(name, "")
    monkeypatch.delenv("RAG_LLM_RATE_WAIT_MAX")


def score(row=None, result=None, judge=None):
    row, result = row or answer_row(), result or good_result()
    judge = good_judge() if judge is None else judge
    return answers.score_answers([row], [result], {answers.judgment_key(row, result): judge})


def test_coverage_zero_six_and_diagnostics():
    row = dict(answer_row(), required_points=[str(i) for i in range(6)])
    judge = dict(good_judge(), points=[dict(point=p, covered=False) for p in row["required_points"]])
    result = good_result(verification={"final_valid": False})
    scores = score(row, result, judge)
    assert scores["samples"]["a"]["correct"] == 1
    assert scores["samples"]["a"]["correct_covered"] == 0
    assert scores["inconsistent_ids"] == scores["final_invalid_ids"] == ["a"]
    assert scores["meaning_ok_rate"] == scores["citation_rule_rate"] == scores["citation_relevant_rate"] == 1
    assert scores["confidence_intervals"]["correct_covered_rate"] == [0, 0]
    assert answers.COVERAGE_THRESHOLD == .5


def test_no_points_and_threshold_boundary():
    assert score(dict(answer_row(), required_points=[]), judge=dict(good_judge(), points=[]))["correct_covered_rate"] == 1
    row = dict(answer_row(), required_points=["a", "b"])
    judge = dict(good_judge(), points=[dict(point="a", covered=True), dict(point="b", covered=False)])
    assert score(row, judge=judge)["correct_covered_rate"] == 1


def test_rule_and_semantic_citation_are_separate():
    scores = score(result=good_result(check={"valid": False}))
    assert scores["correct_rate"] == scores["citation_rule_rate"] == 0
    assert scores["citation_relevant_rate"] == 1
    scores = score(judge=dict(good_judge(), citations_relevant=False,
                             citation_issues=[dict(code="E1", reason="Sai khoản")]))
    assert scores["correct_rate"] == scores["citation_relevant_rate"] == 0
    assert scores["citation_rule_rate"] == 1
    assert scores["citation_issue_ids"] == ["a"]


@pytest.mark.parametrize("issues", [None, {}, ["E1"], [{"code": "E1"}],
    [dict(code=1, reason="x")], [dict(code="E1", reason="")], [dict(code="E1", reason="x", extra=True)]])
def test_v2_requires_issue_schema(issues):
    chat = FakeChat(dict(good_judge(), citation_issues=issues))
    verdict = answers.judge_answer(answer_row(), good_result(), chat, "judge")
    assert verdict["judge_error"] and verdict["judge_version"] == "judge_v2"


def test_missing_issues_v2_invalid_legacy_valid():
    old = good_judge()
    old.pop("citation_issues")
    assert answers.valid_judgment(old, answer_row())
    verdict = answers.judge_answer(answer_row(), good_result(), FakeChat(old), "judge")
    assert verdict["judge_error"]


def test_paired_all_metrics():
    a = dict(samples={"a": dict(correct=1, correct_covered=0, required_points=0)})
    b = dict(samples={"a": dict(correct=0, correct_covered=1, required_points=.5)})
    compared = answers.compare(a, b)
    assert compared["difference"] == 1
    assert compared["metrics"]["correct_covered"]["difference"] == -1
    assert compared["metrics"]["required_points"]["confidence_interval"] == [-.5, -.5]


def test_legacy_score_only_counts_and_new_key_priority(tmp_path, monkeypatch):
    dataset(tmp_path, answer_rows=[answer_row()])
    directory = tmp_path / "runs/eval/r"
    result = good_result()
    old = good_judge()
    old.pop("citation_issues")
    key = answers.judgment_key(answer_row(), result, version="judge_v1")
    run.append_jsonl(directory / "full.answers.jsonl", result)
    run.append_jsonl(directory / "full.judgments.jsonl", dict(old, key=key, judge_model="old"))
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers", "--score-only"]
    forbidden = lambda _: pytest.fail("Không dựng executor")
    assert run.main(args, tmp_path, forbidden) == 0
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    scores = summary["configs"]["full"]["answers"]
    assert scores["correct_rate"] == scores["citation_valid_rate"] == scores["required_points_rate"] == 1
    assert scores["judge_versions"] == {"judge_v1": 1}
    assert scores["judge_models"] == {"old": 1}
    # Phán quyết v2 được ưu tiên nếu cùng câu trả lời và tham chiếu.
    monkeypatch.setenv("RAG_JUDGE_MODEL", "new")
    judgment = answers.judge_answer(answer_row(), result,
        FakeChat(dict(good_judge(), meaning_ok=False)), "new")
    run.append_jsonl(directory / "full.judgments.jsonl", judgment)
    assert run.main(args, tmp_path, forbidden) == 0
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["configs"]["full"]["answers"]["correct_rate"] == 0


def test_model_change_same_answer_rejudges(tmp_path, monkeypatch):
    dataset(tmp_path, answer_rows=[answer_row()])
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers"]
    monkeypatch.setenv("RAG_JUDGE_MODEL", "j1")
    first = Executor()
    assert run.main(args, tmp_path, lambda _: first) == 0
    monkeypatch.setenv("RAG_JUDGE_MODEL", "j2")
    second = Executor()
    assert run.main(args, tmp_path, lambda _: second) == 0
    assert not second.calls and second.chat.payloads[0]["model"] == "j2"
    path = tmp_path / "runs/eval/r/full.judgments.jsonl"
    judgments = run.read_jsonl(path)
    assert len(judgments) == 2 and judgments[0]["key"] != judgments[1]["key"]
    assert {j["judge_version"] for j in judgments} == {"judge_v2"}
    assert {j["judge_model"] for j in judgments} == {"j1", "j2"}


def test_judge_error_exit_retry_and_score_only(tmp_path, capsys):
    dataset(tmp_path, answer_rows=[answer_row()])
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers"]
    bad = Executor()
    bad.chat = FakeChat(LLMError("HTTP 429", 429))
    assert run.main(args, tmp_path, lambda _: bad) == 4
    assert "lỗi chấm 1 câu ['a']" in capsys.readouterr().out
    path = tmp_path / "runs/eval/r/summary.json"
    assert not json.loads(path.read_text(encoding="utf-8"))["complete"]
    assert run.main([*args, "--score-only"], tmp_path, lambda _: pytest.fail("LLM")) == 4
    fixed = Executor()
    assert run.main(args, tmp_path, lambda _: fixed) == 0
    assert not fixed.calls
    assert json.loads(path.read_text(encoding="utf-8"))["complete"]


def test_summary_all_files_order_independent_and_limit(tmp_path):
    dataset(tmp_path, answer_rows=[answer_row()], questions=[dict(id="q", question="AI")])
    base = ["--run-id", "r", "--configs", "full"]
    assert run.main([*base, "--layers", "behavior"], tmp_path, lambda _: Executor()) == 0
    assert run.main([*base, "--layers", "answers"], tmp_path, lambda _: Executor()) == 0
    path = tmp_path / "runs/eval/r/summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert {"answers", "behavior"} <= summary["configs"]["full"].keys()
    # basic có câu trả lời, chưa có lớp hành vi: không tạo số 0 giả.
    assert run.main(["--run-id", "r", "--configs", "basic", "--layers", "answers"], tmp_path, lambda _: Executor()) == 0
    before = path.read_bytes()
    for configs, layer in (("basic,full", "answers"), ("full,basic", "answers"), ("full", "behavior")):
        assert run.main(["--run-id", "r", "--configs", configs, "--layers", layer, "--score-only"], tmp_path) == 0
        assert path.read_bytes() == before
    assert "behavior" not in json.loads(before)["configs"]["basic"]
    assert run.main([*base, "--layers", "answers", "--score-only", "--limit", "2"], tmp_path) == 0
    assert path.read_bytes() == before
    assert path.with_name("summary.limit-2.json").exists()


@pytest.mark.parametrize("judge,fallback", [("", ""), ("gen", ""), ("judge", "backup")])
def test_official_preflight_no_executor(tmp_path, monkeypatch, judge, fallback):
    monkeypatch.setenv("RAG_LLM_MODEL", "gen")
    monkeypatch.setenv("RAG_JUDGE_MODEL", judge)
    monkeypatch.setenv("RAG_LLM_FALLBACK_MODELS", fallback)
    monkeypatch.setattr(run, "SharedPipeline", lambda *_: pytest.fail("Không nạp model"))
    assert run.main(["--run-id", "r", "--official"], tmp_path,
                    lambda _: pytest.fail("Không dựng executor")) == 2
    assert not (tmp_path / "runs").exists()


def test_official_model_mixing_and_draft_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAG_LLM_MODEL", "gen")
    monkeypatch.setenv("RAG_JUDGE_MODEL", "judge")
    rows = [dict(answer_row(str(i)), review_status="ai_draft") for i in range(2)]
    dataset(tmp_path, answer_rows=rows)
    executor = Executor({"0": {"model": "gen"}, "1": {"model": "backup"}})
    executor.chat = FakeChat(good_judge(), good_judge())
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers", "--official"]
    assert run.main(args, tmp_path, lambda _: executor) == 4
    assert "Trộn nhiều model sinh" in capsys.readouterr().out
    data = json.loads((tmp_path / "runs/eval/r/summary.json").read_text(encoding="utf-8"))
    value = data["comparability"]["full"]
    assert value["generation_models"] == ["backup", "gen"] and value["judge_models"] == ["judge"]
    assert value["judge_same_model"] == 0 and "Nhãn còn ai_draft." in value["warnings"]
    # Chỉ cảnh báo nháp không chặn official.
    executor = Executor()
    executor.chat = FakeChat(good_judge(), good_judge())
    assert run.main([args[0], "draft", *args[2:]], tmp_path, lambda _: executor) == 0


def test_between_config_models_and_same_model_warnings(tmp_path):
    dataset(tmp_path, answer_rows=[answer_row()])
    args = ["--run-id", "r", "--layers", "answers"]
    assert run.main(args, tmp_path, lambda name: Executor({"a": {"model": name}})) == 0
    data = json.loads((tmp_path / "runs/eval/r/summary.json").read_text(encoding="utf-8"))
    for value in data["comparability"].values():
        assert value["judge_same_model"] == 1
        assert "Model chấm trùng model sinh." in value["warnings"]
        assert "Model sinh khác giữa các cấu hình." in value["warnings"]


def test_generate_only_then_only_missing_judgments(tmp_path):
    rows = [dict(answer_row(str(i)), reference_answer=str(i)) for i in range(2)]
    dataset(tmp_path, answer_rows=rows)
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers"]
    generation = Executor()
    generation.chat = FakeChat()  # Gọi chấm sẽ lỗi ngay.
    assert run.main([*args, "--generate-only"], tmp_path, lambda _: generation) == 0
    directory = tmp_path / "runs/eval/r"
    assert len(generation.calls) == 2 and not generation.chat.payloads
    assert not (directory / "full.judgments.jsonl").exists()
    assert json.loads((directory / "summary.json").read_text(encoding="utf-8"))["complete"] is False
    # Đã có một phán quyết, lần tiếp theo chỉ chấm câu còn thiếu.
    result = run.latest(directory / "full.answers.jsonl")["0"]
    run.append_jsonl(directory / "full.judgments.jsonl",
                     answers.judge_answer(rows[0], result, FakeChat(good_judge()), "fake"))
    judging = Executor()
    assert run.main(args, tmp_path, lambda _: judging) == 0
    assert not judging.calls and len(judging.chat.payloads) == 1
    assert json.loads((directory / "summary.json").read_text(encoding="utf-8"))["complete"]


def test_generate_only_generation_error(tmp_path):
    dataset(tmp_path, answer_rows=[answer_row()])
    assert run.main(["--run-id", "r", "--configs", "full", "--layers", "answers", "--generate-only"],
                    tmp_path, lambda _: Executor({"a": LLMError("HTTP 500", 500)})) == 4


@pytest.mark.parametrize("message,maximum,waits_expected", [
    ("retry in 22s", 65, [23]), ("retry in 300s", 65, []),
    ("per day retry in 22s", 65, []), ("retry in 22s", 0, [])])
def test_rate_wait_not_attempt(message, maximum, waits_expected):
    sent, waits = [], []
    def opener(request, **kwargs):
        sent.append(1)
        if len(sent) == 1:
            raise HTTPError(request.full_url, 429, "rate", {}, BytesIO(
                json.dumps({"error": {"message": message}}).encode()))
        return response("ok")
    client = HTTPChatClient("https://fake.invalid", "secret", opener=opener,
                            sleep=waits.append, max_attempts=1, rate_wait_max=maximum)
    if waits_expected:
        assert client.complete({}) == "ok" and client.request_count == 2
    else:
        with pytest.raises(LLMError):
            client.complete({})
        assert client.request_count == 1
    assert waits == waits_expected


def test_five_waits_per_request_and_env(monkeypatch):
    monkeypatch.setenv("RAG_LLM_RATE_WAIT_MAX", "65")
    waits = []
    def opener(request, **kwargs):
        raise HTTPError(request.full_url, 429, "rate", {}, BytesIO(
            b'{"error":{"message":"retry in 22s"}}'))
    client = HTTPChatClient("https://fake.invalid", "secret", opener=opener, sleep=waits.append, max_attempts=1)
    for _ in range(2):
        with pytest.raises(LLMError, match="HTTP 429") as caught:
            client.complete({})
        assert not isinstance(caught.value, QuotaExhaustedError)
    assert waits == [23] * 10 and client.request_count == 12


def test_wait_preserves_ordinary_retry_budget():
    waits, sent = [], []
    def opener(request, **kwargs):
        sent.append(1)
        status = 500 if len(sent) == 1 else 429
        if len(sent) <= 2:
            raise HTTPError(request.full_url, status, "rate", {}, BytesIO(
                b'{"error":{"message":"retry in 22s"}}'))
        return response("ok")
    client = HTTPChatClient("https://fake.invalid", "secret", opener=opener, sleep=waits.append,
                            max_attempts=2, rate_wait_max=65)
    assert client.complete({}) == "ok"
    assert 1 <= waits[0] <= 2 and waits[1] == 23


def test_eval_clients_receive_wait_max(tmp_path, monkeypatch):
    seen = []
    def client(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(complete=lambda _: "ok")
    monkeypatch.setattr(run, "HTTPChatClient", client)
    root = cli_root(tmp_path)
    settings = SimpleNamespace(model="fake", base_url="fake", api_key="secret")
    run.BasicExecutor(root, None, settings=settings)
    def build(*args, **kwargs):
        kwargs["client_factory"]("url", "key")
        return None, None, settings
    monkeypatch.setattr(run, "build_agent", build)
    run.AgentExecutor(root, "full", None)
    assert [value["rate_wait_max"] for value in seen] == [65, 65]


def check_module():
    path = Path(__file__).resolve().parents[2] / "scripts/check_judge.py"
    spec = importlib.util.spec_from_file_location("check_judge_t32", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_judge_success_failure_missing_dry(tmp_path, monkeypatch, capsys):
    module = check_module()
    row = dict(id="trap", question="AI", answer="Đáp [E1]", reference_answer="Đáp",
               required_points=["Nội dung"], evidence=[dict(id="E1", text="Đáp")],
               expect=dict(meaning_ok=True, citations_relevant=True, citation_issue_codes=[]))
    path = tmp_path / "eval/judge_traps.jsonl"
    write_rows(path, [row])
    monkeypatch.setenv("RAG_JUDGE_MODEL", "judge")
    assert module.main([], tmp_path, FakeChat(good_judge())) == 0
    assert "meaning_ok: 1/1" in capsys.readouterr().out
    assert module.main([], tmp_path, FakeChat(dict(good_judge(), meaning_ok=False))) == 1
    monkeypatch.setenv("RAG_JUDGE_MODEL", "")
    assert module.main([], tmp_path, FakeChat()) == 2
    assert module.main(["--dry-run"], tmp_path, FakeChat()) == 0
    assert module.main(["--file", str(tmp_path / "missing.jsonl")], tmp_path) == 2
    assert not (tmp_path / "missing.jsonl").exists()


@pytest.mark.parametrize("field,value", [("evidence", "x"), ("expect", {}),
    ("expect", {"meaning_ok": 1}), ("expect", {"citation_issue_codes": [1]}),
    ("required_points", [1]), ("answer", None)])
def test_check_judge_bad_schema(tmp_path, field, value):
    row = dict(id="trap", question="AI", answer="Đáp", reference_answer="Đáp",
               required_points=[], evidence=[], expect=dict(meaning_ok=True))
    row[field] = value
    path = tmp_path / "traps.jsonl"
    write_rows(path, [row])
    assert check_module().main(["--file", str(path), "--dry-run"], tmp_path, FakeChat()) == 2


def test_score_only_ignores_judge_env_and_old_judgment_does_not_block(tmp_path, monkeypatch):
    dataset(tmp_path, answer_rows=[answer_row()])
    args = ["--run-id", "r", "--configs", "full", "--layers", "answers"]
    monkeypatch.setenv("RAG_JUDGE_MODEL", "j1")
    assert run.main(args, tmp_path, lambda _: Executor()) == 0
    directory = tmp_path / "runs/eval/r"
    before = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    forbidden = lambda _: pytest.fail("LLM")
    # Chấm lại từ kết quả đã lưu phải cho cùng số, dù biến môi trường đã đổi hoặc không còn.
    for value in ("", "khac"):
        monkeypatch.setenv("RAG_JUDGE_MODEL", value)
        assert run.main([*args, "--score-only"], tmp_path, forbidden) == 0
        after = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        assert after["configs"] == before["configs"]
    # Phán quyết judge_v1 chỉ để đọc lại số cũ, không chặn chấm bằng prompt hiện tại.
    result = run.read_jsonl(directory / "full.answers.jsonl")[-1]
    path = directory / "full.judgments.jsonl"
    path.write_text("", encoding="utf-8")
    old = dict(good_judge(), id="a", judge_model="j1",
               key=answers.judgment_key(answer_row(), result, version="judge_v1"))
    run.append_jsonl(path, old)
    monkeypatch.setenv("RAG_JUDGE_MODEL", "j2")
    executor = Executor()
    assert run.main(args, tmp_path, lambda _: executor) == 0
    assert executor.chat.payloads and executor.chat.payloads[0]["model"] == "j2"
