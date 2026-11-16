"""T17: thứ tự ngữ cảnh và thí nghiệm từ cache giả, không nạp model."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from legal_rag.evaluation.retrieval import evaluate
from legal_rag.retrieval.cache import VectorCache, write_json
from legal_rag.retrieval.context import select_context
from legal_rag.retrieval.pipeline import DEFAULT_CONFIG, RetrievalPipeline
from legal_rag.retrieval import dense, rerank as rerank_module

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_siblings", ROOT / "scripts/eval_siblings.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def parent(article, clause, document="d", level="clause", text="abc"):
    key = f"{document}_dieu-{article}"
    if clause is not None:
        key += f"_khoan-{clause}"
    return dict(parent_id=key, document_id=document, article=article,
                clause=clause, level=level, text=text)


def hit(p):
    return dict(chunk_id=p["parent_id"], parent_id=p["parent_id"])


def example():
    parents = [parent("A", str(i)) for i in (1, 2, 3)]
    parents += [parent("B", str(i)) for i in (1, 2)]
    return parents, [hit(parents[i]) for i in (2, 3, 0)]


@pytest.mark.parametrize("n,indices", [(0, [2, 3, 0]), (1, [2, 0, 1, 3]), (2, [2, 0, 1, 3, 4])])
@pytest.mark.parametrize("mapping", [False, True])
def test_example(n, indices, mapping):
    parents, hits = example()
    source = {p["parent_id"]: p for p in parents} if mapping else parents
    assert select_context(hits, source, 100, n) == ([parents[i] for i in indices], len(indices))


def test_budget_stops_at_inserted_clause_and_never_skips():
    parents, hits = example()
    parents[0]["text"] = "x" * 30
    assert select_context(hits, parents, 2, 1) == ([parents[2]], 1)
    assert select_context(hits, parents, 11, 1) == ([parents[2], parents[0]], 11)
    assert select_context(hits, parents, 0, 1) == ([parents[2]], 1)
    assert select_context([], parents, 0, 1) == ([], 0)


@pytest.mark.parametrize("level", ["article", "list_item", "appendix_item"])
def test_non_clause_does_not_open_or_consume_article_limit(level):
    parents, hits = example()
    other = parent("C", None, level=level)
    sibling = parent("C", "1")
    source = [other, sibling, *parents]
    assert select_context([hit(other), *hits], source, 100, 1)[0] == [
        other, parents[2], parents[0], parents[1], parents[3]]


def test_document_article_pair_and_parent_order():
    a1, a2 = parent("1", "1"), parent("1", "2")
    b1, b2 = parent("1", "1", "other"), parent("1", "2", "other")
    parents = [b2, a2, b1, a1]
    assert select_context([hit(a1), hit(b1)], parents, 100, 1)[0] == [a1, a2, b1]
    assert select_context([hit(a1), hit(b1)], parents, 100, 2)[0] == [a1, a2, b1, b2]


def test_default_matches_legacy_bytes_without_level_and_split_hits():
    parents, hits = example()
    for p in parents:
        del p["level"]
    hits.insert(1, dict(hits[0], chunk_id=hits[0]["chunk_id"] + "_diem-a_phan-2"))
    expected = ([parents[i] for i in (2, 3, 0)], 3)
    for n in (0, 2):
        actual = select_context(hits, parents, 100, n)
        assert json.dumps(actual, ensure_ascii=False).encode() == json.dumps(expected, ensure_ascii=False).encode()
    assert select_context(hits, parents, 2) == ([parents[2], parents[3]], 2)
    with pytest.raises(ValueError, match="Thiếu parent"):
        select_context([dict(chunk_id="missing", parent_id="missing")], parents, 100)


@pytest.mark.parametrize("n", [-1, 1.5, True])
def test_invalid_sibling_count(n):
    with pytest.raises(ValueError, match="sibling_articles"):
        select_context([], [], 100, n)
    with pytest.raises(ValueError, match="sibling_articles"):
        replace(DEFAULT_CONFIG, sibling_articles=n)


def test_pipeline_passes_sibling_config(monkeypatch):
    parents, hits = example()
    config = replace(DEFAULT_CONFIG, dense=(), cap=None, rerank_pool=None,
                     exact_first=False, sibling_articles=1)
    pipeline = RetrievalPipeline([], parents, config)
    monkeypatch.setattr(pipeline.bm25, "search", lambda q: hits)
    assert pipeline.context("q") == [parents[i] for i in (2, 0, 1, 3)]
    assert DEFAULT_CONFIG.sibling_articles == 0


def gold_row(key="q", **extra):
    return dict(id=key, question="tìm nghĩa vụ", category="test", priority=True,
                gold_parents=["d_dieu-A_khoan-1"], gold_articles=["d_dieu-A"], **extra)


def test_evaluate_passes_siblings_and_preserves_default():
    parents, hits = example()
    row = gold_row()
    predictions = {"q": hits[:1]}
    baseline = evaluate([row], predictions, parents=parents)
    assert baseline == evaluate([row], predictions, parents=parents, sibling_articles=0)
    assert baseline["questions"]["parent"]["recall@3000"] == 0
    measured = evaluate([row], predictions, parents=parents, sibling_articles=1)
    assert measured["questions"]["parent"]["recall@3000"] == 1


def selection_runs(questions, turns):
    return {str(n): {"metrics": {g: {"parent": {"recall@3000": values[n]}}
                                for g, values in (("questions", questions), ("turns", turns))}}
            for n in range(4)}


@pytest.mark.parametrize("questions,turns,expected", [
    ([.5, .55, .55, .54], [.7, .7, .7, .7], 1),
    ([.5, .51, .51, .50], [.7, .7, .7, .7], 0),
    ([.5, .55, .55, .54], [.7, .68, .7, .7], 0),
    ([.5, .52, .52, .51], [.7, .69, .7, .7], 1),
    ([.5, .5, .5, .5], [.7, .7, .7, .7], 0),
    ([.5, .55, .54, .53], [None, None, None, None], 0),
])
def test_selection(questions, turns, expected):
    assert cli.choose_siblings(selection_runs(questions, turns))["selected"] == expected


@pytest.fixture
def fake_data(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Không được nạp model hay gọi encoder thật")
    monkeypatch.setattr(dense, "ModelEncoder", forbidden)
    monkeypatch.setattr(rerank_module, "ModelScorer", forbidden)
    parents, _ = example()
    chunks = [dict(hit(p), article_id=f"d_dieu-{p['article']}",
                   index_text="tìm nghĩa vụ", body="nghĩa vụ", level="clause",
                   document_id="d", document_number="134/2025/QH15",
                   article=p["article"], clause=p["clause"], point=None) for p in parents]
    gold = [gold_row(), gold_row("turn", scenario_id="s", turn_text="lượt hiện tại")]
    for name, rows in (("data/processed/chunks.jsonl", chunks),
                       ("data/processed/parents.jsonl", parents), ("eval/retrieval.jsonl", gold)):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return tmp_path, chunks, parents, gold


def write_fake_vectors(root, chunks, gold):
    cache = VectorCache(root / ".cache/index", chunks, "jina")
    cache.path.mkdir(parents=True)
    from legal_rag.retrieval.dense import embedding_config
    np.save(cache.path / "vectors.npy", np.ones((len(chunks), 1)), allow_pickle=False)
    write_json(cache.path / "meta.json", dict(key=cache.key, config=embedding_config("jina"),
                                             chunk_ids=[c["chunk_id"] for c in chunks]))
    for row in gold:
        write_json(cache.query_path(row["question"]),
                   dict(key=cache.key, query=row["question"], vector=[1.], encoding_ms=0))
    return cache


@pytest.mark.parametrize("missing", ["documents", "query", "rerank_file", "rerank_pair"])
def test_cli_missing_cache(fake_data, capsys, missing):
    root, chunks, _, gold = fake_data
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
    assert not (root / "runs/t17/siblings.json").exists()


def test_cli_cached_success_and_output_override(fake_data, capsys):
    root, chunks, _, gold = fake_data
    write_fake_vectors(root, chunks, gold)
    path = root / ".cache/rerank/scores.jsonl"
    scorer = cli.CacheOnlyScorer(path)
    path.parent.mkdir(parents=True)
    entries = [dict(key=scorer.pair_key((r["question"], c["index_text"])), score=1, latency_ms=0)
               for r in gold for c in chunks]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    before = path.read_bytes()
    output = root / "runs/custom.json"
    assert cli.main(["--output", str(output)], root=root) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert set(result["runs"]) == {"0", "1", "2", "3"}
    for run in result["runs"].values():
        assert set(run["metrics"]) == {"questions", "turns"}
        for group in run["metrics"].values():
            assert set(group) == {"parent", "article"}
            assert set(group["parent"]) == {"labeled_questions", "recall@1500", "recall@3000",
                                            "recall@6000", "hit@3000"}
    assert "Áp dụng quy tắc" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_changed_label_counts_and_unreachable_stop(fake_data):
    _, chunks, parents, gold = fake_data
    dense_hits = [hit(parents[2])]
    class FakeDense:
        def search(self, query):
            return dense_hits
    # Không dùng điểm/vị trí giả để thay thuật toán: BM25 rỗng vì không có token truy vấn.
    gold = [dict(r, question="zzzz") for r in gold]
    result = cli.run_siblings(chunks, parents, gold, FakeDense(), lambda pairs: [1] * len(pairs))
    assert result["runs"]["1"]["changed_parent_labels_at_3000"] == [
        dict(id="q", group="questions", before=0, after=1),
        dict(id="turn", group="turns", before=0, after=1)]
    gold[0]["gold_parents"] = ["missing"]
    with pytest.raises(ValueError, match="Nhãn không chạm được"):
        cli.run_siblings(chunks, parents, gold, None, None)


def test_experiment_locked_stages_and_exact_promotion(fake_data, monkeypatch):
    _, chunks, parents, gold = fake_data
    events, captured = [], []
    hits = [hit(p) for p in parents]

    class FakeBM25:
        def __init__(self, source, config):
            assert source == chunks
            assert (config.tokenizer, config.accents, config.source) == ("syllable", "both", "index_text")

        def search(self, query):
            events.append("bm25")
            return hits

    class FakeDense:
        def search(self, query):
            events.append("dense")
            return hits

    def fusion(rankings):
        events.append("rrf")
        assert rankings == [hits, hits]
        return hits

    def cap(ranked, source, n):
        events.append("cap")
        assert ranked == hits and source == chunks and n == 3
        return hits

    def rerank(query, ranked, source, scorer, pool):
        events.append("rerank")
        assert ranked == hits and source == chunks and pool == 20 and scorer == "cache"
        return hits

    def exact(query, source):
        events.append("exact")
        return {"results": [dict(hits[1], match_level="document"),
                            dict(hits[-1], match_level="article")]}

    real_evaluate = cli.evaluate

    def measured(rows, predictions, **kwargs):
        captured.append(predictions)
        return real_evaluate(rows, predictions, **kwargs)

    for name, replacement in (("BM25Retriever", FakeBM25), ("rrf", fusion),
                              ("cap_list_items", cap), ("rerank", rerank),
                              ("exact_lookup", exact), ("evaluate", measured)):
        monkeypatch.setattr(cli, name, replacement)
    cli.run_siblings(chunks, parents, gold, FakeDense(), "cache")
    assert events == ["bm25", "dense", "rrf", "cap", "rerank", "exact"] * len(gold)
    for predictions in captured:
        for ranked in predictions.values():
            assert [h["chunk_id"] for h in ranked] == [hits[-1]["chunk_id"],
                                                        *(h["chunk_id"] for h in hits[:-1])]
