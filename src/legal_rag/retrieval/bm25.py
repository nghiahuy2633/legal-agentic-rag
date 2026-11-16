"""BM25 trong bộ nhớ, không cache chỉ mục trên đĩa."""

from dataclasses import dataclass
import re
import unicodedata

from rank_bm25 import BM25Okapi

from legal_rag.retrieval.exact import fold


@dataclass(frozen=True)
class BM25Config:
    tokenizer: str = "pyvi"
    accents: str = "keep"
    source: str = "index_text"

    def __post_init__(self):
        if self.tokenizer not in {"syllable", "pyvi"}:
            raise ValueError("tokenizer phải là syllable hoặc pyvi")
        if self.accents not in {"keep", "both"}:
            raise ValueError("accents phải là keep hoặc both")
        if self.source not in {"body", "index_text"}:
            raise ValueError("source phải là body hoặc index_text")


def tokenize(text: str, config: BM25Config) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    if config.tokenizer == "pyvi":
        from pyvi import ViTokenizer
        text = ViTokenizer.tokenize(text)
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    if config.accents == "both":
        # Một token không dấu cho mỗi âm tiết: truy vấn không dấu vẫn khớp
        # khi pyvi chia từ khác nhau giữa câu có dấu và không dấu.
        tokens += ["fold:" + fold(t) for t in re.findall(r"[^\W_]+", text, re.UNICODE)]
    return tokens


class BM25Retriever:
    def __init__(self, chunks: list[dict], config: BM25Config = BM25Config()):
        self.config = config
        self.chunks = sorted(chunks, key=lambda c: c["chunk_id"])
        corpus = [tokenize(c[config.source], config) for c in self.chunks]
        self.index = BM25Okapi(corpus) if any(corpus) else None

    def search(self, query: str, limit: int | None = None) -> list[dict]:
        if limit is not None and limit < 0:
            raise ValueError("limit phải không âm")
        if self.index is None:
            return []
        scores = self.index.get_scores(tokenize(query, self.config))
        ranked = sorted(range(len(self.chunks)), key=lambda i: (-scores[i], self.chunks[i]["chunk_id"]))
        return [{"chunk_id": self.chunks[i]["chunk_id"], "parent_id": self.chunks[i]["parent_id"],
                 "article_id": self.chunks[i].get("article_id"), "score": float(scores[i])}
                for i in ranked[:limit] if scores[i] > 0]
