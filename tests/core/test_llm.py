from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from legal_rag.llm import HTTPChatClient, LLMError


def response(text="bản chép"):
    return BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": text}}]}).encode())


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_stops_after_five_attempts(status):
    attempts, waits = [], []

    def opener(request, **kwargs):
        attempts.append(request)
        raise HTTPError(request.full_url, status, "fake-secret", {}, BytesIO(b"fake-secret"))

    client = HTTPChatClient("https://fake.invalid/v1", "fake-secret", opener=opener, sleep=waits.append)
    with pytest.raises(LLMError) as caught:
        client.complete({})
    assert len(attempts) == 5
    assert len(waits) == 4
    assert all(base <= wait <= base + 1 for base, wait in zip([1, 2, 4, 8], waits))
    assert f"HTTP {status}" in str(caught.value)
    assert caught.value.status == status
    assert "fake-secret" not in str(caught.value)


def test_retry_then_success():
    attempts, waits = [], []

    def opener(request, **kwargs):
        attempts.append(request)
        if len(attempts) == 1:
            raise HTTPError(request.full_url, 429, "rate limit", {}, BytesIO())
        assert request.full_url == "https://fake.invalid/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer fake-secret"
        assert json.loads(request.data) == {"temperature": 0}
        return response()

    client = HTTPChatClient("https://fake.invalid/v1/", "fake-secret", opener=opener, sleep=waits.append)
    assert client.complete({"temperature": 0}) == "bản chép"
    assert len(attempts) == 2
    assert len(waits) == 1 and 1 <= waits[0] <= 2


@pytest.mark.parametrize("error", [
    HTTPError("https://fake.invalid", 401, "fake-secret", {}, BytesIO(b"fake-secret")),
])
def test_nonretryable_errors_hide_secret(error):
    attempts = []

    def opener(*args, **kwargs):
        attempts.append(1)
        raise error

    with pytest.raises(LLMError) as caught:
        HTTPChatClient("https://fake.invalid", "fake-secret", opener=opener).complete({})
    assert len(attempts) == 1
    assert "fake-secret" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("body", [b"fake-secret", b"{}", b'{"choices": []}',
                                  b'{"choices":[{"message":{"content":null}}]}'])
def test_invalid_response_does_not_leak(body):
    client = HTTPChatClient("https://fake.invalid", "fake-secret",
                            opener=lambda *a, **k: BytesIO(body))
    with pytest.raises(LLMError) as caught:
        client.complete({})
    assert "fake-secret" not in str(caught.value)


def test_quota_message_is_available_without_key():
    def opener(request, **kwargs):
        body = json.dumps({"error": {"message": "Quota exhausted for fake-secret"}}).encode()
        raise HTTPError(request.full_url, 429, "quota", {}, BytesIO(body))

    client = HTTPChatClient("https://fake.invalid", "fake-secret", opener=opener,
                            max_attempts=1)
    with pytest.raises(LLMError) as caught:
        client.complete({})
    assert "Quota exhausted" in str(caught.value)
    assert "fake-secret" not in str(caught.value)
