"""T15: khung cố định, định tuyến và lỗi với HTTP giả."""

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
from urllib.error import HTTPError

import pytest

from legal_rag.generation.citations import check_answer, check_blocks
from legal_rag.generation.evidence import build_evidence, format_evidence
from legal_rag.generation.prompt import build_messages
from legal_rag.knowledge.frame import is_broad_obligation_query, load_frame
from legal_rag.llm import HTTPChatClient
from test_basic_rag import cli_root, FakePipeline, load_ask

ROOT = Path(__file__).resolve().parents[2]
FRAME = ROOT / "src/legal_rag/knowledge/core_frame.yaml"
LABELS = ["Hành vi bị cấm", "Phân loại và thông báo", "Nghĩa vụ theo mức rủi ro", "Nghĩa vụ chung"]


@pytest.mark.parametrize("query,expected", [
    ("Một sản phẩm AI cần có những nghĩa vụ gì?", True),
    ("lam AI can tuan thu nhung gi vay", True),
    ("làm app AI thì cần lưu ý luật gì", True),
    ("Hệ thống AI cần tuân thủ gì", True),
    ("Chatbot bán hàng của tôi cần tuân thủ gì", False),
    ("Các mức phân loại rủi ro gồm những mức nào?", False),
    ("Điều 9 Luật 134 có nghĩa vụ gì", False),
    ("Giá vàng hôm nay bao nhiêu?", False),
    ("", False), ("AI", False), ("AI cần lưu ý dữ liệu", False),
    ("AI cần, tuân thủ gì?", True),
])
def test_query_rules(query, expected):
    assert is_broad_obligation_query(query) is expected
    assert is_broad_obligation_query(unicodedata.normalize("NFD", query.upper())) is expected


