"""Đọc cấu hình LLM mà không tiết lộ giá trị bí mật trong lỗi."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class LLMSettings:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    fallback_models: tuple[str, ...] = ()
    offline: bool = False
    # Model người dùng demo được chọn theo phiên; luôn có model mặc định ở đầu.
    models: tuple[str, ...] = ()

    def __post_init__(self):
        models = dict.fromkeys(name.strip() for name in self.fallback_models
                               if name.strip() and name.strip() != self.model)
        object.__setattr__(self, "fallback_models", tuple(models))
        choices = dict.fromkeys(name.strip() for name in (self.model, *self.models) if name.strip())
        object.__setattr__(self, "models", tuple(choices))


def get_llm_settings(*, allow_missing_key=False) -> LLMSettings:
    """Nạp .env; giữ ưu tiên biến môi trường đã đặt, kể cả giá trị rỗng."""
    load_dotenv(ENV_FILE, override=False)
    names = ("RAG_LLM_MODEL", "RAG_LLM_BASE_URL", "RAG_LLM_API_KEY")
    values = [os.environ.get(name, "").strip() for name in names]
    offline = os.environ.get("RAG_LLM_OFFLINE", "").strip() == "1"
    missing = [name for name, value in zip(names, values) if not value
               and (not offline or name == "RAG_LLM_MODEL")
               and not (allow_missing_key and name == "RAG_LLM_API_KEY")]
    if missing:
        raise ValueError("Thiếu biến môi trường: " + ", ".join(missing))
    return LLMSettings(*values, fallback_models=tuple(
        os.environ.get("RAG_LLM_FALLBACK_MODELS", "").split(",")), offline=offline,
        models=tuple(os.environ.get("RAG_LLM_MODELS", "").split(",")))


@dataclass(frozen=True)
class OcrSettings:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    tesseract_exe: str
    tessdata_dir: str


def get_ocr_settings() -> OcrSettings:
    """Đọc cấu hình OCR, không đưa giá trị cấu hình vào thông báo lỗi."""
    load_dotenv(ENV_FILE, override=False)
    names = (
        "RAG_OCR_MODEL", "RAG_LLM_BASE_URL", "RAG_LLM_API_KEY",
        "RAG_TESSERACT_EXE", "RAG_TESSDATA_DIR",
    )
    values = [os.environ.get(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise ValueError("Thiếu biến môi trường: " + ", ".join(missing))
    return OcrSettings(*values)
