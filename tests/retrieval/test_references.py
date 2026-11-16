"""T20b: dữ liệu thật và client/cache giả; không gọi mạng hoặc nạp model."""

from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from answer_support import composed_answer
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.agent.references import disambiguate_location
from legal_rag.generation.evidence import build_evidence, format_evidence
from legal_rag.retrieval.exact import exact_lookup
from legal_rag.retrieval.references import ReferenceGraph, expand_references
from test_agent_graph import FakeChat, analysis, state
from test_siblings import fake_data, write_fake_vectors

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_references", ROOT / "scripts/eval_references.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def read(name):
    return [json.loads(line) for line in (ROOT / f"data/processed/{name}.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def corpus():
    import csv
    parents, chunks, refs = read("parents"), read("chunks"), read("references")
    with (ROOT / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        docs = list(csv.DictReader(stream))
    return parents, chunks, refs, docs, ReferenceGraph(refs, parents, chunks)


def test_real_graph_examples_and_coverage(corpus):
    _, _, refs, _, graph = corpus
    targets = graph.targets("134-2025-QH15_dieu-14_khoan-1")
    ids = {target["parent_id"] for target in targets}
    assert {"134-2025-QH15_dieu-11_khoan-1", "134-2025-QH15_dieu-12_khoan-1"} <= ids
    assert all(not target["specific"] for target in targets)
    assert graph.targets("33-2026-QD-TTg_dieu-2_khoan-2") == [dict(
        parent_id="142-2026-ND-CP_dieu-8_khoan-2", raw_text="khoản 2 Điều 8 của Nghị định số 142/2026/NĐ-CP", specific=True)]
    assert any("Luật Công nghiệp công nghệ số" in raw for raw in graph.external("134-2025-QH15_dieu-33"))
    assert graph.articles_mentioned(["134-2025-QH15_dieu-14_khoan-1"], "11") == {"134-2025-QH15"}
    coverage = cli.reference_coverage(refs, graph)
    assert coverage["missing"] == []
    assert coverage["resolved_with_article"] == coverage["with_targets"] > 0


@pytest.mark.parametrize("message,history,suffix", [
    ("Điều 11 là gì?", ["134-2025-QH15_dieu-14_khoan-1"], " 134/2025/QH15"),
    ("Điều 11 là gì?", [], ""),
    ("Điều 11 Nghị định 142 là gì?", ["134-2025-QH15_dieu-14_khoan-1"], ""),
    ("Nghĩa vụ minh bạch là gì?", ["134-2025-QH15_dieu-14_khoan-1"], ""),
    ("Điều 11 là gì?", ["134-2025-QH15_dieu-11_khoan-1"], " 134/2025/QH15"),
    ("Điều 11 là gì?", ["134-2025-QH15_dieu-11_khoan-1", "142-2026-ND-CP_dieu-11_khoan-1"], ""),
    ("Điều 11 và Điều 8?", ["134-2025-QH15_dieu-14_khoan-1", "33-2026-QD-TTg_dieu-2_khoan-2"], ""),
])
def test_followup_examples(corpus, message, history, suffix):
    _, chunks, _, _, graph = corpus
    query = disambiguate_location(message, "query", history, graph, chunks)
    assert query == "query" + suffix
    if suffix:
        exact = exact_lookup("Điều 11" + suffix, chunks)
        lookup = {c["chunk_id"]: c for c in chunks}
        assert exact["results"] and {lookup[h["chunk_id"]]["document_id"] for h in exact["results"]} == {"134-2025-QH15"}


def synthetic():
    def parent(pid, article, clause=None, text="abc", chunk_ids=None):
        return dict(parent_id=pid, document_id="d", article=article, clause=clause,
                    level="clause" if clause else "article", text=text, title="Tiêu đề",
                    chunk_ids=chunk_ids or [pid])
    parents = [parent("source", "1", chunk_ids=["c1", "c2"]), parent("second", "2"),
               parent("a", "3", "1"), parent("b", "3", "2"),
               parent("large", "4", text="x" * 90), parent("small", "5")]
    def ref(chunk, article, clause=None, resolved=True, **kwargs):
        return dict(source_chunk_id=chunk, target_document_id="d", target_article=article,
                    target_clause=clause, target_point=None, resolved=resolved, raw_text="ref", **kwargs)
    refs = [ref("c1", "1"), ref("c1", "3"), ref("c1", "4", resolved=True),
            ref("c2", "3", "2"), ref("c2", "5"), ref("c2", "3"), ref("c2", None),
            ref("second", "5"), ref("c1", "9", resolved=False), ref("c2", "9", resolved=False)]
    # Điểm vẫn dẫn tới Khoản chứa Điểm.
    refs[3]["target_point"] = "đ"
    return parents, refs, ReferenceGraph(refs, parents, [])


def test_graph_order_dedup_self_article_without_clause_and_unknown():
    _, _, graph = synthetic()
    assert graph.targets("source") == [
        dict(parent_id=pid, raw_text="ref", specific=False) for pid in ("a", "b", "large", "small")]
    assert graph.external("source") == ["ref"]
    assert graph.targets("missing") == [] and graph.external("missing") == []
    assert graph.targets("second") == [dict(parent_id="small", raw_text="ref", specific=False)]


def test_expand_priority_budget_skip_duplicates_first_source_and_purity():
    parents, refs, _ = synthetic()
    # Đặt dẫn chiếu cụ thể sau dẫn chiếu Điều khác; vẫn phải kéo trước.
    refs = [refs[1], dict(refs[3], target_article="5", target_clause=None),
            dict(refs[3], target_article="3", target_clause="2"), refs[2], refs[7]]
    graph = ReferenceGraph(refs, parents, [])
    before = json.dumps(parents)
    units = parents[:2]
    extras = expand_references(units, graph, parents, 3, 2)
    # a là dẫn Điều, b được gặp ở dẫn Điều trước nên còn specific=false sau khử trùng.
    assert [p["parent_id"] for p in extras] == ["a", "b", "small"]
    assert all(p["referenced_from"] == "source" for p in extras)
    # Không có dẫn Điều đè lên b: b cụ thể được ưu tiên, large bị bỏ qua.
    graph = ReferenceGraph([refs[2], refs[3], refs[1]], parents, [])
    extras = expand_references(units, graph, parents, 2, 1)
    assert [p["parent_id"] for p in extras] == ["b", "small"]
    assert json.dumps(parents) == before and all(p is not parents[3] for p in extras)
    assert expand_references(units, graph, parents, 0, 2) == []
    assert expand_references(units, graph, parents, 3, 0) == []
    assert expand_references(units, graph, parents, 1, 2)[0]["parent_id"] == "b"


def test_evidence_sources_codes_notes_and_citation_unchanged():
    from test_basic_rag import DOCUMENTS, parents
    from legal_rag.generation.citations import format_citation
    units = parents()
    items = build_evidence([units[0], dict(units[1], block="Nhóm")], DOCUMENTS,
                           [dict(units[2], referenced_from=units[0]["parent_id"])])
    assert [p["source"] for p in items] == ["retrieval", "frame", "reference"]
    assert items[2]["referenced_from"] == "E1"
    citation = format_citation(items[2])
    items[2]["external_refs"] = ["Luật khác", "Chương II"]
    formatted = format_evidence(items)
    assert 'Tiêu đề: Tiêu đề\nĐược dẫn chiếu từ [E1], kéo thêm để đủ ngữ cảnh.' in formatted
    assert 'Dẫn chiếu tới văn bản ngoài dữ liệu: Luật khác; Chương II.' in formatted
    assert format_citation(items[2]) == citation
    assert build_evidence([], DOCUMENTS, [dict(units[2], referenced_from="unknown")])[0]["referenced_from"] == "unknown"


def test_answer_disabled_enabled_and_broad_external(corpus, monkeypatch):
    parents, chunks, refs, docs, graph = corpus
    source = graph.parents["134-2025-QH15_dieu-14_khoan-1"]
    pipeline = lambda: SimpleNamespace(context_many=lambda qs, q, b: [source], last_detail={}, last_timing={})
    kwargs = dict(chunks_loader=lambda: chunks, references=refs)
    default = composed_answer(pipeline, parents, docs, **kwargs)(
        "Nghĩa vụ nhà cung cấp", ["query"], EMPTY_PROFILE, FakeChat("Nội dung [E1]"), "fake")
    assert default["evidence"] == build_evidence([source], docs)
    assert default["references_added"] == []
    enabled = composed_answer(pipeline, parents, docs, config=AgentConfig(enable_references=True), **kwargs)(
        "Nghĩa vụ nhà cung cấp", ["query"], EMPTY_PROFILE, FakeChat("Nội dung [E1]"), "fake")
    assert enabled["references_added"]
    assert enabled["evidence"][1]["source"] == "reference"
    assert enabled["evidence"][1]["referenced_from"] == "E1"
    import legal_rag.agent.answer as module
    monkeypatch.setattr(module, "expand_references", lambda *args: pytest.fail("Không mở rộng khung"))
    monkeypatch.setattr(module, "load_frame", lambda *args: [dict(label="Nhóm", parents=[graph.parents["134-2025-QH15_dieu-33"]])])
    broad = composed_answer(lambda: pytest.fail("Không tạo pipeline"), parents, docs,
                         config=AgentConfig(enable_references=True), **kwargs)(
        "Một sản phẩm AI cần có những nghĩa vụ gì?", ["query"], EMPTY_PROFILE, FakeChat("Nội dung [E1]"), "fake")
    assert broad["route"] == "broad_frame" and broad["references_added"] == []
    assert broad["evidence"][0]["source"] == "frame"
    assert broad["evidence"][0]["external_refs"] == graph.external("134-2025-QH15_dieu-33")
    assert not AgentConfig().enable_references
    with pytest.raises(FrozenInstanceError):
        AgentConfig().enable_references = True


def test_last_parents_followup_trace_greeting_empty_and_isolated_session(corpus):
    parents, chunks, refs, docs, graph = corpus
    queries = []
    source = graph.parents["134-2025-QH15_dieu-14_khoan-1"]
    responses = iter([[source], [graph.parents["134-2025-QH15_dieu-11_khoan-1"]], []])
    def context(query, budget):
        queries.append(query)
        return next(responses)
    from legal_rag.agent.answer import prepare_evidence
    answer = prepare_evidence(lambda: SimpleNamespace(context_many=lambda qs, q, b: context(qs[0], b), last_detail={}, last_timing={}), parents, docs,
                          references=refs, chunks_loader=lambda: chunks)
    chat = FakeChat(analysis(), "## Trả lời ngắn\nĐáp [E1]\n\n## Căn cứ\nĐáp [E1]",
                    analysis(), "## Trả lời ngắn\nĐáp [E1]\n\n## Căn cứ\nĐáp [E1]",
                    analysis(), "## Trả lời ngắn\nKhông có căn cứ\n\n## Căn cứ\nKhông có căn cứ")
    session = build_graph(GraphDeps(chat, "fake", answer, AgentConfig(enable_rewrite=False, enable_verifier=False)))
    run_turn(session, "s", "Nghĩa vụ nhà cung cấp")
    assert state(session)["last_parents"] == [source["parent_id"]]
    run_turn(session, "s", "xin chào")
    assert state(session)["last_parents"] == [source["parent_id"]]
    result = run_turn(session, "s", "Điều 11 là gì?")
    node = next(node for node in result["trace"] if node["node"] == "retrieve")
    assert node["query_used"] == queries[-1] == "Điều 11 là gì? 134/2025/QH15"
    assert node["references_added"] == []
    retained = state(session)["last_parents"]
    run_turn(session, "s", "Câu không có bằng chứng")
    assert state(session)["last_parents"] == retained
    run_turn(session, "other", "xin chào")
    assert state(session, "other")["last_parents"] == []


def selection_runs(gain=.03, turns=.6, plain=.53):
    def run(q, t):
        return dict(metrics=dict(questions=dict(recall=q), turns=dict(recall=t)))
    return {"base": run(.5, .6), **{f"plain@{t}": run(plain, .6) for t in (3500, 4000, 4500, 6000)},
            **{f"ref@{r},top@{k}": run(.5 + gain, turns) for r, k in cli.REFERENCE_SETTINGS}}


@pytest.mark.parametrize("kwargs,enabled", [({}, True), (dict(gain=.019), False),
    (dict(turns=.599), False), (dict(plain=.541), False), (dict(gain=.02, plain=.53), True)])
def test_selection_rule(kwargs, enabled):
    result = cli.choose_references(selection_runs(**kwargs))
    assert result["candidate"] == dict(budget=500, top_units=3)
    assert result["enabled"] is enabled


@pytest.mark.parametrize("missing", ["documents", "query", "rerank_file", "rerank_pair"])
def test_cli_missing_cache(fake_data, capsys, missing):
    root, chunks, _, gold = fake_data
    (root / "data/processed/references.jsonl").write_text("", encoding="utf-8")
    if missing != "documents":
        cache = write_fake_vectors(root, chunks, gold)
        if missing == "query":
            cache.query_path(gold[0]["question"]).unlink()
        if missing == "rerank_pair":
            path = root / ".cache/rerank/scores.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("", encoding="utf-8")
    assert cli.main([], root=root) == 1
    error = capsys.readouterr().err
    assert {"documents": "Thiếu cache jina", "query": "Thiếu vector truy vấn",
            "rerank_file": "Thiếu cache rerank", "rerank_pair": "cặp"}[missing] in error
    assert not (root / "runs/t20b/references.json").exists()


def test_macro_primary_labels_tokens_changes_and_baseline_gate():
    parents, refs, graph = synthetic()
    gold = [dict(id="q", gold_parents=["source", "small"], gold_secondary=["a"]),
            dict(id="t", scenario_id="s", gold_parents=["small"]),
            dict(id="no-label", gold_parents=[])]
    hits = {row["id"]: [dict(chunk_id="source", parent_id="source")] for row in gold}
    runs = cli.measure_contexts(gold, hits, parents, graph)
    assert runs["base"]["metrics"]["questions"] == dict(labeled_questions=1, recall=.5, mean_tokens=1)
    assert runs["base"]["metrics"]["turns"]["recall"] == 0
    ref = runs["ref@500,top@3"]
    assert ref["metrics"]["questions"]["recall"] == 1
    assert ref["metrics"]["questions"]["mean_tokens"] == 34
    assert ref["changed_parent_labels"] == [dict(id="q", group="questions", before=1, after=2),
                                            dict(id="t", group="turns", before=0, after=1)]
    with pytest.raises(ValueError, match="lệch số đã chốt"):
        cli.validate_baseline(runs)
    runs["base"]["metrics"]["questions"]["recall"] = .69524
    runs["base"]["metrics"]["turns"]["recall"] = .52644
    cli.validate_baseline(runs)


def test_cli_cache_only_output_override_and_reachability(fake_data, monkeypatch, capsys):
    root, chunks, parents, gold = fake_data
    (root / "data/processed/references.jsonl").write_text("", encoding="utf-8")
    write_fake_vectors(root, chunks, gold)
    path = root / ".cache/rerank/scores.jsonl"
    scorer = cli.CacheOnlyScorer(path)
    path.parent.mkdir(parents=True)
    entries = [dict(key=scorer.pair_key((row["question"], c["index_text"])), score=1, latency_ms=0)
               for row in gold for c in chunks]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    before = path.read_bytes()
    # Cache giả không được coi là đạt mốc baseline thật.
    assert cli.main([], root=root) == 1
    assert "lệch số đã chốt" in capsys.readouterr().err
    assert not (root / "runs/t20b/references.json").exists()
    checked = []
    monkeypatch.setattr(cli, "validate_baseline", lambda runs: checked.append(runs["base"]))
    output = root / "runs/custom.json"
    assert cli.main(["--output", str(output)], root=root) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(checked) == 1 and len(result["runs"]) == 13
    assert result["coverage"]["missing"] == []
    assert not result["selection"]["enabled"]
    assert path.read_bytes() == before
    assert "Áp dụng quy tắc" in capsys.readouterr().out
    gold[0]["gold_parents"] = ["missing"]
    (root / "eval/retrieval.jsonl").write_text("".join(json.dumps(row) + "\n" for row in gold), encoding="utf-8")
    monkeypatch.setattr(cli.VectorCache, "load_documents", lambda self: pytest.fail("Phải kiểm nhãn trước đọc cache"))
    assert cli.main([], root=root) == 1
    assert "Nhãn không chạm được" in capsys.readouterr().err


def test_predict_locked_stages_and_exact_dedup(fake_data, monkeypatch):
    _, chunks, parents, gold = fake_data
    hits = [dict(chunk_id=p["parent_id"], parent_id=p["parent_id"]) for p in parents]
    events = []
    class BM25:
        def __init__(self, source, config):
            assert source == chunks
            assert (config.tokenizer, config.accents, config.source) == ("syllable", "both", "index_text")
        def search(self, query):
            events.append("bm25")
            return hits
    class Dense:
        def search(self, query):
            events.append("dense")
            return hits
    def fusion(rankings):
        events.append("rrf")
        assert rankings == [hits, hits]
        return hits
    def cap(found, source, limit):
        events.append("cap")
        assert found == hits and source == chunks and limit == 3
        return hits
    scorer = object()
    def rerank(query, found, source, score, pool):
        events.append("rerank")
        assert found == hits and source == chunks and score is scorer and pool == 20
        return hits
    def exact(query, source):
        events.append("exact")
        return {"results": [dict(hits[-1], match_level="article"), dict(hits[-2], match_level="document")]}
    for name, value in (("BM25Retriever", BM25), ("rrf", fusion), ("cap_list_items", cap),
                        ("rerank", rerank), ("exact_lookup", exact)):
        monkeypatch.setattr(cli, name, value)
    predictions = cli.predict(chunks, gold, Dense(), scorer)
    assert events == ["bm25", "dense", "rrf", "cap", "rerank", "exact"] * len(gold)
    assert predictions[gold[0]["id"]] == [dict(hits[-1], match_level="article"), *hits[:-1]]


def test_same_article_reference_needs_specific_clause():
    parents = [dict(parent_id="d_dieu-1_khoan-1", level="clause", document_id="d", article="1", clause="1", chunk_ids=["c1"], text="x"),
               dict(parent_id="d_dieu-1_khoan-2", level="clause", document_id="d", article="1", clause="2", chunk_ids=["c2"], text="y")]
    base = dict(source_chunk_id="c1", resolved=True, target_document_id="d", target_article="1", target_point=None)
    whole = ReferenceGraph([dict(base, raw_text="Điều này", target_clause=None)], parents, [])
    assert whole.targets("d_dieu-1_khoan-1") == []
    one = ReferenceGraph([dict(base, raw_text="khoản 2 Điều này", target_clause="2")], parents, [])
    assert [t["parent_id"] for t in one.targets("d_dieu-1_khoan-1")] == ["d_dieu-1_khoan-2"]
