"""Phiên đánh giá trong RAM; chỉ công bố kết quả sau khi thao tác thành công."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from legal_rag.assessment.facts_extract import merge_facts
from legal_rag.assessment.pipeline import prepare_assessment, run_assessment
from legal_rag.assessment.questions import followup_questions, ready_for_assessment
from legal_rag.assessment.report import render_markdown, build_report
from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.assessment.groups import describe_groups, next_group, status_groups
from legal_rag.assessment.grouped import score_group, score_banned, combined_status, evidence_sources
from legal_rag.assessment.claims import chat_claims
from legal_rag.api.connections import active_model
from legal_rag.api.session_store import SessionStore, new_session, stale
from legal_rag.knowledge.facts import FACT_FIELDS, FACT_LABELS, validate_facts
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.llm import LLMError

TABLE = Path(__file__).resolve().parents[1] / "knowledge/obligations.yaml"
LLM_REPLY = "Dịch vụ LLM tạm thời lỗi. Vui lòng thử lại sau."


class AssessmentError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class AssessmentService:
    def __init__(self, chat, settings, trace_dir, rows_loader=None, clock=None, store=None):
        self.chat, self.settings = chat, settings
        self.trace_dir = Path(trace_dir)
        self.rows_loader = rows_loader or (lambda: load_obligations(TABLE))
        self.custom_rows = rows_loader is not None
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.store = store if store is not None else SessionStore()

    @property
    def sessions(self):
        return self.store.sessions

    @property
    def lock(self):
        return self.store.lock

    @property
    def model(self):
        """Model phiên chọn trong thao tác hiện tại; mặc định là model cấu hình."""
        return active_model(self.settings.model)

    def _call(self, operation, session_id, inputs, action, create=False):
        with self.lock:
            started = perf_counter()
            trace = dict(operation=operation, session_id=session_id, input=inputs,
                         time=str(self.clock()), model=self.model)
            try:
                original = self.store.get(session_id)
                if original is None and not create:
                    raise AssessmentError(404, "Không tìm thấy phiên đánh giá.")
                session = deepcopy(original if original is not None else new_session())
                result = action(session)
                self.store.put(session_id, session)
                trace["output"] = result
                return deepcopy(result)
            except LLMError:
                trace["error"] = LLM_REPLY
                raise AssessmentError(503, LLM_REPLY) from None
            except AssessmentError as error:
                trace["error"] = error.detail
                raise
            except ValueError:
                trace["error"] = "Dữ kiện hoặc mã tự kiểm không hợp lệ."
                raise AssessmentError(422, trace["error"]) from None
            except Exception:
                trace["error"] = "Không xử lý được yêu cầu. Vui lòng thử lại."
                raise
            finally:
                trace["total_ms"] = (perf_counter() - started) * 1000
                try:
                    self.trace_dir.mkdir(parents=True, exist_ok=True)
                    (self.trace_dir / f"{uuid4().hex}.json").write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except OSError:
                    pass  # Lỗi ghi trace không làm mất kết quả của người dùng.

    def _prepared(self, session, changes):
        return dict(facts=session["facts"], evidence=session["evidence"], labels=FACT_LABELS,
                    fields={k: {**v, **({"values": sorted(v["values"])} if "values" in v else {})}
                            for k, v in FACT_FIELDS.items()},
                    questions=followup_questions(self.rows_loader(), session["facts"]),
                    ready=ready_for_assessment(session["facts"]), changes=changes,
                    groups=describe_groups(self._items(session)), stale=stale(session))

    def _items(self, session):
        return applicable_obligations(self.rows_loader(), session["facts"])["items"]

    def _changed(self, session, changes):
        session["changes"] = changes
        if changes:
            session["facts_version"] += 1
            session["checks"] = {}
            session["group_status"] = {}
            session["banned_status"] = None

    def _prepare(self, session):
        if session["messages"]:
            result = prepare_assessment(session["messages"], self.chat, self.model,
                previous=session["facts"], form=session["form"], rows=self.rows_loader())
            if result.get("error"):
                raise AssessmentError(503, LLM_REPLY)
            session["facts"] = result["facts"]
            self._changed(session, result["changes"])
            for change in result["changes"]:
                session["evidence"].pop(change["field"], None)
            session["evidence"].update({k: v for k, v in result["evidence"].items()
                                        if k not in session["form"]})
        else:
            session["changes"] = []
        session["description"] = "\n".join(session["messages"])
        session["prepared"] = True
        if session["messages"]:
            self._check_status_error(score_banned(session, self._items(session), self.chat, self.model))
        return self._prepared(session, session["changes"])

    def start(self, session_id):
        return self._call("start", session_id, {}, self._prepare, create=True)

    def describe(self, session_id, message):
        def action(session):
            session["messages"].append(message)
            return self._prepare(session)
        return self._call("describe", session_id, {"message": message}, action, create=True)

    def next(self, session_id):
        return self._call("next", session_id, {},
                          lambda s: next_group(self._items(s), s["answers"]))

    def state(self, session_id):
        def action(s):
            return {**self._prepared(s, s["changes"]),
                    "progress": next_group(self._items(s), s["answers"])["progress"],
                    "report": s["report"],
                    "markdown": render_markdown(s["report"]) if s["report"] else None}
        return self._call("state", session_id, {}, action)

    def _group_report(self, session):
        items = self._items(session)
        status = combined_status(session, items)
        rows = self.rows_loader()
        table_bytes = (json.dumps(rows, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8") if self.custom_rows else TABLE.read_bytes())
        session["report"] = build_report(session["facts"], items, status, dict(
            model=self.model, created=str(self.clock()),
            table_sha256=hashlib.sha256(table_bytes).hexdigest()))
        session["report_facts_version"] = session["facts_version"]
        session["mode"] = "grouped"
        return dict(report=session["report"], markdown=render_markdown(session["report"]),
                    stale=False, next=next_group(items, session["answers"]))

    def _check_status_error(self, result):
        if any(e.get("error") == "LLMError" for e in result.get("errors", [])):
            raise AssessmentError(503, LLM_REPLY)

    def answer(self, session_id, group, text, unknown=False):
        def action(s):
            items = self._items(s)
            groups = status_groups(items)
            if group not in groups or (not unknown and not text.strip()):
                raise AssessmentError(422, "Nhóm hoặc lời khai hiện trạng không hợp lệ.")
            s["answers"][group] = dict(text=text, unknown=unknown)
            # Lời khai mới thay cả tự kiểm cũ của nhóm.
            ids = {i["row"]["id"] for i in groups[group]}
            s["checks"] = {k: v for k, v in s["checks"].items() if k[0] not in ids}
            self._check_status_error(score_group(s, groups[group], group, self.chat, self.model))
            if not unknown:
                self._check_status_error(score_banned(s, items, self.chat, self.model))
            else:
                # Bỏ câu trích cũ nếu lời khai vừa bị thay bằng không biết.
                from legal_rag.assessment.grouped import retain_banned
                retain_banned(s)
            return self._group_report(s)
        return self._call("answer", session_id, dict(group=group, text=text, unknown=unknown), action)

    def set_facts(self, session_id, facts):
        def action(session):
            clean, errors = validate_facts(facts)
            # Validator trả đủ trường; chỉ cập nhật trường thực sự được gửi và hợp lệ.
            accepted = {key: clean[key] for key, value in facts.items()
                        if key in clean and (value is None or clean[key] is not None)}
            session["form"].update(accepted)
            session["facts"], changes = merge_facts(session["facts"], {}, session["form"])
            for key in accepted:
                session["evidence"].pop(key, None)
            self._changed(session, changes)
            return {**self._prepared(session, changes), "errors": errors}
        return self._call("set_facts", session_id, {"facts": facts}, action)

    def _run(self, session, statement):
        if not statement.strip():
            raise AssessmentError(422, "Vui lòng nhập lời khai hiện trạng trước khi đánh giá.")
        result = run_assessment(session["facts"], statement, session["description"],
            self.chat, self.model, rows=self.rows_loader() if self.custom_rows else None,
            checks=session["checks"],
            created=str(self.clock()))
        # Lõi T34 bắt lỗi LLM và ghi trace; API phải chuyển thành 503.
        if (any(e.get("error") == "LLMError" for e in result["trace"]["status"]["errors"])
                or "LLMError" in result["trace"]["summary"].get("errors", [])):
            raise AssessmentError(503, LLM_REPLY)
        evidence_sources(result["trace"]["status"], statement, chat_claims(session["messages"]))
        # Report đã sao chép criteria, cập nhật nguồn sau khi gán nhãn.
        sources = {r["row_id"]: r["criteria"] for r in result["trace"]["status"]["rows"]}
        for row in result["report"]["obligations"] + result["report"]["warnings"]:
            row["criteria"] = sources[row["id"]]
        session["statement"], session["report"] = statement, result["report"]
        session["mode"] = "legacy"
        session["report_facts_version"] = session["facts_version"]
        return {"report": session["report"], "markdown": render_markdown(session["report"]), "stale": False}

    def run(self, session_id, statement):
        return self._call("run", session_id, {"statement": statement}, lambda s: self._run(s, statement))

    def check(self, session_id, row_id, criterion_id, value):
        def action(session):
            if session["report"] is None:
                raise AssessmentError(404, "Chưa có bản đánh giá trong phiên này.")
            if stale(session):
                raise AssessmentError(409, "Dữ kiện đã đổi. Vui lòng đánh giá lại trước khi tự kiểm.")
            allowed = {(r["id"], c["id"]) for r in session["report"]["obligations"] for c in r["criteria"]}
            key = (row_id, criterion_id)
            if key not in allowed or value not in ("da", "chua", None):
                raise AssessmentError(422, "Mã nghĩa vụ, tiêu chí hoặc câu trả lời tự kiểm không hợp lệ.")
            if value is None:
                session["checks"].pop(key, None)
            else:
                session["checks"][key] = value
            if session["mode"] == "grouped":
                groups = status_groups(self._items(session))
                group = next(g for g, entries in groups.items() if any(i["row"]["id"] == row_id for i in entries))
                # Tự kiểm áp dụng cả với nhóm chưa có lời khai.
                if group not in session["answers"] or session["answers"][group]["unknown"]:
                    from legal_rag.assessment.grouped import empty_status
                    from legal_rag.assessment.status import _aggregate
                    status = empty_status(groups[group])
                    for row in status["rows"]:
                        for c in row["criteria"]:
                            k = (row["row_id"], c["id"])
                            if k in session["checks"]:
                                c.update(status=session["checks"][k], source="nguoi_dung", evidence_source="nguoi_dung")
                        row["status"] = _aggregate(row["criteria"], False)
                    session["group_status"][group] = status
                else:
                    self._check_status_error(score_group(session, groups[group], group, self.chat, self.model))
                return self._group_report(session)
            return self._run(session, session["statement"])
        return self._call("check", session_id, dict(row_id=row_id, criterion_id=criterion_id, value=value), action)

    def markdown(self, session_id):
        def action(session):
            if session["report"] is None:
                raise AssessmentError(404, "Chưa có bản đánh giá trong phiên này.")
            return render_markdown(session["report"])
        return self._call("markdown", session_id, {}, action)
