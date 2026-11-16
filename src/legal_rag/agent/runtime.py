"""Dựng agent dùng chung cho CLI chat và bộ đánh giá."""

import csv
import json
from pathlib import Path

from legal_rag.agent.answer import prepare_evidence
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph
from legal_rag.config import get_llm_settings
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, OfflineClient
from legal_rag.retrieval.pipeline import RetrievalPipeline


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def build_agent(root, config=AgentConfig(), client_factory=HTTPChatClient,
                pipeline_factory=RetrievalPipeline, pipeline=None, chat_wrapper=None, settings=None):
    root = Path(root)
    settings = settings if settings is not None else get_llm_settings()
    parents = read_jsonl(root / "data/processed/parents.jsonl")
    references = read_jsonl(root / "data/processed/references.jsonl")
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))

    def make_pipeline():
        nonlocal pipeline
        if pipeline is None:
            pipeline = pipeline_factory(read_jsonl(root / "data/processed/chunks.jsonl"), parents)
        return pipeline

    fallback = getattr(settings, "fallback_models", ())
    client = OfflineClient() if getattr(settings, "offline", False) else (
              client_factory(settings.base_url, settings.api_key, max_attempts=3)
              if fallback else client_factory(settings.base_url, settings.api_key))
    chat = FallbackChat(CachedChat(client, root / ".cache/llm"), fallback)
    if chat_wrapper is not None:
        chat = chat_wrapper(chat)
    prepare = prepare_evidence(make_pipeline, parents, documents,
        chunks_loader=lambda: read_jsonl(root / "data/processed/chunks.jsonl"),
        references=references, config=config)

    graph = build_graph(GraphDeps(chat, settings.model, prepare, config=config,
        pipeline_factory=make_pipeline, parents=parents, documents=documents,
        chunks_loader=lambda: read_jsonl(root / "data/processed/chunks.jsonl"),
        high_risk_loader=lambda: read_jsonl(root / "data/processed/high_risk_list.jsonl"),
        obligations_loader=lambda: load_obligations(
            Path(__file__).resolve().parents[1] / "knowledge/obligations.yaml")))
    return graph, chat, settings
