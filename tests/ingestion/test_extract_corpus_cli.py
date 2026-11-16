import importlib.util
from pathlib import Path
from unittest.mock import Mock

from legal_rag.config import OcrSettings


spec = importlib.util.spec_from_file_location(
    "extract_corpus", Path(__file__).resolve().parents[2] / "scripts/extract_corpus.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_skip_cli_keeps_http_retries_and_passes_flags(monkeypatch):
    settings = OcrSettings("fake-model", "https://fake.invalid", "fake-key", "fake.exe", "fake-data")
    client_factory, engine_factory, extract = Mock(), Mock(), Mock()
    monkeypatch.setattr(module, "get_ocr_settings", lambda: settings)
    monkeypatch.setattr(module, "HTTPChatClient", client_factory)
    monkeypatch.setattr(module, "GeminiEngine", engine_factory)
    monkeypatch.setattr(module, "extract_corpus", extract)
    monkeypatch.setattr("sys.argv", ["extract_corpus.py", "--on-block", "skip", "--retry-blocked"])
    assert module.main() == 0
    assert "max_attempts" not in client_factory.call_args.kwargs
    assert extract.call_args.kwargs["on_block"] == "skip"
    assert extract.call_args.kwargs["retry_blocked"] is True
    assert extract.call_args.kwargs["model"] == "fake-model"
