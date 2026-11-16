"""Bộ mã hóa CPU nạp lười và tra vector đã tính; không đọc dữ liệu đánh giá."""

from typing import Protocol

import numpy as np

MODELS = {
    "jina": {"model": "jinaai/jina-embeddings-v3",
             "revision": "ab036b023d30b4d1138c4c3bfa9f0c445ab455d6"},
    "viet": {"model": "AITeamVN/Vietnamese_Embedding_v2",
             "revision": "18b44161e041bf1d3a333ab5144b5b7b93f914d2"},
}


class Encoder(Protocol):
    def encode_documents(self, texts: list[str]) -> np.ndarray: ...
    def encode_queries(self, texts: list[str]) -> np.ndarray: ...


def embedding_config(name):
    return dict(MODELS[name], encoder=name, source="index_text", device="cpu",
                max_length=512 if name == "viet" else None,
                pooling="cls_l2" if name == "viet" else "retrieval_tasks", version=1)


class ModelEncoder:
    def __init__(self, name, batch_size=8):
        if name not in MODELS:
            raise ValueError("model phải là jina hoặc viet")
        if batch_size <= 0:
            raise ValueError("batch_size phải dương")
        self.name, self.batch_size = name, batch_size
        self.model = self.tokenizer = None
        self.truncated_documents = self.truncated_queries = 0

    def _load(self):
        if self.model is not None:
            return
        from transformers import AutoModel, AutoTokenizer
        config = MODELS[self.name]
        self.model = AutoModel.from_pretrained(config["model"], revision=config["revision"],
                                              trust_remote_code=self.name == "jina")
        self.model.to("cpu").eval()
        if self.name == "viet":
            self.tokenizer = AutoTokenizer.from_pretrained(config["model"], revision=config["revision"])

    def _encode(self, texts, documents):
        if not texts:
            raise ValueError("Danh sách mã hóa phải có ít nhất một văn bản")
        self._load()
        import torch
        if self.name == "jina":
            with torch.inference_mode():
                result = self.model.encode(texts, task="retrieval.passage" if documents else "retrieval.query")
            if hasattr(result, "detach"):
                result = result.detach().cpu().numpy()
            return np.asarray(result, dtype=np.float32)
        outputs, truncated = [], 0
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            lengths = self.tokenizer(batch, truncation=False, padding=False)["input_ids"]
            truncated += sum(len(ids) > 512 for ids in lengths)
            inputs = self.tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            with torch.inference_mode():
                cls = self.model(**inputs).last_hidden_state[:, 0]
                outputs.append(torch.nn.functional.normalize(cls, p=2, dim=1).cpu().numpy())
        if documents:
            self.truncated_documents += truncated
        else:
            self.truncated_queries += truncated
        return np.concatenate(outputs).astype(np.float32)

    def encode_documents(self, texts):
        return self._encode(texts, True)

    def encode_queries(self, texts):
        return self._encode(texts, False)


class DenseRetriever:
    def __init__(self, chunks, vectors, query_vectors):
        self.chunks = list(chunks)
        self.vectors = np.asarray(vectors)
        self.query_vectors = query_vectors
        if self.vectors.ndim != 2 or len(self.vectors) != len(chunks):
            raise ValueError("Vector phải là ma trận có một dòng cho mỗi chunk")
        if not np.isfinite(self.vectors).all():
            raise ValueError("Vector chứa giá trị không hữu hạn")

    def search(self, query, limit=None):
        if limit is not None and limit < 0:
            raise ValueError("limit phải không âm")
        if query not in self.query_vectors:
            raise ValueError(f"Thiếu vector truy vấn đã mã hóa: {query!r}")
        vector = np.asarray(self.query_vectors[query])
        if vector.shape != (self.vectors.shape[1],) or not np.isfinite(vector).all():
            raise ValueError("Vector truy vấn sai chiều hoặc không hữu hạn")
        scores = self.vectors @ vector
        order = sorted(range(len(self.chunks)), key=lambda i: (-float(scores[i]), self.chunks[i]["chunk_id"]))
        return [dict(chunk_id=self.chunks[i]["chunk_id"], parent_id=self.chunks[i]["parent_id"],
                     article_id=self.chunks[i].get("article_id"), score=float(scores[i]))
                for i in order[:limit]]
