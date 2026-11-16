import pytest

from legal_rag import config


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    for name in ("RAG_LLM_MODEL", "RAG_LLM_BASE_URL", "RAG_LLM_API_KEY",
                 "RAG_LLM_FALLBACK_MODELS", "RAG_OCR_MODEL", "RAG_TESSERACT_EXE", "RAG_TESSDATA_DIR"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    return path


def test_dotenv_and_environment_priority(env_file, monkeypatch):
    env_file.write_text(
        "RAG_LLM_MODEL=file-model\n"
        "RAG_LLM_BASE_URL=https://fake.invalid/api\n"
        "RAG_LLM_API_KEY=fake-file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_LLM_MODEL", "env-model")
    settings = config.get_llm_settings()
    assert settings.model == "env-model"
    assert settings.base_url == "https://fake.invalid/api"
    assert settings.api_key == "fake-file-key"
    assert "fake-file-key" not in repr(settings)
    assert settings.fallback_models == ()


def test_fallback_models_normalized(env_file, monkeypatch):
    env_file.write_text(
        "RAG_LLM_MODEL=main\nRAG_LLM_BASE_URL=https://fake.invalid\n"
        "RAG_LLM_API_KEY=fake-key\nRAG_LLM_FALLBACK_MODELS= main, second ,, third,second ,\n",
        encoding="utf-8")
    assert config.get_llm_settings().fallback_models == ("second", "third")
    monkeypatch.setenv("RAG_LLM_FALLBACK_MODELS", " third, main, third , fourth ")
    assert config.get_llm_settings().fallback_models == ("third", "fourth")
    monkeypatch.setenv("RAG_LLM_FALLBACK_MODELS", "")
    assert config.get_llm_settings().fallback_models == ()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_error_does_not_leak_other_values(env_file, monkeypatch, key):
    monkeypatch.setenv("RAG_LLM_MODEL", "private-fake-model")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "https://private-fake.invalid")
    if key is not None:
        monkeypatch.setenv("RAG_LLM_API_KEY", key)
    with pytest.raises(ValueError) as caught:
        config.get_llm_settings()
    message = str(caught.value)
    assert "RAG_LLM_API_KEY" in message
    assert "private-fake-model" not in message
    assert "https://private-fake.invalid" not in message


def test_all_missing_names_reported(env_file):
    with pytest.raises(ValueError) as caught:
        config.get_llm_settings()
    for name in ("RAG_LLM_MODEL", "RAG_LLM_BASE_URL", "RAG_LLM_API_KEY"):
        assert name in str(caught.value)


def test_empty_environment_not_overwritten(env_file, monkeypatch):
    env_file.write_text("RAG_LLM_API_KEY=fake-key\n", encoding="utf-8")
    monkeypatch.setenv("RAG_LLM_MODEL", "fake-model")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "https://fake.invalid")
    monkeypatch.setenv("RAG_LLM_API_KEY", "")
    with pytest.raises(ValueError, match="RAG_LLM_API_KEY"):
        config.get_llm_settings()


def test_ocr_settings_priority_and_key_repr(env_file, monkeypatch):
    env_file.write_text(
        "RAG_OCR_MODEL=file-ocr\nRAG_LLM_BASE_URL=https://fake.invalid\n"
        "RAG_LLM_API_KEY=fake-key\nRAG_TESSERACT_EXE=fake.exe\nRAG_TESSDATA_DIR=fake-data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_OCR_MODEL", "env-ocr")
    settings = config.get_ocr_settings()
    assert settings.model == "env-ocr"
    assert settings.tesseract_exe == "fake.exe"
    assert settings.tessdata_dir == "fake-data"
    assert settings.api_key == "fake-key"
    assert "fake-key" not in repr(settings)


def test_ocr_missing_names_and_no_values_in_error(env_file, monkeypatch):
    monkeypatch.setenv("RAG_OCR_MODEL", "private-model")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "private-url")
    with pytest.raises(ValueError) as caught:
        config.get_ocr_settings()
    message = str(caught.value)
    for name in ("RAG_LLM_API_KEY", "RAG_TESSERACT_EXE", "RAG_TESSDATA_DIR"):
        assert name in message
    assert "private-model" not in message
    assert "private-url" not in message
