"""Render, OCR từng trang và cache bản chép nguyên văn."""

import base64
from dataclasses import dataclass
from hashlib import file_digest, sha256
import json
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Protocol

import pymupdf

from legal_rag.config import OcrSettings
from legal_rag.llm import HTTPChatClient


ROOT = Path(__file__).resolve().parents[3]
SAMPLES = (
    ("134-2025-QH15", 3, "text"),
    ("134-2025-QH15", 6, "text"),
    ("142-2026-ND-CP", 7, "text"),
    ("142-2026-ND-CP", 30, "text"),
    ("33-2026-QD-TTg", 4, "table"),
    ("33-2026-QD-TTg", 10, "table"),
)


class OcrEngine(Protocol):
    name: str
    version_key: str

    def recognize(self, image_png: bytes) -> str: ...


def _fingerprint(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def render_page(pdf_path: Path, page: int, dpi: int = 300) -> bytes:
    if page < 1 or dpi < 1:
        raise ValueError("Trang và DPI phải lớn hơn 0")
    with pymupdf.open(pdf_path) as document:
        if page > len(document):
            raise ValueError("Trang nằm ngoài PDF")
        return document[page - 1].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


class TesseractEngine:
    name = "tesseract"

    def __init__(self, settings: OcrSettings, *, runner=None):
        self._runner = runner if runner is not None else subprocess.run
        self._command = [settings.tesseract_exe, "stdin", "stdout", "-l", "vie",
                         "--psm", "4", "--tessdata-dir", settings.tessdata_dir]
        self._api_key = settings.api_key
        self.version_key = _fingerprint({"command": self._command, "version": 1})

    def recognize(self, image_png: bytes) -> str:
        try:
            result = self._runner(self._command, input=image_png, capture_output=True,
                                  timeout=180, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            message = str(error).replace(self._api_key, "[REDACTED]")
            raise RuntimeError(f"Không chạy được Tesseract: {message}") from None
        if result.returncode:
            message = result.stderr.decode("utf-8", errors="replace")
            message = message.replace(self._api_key, "[REDACTED]")
            raise RuntimeError(f"Tesseract lỗi {result.returncode}: {message}")
        return result.stdout.decode("utf-8")


class GeminiEngine:
    name = "gemini"

    def __init__(self, settings: OcrSettings, *, prompt_path=None, client=None):
        self._prompt = (prompt_path or ROOT / "prompts/ocr_v1.txt").read_text(
            encoding="utf-8"
        )
        self._model = settings.model
        self._client = client if client is not None else HTTPChatClient(
            settings.base_url, settings.api_key
        )
        self.version_key = _fingerprint({
            "model": self._model, "prompt": self._prompt, "temperature": 0,
            "base_url": settings.base_url, "format": "data-url-png", "version": 1,
        })

    def recognize(self, image_png: bytes) -> str:
        image_url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
        return self._client.complete({
            "model": self._model, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": self._prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}],
        })

    @property
    def request_count(self) -> int:
        return self._client.request_count


@dataclass(frozen=True)
class OcrResult:
    text: str
    seconds: float
    cached: bool


def page_cache_path(engine: OcrEngine, pdf_path: Path, page: int, dpi: int = 300,
                    cache_root: Path = ROOT / ".cache/ocr") -> Path:
    with pdf_path.open("rb") as source:
        pdf_hash = file_digest(source, "sha256").hexdigest()
    key = _fingerprint({"pdf_sha256": pdf_hash, "page": page, "dpi": dpi,
                        "version_key": engine.version_key})
    return cache_root / engine.name / f"{key}.txt"


def read_page_cache(path: Path) -> str | None:
    if path.exists():
        # newline="" giữ nguyên CRLF nếu phản hồi gốc có CRLF.
        with path.open(encoding="utf-8", newline="") as source:
            text = source.read()
        if text.strip():
            return text
    return None


def recognize_page(engine: OcrEngine, pdf_path: Path, page: int, dpi: int = 300,
                   cache_root: Path = ROOT / ".cache/ocr") -> OcrResult:
    started = perf_counter()
    path = page_cache_path(engine, pdf_path, page, dpi, cache_root)
    cached = read_page_cache(path)
    if cached is not None:
        return OcrResult(cached, perf_counter() - started, True)
    text = engine.recognize(render_page(pdf_path, page, dpi))
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"OCR {engine.name} trả về nội dung rỗng")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return OcrResult(text, perf_counter() - started, False)
