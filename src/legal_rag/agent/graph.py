"""Khung hội thoại tuần tự, lưu hồ sơ và lịch sử theo phiên trong RAM."""

from dataclasses import dataclass
from copy import deepcopy
from math import ceil
from time import perf_counter
from typing import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from legal_rag.agent.navigation import navigate
from legal_rag.agent.analyze import analyze_turn
from legal_rag.agent.answer import generate_answer
from legal_rag.agent.config import MAX_QUERIES, AgentConfig
from legal_rag.agent.grade import grade_evidence as grade_items
from legal_rag.agent.verify import verify_answer
from legal_rag.agent.repair import repair_answer as repair_text
from legal_rag.agent.followup import ask_followup as followup, append_before_closing, NOTICE
from legal_rag.generation.citations import check_answer, citation_list
from legal_rag.agent.blocks import apply_blocks
from legal_rag.agent.presentation import (build_context, facts_context, present_answer, apply_presentation_errors,
                                          answer_first)
from legal_rag.agent.obligation_sources import plan_sources, check_sources
from legal_rag.agent.explanations import with_rows
from legal_rag.generation.evidence import append_evidence
from legal_rag.agent.report import assemble_report, LIST_ITEM_PREFIX
from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.profile_bridge import facts_from_profile
from legal_rag.knowledge.facts import validate_facts
from legal_rag.agent.policy import request_plan, DIRECT_QUESTION_TYPES
from legal_rag.knowledge.high_risk import candidate_items, assess_items, render_assessment
from legal_rag.retrieval.context import clause_unit
from legal_rag.agent.budget import BudgetChat, sum_tokens
from legal_rag.agent.guard import check_input as guard_input, scope_reply
from legal_rag.agent.profile import EMPTY_PROFILE, merge_profile
from legal_rag.agent.state import AgentState, TurnContext, turn_input
from legal_rag.llm import CacheMissError, LLMError, QuotaExhaustedError
from legal_rag.knowledge.frame import is_broad_obligation_query

LLM_ERROR_REPLY = "Dịch vụ LLM tạm thời lỗi. Vui lòng thử lại sau."
REPORT_VERSIONS = ("answer_v10", "answer_v11", "answer_v12")


def llm_error_reply(error):
    if isinstance(error, CacheMissError):
        return "Câu này chưa có sẵn trong chế độ trình diễn. Vui lòng chọn câu đã chuẩn bị."
    if isinstance(error, QuotaExhaustedError):
        hours = max(1, ceil((error.retry_after if error.retry_after is not None else 3600) / 3600))
        return f"Dịch vụ AI đã hết lượt trong ngày, vui lòng thử lại sau khoảng {hours} giờ."
    return LLM_ERROR_REPLY


@dataclass
class GraphDeps:
    chat: object
    model: str
    prepare_fn: Callable
    config: AgentConfig = AgentConfig()
    generate_fn: Callable = generate_answer
    pipeline_factory: Callable | None = None
    parents: object = ()
    documents: object = ()
    chunks_loader: Callable | None = None
    high_risk_loader: Callable | None = None
    obligations_loader: Callable | None = None


