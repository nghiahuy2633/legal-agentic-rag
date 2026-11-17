"""Công tắc các thành phần của agent."""

from dataclasses import dataclass

# Ngân sách ngữ cảnh (token ước lượng) cho basic và full; chọn theo điểm gãy recall (T58).
DEFAULT_CONTEXT_BUDGET = 8000
# Tối đa số truy vấn mỗi lượt truy xuất: truy vấn con, câu gốc (T59) và truy vấn viết lại.
MAX_QUERIES = 6


@dataclass(frozen=True)
class AgentConfig:
    enable_references: bool = False
    enable_navigation: bool = True
    reference_budget: int = 1500
    reference_top_units: int = 5
    enable_rewrite: bool = True
    enable_obligations: bool = True
    enable_verifier: bool = True
    enable_high_risk: bool = True
    extra_budget: int = 1500
    budget: int = DEFAULT_CONTEXT_BUDGET
    rerank_mode: str = "message"
    accept_ai_reviewed: bool = True
    analyze_prompt: str = "analyze_v7"
    grade_prompt: str = "grade_v3"
    max_rewrites: int = 1
    verifier_mode: str = "rule"

    def __post_init__(self):
        if self.analyze_prompt not in ("analyze_v2", "analyze_v3", "analyze_v4", "analyze_v5", "analyze_v6", "analyze_v7"):
            raise ValueError("analyze_prompt phải là analyze_v2, analyze_v3, analyze_v4, analyze_v5, analyze_v6 hoặc analyze_v7")
        if self.grade_prompt not in ("grade_v1", "grade_v2", "grade_v3"):
            raise ValueError("grade_prompt phải là grade_v1, grade_v2 hoặc grade_v3")
        if type(self.max_rewrites) is not int or not 0 <= self.max_rewrites <= 2:
            raise ValueError("max_rewrites phải là số nguyên từ 0 đến 2")
        if self.verifier_mode not in ("rule", "rule_llm"):
            raise ValueError("verifier_mode phải là rule hoặc rule_llm")
        if type(self.budget) is not int or self.budget < 0:
            raise ValueError("budget phải là số nguyên không âm")
        if type(self.extra_budget) is not int or self.extra_budget < 0:
            raise ValueError("extra_budget phải là số nguyên không âm")
        if self.rerank_mode not in ("message", "joined", "first"):
            raise ValueError("rerank_mode phải là message, joined hoặc first")
