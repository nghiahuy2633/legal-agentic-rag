"""HTTP chat tương thích OpenAI, dùng urllib và lỗi không chứa bí mật."""

import json
import os
import hashlib
import random
import re
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class FinishReasonError(LLMError):
    pass


class CacheMissError(LLMError):
    def __init__(self):
        # Trace lưu chuỗi lỗi; giữ dấu nhận diện để kiểm tra cả các nút phụ.
        super().__init__("CacheMissError: Không có phản hồi trong cache.")


class OfflineClient:
    def complete(self, payload):
        raise CacheMissError()


class QuotaExhaustedError(LLMError):
    def __init__(self, message="HTTP 429; hết hạn mức ngày.", retry_after=None):
        super().__init__(message if "HTTP 429" in message else "HTTP 429; " + message, status=429)
        self.retry_after = retry_after


def quota_retry_after(message):
    match = re.search(r"retry in\s+(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?",
                      message, re.I)
    if not match or not any(match.groups()):
        return None
    return sum(float(value or 0) * scale for value, scale in zip(match.groups(), (3600, 60, 1)))


def normalize_usage(usage):
    """Số token từ trường usage của API; thiếu hoặc sai kiểu thì None (T62)."""
    if not isinstance(usage, dict):
        return None
    value = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
             if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)}
    return value or None


class CachedChat:
    """Cache theo toàn bộ payload; không lưu cấu hình xác thực của client."""

    def __init__(self, client, cache_dir=".cache/llm"):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.cache_hits = 0
        self.request_count = 0
        self.last_usage = None

    def _path(self, payload):
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self.cache_dir / (key + ".json")

    def lookup(self, payload):
        path = self._path(payload)
        if path.exists():
            answer = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(answer, str):
                raise ValueError("Cache LLM không phải chuỗi")
            self.cache_hits += 1
            usage_path = path.with_name(path.stem + ".usage.json")
            self.last_usage = (normalize_usage(json.loads(usage_path.read_text(encoding="utf-8")))
                               if usage_path.exists() else None)
            return answer
        return None

    def complete(self, payload):
        answer = self.lookup(payload)
        if answer is not None:
            return answer
        self.request_count += 1
        self.last_usage = None
        answer = self.client.complete(payload)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(payload)
        path.write_text(json.dumps(answer, ensure_ascii=False) + "\n", encoding="utf-8")
        self.last_usage = normalize_usage(getattr(self.client, "last_usage", None))
        if self.last_usage is not None:
            path.with_name(path.stem + ".usage.json").write_text(json.dumps(self.last_usage) + "\n", encoding="utf-8")
        return answer


class FallbackChat:
    """Ưu tiên cache mọi model trước khi gọi model theo thứ tự dự phòng."""

    def __init__(self, chat, fallback_models=(), *, clock=None):
        self.chat = chat
        self.fallback_models = tuple(fallback_models)
        self.last_model = None
        self.last_usage = None
        self.attempts = []
        self._clock = clock if clock is not None else time.monotonic
        self._quota_until = {}

    @property
    def request_count(self):
        return self.chat.request_count

    @property
    def cache_hits(self):
        return self.chat.cache_hits

    def complete(self, payload):
        self.last_model = None
        self.last_usage = None
        self.attempts = []
        models = dict.fromkeys((payload["model"], *self.fallback_models))
        for model in models:
            answer = self.chat.lookup(dict(payload, model=model))
            if answer is not None:
                self.last_model = model
                self.last_usage = getattr(self.chat, "last_usage", None)
                return answer
        last_error = None
        for model in models:
            attempt = {"model": model, "status": None}
            self.attempts.append(attempt)
            if self._quota_until.get(model, 0) > self._clock():
                attempt["status"] = "skipped_quota"
                continue
            try:
                answer = self.chat.complete(dict(payload, model=model))
            except LLMError as error:
                attempt["status"] = "finish_reason" if isinstance(error, FinishReasonError) else error.status
                if isinstance(error, QuotaExhaustedError):
                    self._quota_until[model] = self._clock() + (error.retry_after if error.retry_after is not None else 3600)
                    continue
                if not (isinstance(error, FinishReasonError) or error.status == 429
                        or error.status is not None and 500 <= error.status <= 599):
                    raise
                last_error = error
            else:
                self.last_model = model
                self.last_usage = getattr(self.chat, "last_usage", None)
                return answer
        if last_error is not None:
            raise last_error
        remaining = [max(0, self._quota_until[model] - self._clock()) for model in models]
        raise QuotaExhaustedError(retry_after=min(remaining))


