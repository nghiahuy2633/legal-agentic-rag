"""T13: chỉ dùng client, encoder và scorer giả."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata

import numpy as np
import pytest

from legal_rag.generation.citations import check_answer, format_citation
from legal_rag.generation.evidence import build_evidence, format_evidence
from legal_rag.generation.prompt import build_messages
from legal_rag.llm import CachedChat
from legal_rag.retrieval.bm25 import BM25Config
from legal_rag.retrieval import pipeline as module
from legal_rag.retrieval.pipeline import DEFAULT_CONFIG, RetrievalConfig, RetrievalPipeline

ROOT = Path(__file__).resolve().parents[2]


def chunks():
    return [dict(chunk_id=key, parent_id=key, article_id=key, index_text=text,
                 body=text, level="article", document_id="d", document_number="134/2025/QH15",
                 article=str(i + 1), clause=None, point=None)
            for i, (key, text) in enumerate((("a", "hệ thống"), ("b", "rủi ro"), ("c", "nhãn")))]


def parents():
    return [dict(parent_id=c["parent_id"], document_id="d", article=c["article"],
                 clause=None, title="Tiêu đề", text=c["body"]) for c in chunks()]


DOCUMENTS = [dict(document_id="d", document_number="134/2025/QH15",
                  document_title="Luật Trí tuệ nhân tạo", official_source_url="https://example.invalid/source")]


class Encoder:
    def __init__(self):
        self.queries = []

    def encode_queries(self, texts):
        self.queries.extend(texts)
        return np.array([[1., 0.]] * len(texts))


def config(**kwargs):
    return RetrievalConfig(**(dict(bm25=BM25Config("syllable", "both", "index_text"),
                                   dense=(), cap=None, rerank_pool=None, exact_first=False) | kwargs))


def test_chat_cache_is_canonical_persistent_and_payload_sensitive(tmp_path):
    calls = []
    client = SimpleNamespace(complete=lambda payload: calls.append(payload) or "Trả lời")
    payload = {"messages": [{"content": "câu hỏi", "role": "user"}], "temperature": 0}
    cache = CachedChat(client, tmp_path)
    assert cache.complete(payload) == "Trả lời"
    assert cache.complete(dict(reversed(list(payload.items())))) == "Trả lời"
    assert (cache.request_count, cache.cache_hits, len(calls)) == (1, 1, 1)
    cache = CachedChat(client, tmp_path)
    assert cache.complete(payload) == "Trả lời"
    assert (cache.request_count, cache.cache_hits) == (0, 1)
    for change in ({"temperature": 1}, {"model": "khác"}, {"messages": []}):
        cache.complete(payload | change)
    assert len(calls) == 4
    key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()
    assert json.loads((tmp_path / (key + ".json")).read_text(encoding="utf-8")) == "Trả lời"
    assert all("api_key" not in p.read_text(encoding="utf-8") for p in tmp_path.iterdir())


def test_cache_does_not_store_failed_calls(tmp_path):
    def fail(payload):
        raise RuntimeError("thử lỗi")
    chat = CachedChat(SimpleNamespace(complete=fail), tmp_path)
    with pytest.raises(RuntimeError):
        chat.complete({})
    assert chat.request_count == 1
    assert list(tmp_path.iterdir()) == []


def test_pipeline_stage_order_multiple_dense_and_dedup(monkeypatch):
    events = []
    hits = [dict(chunk_id=c["chunk_id"], parent_id=c["parent_id"], score=1) for c in chunks()]
    monkeypatch.setattr(module.BM25Retriever, "search", lambda self, q: events.append("bm25") or hits)
    encoders = {}
    for name in ("jina", "viet"):
        encoders[name] = SimpleNamespace(encode_queries=lambda texts, n=name:
                                        events.append("encode_" + n) or np.array([[1., 0.]]))
    real_dense = module.DenseRetriever.search
    monkeypatch.setattr(module.DenseRetriever, "search", lambda self, q:
                        events.append("dense") or real_dense(self, q))
    def fusion(rankings):
        events.append("rrf")
        assert len(rankings) == 3
        return hits
    def cap(h, c, n):
        events.append("cap")
        assert n == 1
        return list(reversed(h))
    def rerank(q, h, c, scorer, pool, cache=None):
        events.append("rerank")
        assert h == list(reversed(hits)) and pool == 2
        return h
    monkeypatch.setattr(module, "rrf", fusion)
    monkeypatch.setattr(module, "cap_list_items", cap)
    monkeypatch.setattr(module, "rerank", rerank)
    monkeypatch.setattr(module, "exact_lookup", lambda q, c: events.append("exact") or {
        "results": [dict(hits[0], match_level="article"), dict(hits[1], match_level="document")]})
    pipeline = RetrievalPipeline(chunks(), parents(), config(dense=("jina", "viet"), cap=1,
                                rerank_pool=2, exact_first=True), encoders,
                                {n: np.ones((3, 2)) for n in encoders}, scorer=object())
    assert [h["chunk_id"] for h in pipeline.search("q")] == ["a", "c", "b"]
    assert events == ["encode_jina", "encode_viet", "bm25", "dense", "dense", "rrf", "cap", "rerank", "exact"]
    assert all(row["query_ms"] >= 0 for row in pipeline.last_timing.values())


def test_single_source_skips_rrf_and_context_uses_budget(monkeypatch):
    monkeypatch.setattr(module, "rrf", lambda *a: pytest.fail("Không được fusion một nguồn"))
    pipeline = RetrievalPipeline(chunks(), parents(), config())
    hits = [dict(chunk_id=c["chunk_id"], parent_id=c["parent_id"]) for c in chunks()]
    monkeypatch.setattr(pipeline.bm25, "search", lambda q: hits)
    assert pipeline.search("q") == hits
    assert pipeline.context("q", budget=0) == parents()[:1]
    assert "rrf" not in pipeline.last_timing
    assert "context" in pipeline.last_timing


def test_dense_queries_encoded_directly_and_documents_loaded_once(monkeypatch):
    encoder, loads = Encoder(), []
    monkeypatch.setattr(module.VectorCache, "load_documents",
                        lambda self: loads.append(self.name) or np.ones((3, 2)))
    monkeypatch.setattr(module.VectorCache, "load_queries", lambda *a: pytest.fail("Cache đánh giá"))
    monkeypatch.setattr(module, "ModelEncoder", lambda name: encoder)
    pipeline = RetrievalPipeline(chunks(), parents(), config(dense=("viet",)))
    assert loads == [] and pipeline.encoders == {}
    pipeline.search("mới")
    pipeline.search("mới")
    assert loads == ["viet"] and encoder.queries == ["mới"]


def test_missing_cache_fails_before_loading_encoder(monkeypatch):
    def missing(self):
        raise FileNotFoundError("Thiếu cache viet")
    monkeypatch.setattr(module.VectorCache, "load_documents", missing)
    monkeypatch.setattr(module, "ModelEncoder", lambda n: pytest.fail("Không nạp model"))
    pipeline = RetrievalPipeline(chunks(), parents(), DEFAULT_CONFIG)
    with pytest.raises(FileNotFoundError, match="Thiếu cache"):
        pipeline.search("q")


def test_real_rerank_with_fake_scorer():
    encoder = Encoder()
    pairs = []
    def scorer(inputs):
        pairs.extend(inputs)
        return [0, 2]
    pipeline = RetrievalPipeline(chunks(), parents(), config(dense=("viet",), rerank_pool=2),
                                 {"viet": encoder}, {"viet": np.array([[3., 0], [2., 0], [1., 0]])}, scorer)
    assert [h["chunk_id"] for h in pipeline.search("không khớp")] == ["b", "a", "c"]
    assert pairs == [("không khớp", "hệ thống"), ("không khớp", "rủi ro")]


def test_evidence_order_extra_and_list_item():
    listing = dict(parent_id="list", document_id="d", article=None, clause=None,
                   title="Danh mục robot phẫu thuật", text="Nội dung danh mục")
    items = build_evidence(list(reversed(parents())), DOCUMENTS, extra=[listing])
    assert [i["id"] for i in items] == ["E1", "E2", "E3", "E4"]
    assert [i["parent_id"] for i in items] == ["c", "b", "a", "list"]
    assert items[0]["article_title"] == "Tiêu đề"
    assert "Danh mục robot phẫu thuật" in format_citation(items[-1])
    assert DOCUMENTS[0]["official_source_url"] in format_citation(items[-1])
    assert "Điều" not in format_citation(items[-1])
    assert "[E4]" in format_evidence(items)
    assert "Khoản 2" in format_citation(items[0] | {"clause": "2"})


@pytest.fixture
def evidence():
    return build_evidence([parents()[0] | {"article": "9", "text": "Theo Điều 11, áp dụng 10 triệu đồng."}], DOCUMENTS)


@pytest.mark.parametrize("answer,valid", [
    ("Áp dụng [E9]", False),
    ("Có nghĩa vụ minh bạch.", False),
    ("Không có căn cứ để trả lời.", True),
    ("Câu hỏi ngoài phạm vi.", True),
    ("Theo Điều 40 [E1]", False),
    ("Theo Điều 9 [E1]", True),
    ("Theo Điều 11 [E1]", True),
    ("Theo 13/2023/NĐ-CP [E1]", False),
    ("Theo 134/2025/QH15 [E1]", True),
    ("Phạt 50 triệu đồng [E1]", False),
    ("10 triệu đồng [E1]", True),
    ("Phạt 50.000.000 đồng [E1]", False),
])
def test_citation_cases(answer, valid, evidence):
    assert check_answer(answer, evidence)["valid"] is valid
    assert check_answer(unicodedata.normalize("NFD", answer.upper()), evidence)["valid"] is valid


def test_citation_document_references_and_used_order(evidence):
    evidence[0]["text"] += " Nghị định 13/2023/NĐ-CP."
    result = check_answer("Điều 11, 13/2023/NĐ-CP [E1] [e1]", evidence)
    assert result == {"valid": True, "errors": [], "used": ["E1"], "warnings": []}


def test_prompt_version_and_temperature(tmp_path, monkeypatch, evidence):
    payload = build_messages("Câu hỏi rộng", evidence)
    assert payload["temperature"] == 0
    assert payload["messages"][0]["content"].startswith("Phiên bản: answer_v9\n")
    assert build_messages("q", [], version="answer_v1")["messages"][0]["content"].startswith(
        "Phiên bản: answer_v1\n")
    assert "[E1]" in payload["messages"][1]["content"]
    from legal_rag.generation import prompt
    path = tmp_path / "answer_v9.txt"
    path.write_text("Phiên bản: answer_v1", encoding="utf-8")
    monkeypatch.setattr(prompt, "PROMPT_DIR", tmp_path)
    with pytest.raises(ValueError, match="phiên bản"):
        build_messages("q", [])


def load_ask():
    spec = importlib.util.spec_from_file_location("ask_t13", ROOT / "scripts/ask.py")
    ask = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ask)
    return ask


def cli_root(tmp_path):
    for name, rows in (("chunks", chunks()), ("parents", parents()), ("references", [])):
        path = tmp_path / f"data/processed/{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    path = tmp_path / "data/source_registry/documents.csv"
    path.parent.mkdir(parents=True)
    import csv
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(DOCUMENTS[0]))
        writer.writeheader()
        writer.writerows(DOCUMENTS)
    return tmp_path


class FakePipeline:
    config = config()
    last_timing = {"bm25": {"query_ms": 0.1}}

    def __init__(self, chunks, units):
        self.units = units

    def context(self, query, budget):
        assert query == "q" and budget == 123
        return self.units[:1]


def test_cli_evidence_only_never_constructs_llm_or_reads_settings(tmp_path, monkeypatch, capsys):
    ask = load_ask()
    monkeypatch.setattr(ask, "get_llm_settings", lambda: pytest.fail("Không đọc LLM config"))
    def forbidden(*args):
        pytest.fail("Không tạo client")
    assert ask.main(["--query", "q", "--budget", "123", "--evidence-only"],
                    cli_root(tmp_path), FakePipeline, forbidden) == 0
    output = capsys.readouterr().out
    assert "[E1]" in output and '"llm_calls": 0' in output


def test_cli_fake_answer_and_cache(tmp_path, monkeypatch, capsys):
    ask, calls = load_ask(), []
    monkeypatch.setattr(ask, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://example.invalid", api_key="secret", model="fake"))
    def client(url, key):
        return SimpleNamespace(complete=lambda payload: calls.append(payload) or "Nội dung [E1]")
    root = cli_root(tmp_path)
    for _ in range(2):
        assert ask.main(["--query", "q", "--budget", "123"], root, FakePipeline, client) == 0
    output = capsys.readouterr().out
    assert len(calls) == 1 and calls[0]["temperature"] == 0
    assert '"valid": true' in output and '"cache_hits": 1' in output
    assert "secret" not in output


def test_cli_missing_configuration_and_cache_are_clear(tmp_path, monkeypatch, capsys):
    ask = load_ask()
    def missing():
        raise ValueError("Thiếu biến môi trường: RAG_LLM_MODEL")
    monkeypatch.setattr(ask, "get_llm_settings", missing)
    assert ask.main(["--query", "q"], tmp_path) == 1
    assert "RAG_LLM_MODEL" in capsys.readouterr().err
    def missing_cache(*args):
        raise FileNotFoundError("secret")
    assert ask.main(["--query", "q", "--evidence-only"], cli_root(tmp_path), missing_cache) == 1
    error = capsys.readouterr().err
    assert "build_index.py --model jina" in error and "secret" not in error
