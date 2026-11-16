"""Dựng bằng chứng: cảnh báo, dự phòng, mục liệt kê, độ đủ của câu trả lời."""

from collections import Counter
import csv
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
from urllib.error import HTTPError
import pytest
from legal_rag.generation.citations import check_answer
from legal_rag.generation.evidence import build_evidence, format_evidence
from legal_rag.llm import CachedChat, FallbackChat, FinishReasonError, HTTPChatClient, LLMError
from test_basic_rag import DOCUMENTS, FakePipeline, cli_root, load_ask, parents
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.report import assemble_report, LIST_ITEM_PREFIX
from legal_rag.generation.citations import check_answer, format_citation
from legal_rag.generation.evidence import build_evidence
from legal_rag.knowledge.high_risk import FIXED_PARENTS
from legal_rag.llm import LLMError
from test_agent_graph import FakeChat, analysis
from test_map_report import fixture_data
from legal_rag.agent.answer import AGENT_ANSWER_VERSION, prepare_evidence
from legal_rag.generation.prompt import BROAD_VERSION, DEFAULT_VERSION, build_messages
from test_basic_rag import chunks, parents, DOCUMENTS


ROOT = Path(__file__).resolve().parents[2]


NOTE = "Đánh giá sự phù hợp theo điểm a, khoản 2 Điều 13 Luật Trí tuệ nhân tạo"


