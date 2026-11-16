"""Ngân sách lời gọi logic, độc lập với cache và model dự phòng."""

from legal_rag.llm import LLMError

MAX_LLM_CALLS_PER_TURN = 8


class LLMBudgetExceeded(LLMError):
    pass


class BudgetChat:
    def __init__(self, chat, limit=MAX_LLM_CALLS_PER_TURN):
        self.chat = chat
        self.limit = limit
        self.reset()

    def reset(self):
        self.calls = 0
        self.history = []

    @property
    def last_model(self):
        return getattr(self.chat, "last_model", None)

    @property
    def attempts(self):
        return getattr(self.chat, "attempts", [])

    def complete(self, payload):
        if self.calls >= self.limit:
            raise LLMBudgetExceeded("Đã hết ngân sách gọi LLM của lượt này.")
        self.calls += 1
        usage = None
        try:
            answer = self.chat.complete(payload)
            usage = getattr(self.chat, "last_usage", None)
            return answer
        finally:
            # Chỉ lấy metadata được phép; không tuần tự hóa client hay cấu hình.
            self.history.append({
                "model": self.last_model,
                "attempts": [{"model": item["model"], "status": item["status"]}
                             for item in self.attempts],
                "usage": dict(usage) if isinstance(usage, dict) else None,
            })


def sum_tokens(usages):
    """Cộng số token của các lượt gọi; calls_with_usage cho biết bao nhiêu lượt có số liệu (T62)."""
    known = [u for u in usages if isinstance(u, dict)]
    return dict(input=sum(u.get("prompt_tokens", 0) for u in known),
                output=sum(u.get("completion_tokens", 0) for u in known),
                total=sum(u.get("total_tokens", 0) for u in known),
                calls_with_usage=len(known))
