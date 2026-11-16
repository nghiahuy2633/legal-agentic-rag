"""T58: basic và full dùng cùng ngân sách ngữ cảnh 8000 token."""
from legal_rag.agent.config import AgentConfig, DEFAULT_CONTEXT_BUDGET


def test_default_budget_is_8000_and_shared():
    assert DEFAULT_CONTEXT_BUDGET == 8000
    assert AgentConfig().budget == DEFAULT_CONTEXT_BUDGET