class HTTPChatClient:
    def __init__(self, base_url, api_key, *, opener=None, sleep=None,
                 max_attempts=5, timeout=120, before_request=None, rate_wait_max=0):
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts phải nằm trong khoảng 1..5")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._opener = opener if opener is not None else urlopen
        self._sleep = sleep if sleep is not None else time.sleep
        self.max_attempts = max_attempts
        self.rate_wait_max = float(os.environ.get("RAG_LLM_RATE_WAIT_MAX", rate_wait_max))
        self.timeout = timeout
        self.before_request = before_request
        self.request_count = 0
        self.last_usage = None

    def complete(self, payload: dict) -> str:
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._api_key},
            method="POST",
        )
        attempt = waits = 0
        self.last_usage = None
        while attempt < self.max_attempts:
            try:
                if self.before_request is not None:
                    self.before_request()
                self.request_count += 1
                with self._opener(request, timeout=self.timeout) as response:
                    data = json.loads(response.read())
                choice = data["choices"][0]
                reason = choice.get("finish_reason")
                if reason != "stop":
                    reason = (reason if isinstance(reason, str) else "thiếu/không hợp lệ")
                    reason = reason.replace(self._api_key, "[REDACTED]")
                    raise FinishReasonError(f"finish_reason={reason}; không nhận nội dung.")
                text = choice["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError
                self.last_usage = normalize_usage(data.get("usage"))
                return text
            except HTTPError as error:
                status = error.code
                detail = ""
                message = ""
                try:
                    body = json.loads(error.read())
                    if isinstance(body, list) and len(body) == 1:
                        body = body[0]
                    message = body.get("error", {}).get("message", "")
                    if isinstance(message, str) and message:
                        detail = " " + message.replace(self._api_key, "[REDACTED]")[:2000]
                except (OSError, ValueError, AttributeError, TypeError):
                    pass
                finally:
                    error.close()
                if status == 429 and isinstance(message, str) and "per day" in message.lower():
                    raise QuotaExhaustedError(f"HTTP 429;{detail}", quota_retry_after(message)) from None
                delay = quota_retry_after(message) if isinstance(message, str) else None
                if status == 429 and self.rate_wait_max > 0 and delay is not None and delay <= self.rate_wait_max and waits < 5:
                    waits += 1
                    self._sleep(delay + 1)
                    continue
                retryable = status == 429 or 500 <= status <= 599
                if retryable and attempt + 1 < self.max_attempts:
                    self._sleep(2 ** attempt + random.uniform(0, 1))
                    attempt += 1
                    continue
                advice = (" Nhà cung cấp quá tải; có thể thử lại sau." if status == 503 else
                          " Nhà cung cấp giới hạn tần suất; có thể thử lại sau." if status == 429 else "")
                raise LLMError(
                    f"HTTP {status}; đã gọi {attempt + 1} lần.{advice}{detail}", status=status
                ) from None
            except (URLError, OSError, TimeoutError):
                if attempt + 1 < self.max_attempts:
                    self._sleep(2 ** attempt + random.uniform(0, 1))
                    attempt += 1
                    continue
                raise LLMError("Không kết nối được endpoint LLM.") from None
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError("Phản hồi LLM không có nội dung text hợp lệ.") from None