def build_graph(deps):
    def traced(fn):
        def node(state: AgentState, runtime: Runtime[TurnContext]):
            if fn.__name__ == "check_input":
                runtime.context.chat = BudgetChat(deps.chat)
            chat = runtime.context.chat
            before, start = chat.calls, perf_counter()
            extra = {}
            try:
                update, extra = fn(state, chat)
            except LLMError as error:
                if fn.__name__ not in ("analyze", "generate"):
                    raise
                update = dict(reply=llm_error_reply(error), route="error", error=str(error))
            calls = chat.history[before:]
            entry = dict(node=fn.__name__, ms=(perf_counter() - start) * 1000,
                         llm_calls=chat.calls - before,
                         tokens=sum_tokens(call.get("usage") for call in calls), **extra)
            if calls:
                entry.update(model=calls[-1]["model"],
                             llm_attempts=[attempt for call in calls for attempt in call["attempts"]])
            update["trace"] = [*state.get("trace", []), entry]
            return update
        node.__name__ = fn.__name__
        return node

    @traced
    def check_input(state, chat):
        result = guard_input(state["message"])
        update = {"profile": state.get("profile", dict(EMPTY_PROFILE)),
                  "followup_asked": state.get("followup_asked", False),
                  "messages": state.get("messages", []),
                  "last_parents": state.get("last_parents", [])}
        if state.get("profile_override") is not None:
            update["profile"] = {**update["profile"], **state["profile_override"]}
        if result["status"] != "ok":
            update.update(reply=result["reply"], route="input_rejected")
            return update, {"status": result["status"]}
        nav = navigate(state["message"]) if deps.config.enable_navigation else None
        if nav:
            update.update(reply=nav["reply"], route="navigation", last_parents=[])
            return update, {"status": "navigation", "kind": nav["kind"], "document_id": nav["document_id"]}
        return update, {"status": result["status"]}

    @traced
    def analyze(state, chat):
        analysis = analyze_turn(state["message"], state["profile"],
                                state["messages"][-4:], chat, deps.model, version=deps.config.analyze_prompt)
        return {"analysis": analysis}, {"analysis": analysis, "question_type": analysis["question_type"]}

    @traced
    def check_scope(state, chat):
        scope = state["analysis"]["scope"]
        update = dict(reply=scope_reply(), route="out_of_scope") if scope == "ngoai" else {}
        details = {"scope": scope}
        if scope == "ngoai":
            plan = request_plan(state["analysis"], state["profile"], state.get("context"), deps.config)
            update["request_plan"] = plan
            details["request_plan"] = plan
        return update, details

    @traced
    def update_profile(state, chat):
        profile, ignored = merge_profile(state["profile"], state["analysis"]["profile_update"])
        if state.get("profile_override") is not None:
            profile.update(state["profile_override"])
        return {"profile": profile}, {"before": state["profile"], "after": profile, "ignored": ignored}

    @traced
    def plan_queries(state, chat):
        plan = request_plan(state["analysis"], state["profile"], state.get("context"), deps.config)
        return {"request_plan": plan}, {"sub_queries": state["analysis"]["sub_queries"], "request_plan": plan,
                                       "facts_source": "assessment" if state.get("facts_override") is not None else "profile"}

    def prepare(state):
        return deps.prepare_fn(state["message"], state["analysis"]["sub_queries"],
                               last_parents=state["last_parents"], rewritten=state["rewritten"])

    # Chunks và chỉ mục dùng chung cho mọi phiên, không đưa vào checkpoint vì checkpoint lưu sau mỗi nút.
    location = {}

    def prepare_light(state):
        result = dict(prepare(state))
        for key in ("index", "chunks"):
            if key in result:
                location[key] = result.pop(key)
        context = state.get("context") or {}
        row = context.get("assessment")
        if row:
            chunks = load_knowledge("chunks", deps.chunks_loader, "chunk_id")
            ids = list(dict.fromkeys(clause_unit(chunks[c["chunk_id"]])
                       for c in row["citations"] if c["chunk_id"] in chunks))
            registry = deps.parents if isinstance(deps.parents, dict) else {p["parent_id"]: p for p in deps.parents}
            pinned, cost = append_evidence([], [i for i in ids if i in registry], deps.parents,
                                           deps.documents, "pinned", deps.config.extra_budget)
            pinned_ids = {i["parent_id"] for i in pinned}
            entries = pinned + [i for i in result["evidence"] if i["parent_id"] not in pinned_ids]
            new_codes = {i["parent_id"]: f"E{n}" for n, i in enumerate(entries, 1)}
            codes = {i["id"]: new_codes[i["parent_id"]] for i in result["evidence"]}
            entries = [dict(i, id=f"E{n}", **({"referenced_from": codes.get(i["referenced_from"], i["referenced_from"])}
                       if "referenced_from" in i else {})) for n, i in enumerate(entries, 1)]
            result.update(evidence=entries, parents_used=[i["parent_id"] for i in entries],
                          pinned_tokens=cost, pinned_parents=[i["parent_id"] for i in pinned])
        return result

    @traced
    def retrieve(state, chat):
        result = prepare_light(state)
        previous = set(state["retrieved_parents"])
        current = {item["parent_id"] for item in result["evidence"]}
        added = len(current - previous)
        count = state["retrieval_count"] + 1
        return {"prepared": result, "evidence": result["evidence"],
                "extra_tokens": result.get("pinned_tokens", 0),
                "pinned_parents": result.get("pinned_parents", []),
                "retrieved_parents": sorted(current), "new_parent_count": added,
                "retrieval_count": count}, {
            "retrieval_count": count, "new_parent_count": added,
            "query_used": result["query_used"], "references_added": result["references_added"],
            "last_detail": result["detail"], "timing": result["timing"],
            "selected": [dict(parent_id=item["parent_id"], source=item["source"])
                         for item in result["evidence"]]}

    @traced
    def grade_evidence(state, chat):
        extra = {}
        if not deps.config.enable_rewrite:
            grade = dict(status="bo_qua", missing=[], rewrite=[], grade_ok=True)
        else:
            try:
                grade = grade_items(state["message"], state["prepared"]["queries"],
                                    state["evidence"], chat, deps.model, version=deps.config.grade_prompt)
            except LLMError as error:
                grade = dict(status="du", missing=[], rewrite=[], grade_ok=False)
                extra["grade_error"] = str(error)
        reason = rewrite_stop_reason(dict(state, grade=grade))
        return {"grade": grade, "rewrite_stop_reason": reason}, {
            **grade, **extra, "retrieval_count": state["retrieval_count"],
            "new_parent_count": state["new_parent_count"], "stop_reason": reason}

    def new_queries(state):
        used = set(state["prepared"]["queries"]) | set(state["rewritten"])
        return [q for q in state["grade"]["rewrite"] if q not in used][:max(0, MAX_QUERIES - len(used))]

    def rewrite_stop_reason(state):
        if not deps.config.enable_rewrite:
            return "rewrite_disabled"
        status = state["grade"]["status"]
        if status in ("du", "khong_co_chi_tiet"):
            return status
        if state["rewrites"] and state["new_parent_count"] == 0:
            return "no_new_parents"
        if state["rewrites"] >= deps.config.max_rewrites:
            return "max_rewrites"
        if not new_queries(state):
            return "no_new_queries"
        return None

    @traced
    def rewrite_query(state, chat):
        added = new_queries(state)
        return {"rewritten": [*state["rewritten"], *added], "rewrites": state["rewrites"] + 1}, {
            "rewrite": added, "rewrite_count": state["rewrites"] + 1}

    # Dữ liệu tĩnh nằm ngoài checkpoint, nạp khi nút cần dùng.
    knowledge = {}

    def load_knowledge(name, loader, key):
        if name not in knowledge:
            rows = loader() if loader else []
            knowledge[name] = {row[key]: row for row in rows} if key else rows
        return knowledge[name]

    def append_parents(state, parent_ids, source):
        if state.get("high_risk"):
            parent_ids = [key for key in parent_ids if not key.startswith(LIST_ITEM_PREFIX)]
        items, cost = append_evidence(state["evidence"], parent_ids, deps.parents,
            deps.documents, source, deps.config.extra_budget - state["extra_tokens"])
        # Không cấp lại mã đã tách, kể cả khi mã đó nằm ở cuối danh sách cũ.
        previous = [*state["evidence"], *state.get("high_risk_items", [])]
        last_code = max((int(item["id"][1:]) for item in previous), default=0)
        for offset, item in enumerate(items[len(state["evidence"]):], 1):
            item["id"] = f"E{last_code + offset}"
        prepared = dict(state["prepared"], evidence=items,
                        parents_used=[item["parent_id"] for item in items])
        return dict(evidence=items, prepared=prepared, extra_tokens=state["extra_tokens"] + cost)

    @traced
    def check_high_risk(state, chat):
        prepared_update = {}
        if state["prepared"] is None:
            prepared = prepare_light(state)
            prepared_update = dict(prepared=prepared, evidence=prepared["evidence"],
                                   extra_tokens=prepared.get("pinned_tokens", 0),
                                   pinned_parents=prepared.get("pinned_parents", []))
            state = dict(state, **prepared_update)
        description = state["profile"].get("product_description")
        if not state["request_plan"]["use_high_risk"]:
            return prepared_update, {"status": "bo_qua", "reason": state["request_plan"]["high_risk_reason"]}
        if deps.pipeline_factory is None:
            return prepared_update, {"status": "bo_qua", "reason": "no_pipeline"}
        try:
            items = load_knowledge("high_risk", deps.high_risk_loader, "item_id")
            hits = deps.pipeline_factory().search(description)
            candidates = candidate_items(hits, items)
            result = assess_items(description, candidates, chat, deps.model, version="high_risk_v2")
            rendered = render_assessment(description, result, items, deps.parents)
            pinned = set(state.get("pinned_parents", []))
            removed = [item for item in state["evidence"]
                       if item["parent_id"].startswith(LIST_ITEM_PREFIX) and item["parent_id"] not in pinned]
            remaining = [item for item in state["evidence"]
                         if not item["parent_id"].startswith(LIST_ITEM_PREFIX) or item["parent_id"] in pinned]
            filtered = dict(state, evidence=remaining, high_risk=rendered, high_risk_items=removed)
            update = append_parents(filtered, rendered["parent_ids"], "high_risk")
            update["prepared"]["high_risk_decisions"] = deepcopy(result["items"])
            update.update(high_risk=rendered, high_risk_items=removed,
                          pinned_parents=state.get("pinned_parents", []))
            return update, {"high_risk": rendered, "assess_ok": result["assess_ok"],
                            "candidate_selection": dict(version=result["version"],
                                candidate_ids=[c["item_id"] for c in candidates], relevance=result["relevance"],
                                eligible_ids=[r["item_id"] for r in result["items"]],
                                displayed_ids=[p for p in rendered["parent_ids"] if p in items],
                                reason=rendered["selection_reason"]),
                            "removed_list_items": [item["parent_id"] for item in removed]}
        except LLMError as error:
            return {**prepared_update, "high_risk_error": str(error)}, {"high_risk_error": str(error)}

    @traced
    def map_obligations(state, chat):
        # Nhánh câu rộng vẫn chuẩn bị khung kể cả khi tắt bảng nghĩa vụ.
        if state["prepared"] is None:
            prepared = prepare_light(state)
            state = dict(state, prepared=prepared, evidence=prepared["evidence"])
        if state["prepared"].get("pinned_parents"):
            state = dict(state, extra_tokens=max(state["extra_tokens"], state["prepared"]["pinned_tokens"]))
        update = dict(prepared=state["prepared"], evidence=state["evidence"],
                      extra_tokens=state["extra_tokens"],
                      pinned_parents=state["prepared"].get("pinned_parents", []))
        source = "assessment" if state.get("facts_override") is not None else "profile"
        if not state["request_plan"]["use_table"]:
            return update, {"status": "bo_qua", "reason": state["request_plan"]["table_reason"], "facts_source": source}
        rows = load_knowledge("obligations", deps.obligations_loader, None)
        facts = (validate_facts(state["facts_override"])[0] if source == "assessment"
                 else facts_from_profile(state["profile"]))
        accept = ("user_reviewed", "ai_reviewed") if deps.config.accept_ai_reviewed else ("user_reviewed",)
        result = applicable_obligations(rows, facts, accept=accept)
        selected = [item["row"] for item in result["items"] if item["applicability"] == "ap_dung"]
        chunks = load_knowledge("chunks", deps.chunks_loader, "chunk_id") if result["items"] else {}
        source_gate = ("nghia_vu" in state["request_plan"]["request_kinds"]
            and state["request_plan"]["effective_question_type"] == "nghia_vu"
            and (state.get("high_risk") or {}).get("version") == "high_risk_v2"
            and state["prepared"].get("prompt_version") in ("answer_v9", "answer_v7"))
        if source_gate:
            source_plan = plan_sources(result["items"], chunks, deps.parents, state["evidence"],
                deps.config.extra_budget - state["extra_tokens"], LIST_ITEM_PREFIX)
            ids = source_plan["added_parent_ids"]
        else:
            ids = [clause_unit(chunks[citation["chunk_id"]])
                   for row in selected for citation in row["citations"] if citation["chunk_id"] in chunks]
        update.update(append_parents(state, ids, "obligation"))
        items = [dict(id=item["row"]["id"], **{k: item[k] for k in
                 ("applicability", "conditions", "missing_facts")}) for item in result["items"]]
        summary = dict(items=items, skipped=result["skipped"], selected=[row["id"] for row in selected],
                       unreviewed_count=result["skipped"]["not_accepted"], rejected_count=result["skipped"]["rejected"])
        present = {item["parent_id"]: item["id"] for item in update["evidence"]}
        bases = []
        for decision, item in zip(items, result["items"]):
            codes = list(dict.fromkeys(present[clause_unit(chunks[c["chunk_id"]])]
                for c in item["row"]["citations"] if c["chunk_id"] in chunks
                and clause_unit(chunks[c["chunk_id"]]) in present))
            if codes:
                bases.append(dict(decision, obligation=item["row"].get("obligation", ""),
                                  situation=(item["row"].get("condition") or "").strip(), evidence_ids=codes,
                                  kind=item["row"].get("kind", "nghia_vu")))
        update["applicability_bases"] = bases
        update["map_obligations"] = summary
        update["prepared"] = dict(update["prepared"], presentation_facts=deepcopy(facts),
                                  presentation_facts_source=source, presentation_summary=deepcopy(summary))
        extra = {}
        if source_gate:
            coverage, eligible_bases = check_sources(source_plan, update["evidence"],
                                                     location.get("index"), location.get("chunks"))
            update["prepared"].update(obligation_source_coverage=coverage,
                                      presentation_eligible_bases=eligible_bases)
            extra["obligation_source_coverage"] = coverage
        return update, {**summary, "risk_level": facts["risk_level"], "facts_source": source,
                        "map_obligations": summary, **extra}

    def answer_before_report(result, prepared, state, chat):
        """Khuôn báo cáo vẫn trả lời thẳng câu hỏi trước, trên cùng bộ bằng chứng (T57)."""
        question_type = state["analysis"].get("question_type")
        question_type = question_type if question_type in DIRECT_QUESTION_TYPES else "khac"
        direct_prepared = {key: value for key, value in prepared.items() if key != "presentation_context"}
        direct_prepared.update(prompt_version="answer_v9", route="retrieval", question_type=question_type)
        message = state["message"]
        if state["analysis"]["scope"] == "mot_phan":
            message += "\nKhông trả lời phần sau vì ngoài phạm vi: " + (
                state["analysis"]["out_of_scope_part"] or "phần ngoài phạm vi của câu hỏi")
        try:
            direct = deps.generate_fn(message, state["analysis"]["sub_queries"], state["profile"],
                                      {**direct_prepared, **location}, chat, deps.model)
        except LLMError as error:
            return result, dict(status="loi", reason=str(error))
        reply, reason = answer_first(result["reply"], direct["reply"])
        if reason:
            return result, dict(status="giu_khuon_cu", reason=reason)
        check = check_answer(reply, result["evidence"], location.get("index"), location.get("chunks"))
        apply_blocks(check, result["evidence"], reply, result["prompt_version"], prepared["question_type"])
        apply_presentation_errors(check, (result.get("presentation") or {}).get("errors", []))
        prepared["direct_reply"] = direct["reply"]
        return dict(result, reply=reply, check=check), dict(
            status="ok", question_type=question_type, direct_valid=direct["check"]["valid"])

    @traced
    def generate(state, chat):
        if state["request_plan"]["request_kinds"] == ["hien_trang"]:
            return dict(reply="Bạn mở Rà soát để cung cấp dữ kiện và đánh giá hiện trạng thực hiện nghĩa vụ. "
                              "Chat chưa xác định bạn đã hay chưa tuân thủ.",
                        route="assessment_guidance", evidence=[], check=None, prompt_version=None), {
                        "effective_question_type": "khac", "effective_prompt_version": None,
                        "reason": "assessment_requires_explicit_flow"}
        prepared = dict(state["prepared"] or prepare_light(state),
                        question_type=state["request_plan"]["effective_question_type"])
        if prepared["question_type"] != "nghia_vu" and prepared.get("prompt_version") == "answer_v7":
            prepared.update(prompt_version="answer_v9", route="retrieval")
        if state.get("applicability_bases") or ("nghia_vu" in state["request_plan"]["request_kinds"]
                and (state.get("high_risk") or {}).get("version") == "high_risk_v2"):
            prepared["presentation_context"] = build_context(prepared.get("presentation_eligible_bases",
                state.get("applicability_bases", [])),
                state["evidence"], state.get("high_risk"), knowledge.get("high_risk", {}),
                prepared.get("high_risk_decisions", []), deps.parents, deps.documents)
        if ("nghia_vu" in state["request_plan"]["request_kinds"]
                and (state.get("high_risk") or {}).get("version") == "high_risk_v2"
                and prepared.get("prompt_version") in ("answer_v9", "answer_v7")):
            prepared["prompt_version"] = "answer_v10"
            if prepared["question_type"] == "nghia_vu" and state["request_plan"]["use_table"]:
                prepared["prompt_version"] = "answer_v11"
                prepared["presentation_context"] = facts_context(prepared["presentation_context"],
                    prepared["presentation_facts"], prepared["presentation_facts_source"], prepared["presentation_summary"])
                if prepared.get("obligation_source_coverage") is not None:
                    counts = prepared["obligation_source_coverage"]["counts"]
                    prepared["presentation_context"]["data"]["Độ đủ căn cứ để trình bày"] = {
                        "Tổng số dòng": counts["core"], "Đủ tập nguồn đã gắn": counts["complete"],
                        "Có căn cứ một phần": counts["partial"], "Chưa có căn cứ hiện diện": counts["none"],
                        "Đủ điều kiện trình bày chi tiết": counts["eligible"],
                        "Cần đối chiếu căn cứ trước khi trình bày chi tiết": counts["withheld"]}
                    prepared["presentation_context"] = with_rows(prepared["presentation_context"])
                    prepared["prompt_version"] = "answer_v12"
        message = state["message"]
        # Quyết định mở rộng theo câu gốc, trước khi nối các chỉ dẫn nội bộ.
        if len(message.split()) < 8 and state["analysis"]["sub_queries"]:
            message += "\nCâu hỏi đầy đủ: " + state["analysis"]["sub_queries"][0]
        if "hien_trang" in state["request_plan"]["request_kinds"]:
            message += "\nKhông tự chấm đã/chưa tuân thủ qua chat. Hướng dẫn người dùng mở Rà soát để đánh giá hiện trạng."
        if "nghia_vu" in state["request_plan"]["request_kinds"]:
            message += "\nXác định nghĩa vụ và điều kiện áp dụng; không tự chấm đã/chưa thực hiện."
        if "huong_dan" in state["request_plan"]["request_kinds"] and not state.get("context"):
            message += "\nChưa có ngữ cảnh kết quả đánh giá: chỉ hướng dẫn chung theo căn cứ, không dựng bản đánh giá hoặc trạng thái."
        message += "\nKhông kết luận một nghĩa vụ không áp dụng chỉ vì chưa xuất hiện trong bằng chứng."
        if state["analysis"]["scope"] == "mot_phan":
            part = state["analysis"]["out_of_scope_part"] or "phần ngoài phạm vi của câu hỏi"
            message += "\nKhông trả lời phần sau vì ngoài phạm vi: " + part
        if state.get("high_risk"):
            message += "\nPhần gợi ý Danh mục đã được trình bày riêng. Không kết luận sản phẩm thuộc hay không thuộc Danh mục, không nhận xét về mức rủi ro của sản phẩm."
        row = (state.get("context") or {}).get("assessment")
        if row:
            labels = {"da": "đã", "chua": "chưa", "chua_ro": "cần xác minh"}
            applies = "áp dụng" if row["applicability"] == "ap_dung" else "áp dụng nếu " + "; ".join(row["conditions"])
            criteria = "; ".join(c["text"] + ": " + labels.get(c["status"], c["status"]) for c in row["criteria"])
            message += ("\nKết quả đánh giá cho nghĩa vụ này: " + applies + "; hiện trạng: "
                        + labels[row["status"]] + "; tiêu chí: " + criteria
                        + ". Trả lời bám theo kết quả này. Không kết luận ngược kết quả đánh giá; "
                        "nếu bằng chứng cho thấy khác, nói rõ là có điểm cần xem lại.")
            if state["context"].get("stale"):
                message += " Bản đánh giá cũ do dữ kiện đã đổi; cần đánh giá lại."
        result = deps.generate_fn(message, state["analysis"]["sub_queries"],
                                  state["profile"], {**prepared, **location}, chat, deps.model)
        if prepared.get("prompt_version") in ("answer_v10", "answer_v11", "answer_v12") and "presentation" not in result:
            version = prepared["prompt_version"]
            result = dict(result, raw_reply=result["reply"], prompt_version=version)
            result["reply"], result["presentation"] = present_answer(result["reply"],
                prepared.get("presentation_context"), version,
                **(dict(items=result["evidence"], index=location.get("index"), chunks=location.get("chunks"))
                   if version == "answer_v12" else {}))
            result["check"] = check_answer(result["reply"], result["evidence"], location.get("index"), location.get("chunks"))
            apply_blocks(result["check"], result["evidence"], result["reply"], version, prepared["question_type"])
            apply_presentation_errors(result["check"], result["presentation"]["errors"])
        direct = None
        if prepared.get("prompt_version") in REPORT_VERSIONS:
            result, direct = answer_before_report(result, prepared, state, chat)
        update = {key: result[key] for key in ("reply", "route", "evidence", "check", "prompt_version")}
        update["llm_messages"] = result.get("messages", [])
        update["prepared"] = prepared
        if result.get("presentation"):
            prepared["presentation_errors"] = result["presentation"]["errors"]
            prepared["presentation_audit"] = deepcopy(result["presentation"])
        if result["parents_used"]:
            update["last_parents"] = result["parents_used"]
        return update, {"check": result["check"], "effective_question_type": prepared["question_type"],
                        "effective_prompt_version": prepared.get("prompt_version"),
                        "presentation": result.get("presentation"), "raw_reply": result.get("raw_reply"),
                        "answer_first": direct,
                        "selected": [dict(parent_id=item["parent_id"], source=item["source"])
                                     for item in result["evidence"]]}

    @traced
    def verify_citations(state, chat):
        result = dict(issues=[], verify_ok=True)
        extra = {}
        if (deps.config.enable_verifier and deps.config.verifier_mode == "rule_llm"
                and state["route"] in ("retrieval", "broad_frame")):
            try:
                result = verify_answer(state["reply"], state["evidence"], chat, deps.model)
            except LLMError as error:
                result["verify_ok"] = False
                extra["verify_error"] = str(error)
        verification = dict(issues=result["issues"], repaired=False,
                            final_valid=bool((state["check"] or {}).get("valid", True)))
        return {"verification": verification}, {**result, **extra,
            "verifier_mode": deps.config.verifier_mode, "verification": verification}

    @traced
    def repair_answer(state, chat):
        extra = {}
        update = {}
        try:
            audit = {}
            context = (state.get("prepared") or {}).get("presentation_context")
            kwargs = dict(presentation_context=context, presentation_audit=audit) if context is not None else {}
            if state["prompt_version"] == "answer_v12":
                kwargs.update(presentation_index=location.get("index"), presentation_chunks=location.get("chunks"))
            reply = repair_text(state["reply"], (state["check"] or {}).get("errors", []),
                                state["verification"]["issues"], state["evidence"], chat, deps.model,
                                version=state["prompt_version"],
                                question_type=state["request_plan"]["effective_question_type"], **kwargs)
            if not isinstance(reply, str) or not reply.strip():
                raise LLMError("Phản hồi sửa rỗng.")
            direct = (state.get("prepared") or {}).get("direct_reply")
            if direct:
                # Sửa dựng lại báo cáo từ phần giải thích; ghép lại lời trả lời trực tiếp (T57).
                reply = answer_first(reply, direct)[0]
            update["reply"] = reply
            update["verification"] = dict(state["verification"], repaired=True)
            if context is not None:
                prepared = dict(state["prepared"])
                prepared["presentation_errors"] = list(dict.fromkeys([
                    *[error for error in prepared.get("presentation_errors", [])
                      if error.startswith("Chưa giải được mã nghĩa vụ")],
                    *audit.get("presentation", {}).get("errors", [])]))
                update["prepared"] = prepared
                prepared["presentation_audit"] = deepcopy(audit.get("presentation", {}))
                extra.update(audit)
        except LLMError as error:
            extra["repair_error"] = str(error)
        return update, extra

    @traced
    def recheck(state, chat):
        check = state["check"]
        verification = dict(state["verification"])
        if verification["repaired"]:
            check = check_answer(state["reply"], state["evidence"], location.get("index"), location.get("chunks"))
            apply_blocks(check, state["evidence"], state["reply"], state["prompt_version"],
                         state["request_plan"]["effective_question_type"])
            if (state.get("prepared") or {}).get("presentation_context") is not None:
                apply_presentation_errors(check, state["prepared"].get("presentation_errors", []))
        verification["final_valid"] = bool((check or {}).get("valid", True))
        reply = state["reply"]
        if not verification["final_valid"] or (verification["issues"] and not verification["repaired"]):
            if NOTICE not in reply:
                reply = append_before_closing(reply, NOTICE)
        return dict(reply=reply, check=check, verification=verification), {"check": check, "verification": verification,
            "effective_prompt_version": state["prompt_version"],
            "presentation": dict(has_snapshot=(state.get("prepared") or {}).get("presentation_context") is not None,
                opening_source="code" if state["prompt_version"] in ("answer_v10", "answer_v11", "answer_v12") else "llm",
                **({key: (state["prepared"]["presentation_context"])[key] for key in
                    ("facts_source", "snapshot_rows", "displayed_rows")}
                   | {"owned_sections": (["Trả lời ngắn", "Quy định áp dụng", "Nghĩa vụ cần xem xét", "Thông tin còn thiếu và giới hạn"]
                                         if state["prompt_version"] == "answer_v12" else
                                         ["Trả lời ngắn", "Nghĩa vụ cần xem xét", "Thông tin còn thiếu và giới hạn"])}
                   | ({"source_coverage": deepcopy(state["prepared"]["presentation_context"]["data"]["Độ đủ căn cứ để trình bày"])}
                      if "Độ đủ căn cứ để trình bày" in state["prepared"]["presentation_context"]["data"] else {})
                   if state["prompt_version"] in ("answer_v11", "answer_v12") else {}),
                **({"explanations": deepcopy(state["prepared"].get("presentation_audit", {}).get("explanations", {}))}
                   if state["prompt_version"] == "answer_v12" else {}),
                errors=(state.get("prepared") or {}).get("presentation_errors", []))}

    @traced
    def ask_followup(state, chat):
        if "nghia_vu" not in state["request_plan"]["request_kinds"]:
            return {}, {"field": None, "verification": state["verification"]}
        update, field = followup(dict(state, analysis=dict(state["analysis"], question_type="nghia_vu")))
        return update, {"field": field, "verification": state["verification"]}

    @traced
    def respond(state, chat):
        reply = state["reply"]
        analysis = state["analysis"]
        if analysis and analysis["scope"] == "mot_phan":
            part = analysis["out_of_scope_part"] or "phần ngoài phạm vi của câu hỏi"
            reply = f"Phần ngoài phạm vi ({part}) không được trả lời.\n\n{reply}"
        answer = reply
        if state["route"] in ("retrieval", "broad_frame"):
            reply = assemble_report(reply, citation_list(state["check"] or {}, state["evidence"]),
                                    state.get("high_risk"), state.get("high_risk_items", []),
                                    deps.parents, deps.documents)
        return {"answer": answer, "reply": reply, "messages": [*state["messages"],
                {"role": "user", "content": state["message"]},
                {"role": "assistant", "content": reply}]}, {}

    builder = StateGraph(AgentState, context_schema=TurnContext)
    for node in (check_input, analyze, check_scope, update_profile, plan_queries, retrieve,
                 grade_evidence, rewrite_query, check_high_risk, map_obligations, generate, verify_citations, repair_answer,
                 recheck, ask_followup, respond):
        builder.add_node(node.__name__, node)
    builder.add_edge(START, "check_input")
    builder.add_conditional_edges("check_input", lambda s: "respond" if s["route"] else "analyze",
                                  ["respond", "analyze"])
    builder.add_conditional_edges("analyze", lambda s: "respond" if s["error"] else "check_scope",
                                  ["respond", "check_scope"])
    builder.add_conditional_edges("check_scope", lambda s: "respond" if s["route"] else "update_profile",
                                  ["respond", "update_profile"])
    builder.add_edge("update_profile", "plan_queries")
    builder.add_conditional_edges("plan_queries", lambda s: "generate" if
        s["request_plan"]["request_kinds"] == ["hien_trang"] else "check_high_risk" if
        is_broad_obligation_query(s["message"]) else "retrieve", ["generate", "check_high_risk", "retrieve"])
    builder.add_edge("retrieve", "grade_evidence")
    builder.add_conditional_edges("grade_evidence", lambda s: "rewrite_query" if (
        s["rewrite_stop_reason"] is None) else "check_high_risk", ["rewrite_query", "check_high_risk"])
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_edge("check_high_risk", "map_obligations")
    builder.add_edge("map_obligations", "generate")
    builder.add_conditional_edges("generate", lambda s: "respond" if s["error"] else "verify_citations",
                                  ["respond", "verify_citations"])
    builder.add_conditional_edges("verify_citations", lambda s: "repair_answer" if (
        (s["check"] or {}).get("errors") or s["verification"]["issues"]) else "ask_followup",
        ["repair_answer", "ask_followup"])
    builder.add_edge("repair_answer", "recheck")
    builder.add_edge("recheck", "ask_followup")
    builder.add_edge("ask_followup", "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=InMemorySaver())


def run_turn(graph, session_id, message, profile_override=None, context=None, facts_override=None) -> dict:
    inputs = dict(turn_input(message), profile_override=profile_override, context=context,
                  facts_override=validate_facts(facts_override)[0] if facts_override is not None else None,
                  pinned_parents=[])
    state = graph.invoke(inputs, {"configurable": {"thread_id": session_id}}, context=TurnContext())
    result = {key: state[key] for key in
              ("answer", "reply", "route", "profile", "evidence", "check", "error", "trace", "verification", "high_risk", "high_risk_error", "map_obligations")}
    result["llm_calls"] = sum(node["llm_calls"] for node in state["trace"])
    node_tokens = [node.get("tokens") or {} for node in state["trace"]]
    result["tokens"] = {key: sum(t.get(key, 0) for t in node_tokens)
                        for key in ("input", "output", "total", "calls_with_usage")}
    return result
