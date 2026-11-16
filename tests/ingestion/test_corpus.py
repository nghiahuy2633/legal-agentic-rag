import csv
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import Mock
import unicodedata

import pymupdf
import pytest

from legal_rag.config import OcrSettings
from legal_rag.ingestion.corpus import RequestPacer, extract_corpus
from legal_rag.ingestion.ocr import GeminiEngine, page_cache_path, recognize_page
from legal_rag.llm import FinishReasonError, HTTPChatClient


@pytest.fixture
def corpus(tmp_path):
    pdf = tmp_path / "fake.pdf"
    with pymupdf.open() as document:
        for _ in range(3):
            document.new_page(width=72, height=72).insert_text((2, 20), "1\nText with newline")
        document.save(pdf)
    registry = tmp_path / "data/source_registry/documents.csv"
    registry.parent.mkdir(parents=True)
    with registry.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("document_id", "pdf_path", "pdf_sha256", "body_last_page"))
        writer.writerow(("fake", "fake.pdf", sha256(pdf.read_bytes()).hexdigest(), 2))
    inventory = tmp_path / "data/processed/page_inventory.csv"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("document_id,page,kind,content_chars\nfake,1,scan,0\nfake,2,scan,0\nfake,3,scan,0\n", encoding="utf-8")
    return tmp_path, pdf, inventory


class FakeEngine:
    name, version_key = "gemini", "fake-v1"

    def __init__(self, failure=None):
        self.request_count = 0
        self.failure = failure

    def recognize(self, image_png):
        self.request_count += 1
        if self.request_count == self.failure:
            raise RuntimeError("fake interrupted")
        return "1\nma\u0301\r\nnguyên văn\n"


def test_limits_order_schema_and_nfc(corpus):
    root, _, _ = corpus
    engine = FakeEngine()
    extract_corpus(engine, root)
    assert engine.request_count == 2  # Trang 3 ngoài phần thân không được render/OCR.
    output = root / "data/processed/text/fake.jsonl"
    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    rows = [json.loads(line) for line in raw.splitlines()]
    assert [row["page"] for row in rows] == [1, 2]
    assert all(set(row) == {"document_id", "page", "source", "engine", "text"} for row in rows)
    assert rows[0] == {"document_id": "fake", "page": 1, "source": "ocr", "engine": "gemini",
                       "text": "1\nmá\r\nnguyên văn\n"}
    assert all(unicodedata.is_normalized("NFC", row["text"]) for row in rows)
    assert not list(output.parent.glob("*.tmp"))


def test_resume_after_failure_and_no_partial_output(corpus):
    root, _, _ = corpus
    failed = FakeEngine(failure=2)
    with pytest.raises(RuntimeError, match="fake trang 2"):
        extract_corpus(failed, root)
    output = root / "data/processed/text/fake.jsonl"
    assert not output.exists()
    resumed = FakeEngine()
    extract_corpus(resumed, root)
    assert resumed.request_count == 1
    previous = output.read_bytes()
    again = FakeEngine()
    extract_corpus(again, root)
    assert again.request_count == 0
    assert output.read_bytes() == previous


def test_failure_preserves_previous_complete_output(corpus):
    root, _, _ = corpus
    output = root / "data/processed/text/fake.jsonl"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous-complete\n")
    with pytest.raises(RuntimeError):
        extract_corpus(FakeEngine(failure=2), root)
    assert output.read_bytes() == b"previous-complete\n"


def test_missing_inventory_page_never_calls_engine_or_writes(corpus):
    root, _, inventory = corpus
    inventory.write_text("document_id,page,kind,content_chars\nfake,1,scan,0\n", encoding="utf-8")
    engine = FakeEngine()
    with pytest.raises(ValueError, match="fake trang 2"):
        extract_corpus(engine, root)
    assert engine.request_count == 0
    assert not (root / "data/processed/text/fake.jsonl").exists()