def real_parents():
    return [json.loads(line) for line in (ROOT / "data/processed/parents.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]


def test_frame_real_parents_order_and_missing():
    blocks = load_frame(FRAME, real_parents())
    assert [b["key"] for b in blocks] == ["cam", "phan_loai", "theo_muc", "chung"]
    assert [b["label"] for b in blocks] == LABELS
    expected = [[(7, n) for n in range(1, 7)], [(9, 1), (10, 1), (10, 2), (10, 3)],
                [(13, 1), (14, 1), (14, 2), (15, 1), (15, 2)],
                [(11, n) for n in range(1, 6)] + [(12, 1), (12, 2)]]
    assert [[p["parent_id"] for p in b["parents"]] for b in blocks] == [
        [f"134-2025-QH15_dieu-{a}_khoan-{c}" for a, c in group] for group in expected]
    with pytest.raises(ValueError, match="134-2025-QH15_dieu-7_khoan-1"):
        load_frame(FRAME, {})


def broad_root(tmp_path):
    root = cli_root(tmp_path)
    (root / "data/processed/parents.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in real_parents()), encoding="utf-8")
    # Dùng registry và chunks thật để kiểm vị trí, vẫn không tạo pipeline.
    (root / "data/source_registry/documents.csv").write_bytes(
        (ROOT / "data/source_registry/documents.csv").read_bytes())
    (root / "data/processed/chunks.jsonl").write_bytes(
        (ROOT / "data/processed/chunks.jsonl").read_bytes())
    target = root / "src/legal_rag/knowledge/core_frame.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(FRAME.read_bytes())
    return root


def forbidden(*args):
    pytest.fail("Không được tạo pipeline hoặc client LLM")


def test_broad_evidence_only_skips_pipeline_models_settings(tmp_path, monkeypatch, capsys):
    ask = load_ask()
    monkeypatch.setattr(ask, "get_llm_settings", forbidden)
    root = broad_root(tmp_path)
    assert ask.main(["--query", "Một sản phẩm AI cần có những nghĩa vụ gì?",
                     "--budget", "0", "--evidence-only"], root, forbidden, forbidden) == 0
    record = json.loads(next((root / "runs/traces").glob("*.json")).read_text(encoding="utf-8"))
    assert record["route"] == "broad_frame" and record["retrieval_config"] is None
    expected = [p["parent_id"] for b in load_frame(FRAME, real_parents()) for p in b["parents"]]
    assert [i["parent_id"] for i in record["evidence"]] == expected
    assert list(dict.fromkeys(i["block"] for i in record["evidence"])) == LABELS
    assert len(record["evidence"]) == 22
    output = capsys.readouterr().out
    assert all(f"Nhóm: {label}" in output for label in LABELS)


@pytest.mark.parametrize("answer,missing", [
    ("Nội dung [E1, E2][E3][E4]", []),
    ("Nội dung [E1, E2]", LABELS[2:]),
    ("Không có căn cứ", LABELS),
])
def test_check_blocks(answer, missing):
    blocks = load_frame(FRAME, real_parents())
    documents = {"134-2025-QH15": dict(document_number="134/2025/QH15", document_title="Luật",
                                        official_source_url="https://example.invalid")}
    items = build_evidence([dict(b["parents"][0], block=b["label"]) for b in blocks], documents)
    assert check_blocks(check_answer(answer, items), items) == missing
    assert check_blocks(check_answer("Kết luận [E1]", items), [dict(items[0], block=LABELS[0]),
                        dict(items[0], id="E5", block=LABELS[0])]) == []
    assert "Nhóm:" in format_evidence(items)


def test_prompt_v3_preserves_v2_rules():
    v3 = build_messages("q", [], version="answer_v3")["messages"][0]["content"]
    v2 = build_messages("q", [], version="answer_v2")["messages"][0]["content"]
    assert v3.startswith("Phiên bản: answer_v3\n") and v2.startswith("Phiên bản: answer_v2\n")
    assert "Nhóm:" in v3 and "Nhóm:" not in v2
    assert v2.split("\n", 1)[1] in v3
    assert build_messages("q", [], version="answer_v1")["messages"][0]["content"].startswith(
        "Phiên bản: answer_v1\n")


@pytest.mark.parametrize("status,phrase", [(503, "quá tải"), (429, "giới hạn tần suất")])
def test_http_error_trace_redacts_key_and_retries(tmp_path, monkeypatch, capsys, status, phrase):
    ask, waits, attempts = load_ask(), [], []
    secret = "t15-private-key"
    monkeypatch.setattr(ask, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://example.invalid", api_key=secret, model="fake"))
    def opener(request, **kwargs):
        attempts.append(1)
        body = json.dumps({"error": {"message": "Provider: " + secret}}).encode()
        raise HTTPError(request.full_url, status, secret, {}, BytesIO(body))
    def client(url, key):
        return HTTPChatClient(url, key, opener=opener, sleep=waits.append)
    root = broad_root(tmp_path)
    assert ask.main(["--query", "AI cần tuân thủ gì"], root, forbidden, client) == 1
    output = capsys.readouterr().err
    assert phrase in output and "thử lại sau" in output and f"HTTP {status}" in output
    assert secret not in output
    path = next((root / "runs/traces").glob("*.json"))
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw and "api_key" not in raw
    record = json.loads(raw)
    assert record["answer"] is record["check"] is None
    assert phrase in record["error"] and "[REDACTED]" in record["error"]
    assert record["route"] == "broad_frame" and record["messages"] and record["evidence"]
    assert record["llm_calls"] == 1 and len(attempts) == 5
    assert len(waits) == 4
    assert all(base <= wait <= base + 1 for base, wait in zip([1, 2, 4, 8], waits))


def test_cli_missing_block_invalidates_answer(tmp_path, monkeypatch, capsys):
    ask = load_ask()
    monkeypatch.setattr(ask, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://example.invalid", api_key="secret", model="fake"))
    client = lambda *args: SimpleNamespace(complete=lambda payload: "Kết luận [E1]")
    root = broad_root(tmp_path)
    assert ask.main(["--query", "AI cần tuân thủ gì"], root, forbidden, client) == 0
    record = json.loads(next((root / "runs/traces").glob("*.json")).read_text(encoding="utf-8"))
    assert record["route"] == "broad_frame" and record["prompt_version"] == "answer_v7"
    assert record["check"]["valid"] is False
    assert record["check"]["missing_blocks"] == LABELS[1:]
    assert '"missing_blocks"' in capsys.readouterr().out


def test_non_llm_error_trace_hides_arbitrary_details(tmp_path, monkeypatch, capsys):
    ask = load_ask()
    monkeypatch.setattr(ask, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://example.invalid", api_key="secret", model="fake"))
    def client(*args):
        raise ValueError("secret arbitrary error")
    root = cli_root(tmp_path)
    assert ask.main(["--query", "q", "--budget", "123"], root, FakePipeline, client) == 1
    record = json.loads(next((root / "runs/traces").glob("*.json")).read_text(encoding="utf-8"))
    assert record["route"] == "retrieval" and record["answer"] is record["check"] is None
    assert "secret" not in record["error"] + capsys.readouterr().err
