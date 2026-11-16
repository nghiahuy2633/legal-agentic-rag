"""Kết nối AI cá nhân theo phiên: khóa và cache chỉ ở RAM, không vào trace."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import secrets
from threading import RLock
import time
from urllib.parse import urlsplit

from legal_rag.llm import FallbackChat, HTTPChatClient, LLMError


_active_chat = ContextVar("personal_ai_chat", default=None)
_active_model = ContextVar("selected_ai_model", default=None)


def active_model(default=None):
    """Model phiên đang chọn trong thao tác HTTP hiện tại, nếu có."""
    return _active_model.get() or default


class ConnectionError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


class MemoryCache:
    """Cache hữu hạn của một kết nối; không chia sẻ kết quả giữa các khóa."""
    def __init__(self, client, limit=128):
        self.client, self.limit = client, limit
        self.items = OrderedDict()
        self.cache_hits = self.request_count = 0

    def lookup(self, payload):
        key = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if key in self.items:
            self.cache_hits += 1
            self.items.move_to_end(key)
            return self.items[key]
        return None

    def complete(self, payload):
        cached = self.lookup(payload)
        if cached is not None:
            return cached
        self.request_count += 1
        answer = self.client.complete(payload)
        key = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        self.items[key] = answer
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return answer


class RoutedChat:
    """Graph và assessment giữ cùng proxy, chọn client ở từng thao tác HTTP."""
    def __init__(self, default):
        self.default = default

    def __getattr__(self, name):
        return getattr(_active_chat.get() or self.default, name)

    def complete(self, payload):
        # Model chọn theo phiên thay model mặc định; FallbackChat vẫn dự phòng như cũ.
        model = _active_model.get()
        return (_active_chat.get() or self.default).complete(dict(payload, model=model) if model else payload)


@dataclass(repr=False)
class PersonalConnection:
    chat: object = field(repr=False)
    token: str = field(repr=False)
    touched: float


class ConnectionManager:
    def __init__(self, settings=None, client_factory=HTTPChatClient, clock=time.monotonic,
                 ttl=3600, limit=200):
        self.settings, self.client_factory, self.clock = settings, client_factory, clock
        self.ttl, self.limit = ttl, limit
        self.entries = OrderedDict()
        self.lock = RLock()

    def _expire(self):
        now = self.clock()
        for key in list(self.entries):
            if now - self.entries[key].touched >= self.ttl:
                del self.entries[key]

    def describe(self, session_id, token=None):
        with self.lock:
            self._expire()
            entry = self.entries.get(session_id)
            connected = bool(entry and token and secrets.compare_digest(entry.token, token))
            provider = urlsplit(self.settings.base_url).hostname if self.settings else None
            return dict(available=bool(self.settings and not self.settings.offline),
                        system_available=bool(self.settings and (self.settings.api_key or self.settings.offline)),
                        provider=provider, model=self.settings.model if self.settings else None,
                        models=list(self.settings.models) if self.settings else [],
                        mode="personal" if connected else "system", connected=connected,
                        reconnect_required=bool((entry or token) and not connected), expires_in=self.ttl)

    def connect(self, session_id, api_key):
        if self.settings is None or self.settings.offline:
            raise ConnectionError(503, "Máy chủ chưa có nhà cung cấp AI trực tuyến để kết nối.")
        client = self.client_factory(self.settings.base_url, api_key, max_attempts=1, timeout=20)
        try:
            # Luôn gọi nhà cung cấp để kiểm tra khóa, không dùng cache hệ thống.
            client.complete(dict(model=self.settings.model, temperature=0, max_tokens=8,
                messages=[dict(role="user", content="Trả lời một từ: OK")]))
        except LLMError as error:
            if error.status in (401, 403):
                raise ConnectionError(401, "Khóa không hợp lệ hoặc không có quyền dùng model này.") from None
            if error.status == 429:
                raise ConnectionError(429, "Khóa đang bị giới hạn hoặc đã hết hạn mức. Vui lòng thử lại sau.") from None
            raise ConnectionError(503, "Chưa kết nối được nhà cung cấp AI. Kiểm tra khóa và thử lại.") from None
        chat = FallbackChat(MemoryCache(client), self.settings.fallback_models)
        token = secrets.token_urlsafe(32)
        with self.lock:
            self._expire()
            self.entries[session_id] = PersonalConnection(chat, token, self.clock())
            self.entries.move_to_end(session_id)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
        return {**self.describe(session_id, token), "connection_token": token}

    def disconnect(self, session_id, token=None):
        with self.lock:
            self._expire()
            entry = self.entries.get(session_id)
            if entry and (not token or not secrets.compare_digest(entry.token, token)):
                raise ConnectionError(401, "Kết nối đã thay đổi. Nhập lại khóa hoặc bắt đầu phiên mới.")
            self.entries.pop(session_id, None)
        return self.describe(session_id)

    @contextmanager
    def activate(self, session_id, token=None, model=None):
        if model is not None and (self.settings is None or model not in self.settings.models):
            raise ConnectionError(400, "Model đã chọn không có trong danh sách cho phép. Chọn lại trong Kết nối AI.")
        with self.lock:
            self._expire()
            entry = self.entries.get(session_id)
            if not entry and not token and self.settings and not self.settings.api_key and not self.settings.offline:
                raise ConnectionError(401, "Chưa có khóa AI. Mở Kết nối AI và nhập khóa cá nhân để tiếp tục.")
            if entry or token:
                if not entry or not token or not secrets.compare_digest(entry.token, token):
                    raise ConnectionError(401, "Kết nối cá nhân đã hết hạn hoặc thay đổi. Hãy kết nối lại trong Kết nối AI.")
                entry.touched = self.clock()
                self.entries.move_to_end(session_id)
            context = _active_chat.set(entry.chat if entry else None)
            model_context = _active_model.set(model)
        try:
            yield
        finally:
            _active_model.reset(model_context)
            _active_chat.reset(context)

    def clear(self):
        with self.lock:
            self.entries.clear()
