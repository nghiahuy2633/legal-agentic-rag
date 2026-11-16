"""Cache chuỗi JSON chuẩn và numpy, không pickle."""

import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from legal_rag.retrieval.dense import embedding_config


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stage_key(previous_key, config):
    return digest({"previous": previous_key, "config": config})


def chunk_key(chunks, config=None):
    return stage_key(digest(chunks), {"stage": "chunk", **(config or {})})


def index_keys(chunks, name, chunk_config=None):
    first = chunk_key(chunks, chunk_config)
    return first, stage_key(first, embedding_config(name))


def write_json(path, value):
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


class VectorCache:
    def __init__(self, root, chunks, name, chunk_config=None):
        self.chunk_key, self.key = index_keys(chunks, name, chunk_config)
        self.path = Path(root) / self.key
        self.chunks, self.name = chunks, name

    def load_documents(self):
        meta_path = self.path / "meta.json"
        if not meta_path.exists() or not (self.path / "vectors.npy").exists():
            raise FileNotFoundError(f"Thiếu cache {self.name}; chạy scripts/build_index.py --model {self.name}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta["key"] != self.key or meta["chunk_ids"] != [c["chunk_id"] for c in self.chunks]
                or meta["config"] != embedding_config(self.name)):
            raise ValueError("Metadata cache vector không khớp")
        vectors = np.load(self.path / "vectors.npy", allow_pickle=False)
        if vectors.ndim != 2 or len(vectors) != len(self.chunks) or not np.isfinite(vectors).all():
            raise ValueError("Cache vector chunk không hợp lệ")
        return vectors

    def build_documents(self, encoder):
        try:
            return self.load_documents()
        except FileNotFoundError:
            pass
        start = perf_counter()
        vectors = np.asarray(encoder.encode_documents([c["index_text"] for c in self.chunks]))
        if vectors.ndim != 2 or len(vectors) != len(self.chunks) or not np.isfinite(vectors).all():
            raise ValueError("Bộ mã hóa trả vector chunk không hợp lệ")
        self.path.mkdir(parents=True, exist_ok=True)
        np.save(self.path / "vectors.npy", vectors, allow_pickle=False)
        write_json(self.path / "meta.json", {
            "key": self.key, "chunk_key": self.chunk_key, "config": embedding_config(self.name),
            "chunk_ids": [c["chunk_id"] for c in self.chunks],
            "encoding_ms": (perf_counter() - start) * 1000,
            "truncated_documents": getattr(encoder, "truncated_documents", 0)})
        return vectors

    def query_path(self, query):
        return self.path / (hashlib.sha256(query.encode("utf-8")).hexdigest() + ".json")

    def load_queries(self, queries):
        vectors, times = {}, {}
        for query in dict.fromkeys(queries):
            path = self.query_path(query)
            if not path.exists():
                raise FileNotFoundError(f"Thiếu vector truy vấn; chạy scripts/build_index.py --model {self.name}")
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["query"] != query or row["key"] != self.key:
                raise ValueError("Cache truy vấn không khớp")
            vectors[query], times[query] = np.asarray(row["vector"], dtype=np.float32), row["encoding_ms"]
        return vectors, times

    def build_queries(self, queries, encoder):
        self.path.mkdir(parents=True, exist_ok=True)
        for query in dict.fromkeys(queries):
            if self.query_path(query).exists():
                self.load_queries([query])
                continue
            start = perf_counter()
            before = getattr(encoder, "truncated_queries", 0)
            vector = np.asarray(encoder.encode_queries([query]))
            elapsed = (perf_counter() - start) * 1000
            if vector.ndim != 2 or len(vector) != 1 or not np.isfinite(vector).all():
                raise ValueError("Bộ mã hóa trả vector truy vấn không hợp lệ")
            write_json(self.query_path(query), {"key": self.key, "query": query,
                       "vector": vector[0].tolist(), "encoding_ms": elapsed,
                       "truncated": getattr(encoder, "truncated_queries", 0) - before})
        return self.load_queries(queries)
