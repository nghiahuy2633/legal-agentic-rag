"""T38: số tay, đối chứng và CLI; không gọi mạng hoặc nạp model."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from legal_rag.assessment import baselines
from legal_rag.evaluation import assessments as ev
from legal_rag.llm import CachedChat, LLMError, QuotaExhaustedError

ROOT = Path(__file__).resolve().parents[2]
C = "134-2025-QH15_dieu-11_khoan-1"
P = C + "_diem-a"


def obligation(cid=C, status="da", key="one", applicability="ap_dung", kind="nghia_vu"):
    return dict(key=key, text="Thông báo", chunk_ids=[cid], applicability=applicability,
                kind=kind, status=status, criteria=[])


def gold(gid="G1", units=None, status="da", optional=False):
    return dict(gid=gid, units=units or [C], status=status, optional=optional)


def product(id="A1", **changes):
    return dict(dict(id=id, message="Chatbot", facts={}, message_facts={},
        description="Chatbot", statement="Đã thông báo", gold=[gold()],
        gold_warnings=[], review_status="ai_draft"), **changes)


def output(*obligations, **changes):
    return dict(dict(obligations=list(obligations), warnings=[], llm_calls=1), **changes)


class Chat:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def complete(self, payload):
        self.requests.append(deepcopy(payload))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer, ensure_ascii=False) if not isinstance(answer, str) else answer


class Pipeline:
    chunks = [{"chunk_id": P, "body": "Thông báo cho người dùng"}]

    def __init__(self):
        self.requests = []

    def context(self, query, budget):
        self.requests.append((query, budget))
        return [{"parent_id": C, "text": "Thông báo cho người dùng", "chunk_ids": [P]}]

    def context_many(self, queries, rerank_query, budget):
        self.requests.append((queries, rerank_query, budget))
        return [{"parent_id": C, "text": "Thông báo cho người dùng", "chunk_ids": [P]}]


@pytest.mark.parametrize("cid,expected", [
    (C, {C}), (P, {C, P}), (P + "_phan-2", {C, P}),
    (C + "_cuoi", {C}), (C + "_phan-3", {C}),
    ("134-2025-QH15_dieu-1_mo-dau_phan-2", {"134-2025-QH15_dieu-1"}),
    (C + "_diem-đ", {C, C + "_diem-đ"}),
])
def test_citation_units(cid, expected):
    assert ev.citation_units(cid) == expected


def test_score_hand():
    row = product(gold=[gold(), gold("G2", [P], ["chua", "chua_ro"]),
                        gold("optional", ["optional"], optional=True), gold("missed", ["absent"])],
                  gold_warnings=[C, "missing"])
    result = ev.score_product(row, output(
        obligation(P), obligation(P, "chua", key="two", applicability="ap_dung_neu"),
        obligation("optional"), obligation("extra"),
        obligation("absent", kind="thong_tin"), warnings=[P, "false"]))
    assert result["precision"] == .5
    assert result["recall"] == pytest.approx(2 / 3)
    assert result["recall_definite"] == pytest.approx(2 / 3)
    assert result["status_acc"] == .5
    assert result["false_da"] == 0
    assert result["warnings"] == dict(tp=1, fp=1, fn=1)
    assert [o["key"] for o in result["extra"]] == ["one"]
    assert result["missed"] == ["missed"]


def test_optional_only_and_empty():
    assert ev.score_product(product(gold=[gold(optional=True)]), output(obligation()))["precision"] is None
    result = ev.score_product(product(), output())
    assert result["precision"] is None and result["status_acc"] is None
    assert result["recall"] == 0
    assert ev.score_product(product(gold=[gold(status="chua")]), output(obligation()))["false_da"] == 1


def test_conditional_recall_worst_status():
    result = ev.score_product(product(), output(obligation(applicability="ap_dung_neu")))
    assert result["recall"] == 1 and result["recall_definite"] == 0
    result = ev.score_product(product(), output(obligation(status="chua_ro"), obligation(status="chua")))
    assert result["matched_status"] == {"G1": "chua"}


def record(config, id, score, repeat=0):
    return dict(config=config, id=id, repeat=repeat, score=score, output=output(obligation()), total_ms=10)


def test_summary_compare_bootstrap_hand():
    good = ev.score_product(product(), output(obligation()))
    bad = ev.score_product(product(), output(obligation("other")))
    rows = [record("full", "a", good), record("full", "b", bad),
            record("b0", "a", bad), record("b0", "b", bad), record("b1", "a", good)]
    summary = ev.summarize(rows)["full"]
    assert summary["precision"] == .5 and summary["recall"] == .5
    assert summary["status_acc"] == 1 and summary["status_acc_micro"] == 1
    assert summary["llm_calls_total"] == 2 and summary["llm_calls_median"] == 1
    assert summary["total_ms_median"] == 10
    assert summary["ci95"]["precision"] == [0, 1]
    assert ev.summarize(rows) == ev.summarize(list(reversed(rows)))
    compared = ev.compare(rows)
    assert compared["full-b0"]["recall"] == dict(difference=.5, ci95=[0, 1], n=2)
    assert compared["full-b1"]["precision"]["difference"] == 0
    assert compared["b1-b0"]["precision"]["difference"] == 1
    assert ev.compare(rows) == ev.compare(rows)


def test_facts_and_consistency():
    row = product(message_facts={"roles": ["ben_trien_khai", "nha_cung_cap"], "generates_content": False})
    facts = dict(roles=["nha_cung_cap", "ben_trien_khai"], generates_content=False, uses_personal_data=True)
    scored = ev.score_facts(row, facts)
    assert scored["fact_accuracy"] == 1 and scored["fact_hallucinated"] == 1
    a = record("full", "a", ev.score_product(product(), output(obligation())))
    b = deepcopy(a)
    b["output"]["obligations"].append(obligation("other", key="two"))
    assert ev.consistency([a, b]) == dict(consistency_obligations=.5, consistency_status=1)
    b["score"]["matched_status"]["G1"] = None
    assert ev.consistency([a, b])["consistency_status"] == 0


def test_b0_cached_evidence(tmp_path):
    chat = Chat({"obligations": [{"text": "Thông báo", "evidence_ids": ["E1"], "status": "da"}], "prohibited": ["E1"]})
    cached = CachedChat(chat, tmp_path / "cache")
    pipeline = Pipeline()
    first = baselines.run_baseline("b0", {}, "Chatbot", "Đã thông báo", cached, "fake", lambda: pipeline)
    assert first["obligations"][0]["chunk_ids"] == [P]
    assert first["warnings"] == [P] and first["llm_calls"] == 1
    assert pipeline.requests[0][1] == 3000
    assert first == baselines.run_baseline("b0", {}, "Chatbot", "Đã thông báo", cached, "fake", lambda: pipeline)
    assert len(chat.requests) == 1 and cached.cache_hits == 1
    assert chat.requests[0]["temperature"] == 0


def test_b1_real_assess_status(tmp_path, monkeypatch):
    original = baselines.assess_status
    invoked = []

    def spy(*args, **kwargs):
        invoked.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(baselines, "assess_status", spy)
    chat = Chat({"queries": ["một", "hai", "ba"]},
        {"obligations": [{"text": "Thông báo", "evidence_ids": ["E1"], "criteria": ["Thông báo"]}], "prohibited": []},
        {"results": [{"obligation": "b1-1", "criterion": "c1", "status": "da", "quote": "Đã thông báo"}]},
        {"results": [{"id": "b1-1/c1", "verdict": "ho_tro", "reason": "Đúng tiêu chí"}]})
    pipeline = Pipeline()
    result = baselines.run_baseline("b1", {}, "Chatbot", "Đã thông báo", CachedChat(chat, tmp_path), "fake", lambda: pipeline)
    assert len(invoked) == 1 and result["llm_calls"] == 4
    assert result["obligations"][0]["status"] == "da"
    assert result["obligations"][0]["criteria"][0]["quote"] == "Đã thông báo"
    assert pipeline.requests[0][2] == 4500
    assert all(r["model"] == "fake" and r["temperature"] == 0 for r in chat.requests)


@pytest.mark.parametrize("answer", [
    {"obligations": [{"text": "Sai", "evidence_ids": ["E99"], "status": "da"}]},
    {"obligations": [{"text": "Sai", "evidence_ids": [], "status": "da"}]},
])
def test_baseline_bad_entry_dropped(answer):
    result = baselines.run_baseline("b0", {}, "", "", Chat(answer), "fake", Pipeline)
    assert result["obligations"] == [] and result["dropped"] == 1


def test_baseline_not_json_raises():
    with pytest.raises(ValueError):
        baselines.run_baseline("b0", {}, "", "", Chat("not JSON"), "fake", Pipeline)


@pytest.fixture
def cli_root(tmp_path):
    (tmp_path / "eval").mkdir()
    (tmp_path / "data/processed").mkdir(parents=True)
    table = tmp_path / "src/legal_rag/knowledge/obligations.yaml"
    table.parent.mkdir(parents=True)
    table.write_bytes((ROOT / "src/legal_rag/knowledge/obligations.yaml").read_bytes())
    (tmp_path / "eval/assessments.jsonl").write_text(
        "\n".join(json.dumps(product(id)) for id in ("A1", "A2")), encoding="utf-8")
    (tmp_path / "data/processed/chunks.jsonl").write_text(json.dumps(Pipeline.chunks[0]), encoding="utf-8")
    return tmp_path


def run_cli(root, *args, chat=None, **kwargs):
    return ev.main(["--run-id", "test", "--configs", "b0", *args], root=root,
        settings_factory=lambda: SimpleNamespace(offline=False, model="fake", base_url="fake", api_key="fake"),
        client_factory=lambda *a: chat, pipeline_factory=Pipeline, **kwargs)


def baseline_answer():
    return {"obligations": [{"text": "Thông báo", "evidence_ids": ["E1"], "status": "da"}], "prohibited": []}


def test_cli_quota_resume_score_only(cli_root):
    # Hai sản phẩm có payload giống nhau: cache dùng lại sau lần tiếp tục.
    chat = Chat(QuotaExhaustedError())
    assert run_cli(cli_root, chat=chat) == 3
    summary = cli_root / "runs/eval/test/assessments/summary.json"
    assert not json.loads(summary.read_text(encoding="utf-8"))["complete"]
    resumed = Chat(baseline_answer())
    assert run_cli(cli_root, chat=resumed) == 0
    before = json.loads(summary.read_text(encoding="utf-8"))
    assert len(resumed.requests) == 1
    assert run_cli(cli_root, "--score-only") == 0
    assert json.loads(summary.read_text(encoding="utf-8")) == before
    assert run_cli(cli_root, chat=Chat()) == 0
    markdown = summary.with_suffix(".md").read_text(encoding="utf-8")
    assert "Đáp án `ai_draft`, chưa được người dùng soát" in markdown
    assert "table_sha256" in markdown and "fake" in markdown and "ai_reviewed" in markdown


def test_cli_missing_and_bad_config(cli_root):
    assert run_cli(cli_root, "--score-only") == 4
    assert run_cli(cli_root, "--repeat", "0") == 2
    assert run_cli(cli_root, "--ids", "absent") == 2


def test_cli_llm_error_continues(cli_root):
    chat = Chat(LLMError("dịch vụ lỗi"), baseline_answer())
    assert run_cli(cli_root, chat=chat) == 4
    rows = ev._read_jsonl(cli_root / "runs/eval/test/assessments/b0.jsonl")
    assert rows[0]["output"]["error"] == "LLMError"
    assert "error" not in rows[1]["output"]
    assert json.loads((cli_root / "runs/eval/test/assessments/summary.json").read_text(encoding="utf-8"))["configs"]["b0"]["recall"] == .5


def test_cli_repeat_separate_caches(cli_root):
    chat = Chat(baseline_answer(), baseline_answer(), baseline_answer())
    assert run_cli(cli_root, "--repeat", "3", chat=chat) == 0
    assert len(chat.requests) == 3
    for directory in ("llm", "llm-repeat-1", "llm-repeat-2"):
        assert len(list((cli_root / ".cache" / directory).glob("*.json"))) == 1
    rows = ev._read_jsonl(cli_root / "runs/eval/test/assessments/b0.jsonl")
    assert len(rows) == 6 and {r["repeat"] for r in rows} == {0, 1, 2}


def test_score_only_never_initializes_services(cli_root):
    def fail(*args):
        pytest.fail("Không được dựng client/model/cấu hình")
    assert ev.main(["--run-id", "offline", "--score-only"], root=cli_root,
                   settings_factory=fail, client_factory=fail, pipeline_factory=fail) == 4


def test_unreachable_stops_before_chat(cli_root):
    (cli_root / "data/processed/chunks.jsonl").write_text('{"chunk_id": "other"}', encoding="utf-8")
    assert run_cli(cli_root, chat=Chat()) == 2
    assert not (cli_root / "runs").exists()


def test_execute_full_and_full_msg(monkeypatch):
    observed = []

    def prepare(messages, chat, model):
        assert messages == ["Chatbot"]
        return {"facts": {"roles": None}, "ready": False}

    def run(facts, statement, description, chat, model, summarize_report):
        observed.append((facts, summarize_report))
        return {"report": {"obligations": [{"id": "ob1", "obligation": "Thông báo",
            "citations": [{"chunk_id": P}], "applicability": "ap_dung", "status": "chua_ro", "criteria": []}],
            "warnings": []}, "trace": {"llm_calls": 2,
            "applicable": {"items": [{"row": {"id": "ob1", "kind": "nghia_vu"}}]},
            "status": {"errors": []}}}

    monkeypatch.setattr(ev, "prepare_assessment", prepare)
    monkeypatch.setattr(ev, "run_assessment", run)
    a = ev.execute("full", product(), None, "fake", None)
    b = ev.execute("full_msg", product(), None, "fake", None)
    assert a["obligations"][0]["kind"] == "nghia_vu" and a["llm_calls"] == 2
    assert b["llm_calls"] == 3 and b["preparation"]["ready"] is False
    assert observed == [({}, False), ({"roles": None}, False)]


def test_quota_caught_by_t34_still_stops(cli_root, monkeypatch):
    def execute(config, row, chat, *args):
        try:
            chat.complete({"model": "fake"})
        except LLMError:
            pass
        return output()
    monkeypatch.setattr(ev, "execute", execute)
    chat = Chat(QuotaExhaustedError())
    assert run_cli(cli_root, chat=chat) == 3
    assert len(chat.requests) == 1


def test_real_gold_schema_and_reachability():
    products = ev.load_products(ROOT / "eval/assessments.jsonl")
    ev.check_reachability(products, ev._read_jsonl(ROOT / "data/processed/chunks.jsonl"))
    assert len(products) >= 12


def test_full_reachability_rejects_missing_table_labels():
    products = ev.load_products(ROOT / "eval/assessments.jsonl")
    chunks = ev._read_jsonl(ROOT / "data/processed/chunks.jsonl")
    table = ev.load_obligations(ROOT / "src/legal_rag/knowledge/obligations.yaml")
    missing = ev.check_reachability(products, chunks, table, ("full", "full_msg"))
    # Không phụ thuộc bảng đang thiếu gì: chỉ kiểm dạng kết quả và nhóm trung tính bị bỏ qua.
    assert all("/" in m for m in missing) and not any(m.split("/")[1].startswith("N") for m in missing)
    stripped = [dict(r, gold=[g for g in r["gold"] if g["gid"] != "G01"]) for r in products]
    gone = [dict(t, review_status="user_rejected") if any(c["chunk_id"].startswith("142-2026-ND-CP_dieu-6_khoan-1") for c in t["citations"]) else t for t in table]
    assert len(ev.check_reachability(stripped, chunks, gone, ("full",))) >= len(missing)
    # Tạo bảng thiếu căn cứ thay vì phụ thuộc một thiếu sót đã được sửa trong bảng thật.
    assert "A04/G39" in ev.check_reachability(products, chunks, [], ("full", "full_msg"))
    assert ev.check_reachability(products, chunks, table, ("b0", "b1")) == []


def test_full_cli_real_t34_t35_with_fake_chat(cli_root):
    class StatusChat:
        def __init__(self):
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            if "facts_v2" in request["messages"][0]["content"]:
                return '{"facts": {}}'
            content = request["messages"][1]["content"]
            rows = json.loads(content.split("NGHĨA VỤ VÀ TIÊU CHÍ:\n", 1)[1])
            return json.dumps({"results": [{"obligation": r["id"], "criterion": c["id"],
                "status": "khong_phat_hien" if r["kind"] == "cam" else "chua_ro", "quote": ""}
                for r in rows for c in r["criteria"]]})

    chat = StatusChat()
    assert ev.main(["--run-id", "full", "--configs", "full,full_msg", "--limit", "1"],
        root=cli_root, pipeline_factory=lambda: pytest.fail("Full không truy xuất"),
        settings_factory=lambda: SimpleNamespace(offline=False, model="fake", base_url="fake", api_key="fake"),
        client_factory=lambda *a: chat) == 0
    folder = cli_root / "runs/eval/full/assessments"
    full = ev._read_jsonl(folder / "full.jsonl")[0]["output"]
    msg = ev._read_jsonl(folder / "full_msg.jsonl")[0]["output"]
    assert msg["preparation"]["ready"] is False
    assert msg["llm_calls"] == full["llm_calls"] + 1
    assert all(o["kind"] == "nghia_vu" for o in full["obligations"])
    assert all(r["model"] == "fake" and r["temperature"] == 0 for r in chat.requests)


def test_ids_limit_and_input_change(cli_root):
    assert run_cli(cli_root, "--ids", "A2", "--limit", "1", chat=Chat(baseline_answer())) == 0
    rows = ev._read_jsonl(cli_root / "runs/eval/test/assessments/b0.jsonl")
    assert [r["id"] for r in rows] == ["A2"]
    path = cli_root / "eval/assessments.jsonl"
    path.write_text(json.dumps(product("A2", description="Đã đổi")), encoding="utf-8")
    assert run_cli(cli_root, "--score-only") == 2


def test_optional_warnings_neither_tp_nor_fp():
    b = "134-2025-QH15_dieu-7_khoan-2_diem-b"
    k5 = "134-2025-QH15_dieu-7_khoan-5"
    other = "134-2025-QH15_dieu-7_khoan-3"
    assert ev._warning_score([b, k5], [b], [k5]) == {"tp": 1, "fp": 0, "fn": 0}
    assert ev._warning_score([k5], [b], [k5]) == {"tp": 0, "fp": 0, "fn": 1}
    assert ev._warning_score([b, other], [b], [k5]) == {"tp": 1, "fp": 1, "fn": 0}
