"""Điều phối lượt chat tuần tự, độc lập với lớp HTTP."""

import logging
from copy import deepcopy
from threading import Lock
from time import perf_counter

from legal_rag.agent.graph import LLM_ERROR_REPLY, llm_error_reply, run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.agent.trace_view import trace_view
from legal_rag.generation.citations import citation_list
from legal_rag.generation.trace import write_trace
from legal_rag.llm import LLMError
from legal_rag.api.session_store import SessionStore, stale
from legal_rag.assessment.profile_bridge import profile_override as assessment_profile

EVIDENCE_FIELDS = (
    "id", "document_number", "document_title", "article", "clause", "article_title",
    "text", "source", "source_url", "scope_note", "conformity_note", "referenced_from",
    "external_refs",
)
PRIVATE_FIELDS = frozenset(("api_key", "authorization", "secret", "password", "token",
                            "access_token", "prompt", "messages", "client", "settings"))


def public_value(value):
    """Lọc cả dữ liệu lồng nhau trước khi đưa qua HTTP."""
    if isinstance(value, dict):
        return {key: (LLM_ERROR_REPLY if key.endswith("_error") and item else public_value(item))
                for key, item in value.items()
                if key.lower() not in PRIVATE_FIELDS}
    if isinstance(value, (list, tuple)):
        return [public_value(item) for item in value]
    return value


class ChatService:
    def __init__(self, graph, chat, settings, trace_dir, store=None):
        self.graph, self._chat, self.settings = graph, chat, settings
        self.trace_dir = trace_dir
        self._lock = Lock()
        self.store = store if store is not None else SessionStore()
        self.model_loaded = False

    def health(self):
        return dict(status="ok", model=self.settings.model,
                    fallback_models=list(self.settings.fallback_models), model_loaded=self.model_loaded)

    def chat(self, session_id, message, context=None):
        with self._lock, self.store.lock:
            session = self.store.get(session_id, create=True)
            # Lưu trước đồ thị để giữ được lời người dùng ngay cả khi lượt lỗi.
            session["messages"].append(message)
            session["description"] = "\n".join(session["messages"])
            override = assessment_profile(session["facts"], session["description"]) if session["prepared"] else None
            if override is not None:
                # description là lịch sử lời người dùng, không phải mô tả sản phẩm đã trích.
                # Giữ mô tả trong hồ sơ chat; analyze hiện tại có thể bổ sung mô tả thật.
                override.pop("product_description", None)
            resolved, reason = None, None
            if context:
                report = session["report"]
                row = next((r for r in (report or {}).get("obligations", [])
                            if r["id"] == context.get("obligation_id")), None)
                if row is not None:
                    resolved = dict(context, assessment=row, stale=stale(session))
                else:
                    reason = "no_report" if report is None else "obligation_not_in_report"
            facts = deepcopy(session["facts"]) if session["prepared"] else None
            return self._turn(session_id, message, override, resolved, context, reason, facts)

    def _turn(self, session_id, message, override=None, resolved=None, context=None, context_reason=None, facts_override=None):
        start = perf_counter()
        result, state, failure = {}, {}, None
        try:
            kwargs = {}
            if override is not None:
                kwargs["profile_override"] = override
            if resolved is not None:
                kwargs["context"] = resolved
            if facts_override is not None:
                kwargs["facts_override"] = facts_override
            result = run_turn(self.graph, session_id, message, **kwargs)
        except LLMError as error:
            result = dict(route="error", reply=llm_error_reply(error), error=str(error))
        except Exception as error:
            failure = error
        finally:
            # Đọc checkpoint ngay trong khóa để không trộn trạng thái giữa các lượt.
            try:
                state = self.graph.get_state({"configurable": {"thread_id": session_id}}).values
            except Exception:
                logging.getLogger(__name__).warning("Không đọc được checkpoint của lượt chat.")
            if not result:
                result = dict(route="error", reply="", error="Không xử lý được yêu cầu.")
            evidence = result.get("evidence", state.get("evidence", []))
            check = result.get("check", state.get("check"))
            nodes = result.get("trace", state.get("trace", []))
            total_ms = (perf_counter() - start) * 1000
            calls = [node for node in nodes if node.get("llm_calls")]
            citations = citation_list(check, evidence) if check else []
            record = dict(
                citations=citations, query=message, session_id=session_id,
                profile_override=override, context=context, context_ignored=context_reason,
                pinned_parents=state.get("pinned_parents", []),
                route=result["route"], prompt_version=state.get("prompt_version"),
                model=calls[-1].get("model") if calls and not result.get("error") else None,
                profile=result.get("profile", state.get("profile", dict(EMPTY_PROFILE))),
                messages=state.get("llm_messages", []), conversation=state.get("messages", [])[-2:],
                evidence=evidence, answer=result.get("answer"), reply=result.get("reply"), check=check,
                high_risk=result.get("high_risk", state.get("high_risk")),
                map_obligations=result.get("map_obligations", state.get("map_obligations")),
                llm_calls=result.get("llm_calls", sum(n.get("llm_calls", 0) for n in nodes)),
                verification=result.get("verification", state.get("verification")),
                llm_attempts=[a for n in calls for a in n.get("llm_attempts", [])],
                nodes=nodes, error=result.get("error"), total_ms=total_ms,
            )
            try:
                write_trace(record, self.trace_dir)
            except Exception:
                logging.getLogger(__name__).warning("Không ghi được trace của lượt chat.")
        if failure is not None:
            raise failure
        return dict(session_id=session_id, reply=result["reply"], route=result["route"],
                    profile=record["profile"], citations=citations,
                    evidence=[{key: item[key] for key in EVIDENCE_FIELDS if key in item}
                              for item in evidence],
                    process=public_value(dict(trace_view(record), total_ms=total_ms)),
                    llm_calls=record["llm_calls"], total_ms=total_ms,
                    error=result["reply"] if result.get("error") else None)