def read_rows(name):
    return [json.loads(line) for line in (ROOT / "data/processed" / name).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def test_all_real_list_items_conformity():
    units = [p for p in read_rows("parents.jsonl") if p["level"] == "list_item"]
    listing = {r["item_id"]: r for r in read_rows("high_risk_list.jsonl")}
    with (ROOT / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        items = build_evidence(units, list(csv.DictReader(stream)))
    assert len(items) == len(listing) == 46
    assert {item["parent_id"] for item in items} == listing.keys()
    counts = Counter()
    for unit, item in zip(units, items):
        note = item["conformity_note"]
        assert note == unit["context"].splitlines()[-1]
        conformity = listing[item["parent_id"]]["conformity"]
        assert note == NOTE.replace("điểm a", "điểm " + conformity[-1])
        counts[conformity] += 1
        assert f'Tiêu đề: {item["article_title"]}\n{note}\n{item["text"]}' in format_evidence([item])
        assert check_answer("Theo Điều 13 [" + item["id"] + "]", [item])["valid"]
    assert counts == {"diem_a": 6, "diem_b": 40}


@pytest.mark.parametrize("context", ["", "thiếu dòng", NOTE.replace("điểm a", "điểm c"),
                                          NOTE + "\nDòng khác"])
def test_list_item_requires_conformity_line(context):
    unit = parents()[0] | {"level": "list_item", "context": context}
    with pytest.raises(ValueError, match=unit["parent_id"]):
        build_evidence([unit], DOCUMENTS)


def test_other_parent_has_no_note_and_note_identifiers_are_allowed():
    item = build_evidence([parents()[0] | {"context": NOTE}], DOCUMENTS)[0]
    assert "conformity_note" not in item
    answer = "Theo Điều 13 và 13/2023/NĐ-CP [E1]"
    assert not check_answer(answer, [item])["valid"]
    item["conformity_note"] = NOTE + " và 13/2023/NĐ-CP"
    assert check_answer(answer, [item])["valid"]


@pytest.mark.parametrize("answer,phrases", [
    ("điểm a và điểm b khoản này [E1]", ["khoản này"]),
    ("Theo Điều 9 [E1]", []),
    ("Luật này quy định; Điều này áp dụng [E1]", ["luật này", "điều này"]),
    ("điểm này; khoản này; điểm này; nghị định này; thông tư này; quyết định này [E1]",
     ["điểm này", "khoản này", "nghị định này", "thông tư này", "quyết định này"]),
    ("xđiều này; điều nàyy; xluật này; luật nàyy [E1]", []),
])
def test_context_warnings_order_normalization_and_validity(answer, phrases):
    items = build_evidence([parents()[0] | {"article": "9"}], DOCUMENTS)
    for text in (answer, unicodedata.normalize("NFD", answer.upper()).replace(" ", " \n ")):
        result = check_answer(text, items)
        assert result["warnings"] == ["Cụm mất ngữ cảnh: " + phrase for phrase in phrases]
        assert result["valid"] and result["errors"] == []
    assert not check_answer(answer.replace("[E1]", "[E99]"), items)["valid"]


def fake_chat(tmp_path, outcomes, fallbacks=("backup",)):
    calls = []
    def complete(payload):
        calls.append(payload)
        outcome = outcomes[payload["model"]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    cache = CachedChat(SimpleNamespace(complete=complete), tmp_path)
    return FallbackChat(cache, fallbacks), calls


@pytest.mark.parametrize("error", [LLMError("quá tải", 503), LLMError("tần suất", 429),
                                   LLMError("máy chủ", 500), FinishReasonError("length")])
def test_retryable_failure_uses_fallback_and_resets_state(tmp_path, error):
    chat, calls = fake_chat(tmp_path, {"main": error, "backup": "trả lời"})
    payload = {"model": "main", "temperature": 0, "messages": []}
    assert chat.last_model is None
    assert chat.complete(payload) == "trả lời"
    assert chat.last_model == "backup"
    assert chat.attempts == [{"model": "main", "status": (
        "finish_reason" if isinstance(error, FinishReasonError) else error.status)},
                             {"model": "backup", "status": None}]
    assert chat.request_count == len(calls) == 2 and chat.cache_hits == 0
    assert payload["model"] == "main"
    assert chat.complete(payload) == "trả lời"
    assert chat.last_model == "backup" and chat.attempts == []
    assert chat.request_count == 2 and chat.cache_hits == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize("error", [LLMError("sai", 400), LLMError("xác thực", 401),
                                   LLMError("không thấy", 404), LLMError("kết nối"),
                                   ValueError("lỗi khác")])
def test_nonretryable_failure_propagates_immediately(tmp_path, error):
    chat, calls = fake_chat(tmp_path, {"main": error, "backup": "không được gọi"})
    with pytest.raises(type(error)) as caught:
        chat.complete({"model": "main"})
    assert caught.value is error
    assert [p["model"] for p in calls] == ["main"]
    assert chat.last_model is None and len(chat.attempts) == 1
    assert list(tmp_path.iterdir()) == []


def test_exhausted_models_raise_last_error_and_no_fallback(tmp_path):
    first, last = LLMError("đầu", 503), LLMError("cuối", 502)
    chat, calls = fake_chat(tmp_path, {"main": first, "backup": last})
    with pytest.raises(LLMError) as caught:
        chat.complete({"model": "main"})
    assert caught.value is last and chat.last_model is None
    assert chat.attempts == [{"model": "main", "status": 503}, {"model": "backup", "status": 502}]
    assert len(calls) == 2 and list(tmp_path.iterdir()) == []
    chat, calls = fake_chat(tmp_path, {"main": first}, fallbacks=())
    with pytest.raises(LLMError) as caught:
        chat.complete({"model": "main"})
    assert caught.value is first and len(calls) == 1


def test_lookup_never_calls_client_and_prefers_primary_cache(tmp_path):
    chat, calls = fake_chat(tmp_path, {"main": "chính", "backup": "phụ"})
    assert chat.chat.lookup({"model": "main"}) is None and calls == []
    chat.chat.complete({"model": "backup"})
    assert chat.complete({"model": "main"}) == "phụ"
    assert len(calls) == 1 and chat.last_model == "backup" and chat.attempts == []
    chat.chat.complete({"model": "main"})
    assert chat.complete({"model": "main"}) == "chính"
    assert len(calls) == 2 and chat.last_model == "main"


@pytest.mark.parametrize("backup_status", [None, 503, 404])
def test_cli_fallback_trace_success_error_and_cache(tmp_path, monkeypatch, backup_status):
    ask, requests, options = load_ask(), [], []
    secret = "t16-private-key"
    monkeypatch.setattr(ask, "get_llm_settings", lambda: SimpleNamespace(
        base_url="https://fake.invalid", api_key=secret, model="main", fallback_models=("backup",)))
    def opener(request, **kwargs):
        model = json.loads(request.data)["model"]
        requests.append(model)
        status = 503 if model == "main" else backup_status
        if status:
            body = json.dumps({"error": {"message": secret}}).encode()
            raise HTTPError(request.full_url, status, secret, {}, BytesIO(body))
        return BytesIO(json.dumps({"choices": [{"finish_reason": "stop",
                         "message": {"content": "Kết luận [E1]"}}]}).encode())
    def client(url, key, **kwargs):
        options.append(kwargs)
        return HTTPChatClient(url, key, opener=opener, sleep=lambda _: None, **kwargs)
    root = cli_root(tmp_path)
    expected = 1 if backup_status else 0
    assert ask.main(["--query", "q", "--budget", "123"], root, FakePipeline, client) == expected
    path = next((root / "runs/traces").glob("*.json"))
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw and "api_key" not in raw and "base_url" not in raw
    record = json.loads(raw)
    assert record["model"] == (None if backup_status else "backup")
    assert record["llm_attempts"] == [{"model": "main", "status": 503},
                                       {"model": "backup", "status": backup_status}]
    assert options == [{"max_attempts": 3}]
    assert requests == ["main"] * 3 + ["backup"] * (3 if backup_status == 503 else 1)
    assert record["llm_calls"] == 2
    if backup_status:
        assert record["answer"] is record["check"] is None
    else:
        assert record["answer"] == "Kết luận [E1]"
        assert ask.main(["--query", "q", "--budget", "123"], root, FakePipeline, client) == 0
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (root / "runs/traces").glob("*.json")]
        cached = next(r for r in records if r["cache_hits"] == 1)
        assert cached["model"] == "backup" and cached["llm_attempts"] == [] and cached["llm_calls"] == 0
        assert len(requests) == 4


ITEM = LIST_ITEM_PREFIX + 'II_stt-1'


OTHER = LIST_ITEM_PREFIX + 'II_stt-2'


def make_case(status='dap_ung', *, enabled=True, error=False, retrieved=True, hits=True):
    parents, documents, _, chunks = fixture_data()
    for key in (ITEM, OTHER):
        parents.append(dict(parents[2], parent_id=key, level='list_item', article=None,
                            title='Mục ' + key, text='Điều kiện riêng ' + key))
    items = [dict(item_id=ITEM, name='Robot', sector='Y tế', stt='1', description='Điều kiện riêng ' + ITEM)]
    responses = [analysis(request_kinds=['nghia_vu'], profile_update={'product_description': 'Robot y tế'}, sub_queries=['gốc'])]
    if enabled and hits:
        responses.append(LLMError('lỗi đối chiếu') if error else dict(items=[dict(
            item_id=ITEM, object_match=dict(status='phu_hop', basis='Robot y tế', missing_info=[]),
            conditions=[dict(index=1, status=status, basis='Mô tả')])]))
    responses.append('Nội dung [E1].')
    chat = FakeChat(*responses)

    def prepare(message, queries, **kwargs):
        # Mục bị tách nằm giữa và cuối để bắt lỗi đổi/cấp lại mã E.
        units = [parents[0], parents[-2], parents[1], parents[-1]] if retrieved else parents[:1]
        evidence = build_evidence(units, documents)
        return dict(evidence=evidence, queries=queries, query_used=queries[0], references_added=[],
                    detail={}, timing={}, route='retrieval', prompt_version='answer_v8',
                    parents_used=[p['parent_id'] for p in units])

    graph = build_graph(GraphDeps(chat, 'fake', prepare,
        config=AgentConfig(enable_high_risk=enabled, enable_rewrite=False, enable_verifier=False),
        pipeline_factory=lambda: SimpleNamespace(search=lambda q: [{'chunk_id': ITEM}] if hits else []),
        parents=parents, documents=documents, high_risk_loader=lambda: items,
        obligations_loader=lambda: [], chunks_loader=lambda: chunks))
    return graph, chat, parents, documents


@pytest.mark.parametrize('status,expected', [
    ('dap_ung', 'khop'), ('chua_ro', 'co_the_khop'), ('khong_dap_ung', 'khong_thay')])
def test_removed_for_every_status(status, expected):
    graph, chat, _, _ = make_case(status)
    result = run_turn(graph, 's', 'Robot có rủi ro cao không?')
    assert result['high_risk']['status'] == expected
    assert [e['id'] for e in result['evidence']] == ['E1', 'E3', 'E5', 'E6', 'E7']
    assert [e['parent_id'] for e in result['evidence'][2:]] == list(FIXED_PARENTS)
    assert all(e['source'] == 'high_risk' for e in result['evidence'][2:])
    payload = str(chat.payloads[-1]['messages'])
    assert ITEM not in payload and OTHER not in payload
    node = next(n for n in result['trace'] if n['node'] == 'check_high_risk')
    assert node['removed_list_items'] == [ITEM, OTHER]
    state = graph.get_state({'configurable': {'thread_id': 's'}}).values
    assert [e['id'] for e in state['high_risk_items']] == ['E2', 'E4']
    assert state['prepared']['evidence'] == result['evidence']
    assert state['prepared']['parents_used'] == [e['parent_id'] for e in result['evidence']]
    check = check_answer('Nội dung [E2] và [E4].', result['evidence'])
    assert not check['valid']
    assert 'Trích dẫn không tồn tại: [E2]' in check['errors']
    assert 'Trích dẫn không tồn tại: [E4]' in check['errors']
    references = result['reply'].split('## Căn cứ pháp lý')[1]
    assert OTHER not in references
    assert ITEM in references
    line = next(line for line in references.splitlines() if ITEM in line)
    assert '[E' not in line


@pytest.mark.parametrize('mode', ['disabled', 'skipped', 'error'])
def test_no_result_preserves_items(mode):
    graph, chat, _, _ = make_case(enabled=mode != 'disabled', error=mode == 'error')
    if mode == 'skipped':
        chat.responses = iter([analysis(sub_queries=['gốc']), 'Nội dung [E1].'])
    result = run_turn(graph, 's', 'Robot có rủi ro cao không?')
    assert result['high_risk'] is None
    assert bool(result['high_risk_error']) == (mode == 'error')
    assert [e['id'] for e in result['evidence']] == ['E1', 'E2', 'E3', 'E4']
    assert ITEM in str(chat.payloads[-1]['messages'])
    assert graph.get_state({'configurable': {'thread_id': 's'}}).values['high_risk_items'] == []


def test_no_candidates_still_removes_and_next_turn_resets():
    graph, chat, _, _ = make_case(hits=False)
    first = run_turn(graph, 's', 'Robot có rủi ro cao không?')
    assert first['high_risk']['status'] == 'chua_du_co_so'
    assert not any(e['parent_id'].startswith(LIST_ITEM_PREFIX) for e in first['evidence'])
    chat.responses = iter([analysis(sub_queries=['gốc']), 'Nội dung [E1].'])
    second = run_turn(graph, 's', 'Robot cần tuân thủ điều gì?')
    assert second['high_risk'] is None
    assert ITEM in str(chat.payloads[-1]['messages'])
    assert graph.get_state({'configurable': {'thread_id': 's'}}).values['high_risk_items'] == []


def test_llm_citing_removed_code_is_rejected():
    graph, chat, _, _ = make_case()
    initial = list(chat.responses)[:2]
    chat.responses = iter([*initial, 'Nội dung [E2].', 'Vẫn trích [E2].'])
    result = run_turn(graph, 's', 'Robot có rủi ro cao không?')
    assert not result['check']['valid']
    assert 'Trích dẫn không tồn tại: [E2]' in result['check']['errors']
    assert result['verification']['repaired']
    assert ITEM not in str(chat.payloads[-1]['messages'])


def test_report_fallback_and_parent_order():
    _, _, parents, documents = make_case()
    saved = build_evidence([parents[-2]], documents)
    expected = build_evidence([parents[-1], parents[-2]], documents)
    # OTHER không có trong mục đã tách: phải dựng từ parent và registry.
    for parent_registry in (parents, {p['parent_id']: p for p in parents}):
        report = assemble_report('Nội dung', ['[E1] Căn cứ'],
            dict(text='Đối chiếu', parent_ids=[OTHER, *FIXED_PARENTS, ITEM]),
            saved, parent_registry, documents)
        lines = report.split('## Căn cứ pháp lý\n\n')[1].splitlines()
        assert lines[:3] == ['[E1] Căn cứ', *map(format_citation, expected)]
        assert all('[E' not in line for line in lines[1:3])


def test_report_adds_unretrieved_item_without_e_citations():
    graph, _, parents, documents = make_case(retrieved=False)
    result = run_turn(graph, 's', 'Robot có rủi ro cao không?')
    expected = format_citation(build_evidence([parents[-2]], documents)[0])
    assert expected in result['reply']
    report = assemble_report('Nội dung', [], result['high_risk'], [], parents, documents)
    assert '## Căn cứ pháp lý\n\n' + expected in report


def prepare():
    factory = lambda: SimpleNamespace(context_many=lambda qs, q, b: parents()[:1], last_detail={}, last_timing={})
    return prepare_evidence(factory, parents(), DOCUMENTS, chunks_loader=chunks)


def test_agent_answer_uses_basic_prompt():
    assert AGENT_ANSWER_VERSION == "answer_v2"
    result = prepare()("Nhãn AI có yêu cầu gì?", ["nhãn AI"])
    assert result["route"] == "retrieval" and result["prompt_version"] == "answer_v2"
    messages = build_messages("câu hỏi", result["evidence"], result["prompt_version"])["messages"]
    assert messages[0]["content"].startswith("Phiên bản: answer_v2")


def test_prompt_module_defaults_unchanged():
    # Câu rộng vẫn dùng BROAD_VERSION (khung nghĩa vụ, cần dữ liệu thật nên không dựng ở đây).
    # Hằng của module prompt giữ nguyên cho các nơi khác (basic truyền phiên bản tường minh).
    assert (DEFAULT_VERSION, BROAD_VERSION) == ("answer_v9", "answer_v7")
