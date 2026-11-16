"""Pipeline truy xuất runtime, độc lập dữ liệu và cache truy vấn đánh giá."""

from dataclasses import dataclass
from time import perf_counter

from legal_rag.retrieval.bm25 import BM25Config, BM25Retriever
from legal_rag.retrieval.cache import VectorCache
from legal_rag.retrieval.context import select_context
from legal_rag.retrieval.dense import MODELS, DenseRetriever, ModelEncoder
from legal_rag.retrieval.exact import exact_lookup
from legal_rag.retrieval.fusion import cap_list_items, rrf
from legal_rag.retrieval.rerank import ModelScorer, ScoreLRU, rerank


@dataclass(frozen=True)
class RetrievalConfig:
    bm25: BM25Config
    dense: tuple[str, ...]
    cap: int | None
    rerank_pool: int | None
    exact_first: bool
    sibling_articles: int = 0

    def __post_init__(self):
        if not isinstance(self.bm25, BM25Config):
            raise ValueError("bm25 phải là BM25Config")
        if not isinstance(self.dense, tuple) or any(n not in MODELS for n in self.dense):
            raise ValueError("dense phải là tuple tên model trong MODELS")
        if len(set(self.dense)) != len(self.dense):
            raise ValueError("dense không được trùng model")
        for value in (self.cap, self.rerank_pool):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("cap và rerank_pool phải là số nguyên không âm hoặc None")
        if not isinstance(self.exact_first, bool):
            raise ValueError("exact_first phải là bool")
        if type(self.sibling_articles) is not int or self.sibling_articles < 0:
            raise ValueError("sibling_articles phải là số nguyên không âm")


DEFAULT_CONFIG = RetrievalConfig(BM25Config("syllable", "both", "index_text"),
                                 ("jina",), 3, 20, True)


class RetrievalPipeline:
    def __init__(self, chunks, parents, config=DEFAULT_CONFIG, encoders=None,
                 vectors=None, scorer=None, cache_enabled=True, rerank_cache_size=5000,
                 batch_queries=True):
        self.chunks = list(chunks)
        self.parents = parents
        self.config = config
        self.encoders = dict(encoders or {})
        self.vectors = dict(vectors or {})
        self.scorer = scorer
        self.bm25 = BM25Retriever(self.chunks, config.bm25)
        self.last_detail = {}
        self.last_timing = {}
        self.cache_enabled = cache_enabled
        self.batch_queries = batch_queries
        self.query_vectors = {}
        self.score_cache = ScoreLRU(rerank_cache_size)

    def _measure(self, name, operation):
        start = perf_counter()
        try:
            return operation()
        finally:
            self.last_timing[name] = {"query_ms": (perf_counter() - start) * 1000}

    def _encode_queries(self, name, queries):
        if name not in self.vectors:
            self.vectors[name] = VectorCache(".cache/index", self.chunks, name).load_documents()
        if name not in self.encoders:
            self.encoders[name] = ModelEncoder(name)
        missing = [q for q in queries if not self.cache_enabled or (name, q) not in self.query_vectors]
        def encode():
            if self.batch_queries:
                return self.encoders[name].encode_queries(missing)
            return [self.encoders[name].encode_queries([q])[0] for q in missing]
        if missing:
            encoded = self._measure("encode_" + name, encode)
            if len(encoded) != len(missing):
                raise ValueError("Bộ mã hóa phải trả đúng một vector mỗi truy vấn")
            fresh = dict(zip(missing, encoded))
            if self.cache_enabled:
                self.query_vectors.update({(name, q): v for q, v in fresh.items()})
        else:
            fresh = {}
            self.last_timing["encode_" + name] = {"query_ms": 0.0}
        return {q: fresh[q] if q in fresh else self.query_vectors[name, q] for q in queries}

    def search(self, query):
        return self.search_many([query], query)

    def search_many(self, queries, rerank_query):
        queries = list(dict.fromkeys(queries))
        if not queries:
            raise ValueError("Cần ít nhất một truy vấn")
        self.last_timing = {}
        self.last_detail = dict(queries=queries, rerank_query=rerank_query,
                                retrieval=[], rrf=[], rerank=[], exact=[])
        start = perf_counter()

        def brief(hits):
            return [dict(chunk_id=h["chunk_id"], score=h.get("score")) for h in hits[:10]]

        rankings = []
        encoded = {name: self._encode_queries(name, queries) for name in self.config.dense}
        for i, query in enumerate(queries):
            prefix = "" if len(queries) == 1 else f"q{i+1}_"
            bm25 = self._measure(prefix + "bm25", lambda: self.bm25.search(query))
            detail = dict(query=query, bm25=brief(bm25), dense={})
            rankings.append(bm25)
            for name in self.config.dense:
                hits = self._measure(prefix + "dense_" + name, lambda: DenseRetriever(
                    self.chunks, self.vectors[name], encoded[name]).search(query))
                detail["dense"][name] = brief(hits)
                rankings.append(hits)
            self.last_detail["retrieval"].append(detail)
        hits = self._measure("rrf", lambda: rrf(rankings)) if len(rankings) > 1 else rankings[0]
        self.last_detail["rrf"] = brief(hits)
        if self.config.cap is not None:
            hits = self._measure("cap", lambda: cap_list_items(hits, self.chunks, self.config.cap))
        if self.config.rerank_pool is not None:
            if self.scorer is None:
                self.scorer = ModelScorer()
            hits = self._measure("rerank", lambda: rerank(
                rerank_query, hits, self.chunks, self.scorer, self.config.rerank_pool,
                self.score_cache if self.cache_enabled else None))
            self.last_timing["rerank"].update(
                new_pairs=self.score_cache.new_pairs if self.cache_enabled else min(len(hits), self.config.rerank_pool),
                cached_pairs=self.score_cache.cached_pairs if self.cache_enabled else 0)
        self.last_detail["rerank"] = brief(hits)
        exact_hits = []
        if self.config.exact_first:
            for i, query in enumerate(queries):
                name = "exact" if len(queries) == 1 else f"q{i+1}_exact"
                exact = self._measure(name, lambda: exact_lookup(query, self.chunks))
                exact_hits.extend(h for h in exact["results"] if h.get("match_level") == "article")
        self.last_detail["exact"] = list({h["chunk_id"]: dict(chunk_id=h["chunk_id"], score=h.get("score"))
                                          for h in exact_hits}.values())
        seen, result = set(), []
        for hit in exact_hits + hits:
            if hit["chunk_id"] not in seen:
                seen.add(hit["chunk_id"])
                result.append(hit)
        self.last_timing["total"] = {"query_ms": (perf_counter() - start) * 1000}
        return result

    def context_many(self, queries, rerank_query, budget=3000):
        hits = self.search_many(queries, rerank_query)
        units, _ = self._measure("context", lambda: select_context(
            hits, self.parents, budget, self.config.sibling_articles))
        self.last_timing["total"]["query_ms"] += self.last_timing["context"]["query_ms"]
        return units

    def context(self, query, budget=3000):
        hits = self.search(query)
        units, _ = self._measure("context", lambda: select_context(
            hits, self.parents, budget, self.config.sibling_articles))
        self.last_timing["total"]["query_ms"] += self.last_timing["context"]["query_ms"]
        return units
