"""Trạng thái được checkpoint; client chỉ nằm trong runtime của lượt."""

from dataclasses import dataclass
from typing import TypedDict

from legal_rag.agent.budget import BudgetChat


class AgentState(TypedDict, total=False):
    profile: dict
    profile_override: dict | None
    facts_override: dict | None
    request_plan: dict | None
    applicability_bases: list[dict]
    context: dict | None
    pinned_parents: list[str]
    messages: list[dict]
    last_parents: list[str]
    followup_asked: bool
    verification: dict | None
    message: str
    analysis: dict | None
    answer: str | None
    high_risk: dict | None
    high_risk_error: str | None
    high_risk_items: list[dict]
    map_obligations: dict | None
    extra_tokens: int
    reply: str | None
    evidence: list[dict]
    check: dict | None
    route: str | None
    error: str | None
    trace: list[dict]
    prepared: dict | None
    grade: dict | None
    rewritten: list[str]
    retrieved_parents: list[str]
    retrieval_count: int
    new_parent_count: int
    rewrite_stop_reason: str | None
    rewrites: int
    llm_messages: list[dict]
    prompt_version: str | None


@dataclass
class TurnContext:
    chat: BudgetChat | None = None


def turn_input(message):
    return dict(message=message, facts_override=None, request_plan=None, applicability_bases=[],
                analysis=None, answer=None, high_risk=None, high_risk_error=None,
                high_risk_items=[], map_obligations=None, extra_tokens=0, reply=None, evidence=[], check=None, verification=None,
                route=None, error=None, trace=[], prompt_version=None, prepared=None, grade=None,
                rewritten=[], rewrites=0, llm_messages=[], retrieved_parents=[],
                retrieval_count=0, new_parent_count=0, rewrite_stop_reason=None)
