"""HTTP cho demo cục bộ; chỉ khởi tạo runtime trong lifespan."""

from contextlib import asynccontextmanager
from pathlib import Path
import os
import re
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from legal_rag.agent.runtime import build_agent, read_jsonl
from legal_rag.api.service import ChatService, public_value
from legal_rag.api.session_store import SessionStore
from legal_rag.api.connections import ConnectionManager, ConnectionError, RoutedChat
from legal_rag.api.assessment_service import AssessmentService, AssessmentError, LLM_REPLY
from legal_rag.config import get_llm_settings
from legal_rag.llm import CachedChat, HTTPChatClient, OfflineClient, LLMError
from legal_rag.retrieval.pipeline import RetrievalPipeline

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).parent / "static"
ERROR_REPLY = "Không xử lý được yêu cầu. Vui lòng thử lại."


def load_assessment_service(chat_service=None):
    if chat_service is not None:
        return AssessmentService(chat_service._chat, chat_service.settings,
                                 ROOT / "runs/assessment-traces")
    settings = get_llm_settings(allow_missing_key=True)
    client = OfflineClient() if settings.offline else HTTPChatClient(settings.base_url, settings.api_key)
    return AssessmentService(RoutedChat(CachedChat(client, ROOT / ".cache/llm")), settings,
                             ROOT / "runs/assessment-traces")


def load_service():
    pipeline = RetrievalPipeline(read_jsonl(ROOT / "data/processed/chunks.jsonl"),
                                 read_jsonl(ROOT / "data/processed/parents.jsonl"))
    # Một truy vấn làm nóng nạp vector, encoder và reranker, không gọi LLM.
    pipeline.search("nghĩa vụ của hệ thống trí tuệ nhân tạo")
    settings = get_llm_settings(allow_missing_key=True)
    graph, chat, settings = build_agent(ROOT, pipeline=pipeline, chat_wrapper=RoutedChat, settings=settings)
    service = ChatService(graph, chat, settings, ROOT / "runs/traces")
    service.model_loaded = True
    return service


