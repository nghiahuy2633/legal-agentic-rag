"""Ghép hai giai đoạn để kiểm hồi quy RAG mà không chạy đồ thị."""

from dataclasses import replace
from legal_rag.agent.answer import prepare_evidence, generate_answer
from legal_rag.agent.config import AgentConfig


def composed_answer(factory, parents, documents, budget=None, config=AgentConfig(), **kwargs):
    if budget is not None:
        config = replace(config, budget=budget)
    prepare = prepare_evidence(factory, parents, documents, config=config, **kwargs)
    def answer(message, queries, profile, chat, model, *, last_parents=()):
        prepared = prepare(message, queries, last_parents=last_parents)
        if prepared["prompt_version"] == "answer_v9":
            prepared["prompt_version"] = "answer_v8"
        return generate_answer(message, queries, profile, prepared, chat, model)
    return answer