def test_text_pages_keep_entire_pdf_layer_and_never_ocr(corpus):
    root, pdf, inventory = corpus
    inventory.write_text("document_id,page,kind,content_chars\nfake,1,text,40\nfake,2,text,40\n", encoding="utf-8")
    engine = FakeEngine(failure=1)
    extract_corpus(engine, root)
    assert engine.request_count == 0
    rows = [json.loads(line) for line in (root / "data/processed/text/fake.jsonl").read_text(encoding="utf-8").splitlines()]
    with pymupdf.open(pdf) as document:
        assert rows[0]["text"] == unicodedata.normalize("NFC", document[0].get_text())
    assert all(row["source"] == "pdf_text" and row["engine"] == "pymupdf" for row in rows)


def test_dry_run_never_calls_engine_or_writes(corpus, capsys):
    root, pdf, _ = corpus
    engine = FakeEngine(failure=1)
    path = page_cache_path(engine, pdf, 1, cache_root=root / ".cache/ocr")
    path.parent.mkdir(parents=True)
    path.write_text("cached", encoding="utf-8")
    engine.recognize = Mock(side_effect=AssertionError("must not OCR"))
    extract_corpus(engine, root, dry_run=True)
    engine.recognize.assert_not_called()
    assert "cache=1; sẽ gọi API=1" in capsys.readouterr().out
    assert not (root / "data/processed/text").exists()


def test_bad_checksum_stops_before_network(corpus):
    root, pdf, _ = corpus
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    engine = FakeEngine()
    with pytest.raises(ValueError, match="SHA-256.*fake"):
        extract_corpus(engine, root)
    assert engine.request_count == 0


@pytest.mark.parametrize("reason", ["length", "content_filter", None])
def test_finish_reason_never_retries_or_caches(corpus, reason):
    root, pdf, _ = corpus
    calls, waits = [], []

    def opener(*args, **kwargs):
        calls.append(1)
        return BytesIO(json.dumps({"choices": [{"finish_reason": reason,
                              "message": {"content": "truncated text"}}]}).encode())

    settings = OcrSettings("fake", "https://fake.invalid", "fake-secret", "fake.exe", "fake-data")
    client = HTTPChatClient(settings.base_url, settings.api_key, opener=opener, sleep=waits.append)
    prompt = root / "prompt.txt"
    prompt.write_text("fake prompt", encoding="utf-8")
    engine = GeminiEngine(settings, prompt_path=prompt, client=client)
    with pytest.raises(FinishReasonError, match="finish_reason") as caught:
        recognize_page(engine, pdf, 1, cache_root=root / ".cache/ocr")
    assert str(reason) in str(caught.value) if reason is not None else "thiếu" in str(caught.value)
    assert len(calls) == client.request_count == 1
    assert not waits
    assert not list((root / ".cache/ocr").rglob("*.txt"))


def test_pacing_and_real_request_count_include_retries():
    from urllib.error import HTTPError

    waits, attempts = [], []

    def opener(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise HTTPError("https://fake.invalid", 503, "fake", {}, BytesIO())
        return BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"content":"ok"}}]}')

    client = HTTPChatClient("https://fake.invalid", "fake-secret", opener=opener,
                            sleep=waits.append, before_request=RequestPacer(5, sleep=waits.append))
    assert client.complete({}) == "ok"
    assert client.request_count == 2
    assert len(waits) == 2 and 1 <= waits[0] <= 2 and waits[1] == 5


class BlockEngine(FakeEngine):
    def recognize(self, image_png):
        self.request_count += 1
        if self.request_count == 1:
            raise FinishReasonError("finish_reason=content_filter: RECITATION; không nhận nội dung.")
        return "full page text"