class ChatContext(BaseModel):
    obligation_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    context: ChatContext | None = None

    @field_validator("session_id")
    @classmethod
    def valid_session(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("Mã phiên phải dài 1–64 ký tự, chỉ gồm chữ, số, dấu - hoặc _.")
        return value

    @field_validator("message")
    @classmethod
    def valid_message(cls, value):
        if len(value) > 20000:
            raise ValueError("Tin nhắn không được quá 20000 ký tự.")
        return value


class SessionRequest(BaseModel):
    session_id: str
    valid_session = field_validator("session_id")(ChatRequest.valid_session.__func__)


class ConnectionRequest(SessionRequest):
    api_key: str = Field(min_length=8, max_length=512, repr=False)

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if len(value) < 8 or any(char.isspace() for char in value):
            raise ValueError("Khóa API không được trống hoặc chứa khoảng trắng.")
        return value


class AnswerRequest(SessionRequest):
    group: str
    text: str = ""
    unknown: bool = False
    valid_text = field_validator("text")(ChatRequest.valid_message.__func__)


class FactsRequest(BaseModel):
    session_id: str
    facts: dict
    valid_session = field_validator("session_id")(ChatRequest.valid_session.__func__)


class RunRequest(BaseModel):
    session_id: str
    statement: str
    valid_session = field_validator("session_id")(ChatRequest.valid_session.__func__)
    valid_statement = field_validator("statement")(ChatRequest.valid_message.__func__)


class CheckRequest(BaseModel):
    session_id: str
    row_id: str
    criterion_id: str
    value: Literal["da", "chua"] | None
    valid_session = field_validator("session_id")(ChatRequest.valid_session.__func__)


def create_app(service=None, assessment_service=None, store=None, connections=None):
    session_store = store if store is not None else SessionStore()
    connection_manager = connections if connections is not None else ConnectionManager()
    @asynccontextmanager
    async def lifespan(app):
        assess_only = os.environ.get("RAG_ASSESS_ONLY") == "1"
        # Một dịch vụ giả được tiêm thì không tự nạp dịch vụ còn lại trong test.
        injected = service is not None or assessment_service is not None
        app.state.service = None if assess_only else service
        if not injected and not assess_only:
            app.state.service = load_service()
        app.state.assessment = assessment_service
        if not injected:
            app.state.assessment = (load_assessment_service(app.state.service)
                                    if app.state.service is not None else load_assessment_service())
        app.state.session_store = session_store
        for current in (app.state.service, app.state.assessment):
            if current is not None:
                current.store = session_store
        if connection_manager.settings is None:
            current = app.state.service or app.state.assessment
            connection_manager.settings = getattr(current, "settings", None)
        app.state.connections = connection_manager
        try:
            yield
        finally:
            connection_manager.clear()

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(RequestValidationError)
    def validation_error(request, error):
        details = []
        for item in error.errors():
            field = str(item["loc"][-1])
            message = item["msg"]
            if item["type"] == "missing":
                message = f"Thiếu trường {field}."
            elif item["type"] == "string_type":
                message = f"Trường {field} phải là chuỗi ký tự."
            elif item["type"] == "value_error":
                message = message.removeprefix("Value error, ")
            else:
                message = "Dữ liệu yêu cầu không đúng định dạng."
            details.append(dict(loc=item["loc"], msg=message))
        return JSONResponse(status_code=422, content={"detail": details})

    @app.exception_handler(Exception)
    def unexpected_error(request, error):
        return JSONResponse(status_code=500, content={"detail": ERROR_REPLY})

    @app.exception_handler(AssessmentError)
    def assessment_error(request, error):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    @app.exception_handler(LLMError)
    def llm_error(request, error):
        return JSONResponse(status_code=503, content={"detail": LLM_REPLY})

    @app.exception_handler(ConnectionError)
    def connection_error(request, error):
        return JSONResponse(status_code=error.status, content={"detail": error.detail},
                            headers={"Cache-Control": "no-store"})

    def perform(session_id, request, action):
        with connection_manager.activate(session_id, request.headers.get("X-AI-Connection"),
                                         request.headers.get("X-AI-Model") or None):
            return action()

    @app.get("/api/connection")
    def connection_state(request: Request, session_id: str = Query(...)):
        return JSONResponse(connection_manager.describe(checked_session(session_id),
            request.headers.get("X-AI-Connection")), headers={"Cache-Control": "no-store"})

    @app.post("/api/connection")
    def connect(body: ConnectionRequest):
        return JSONResponse(connection_manager.connect(body.session_id, body.api_key),
                            headers={"Cache-Control": "no-store"})

    @app.delete("/api/connection")
    def disconnect(request: Request, session_id: str = Query(...)):
        return connection_manager.disconnect(checked_session(session_id), request.headers.get("X-AI-Connection"))

    def assessment():
        if app.state.assessment is None:
            raise HTTPException(503, "Dịch vụ đánh giá chưa sẵn sàng.")
        return app.state.assessment

    @app.post("/api/assess/start")
    def start(body: SessionRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().start(body.session_id))

    def checked_session(session_id):
        try:
            return ChatRequest.valid_session(session_id)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/assess/next")
    def next_question(session_id: str = Query(...)):
        return assessment().next(checked_session(session_id))

    @app.get("/api/assess/state")
    def assessment_state(session_id: str = Query(...)):
        return assessment().state(checked_session(session_id))

    @app.post("/api/assess/answer")
    def answer(body: AnswerRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().answer(body.session_id, body.group, body.text, body.unknown))

    @app.post("/api/assess/describe")
    def describe(body: ChatRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().describe(body.session_id, body.message))

    @app.post("/api/assess/facts")
    def facts(body: FactsRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().set_facts(body.session_id, body.facts))

    @app.post("/api/assess/run")
    def run(body: RunRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().run(body.session_id, body.statement))

    @app.post("/api/assess/check")
    def check(body: CheckRequest, request: Request):
        return perform(body.session_id, request, lambda: assessment().check(body.session_id, body.row_id, body.criterion_id, body.value))

    @app.get("/api/assess/report.md")
    def markdown(session_id: str = Query(...)):
        try:
            ChatRequest.valid_session(session_id)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return Response(assessment().markdown(session_id), media_type="text/markdown",
                        headers={"Content-Disposition": 'attachment; filename="assessment.md"'})

    @app.post("/api/chat")
    def chat(body: ChatRequest, request: Request):
        if app.state.service is None:
            with session_store.lock:
                session = session_store.get(body.session_id, create=True)
                session["messages"].append(body.message)
                session["description"] = "\n".join(session["messages"])
            raise HTTPException(503, "Chế độ chỉ đánh giá")
        kwargs = {"context": body.context.model_dump()} if body.context is not None else {}
        return perform(body.session_id, request, lambda: public_value(app.state.service.chat(body.session_id, body.message, **kwargs)))

    @app.get("/api/health")
    def health():
        if app.state.service is not None:
            result = app.state.service.health()
        else:
            settings = getattr(app.state.assessment, "settings", None)
            result = dict(status="ok", model=getattr(settings, "model", None),
                          fallback_models=list(getattr(settings, "fallback_models", ())), model_loaded=False)
        return {**{key: result[key] for key in ("status", "model", "fallback_models", "model_loaded")},
                "assessment": app.state.assessment is not None}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
