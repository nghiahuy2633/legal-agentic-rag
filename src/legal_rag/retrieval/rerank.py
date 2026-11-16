"""Reranker nạp lười, cache từng cặp cùng thời gian chấm thật."""

import json
from collections import OrderedDict
from pathlib import Path
from time import perf_counter

import numpy as np

from legal_rag.retrieval.cache import canonical_json, digest

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


class ModelScorer:
    def __init__(self, batch_size=8):
        if batch_size <= 0:
            raise ValueError("batch_size phải dương")
        self.batch_size = batch_size
        self.model = self.tokenizer = None

    def score(self, pairs):
        if not pairs:
            return []
        if self.model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
            self.model = AutoModelForSequenceClassification.from_pretrained(MODEL, revision=REVISION)
            self.model.to("cpu").eval()
        import torch
        scores = []
        for start in range(0, len(pairs), self.batch_size):
            inputs = self.tokenizer(pairs[start:start + self.batch_size], padding=True, truncation=True,
                                    max_length=512, return_tensors="pt")
            with torch.inference_mode():
                scores.extend(self.model(**inputs).logits.reshape(-1).cpu().tolist())
        return scores


class CachedScorer:
    """scorer chỉ được gọi cho cặp chưa có; khởi tạo không nạp model."""

    def __init__(self, path, scorer=None, model=MODEL, revision=REVISION):
        self.path, self.scorer = Path(path), scorer
        self.model, self.revision = model, revision
        self.entries = {}
        self.last_latency_ms = 0.0
        self.last_call_wall_ms = 0.0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.entries[row["key"]] = row

    def pair_key(self, pair):
        return digest({"model": self.model, "revision": self.revision,
                       "query": pair[0], "text": pair[1], "max_length": 512})

    def score(self, pairs):
        call_start = perf_counter()
        missing = {self.pair_key(p): p for p in pairs if self.pair_key(p) not in self.entries}
        if missing:
            if self.scorer is None:
                self.scorer = ModelScorer()
            # Đo riêng từng cặp để cache chứa thời gian của đúng cặp đó.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                for key, pair in missing.items():
                    start = perf_counter()
                    scores = score_pairs(self.scorer, [pair])
                    row = {"key": key, "model": self.model, "revision": self.revision,
                           "score": scores[0], "latency_ms": (perf_counter() - start) * 1000}
                    stream.write(canonical_json(row) + "\n")
                    self.entries[key] = row
        self.last_latency_ms = sum(self.entries[self.pair_key(p)]["latency_ms"] for p in pairs)
        self.last_call_wall_ms = (perf_counter() - call_start) * 1000
        return [self.entries[self.pair_key(p)]["score"] for p in pairs]


def score_pairs(scorer, pairs):
    values = list(scorer.score(pairs) if hasattr(scorer, "score") else scorer(pairs))
    if len(values) != len(pairs) or not np.isfinite(values).all():
        raise ValueError("scorer phải trả một điểm hữu hạn cho mỗi cặp")
    return [float(value) for value in values]


class ScoreLRU:
    """Điểm runtime trong RAM, thuộc một pipeline có corpus/scorer cố định."""

    def __init__(self, capacity=5000):
        if type(capacity) is not int or capacity < 0:
            raise ValueError("capacity phải là số nguyên không âm")
        self.capacity = capacity
        self.entries = OrderedDict()
        self.new_pairs = self.cached_pairs = 0

    def score(self, query, head, lookup, scorer):
        keys = [(query, hit["chunk_id"]) for hit in head]
        found = {}
        for key in keys:
            if key in self.entries:
                found[key] = self.entries[key]
                self.entries.move_to_end(key)
        missing = list(dict.fromkeys(key for key in keys if key not in found))
        scores = score_pairs(scorer, [(query, lookup[key[1]]["index_text"]) for key in missing]) if missing else []
        self.new_pairs, self.cached_pairs = len(missing), len(keys) - len(missing)
        found.update(zip(missing, scores))
        for key in missing:
            if self.capacity:
                self.entries[key] = found[key]
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
        return [found[key] for key in keys]


def rerank(query, hits, chunks, scorer, pool, cache=None):
    if pool < 0:
        raise ValueError("pool phải không âm")
    lookup = chunks if isinstance(chunks, dict) else {c["chunk_id"]: c for c in chunks}
    head = hits[:pool]
    if not head:
        if cache is not None:
            cache.new_pairs = cache.cached_pairs = 0
        return list(hits)
    scores = (cache.score(query, head, lookup, scorer) if cache is not None else
              score_pairs(scorer, [(query, lookup[h["chunk_id"]]["index_text"]) for h in head]))
    ranked = [dict(h, score=score) for h, score in zip(head, scores)]
    return sorted(ranked, key=lambda h: (-h["score"], h["chunk_id"])) + list(hits[pool:])