def blocked_rows(root):
    with (root / "runs/ocr_blocked.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_skip_records_csv_continues_and_does_not_cache_block(corpus, capsys):
    root, pdf, _ = corpus
    engine = BlockEngine()
    extract_corpus(engine, root, on_block="skip", model="fake-model")
    assert engine.request_count == 2
    assert blocked_rows(root) == [{"document_id": "fake", "page": "1",
                                  "finish_reason": "content_filter: RECITATION", "model": "fake-model"}]
    assert not page_cache_path(engine, pdf, 1, cache_root=root / ".cache/ocr").exists()
    assert page_cache_path(engine, pdf, 2, cache_root=root / ".cache/ocr").exists()
    assert not (root / "data/processed/text/fake.jsonl").exists()
    raw = (root / "runs/ocr_blocked.csv").read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    assert "| fake | 2 | 1 | 1 | 1 | 0 | 0 |" in capsys.readouterr().out


def test_default_still_stops_at_content_filter(corpus):
    root, _, _ = corpus
    engine = BlockEngine()
    with pytest.raises(RuntimeError, match="fake trang 1.*content_filter"):
        extract_corpus(engine, root)
    assert engine.request_count == 1
    assert not (root / "runs/ocr_blocked.csv").exists()


@pytest.mark.parametrize("message", ["HTTP 429", "HTTP 503", "Không kết nối được endpoint LLM."])
def test_skip_does_not_swallow_http_or_network_errors(corpus, message):
    from legal_rag.llm import LLMError

    root, _, _ = corpus
    engine = FakeEngine()
    engine.recognize = Mock(side_effect=LLMError(message))
    with pytest.raises(RuntimeError, match=message):
        extract_corpus(engine, root, on_block="skip", model="fake-model")
    engine.recognize.assert_called_once()
    assert blocked_rows(root) == []


def test_skip_still_stops_at_length(corpus):
    root, _, _ = corpus
    engine = FakeEngine()
    engine.recognize = Mock(side_effect=FinishReasonError("finish_reason=length; không nhận nội dung."))
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        extract_corpus(engine, root, on_block="skip", model="fake-model")
    engine.recognize.assert_called_once()
    assert blocked_rows(root) == []


def test_failed_attempt_is_not_counted_as_untried(corpus, capsys):
    from legal_rag.llm import LLMError

    root, _, _ = corpus
    engine = FakeEngine()
    engine.recognize = Mock(side_effect=LLMError("HTTP 429"))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        extract_corpus(engine, root, on_block="skip", model="fake-model")
    assert "| fake | 2 | 0 | 0 | — | 1 | 1 |" in capsys.readouterr().out


def test_known_blocks_skip_repeat_retry_and_model_scope(corpus):
    root, _, _ = corpus
    extract_corpus(BlockEngine(), root, on_block="skip", model="fake-model")
    repeat = BlockEngine()
    extract_corpus(repeat, root, on_block="skip", model="fake-model")
    assert repeat.request_count == 0
    retry = BlockEngine()
    extract_corpus(retry, root, on_block="skip", retry_blocked=True, model="fake-model")
    assert retry.request_count == 1
    assert len(blocked_rows(root)) == 1
    other_model = BlockEngine()
    extract_corpus(other_model, root, on_block="skip", model="other-model")
    assert other_model.request_count == 1
    assert {row["model"] for row in blocked_rows(root)} == {"fake-model", "other-model"}


def test_retry_success_removes_record_and_writes_complete_jsonl(corpus):
    root, _, _ = corpus
    extract_corpus(BlockEngine(), root, on_block="skip", model="fake-model")
    retry = FakeEngine()
    extract_corpus(retry, root, on_block="skip", retry_blocked=True, model="fake-model")
    assert retry.request_count == 1
    assert blocked_rows(root) == []
    assert (root / "data/processed/text/fake.jsonl").exists()


def test_complete_document_after_blocked_document_is_written(corpus):
    root, _, inventory = corpus
    registry = root / "data/source_registry/documents.csv"
    with registry.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    second = dict(rows[0], document_id="complete")
    with registry.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows + [second])
    with inventory.open("a", encoding="utf-8") as stream:
        stream.write("complete,1,text,40\ncomplete,2,text,40\n")
    extract_corpus(BlockEngine(), root, on_block="skip", model="fake-model")
    assert not (root / "data/processed/text/fake.jsonl").exists()
    path = root / "data/processed/text/complete.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_dry_run_counts_known_blocks_without_network(corpus, capsys):
    root, _, _ = corpus
    extract_corpus(BlockEngine(), root, on_block="skip", model="fake-model")
    capsys.readouterr()
    engine = FakeEngine()
    extract_corpus(engine, root, on_block="skip", model="fake-model", dry_run=True)
    assert engine.request_count == 0
    assert "Tổng: 2 trang; OCR=2; pdf_text=0; cache=1; sẽ gọi API=0; đã chặn=1" in capsys.readouterr().out
