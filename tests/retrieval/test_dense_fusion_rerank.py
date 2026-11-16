"""T11: phép tính tay, cache, CLI và model giả; không tải model thật."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from legal_rag.evaluation.retrieval import evaluate, ranked_units
from legal_rag.evaluation.retrieval_experiment import (
    choose_best, rebuild_overlap, run_experiments, validate_reachability,
)
from legal_rag.retrieval.cache import VectorCache, chunk_key, stage_key
from legal_rag.retrieval.context import clause_unit, estimate_tokens, select_context
from legal_rag.retrieval.dense import DenseRetriever, MODELS, ModelEncoder
from legal_rag.retrieval.fusion import cap_list_items, rrf
from legal_rag.retrieval.rerank import CachedScorer, MODEL, REVISION, ModelScorer, rerank

ROOT = Path(__file__).resolve().parents[2]


def hit(key, score=1):
    return {"chunk_id": key, "parent_id": key, "article_id": None, "score": score}


def fake_chunks():
    return [dict(hit(key), index_text=text, body=text, level="list_item" if key == "a" else "article",
                 document_id="d", document_number="134/2025/QH15", document_title="Luật Trí tuệ nhân tạo",
                 article=None, clause=None, point=None)
            for key, text in (("a", "tín dụng"), ("b", "giáo dục"), ("c", "bình thường"))]


class FakeEncoder:
    def __init__(self, name="jina"):
        self.documents, self.queries = [], []

    def encode_documents(self, texts):
        self.documents.extend(texts)
        return np.array([[1, i + 1] for i, _ in enumerate(texts)], dtype=np.float32)

    def encode_queries(self, texts):
        self.queries.extend(texts)
        return np.array([[1, 0] for _ in texts], dtype=np.float32)


def test_dense_dot_product_ties_missing_and_limits():
    chunks = [hit("z"), hit("a"), hit("b")]
    retriever = DenseRetriever(chunks, np.array([[1, 3], [1, 3], [-1, 0]]), {"q": np.array([1, 1])})
    assert retriever.search("q") == [hit("a", 4), hit("z", 4), hit("b", -1)]
    assert retriever.search("q", 1) == [hit("a", 4)]
    assert retriever.search("q", 0) == []
    with pytest.raises(ValueError, match="Thiếu vector"):
        retriever.search("missing")
    with pytest.raises(ValueError):
        retriever.search("q", -1)
    with pytest.raises(ValueError):
        DenseRetriever(chunks, np.zeros((2, 2)), {})


def test_cache_chain_invalidates_only_current_and_later_stages(tmp_path):
    chunks = fake_chunks()
    def chain(chunk_config, embedding_config, index_config):
        c = chunk_key(chunks, chunk_config)
        e = stage_key(c, embedding_config)
        return c, e, stage_key(e, index_config)
    base = chain({"overlap": 0}, {"model": "jina"}, {"metric": "dot"})
    change_chunk = chain({"overlap": 1}, {"model": "jina"}, {"metric": "dot"})
    assert all(a != b for a, b in zip(base, change_chunk))
    change_embedding = chain({"overlap": 0}, {"model": "viet"}, {"metric": "dot"})
    assert base[0] == change_embedding[0] and base[1] != change_embedding[1] and base[2] != change_embedding[2]
    change_index = chain({"overlap": 0}, {"model": "jina"}, {"metric": "cos"})
    assert base[:2] == change_index[:2] and base[2] != change_index[2]
    assert stage_key("a", {"b": 1, "a": 2}) == stage_key("a", {"a": 2, "b": 1})
    changed = deepcopy(chunks)
    changed[0]["index_text"] += " mới"
    assert chunk_key(chunks) != chunk_key(changed)
    assert VectorCache(tmp_path, chunks, "jina").key != VectorCache(tmp_path, chunks, "viet").key


def test_cache_resume_numpy_queries_and_times(tmp_path):
    chunks, encoder = fake_chunks(), FakeEncoder()
    cache = VectorCache(tmp_path, chunks, "viet")
    with pytest.raises(FileNotFoundError, match="build_index.py --model viet"):
        cache.load_documents()
    vectors = cache.build_documents(encoder)
    np.testing.assert_array_equal(vectors, cache.load_documents())
    cache.build_documents(encoder)
    assert encoder.documents == [c["index_text"] for c in chunks]
    queries, times = cache.build_queries(["có dấu", "lượt", "có dấu"], encoder)
    cache.build_queries(["có dấu", "lượt", "mới"], encoder)
    assert encoder.queries == ["có dấu", "lượt", "mới"]
    assert all(value >= 0 for value in times.values())
    assert set(queries) == {"có dấu", "lượt"}
    assert cache.query_path("có dấu").parent == cache.path
    with pytest.raises(FileNotFoundError, match="build_index.py --model viet"):
        cache.load_queries(["thiếu"])
    assert not list(tmp_path.rglob("*.pkl"))


def test_hand_rrf_cap_rerank_preserve_inputs():
    first, second = [hit("b"), hit("a"), hit("c")], [hit("a"), hit("b")]
    before = deepcopy((first, second))
    fused = rrf([first, second])
    assert [h["chunk_id"] for h in fused] == ["a", "b", "c"]
    assert fused[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[2]["score"] == pytest.approx(1 / 63)
    assert (first, second) == before
    chunks = [dict(hit(k), level="list_item" if k in "abcd" else "article", index_text=k)
              for k in "abcdef"]
    hits = [hit(k) for k in "abecfd"]
    assert [h["chunk_id"] for h in cap_list_items(hits, chunks, 2)] == list("abefcd")
    assert [h["chunk_id"] for h in cap_list_items(hits, chunks, 0)] == list("efabcd")
    assert cap_list_items(hits, chunks, 10) == hits
    calls = []
    def score(pairs):
        calls.extend(pairs)
        return [2, 4, 4]
    result = rerank("q", [hit(k) for k in "cbaed"], chunks, score, 3)
    assert [h["chunk_id"] for h in result] == list("abced")
    assert calls == [("q", "c"), ("q", "b"), ("q", "a")]
    assert result[-2:] == [hit("e"), hit("d")]
    assert rerank("q", hits, chunks, lambda _: pytest.fail("pool 0"), 0) == hits
    with pytest.raises(ValueError, match="một điểm"):
        rerank("q", hits, chunks, lambda _: [], 2)


def test_reranker_cache_revision_and_saved_latency(tmp_path):
    path = tmp_path / "scores.jsonl"
    calls = []
    def score(pairs):
        calls.extend(pairs)
        return [len(t) for _, t in pairs]
    cache = CachedScorer(path, score)
    assert cache.score([("q", "x"), ("q", "xx"), ("q", "x")]) == [1, 2, 1]
    assert calls == [("q", "x"), ("q", "xx")]
    elapsed = cache.last_latency_ms
    restored = CachedScorer(path, lambda _: pytest.fail("cache đã đủ"))
    assert restored.score([("q", "x"), ("q", "xx"), ("q", "x")]) == [1, 2, 1]
    assert restored.last_latency_ms == elapsed
    assert restored.pair_key(("q", "x")) != CachedScorer(path, revision="new").pair_key(("q", "x"))
    assert restored.pair_key(("q", "x")) != restored.pair_key(("q2", "x"))
    assert restored.pair_key(("q", "x")) != restored.pair_key(("q", "xx"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_context_first_over_budget_stop_without_skipping_deduplicate():
    parents = [{"parent_id": key, "text": text} for key, text in (("a", "abcd"), ("b", "x" * 9), ("c", "x"))]
    hits = [hit("a"), hit("a"), hit("b"), hit("c")]
    assert estimate_tokens("abcd") == 2 and estimate_tokens("") == 0
    assert select_context(hits, parents, 0) == ([parents[0]], 2)
    assert select_context(hits, parents, 4) == ([parents[0]], 2)
    assert select_context(hits, parents, 5) == (parents[:2], 5)
    assert select_context(hits, parents, 6) == (parents, 6)
    assert select_context([], parents, 0) == ([], 0)
    split = {"chunk_id": "d_dieu-1_khoan-2_diem-a_phan-3", "parent_id": "d_dieu-1_khoan-2"}
    assert clause_unit(split) == "d_dieu-1_khoan-2"
    assert clause_unit(dict(split, chunk_id="d_dieu-1_khoan-2_phan-2")) == "d_dieu-1_khoan-2"
    with pytest.raises(ValueError, match="Thiếu parent"):
        select_context([hit("missing")], parents, 100)


def test_budget_metrics_macro_denominators_secondary_and_article_units():
    a, b, item = "d_dieu-1_khoan-1", "d_dieu-2_khoan-1", "item"
    rows = [{"id": "q1", "category": "c", "priority": True, "gold_parents": [a, b],
             "gold_articles": ["d_dieu-1", "d_dieu-2"], "gold_secondary": ["secondary"]},
            {"id": "q2", "category": "c", "priority": False, "gold_parents": [item], "gold_articles": []},
            {"id": "empty", "category": "empty", "priority": False, "gold_parents": [], "gold_articles": []}]
    parents = [{"parent_id": key, "text": "x" * 6} for key in (a, b, item, "secondary")]
    predictions = {"q1": [hit(a), hit(a), hit(b)], "q2": [hit(item)]}
    result = evaluate(rows, predictions, parents=parents, budgets=(2, 4))
    for level in ("parent", "article"):
        assert result["all"][level]["labeled_questions"] == 2
        assert result["all"][level]["recall@2"] == .75
        assert result["all"][level]["recall@4"] == 1
        assert result["all"][level]["hit@2"] == 1
        assert result["categories"]["empty"][level]["recall@2"] is None
    assert "recall@3000" not in evaluate(rows, predictions)["all"]["parent"]


def test_selection_uses_questions_then_article_mrr_and_order():
    def run(parent, article, mrr):
        return {"metrics": {"questions": {"parent": {"recall@3000": parent, "mrr": mrr},
                                            "article": {"recall@3000": article}},
                            "all": {"parent": {"recall@3000": 999}},
                            "turns": {"parent": {"recall@3000": 999}}, "median_latency_ms": 0}}
    runs = {"A": run(.8, .2, .1), "B": run(.7, 1, 1), "C": run(.8, .3, .1),
            "D": run(.8, .3, .2), "E": run(.8, .3, .2)}
    assert choose_best(runs, ["A", "B"]) == "A"
    assert choose_best(runs, ["A", "C"]) == "C"
    assert choose_best(runs, ["C", "D"]) == "D"
    assert choose_best(runs, list(runs)) == "D"


def experiment_inputs(tmp_path):
    chunks = fake_chunks()
    parents = [{"parent_id": c["parent_id"], "text": c["body"]} for c in chunks]
    gold = [{"id": "q", "question": "tín dụng", "category": "c", "priority": True,
             "gold_status": "auto", "gold_parents": ["a"], "gold_articles": []},
            {"id": "s.t1", "scenario_id": "s", "turn_text": "hiện tại", "question": "hiện tại tín dụng",
             "category": "c", "priority": False, "gold_status": "auto", "gold_parents": ["a"], "gold_articles": []}]
    queries = [r["question"] for r in gold] + [gold[1]["turn_text"]]
    dense, times = {}, {}
    for name in ("jina", "viet"):
        cache = VectorCache(tmp_path, chunks, name)
        encoder = FakeEncoder()
        vectors = cache.build_documents(encoder)
        query_vectors, _ = cache.build_queries(queries, encoder)
        dense[name] = DenseRetriever(chunks, vectors, query_vectors)
        times[name] = dict.fromkeys(queries, 100)
    return chunks, parents, gold, dense, times


def test_full_experiments_fake_models_and_latency(tmp_path):
    chunks, parents, gold, dense, times = experiment_inputs(tmp_path)
    before = deepcopy((chunks, parents, gold))
    outputs = {f"chunk_{size}_o{o}": {"chunks": chunks, "parents": parents, "split_count": 0}
               for size in (3500, 400) for o in (0, 1)}
    scorer = CachedScorer(tmp_path / "scores.jsonl", lambda pairs: [1] * len(pairs))
    result = run_experiments(chunks, gold, parents, dense, times, scorer, outputs)
    assert list(result["runs"]) == ["A", "B", "C", "D", "E", "bm25_best", "dense_jina", "dense_viet",
                                     "dense_best", "rrf", "rrf_cap3", "base", "rerank20", "rerank40",
                                     "final", "final_exact", "final_turn_only", *outputs]
    assert result["runs"]["dense_jina"]["metrics"]["all"]["median_latency_ms"] >= 100
    assert result["runs"]["rrf"]["latency_ms"]["q"] >= 100
    assert result["runs"]["final_turn_only"]["metrics"]["turns"]["questions"] == 1
    assert (chunks, parents, gold) == before
    no_rerank = run_experiments(chunks, gold, parents, dense, times)
    assert "rerank20" not in no_rerank["runs"] and "--rerank" in no_rerank["reranker"]
    with pytest.raises(ValueError, match="Nhãn không chạm"):
        validate_reachability(chunks, [{**gold[0], "gold_parents": ["missing"]}], parents)


def test_experiment_uses_saved_pair_latency_and_only_promotes_article(tmp_path, monkeypatch):
    chunks, parents, gold, dense, times = experiment_inputs(tmp_path)
    scorer = CachedScorer(tmp_path / "scores.jsonl", lambda pairs: [1] * len(pairs))
    queries = [r["question"] for r in gold] + [gold[1]["turn_text"]]
    scorer.score([(q, c["index_text"]) for q in queries for c in chunks])
    for entry in scorer.entries.values():
        entry["latency_ms"] = 50
    monkeypatch.setattr("legal_rag.evaluation.retrieval_experiment.exact_lookup",
                        lambda q, cs: {"results": [dict(hit("c"), match_level="document")]})
    result = run_experiments(chunks, gold, parents, dense, times, scorer)
    assert result["runs"]["final_exact"]["predictions"] == result["runs"]["final"]["predictions"]
    assert all(t >= 250 for t in result["runs"]["rerank20"]["latency_ms"].values())
    monkeypatch.setattr("legal_rag.evaluation.retrieval_experiment.exact_lookup",
                        lambda q, cs: {"results": [dict(hit("c"), match_level="article")]})
    result = run_experiments(chunks, gold, parents, dense, times, scorer)
    assert result["runs"]["final_exact"]["predictions"]["q"][0]["chunk_id"] == "c"
    assert len(result["runs"]["final_exact"]["predictions"]["q"]) == len(chunks)


def test_real_overlap_and_parent_reachability():
    outputs = rebuild_overlap(ROOT)
    assert outputs["chunk_3500_o0"]["chunks"] == outputs["chunk_3500_o1"]["chunks"]
    assert outputs["chunk_3500_o0"]["split_count"] == outputs["chunk_3500_o1"]["split_count"] == 0
    assert outputs["chunk_400_o0"]["split_count"] > 0
    assert outputs["chunk_400_o1"]["chunks"] != outputs["chunk_400_o0"]["chunks"]
    gold = [json.loads(line) for line in (ROOT / "eval/retrieval.jsonl").read_text(encoding="utf-8").splitlines()]
    for output in outputs.values():
        validate_reachability(output["chunks"], gold, output["parents"])
        parents = {p["parent_id"] for p in output["parents"]}
        assert all(clause_unit(c) in parents for c in output["chunks"])
        split_clauses = [c for c in output["chunks"] if "_phan-" in c["chunk_id"] and "_khoan-" in c["chunk_id"]]
        for c in split_clauses:
            assert "_phan-" not in clause_unit(c) and "_diem-" not in clause_unit(c)


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_cli_build_resume_and_eval_without_embedding_load(tmp_path, monkeypatch, capsys):
    chunks, parents, gold, _, _ = experiment_inputs(tmp_path / "initial")
    write_rows(tmp_path / "data/processed/chunks.jsonl", chunks)
    write_rows(tmp_path / "data/processed/parents.jsonl", parents)
    write_rows(tmp_path / "eval/retrieval.jsonl", gold)
    build = load_script("build_index")
    created = []
    def factory(name):
        encoder = FakeEncoder(name)
        created.append((name, encoder))
        return encoder
    for name in ("jina", "viet"):
        assert build.main(["--model", name], tmp_path, factory) == 0
    assert [name for name, _ in created] == ["jina", "viet"]
    assert created[0][1].documents == [c["index_text"] for c in chunks]
    assert set(created[0][1].queries) == {r["question"] for r in gold} | {gold[1]["turn_text"]}
    assert build.main(["--model", "jina"], tmp_path, factory) == 0
    assert not created[-1][1].documents and not created[-1][1].queries
    evaluation = load_script("eval_retrieval")
    monkeypatch.setattr(evaluation, "rebuild_overlap", lambda _: {})
    monkeypatch.setattr(ModelEncoder, "_load", lambda _: pytest.fail("không được nạp embedding"))
    monkeypatch.setattr(ModelScorer, "score", lambda *args: pytest.fail("không được nạp reranker"))
    assert evaluation.main([], tmp_path) == 0
    result = json.loads((tmp_path / "runs/t11/retrieval.json").read_text(encoding="utf-8"))
    assert "rerank20" not in result["runs"]
    # Với cờ --rerank nhưng cache đủ, scorer thật vẫn không được gọi.
    scores = CachedScorer(tmp_path / ".cache/rerank/scores.jsonl", lambda pairs: [1] * len(pairs))
    scores.score([(query, c["index_text"]) for query in
                  [r["question"] for r in gold] + [gold[1]["turn_text"]] for c in chunks])
    assert evaluation.main(["--rerank"], tmp_path) == 0
    assert evaluation.main(["--cache-dir", str(tmp_path / "missing")], tmp_path) == 1
    assert "build_index.py --model jina" in capsys.readouterr().err


def test_model_adapters_lazy_pinned_and_cls_normalized(monkeypatch):
    import torch
    calls, token_calls = [], []
    class FakeModel:
        def to(self, device):
            assert device == "cpu"
            return self
        def eval(self):
            return self
        def encode(self, texts, task):
            calls.append(task)
            return np.ones((len(texts), 2))
        def __call__(self, **inputs):
            n = len(inputs["input_ids"])
            return SimpleNamespace(last_hidden_state=torch.tensor([[[3., 4.], [100., 0.]]] * n),
                                   logits=torch.tensor([[2.]] * n))
    class Factory:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls.append((name, kwargs))
            return FakeModel()
    class Tokenizer:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls.append((name, kwargs))
            return Tokenizer()
        def __call__(self, texts, **kwargs):
            token_calls.append(kwargs)
            if kwargs.get("truncation") is False:
                return {"input_ids": [[1] * (513 if text == "long" else 2) for text in texts]}
            return {"input_ids": torch.ones((len(texts), 2), dtype=torch.long)}
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=Factory, AutoTokenizer=Tokenizer,
                                                                   AutoModelForSequenceClassification=Factory))
    jina, viet, scorer = ModelEncoder("jina"), ModelEncoder("viet"), ModelScorer()
    assert not calls
    jina.encode_documents(["doc"])
    jina.encode_queries(["query"])
    assert "retrieval.passage" in calls and "retrieval.query" in calls
    assert (MODELS["jina"]["model"], {"revision": MODELS["jina"]["revision"], "trust_remote_code": True}) in calls
    vectors = viet.encode_documents(["short", "long"])
    np.testing.assert_allclose(vectors, [[.6, .8], [.6, .8]])
    viet.encode_queries(["long"])
    assert viet.truncated_documents == 1 and viet.truncated_queries == 1
    assert any(c.get("max_length") == 512 and c["truncation"] for c in token_calls)
    assert scorer.score([("q", "text")]) == [2.]
    assert (MODEL, {"revision": REVISION}) in calls
