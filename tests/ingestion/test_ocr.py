"""OCR theo trang và nhánh dự phòng khi OCR chính bị chặn."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import pymupdf
import pytest
from legal_rag.config import OcrSettings
from legal_rag.ingestion.ocr import GeminiEngine, TesseractEngine, recognize_page, render_page
from legal_rag.ingestion.corpus import extract_corpus
from legal_rag.ingestion.normalize import apply_corrections, normalize_ocr_layout
from legal_rag.ingestion.ocr import page_cache_path
from test_corpus import BlockEngine, FakeEngine, blocked_rows, corpus  # noqa: F401


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        document.new_page(width=72, height=72)
        document.new_page(width=144, height=72)
        document.save(path)
    return path


@pytest.fixture
def settings():
    return OcrSettings("fake-model", "https://fake.invalid/v1", "fake-secret", "fake.exe", "fake-data")


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, payload):
        self.calls.append(payload)
        return "ma\u0301\r\n| x |  |\r\n"


def test_render_page_one_based_and_dpi(pdf):
    png = render_page(pdf, 2, dpi=144)
    pixmap = pymupdf.Pixmap(png)
    assert png.startswith(b"\x89PNG")
    assert (pixmap.width, pixmap.height) == (288, 144)
    for page in (0, 3):
        with pytest.raises(ValueError):
            render_page(pdf, page)


def test_cache_raw_text_and_request_contract(pdf, tmp_path, settings):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("chép nguyên văn", encoding="utf-8")
    client = FakeClient()
    engine = GeminiEngine(settings, prompt_path=prompt, client=client)
    cache = tmp_path / "cache"
    first = recognize_page(engine, pdf, 1, cache_root=cache)
    second = recognize_page(engine, pdf, 1, cache_root=cache)
    assert not first.cached and second.cached
    assert second.text == first.text == "ma\u0301\r\n| x |  |\r\n"
    assert len(client.calls) == 1
    payload = client.calls[0]
    assert payload["temperature"] == 0
    assert payload["model"] == "fake-model"
    content = payload["messages"][0]["content"]
    assert content[0]["text"] == "chép nguyên văn"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR")
    files = list((cache / "gemini").glob("*.txt"))
    key_input = {"pdf_sha256": sha256(pdf.read_bytes()).hexdigest(), "page": 1,
                 "dpi": 300, "version_key": engine.version_key}
    expected = sha256(json.dumps(key_input, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode()).hexdigest()
    assert files[0].stem == expected
    assert files[0].read_bytes() == first.text.encode("utf-8")
    assert "fake-secret" not in engine.version_key


def test_cache_changes_with_prompt_model_pdf_page_dpi(pdf, tmp_path, settings):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("v1", encoding="utf-8")
    client = FakeClient()
    engine = GeminiEngine(settings, prompt_path=prompt, client=client)
    cache = tmp_path / "cache"
    recognize_page(engine, pdf, 1, cache_root=cache)
    recognize_page(engine, pdf, 2, cache_root=cache)
    recognize_page(engine, pdf, 1, dpi=72, cache_root=cache)
    pdf.write_bytes(pdf.read_bytes() + b"\n")
    recognize_page(engine, pdf, 1, cache_root=cache)
    prompt.write_text("v2", encoding="utf-8")
    changed_prompt = GeminiEngine(settings, prompt_path=prompt, client=client)
    assert changed_prompt.version_key != engine.version_key
    recognize_page(changed_prompt, pdf, 1, cache_root=cache)
    changed_model = GeminiEngine(replace(settings, model="other-model"), prompt_path=prompt, client=client)
    assert changed_model.version_key != changed_prompt.version_key
    recognize_page(changed_model, pdf, 1, cache_root=cache)
    assert len(client.calls) == 6
    assert len(list((cache / "gemini").glob("*.txt"))) == 6


def test_tesseract_command_is_mocked(settings):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "văn bản\n".encode(), b"")

    engine = TesseractEngine(settings, runner=runner)
    assert engine.recognize(b"fake-png") == "văn bản\n"
    command, kwargs = calls[0]
    assert command == ["fake.exe", "stdin", "stdout", "-l", "vie", "--psm", "4",
                       "--tessdata-dir", "fake-data"]
    assert kwargs["input"] == b"fake-png"
    assert kwargs["capture_output"]
    assert TesseractEngine(replace(settings, tessdata_dir="other")).version_key != engine.version_key


def test_tesseract_failure_hides_key(settings):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, b"", b"failure fake-secret")

    with pytest.raises(RuntimeError) as caught:
        TesseractEngine(settings, runner=runner).recognize(b"image")
    assert "fake-secret" not in str(caught.value)


def test_failed_ocr_does_not_create_cache(pdf, tmp_path):
    class EmptyEngine:
        name, version_key = "gemini", "empty"

        def recognize(self, image_png):
            return " "

    cache = tmp_path / "cache"
    with pytest.raises(RuntimeError, match="rỗng"):
        recognize_page(EmptyEngine(), pdf, 1, cache_root=cache)
    assert not list(cache.rglob("*.txt"))


class LocalEngine:
    name, version_key = "tesseract", "local-v1"

    def __init__(self):
        self.request_count = 0

    def recognize(self, image_png):
        self.request_count += 1
        return "bản dự phòng\n"


def rows(root):
    return [json.loads(line) for line in
            (root / "data/processed/text/fake.jsonl").read_text(encoding="utf-8").splitlines()]


def test_blocked_page_falls_back_and_records_engine(corpus):
    root, _, _ = corpus
    engine, fallback = BlockEngine(), LocalEngine()
    extract_corpus(engine, root, model="fake-model", fallback=fallback)
    assert engine.request_count == 2 and fallback.request_count == 1
    assert [(r["page"], r["engine"], r["text"]) for r in rows(root)] == [
        (1, "tesseract", "bản dự phòng\n"), (2, "gemini", "full page text")]
    assert blocked_rows(root)[0]["page"] == "1"


def test_known_block_uses_fallback_without_calling_api(corpus):
    root, _, _ = corpus
    extract_corpus(BlockEngine(), root, model="fake-model", fallback=LocalEngine())
    engine, fallback = FakeEngine(), LocalEngine()
    extract_corpus(engine, root, on_block="skip", model="fake-model", fallback=fallback)
    assert engine.request_count == 0  # trang 2 đã có cache; trang 1 đã ghi bị chặn
    assert [r["engine"] for r in rows(root)] == ["tesseract", "gemini"]


def test_no_api_reads_cache_then_fallback(corpus):
    root, pdf, _ = corpus
    extract_corpus(BlockEngine(), root, model="fake-model", fallback=LocalEngine())
    engine, fallback = FakeEngine(), LocalEngine()
    extract_corpus(engine, root, no_api=True, fallback=fallback)
    assert engine.request_count == 0 and fallback.request_count == 0  # cả hai đều từ cache
    assert page_cache_path(fallback, pdf, 1, cache_root=root / ".cache/ocr").exists()
    assert [r["engine"] for r in rows(root)] == ["tesseract", "gemini"]


def test_no_api_without_fallback_or_cache_fails(corpus):
    root, _, _ = corpus
    with pytest.raises(RuntimeError, match="Thiếu cache gemini"):
        extract_corpus(FakeEngine(), root, no_api=True)
    assert not (root / "data/processed/text/fake.jsonl").exists()


def test_layout_normalization_keeps_words():
    text = "  **Điều 1. Phạm vi**  \n\n\n1.  Nội\tdung<br>trong ô\n\n**a** in **đậm** giữa dòng\n"
    assert normalize_ocr_layout(text) == (
        "Điều 1. Phạm vi\n1. Nội dung trong ô\n**a** in **đậm** giữa dòng\n")
    assert normalize_ocr_layout("má") == "má\n"


def test_corrections_apply_after_layout_only_for_ocr_pages(tmp_path):
    path = tmp_path / "text_corrections.csv"
    path.write_text("document_id,page,old,new,evidence,verified_by\n"
                    "doc,1,Hệthống,Hệ thống,ảnh PDF trang 1,người soát\n", encoding="utf-8")
    pages = [{"document_id": "doc", "page": 1, "source": "ocr", "text": "\n\n  Hệthống  \n"},
             {"document_id": "doc", "page": 2, "source": "pdf_text", "text": "  giữ  \n\n"}]
    result = apply_corrections(pages, path)
    assert [p["text"] for p in result] == ["Hệ thống\n", "  giữ  \n\n"]
    assert pages[0]["text"] == "\n\n  Hệthống  \n"  # không sửa bản gốc
