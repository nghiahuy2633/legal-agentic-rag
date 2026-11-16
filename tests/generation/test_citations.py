"""Kiểm trích dẫn: vị trí, con số, báo nhầm, bảng trích dẫn trong prompt và trace."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import pytest
from legal_rag.generation.citations import check_answer, citation_list, format_citation
from legal_rag.generation.evidence import SCOPE_NOTE, build_evidence, format_evidence
from legal_rag.generation.locations import build_location_index, check_locations, check_numbers, sentences
from legal_rag.generation.prompt import DEFAULT_VERSION, BROAD_VERSION
from test_basic_rag import DOCUMENTS, parents, cli_root
from test_agent_graph import load_chat, analysis
from legal_rag.generation.citations import check_answer
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.locations import build_location_index, check_numbers, number_mentions
from dataclasses import asdict
import hashlib
from legal_rag.generation.prompt import build_messages
from legal_rag.generation.trace import write_trace
from test_basic_rag import DOCUMENTS, FakePipeline, build_evidence as build_evidence_citations_prompt_trace, cli_root, load_ask, parents


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def corpus():
    chunks = [dict(document_id=d, article=a, clause=c, point=p,
                   document_number=n, document_title=t)
              for d, n, t in [('134-2025-QH15', '134/2025/QH15', 'Luật Trí tuệ nhân tạo'),
                              ('142-2026-ND-CP', '142/2026/NĐ-CP', 'Nghị định về AI')]
              for a, c, p in [('1', '1', None), ('1', '1', 'đ'), ('1', '2', None), ('2', None, None)]]
    items = [dict(id='E1', document_id='134-2025-QH15', article='1', clause='1', text='đ) Nội dung.',
                  document_number='134/2025/QH15', article_title='Tiêu đề', source_url='url'),
             dict(id='E2', document_id='142-2026-ND-CP', article='2', clause=None, text='Nội dung.',
                  document_number='142/2026/NĐ-CP', article_title='Tiêu đề', source_url='url')]
    return chunks, items, build_location_index([], chunks)


@pytest.mark.parametrize('answer,error', [
    ('Khoản 9 Điều 1 Luật 134 [E1]', 'không tồn tại'),
    ('Điểm d khoản 1 Điều 1 Luật 134 [E1]', 'không tồn tại'),
    ('Điểm đ khoản 1 Điều 1 Luật 134 [E1]', None),
    ('Khoản 2 Điều 1 Luật 134 [E1]', 'không khớp'),
    ('Điều 1 Nghị định 142 [E1]', 'không khớp'),
    ('Điều 1 [E2]', 'không khớp'),
    ('Điều 99 của Bộ luật Dân sự [E1]', None),
    ('Điều 99 theo Luật Ngoài corpus [E1]', None),
    ('Điều 1 Luật 134', None),
    ('Điều 1', None),
    ('Điều 99 [E99]', 'không tồn tại'),
    ('Nghị định 999 [E1]', 'Số hiệu'),
    ('Nghị định 142 [E1]', None),
])
def test_location_rules(corpus, answer, error):
    chunks, items, index = corpus
    errors = check_locations(answer, items, index, chunks)
    assert any(error in e for e in errors) if error else not errors
    assert len(errors) == len(set(errors))


def test_reference_and_note_rules(corpus):
    chunks, items, index = corpus
    items[0]['text'] += ' khoản 2 Điều 1; Điều 2.'
    assert not check_locations('Khoản 2 Điều 1 [E1]', items, index, chunks)
    assert not check_locations('Điều 2 Nghị định 142 [E1]', items, index, chunks)
    for key in ('scope_note', 'conformity_note'):
        items[0][key] = 'Khoản 2 Điều 1 và 20 ngày.'
        assert not check_locations('Khoản 2 Điều 1 [E1]', items, index, chunks)
        assert not check_numbers('20 ngày [E1]', items)
        del items[0][key]
    items[0]['text'] += ' Nghị định 999'
    assert not check_locations('Nghị định 999 [E1]', items, index, chunks)


@pytest.mark.parametrize('answer,error', [
    ('01/09/2027 [E1]', None), ('ngày 1 tháng 9 năm 2027 [E1]', None),
    ('01/09/2028 [E1]', 'Ngày'), ('2 phần trăm [E1]', None),
    ('3% [E1]', 'Tỷ lệ'), ('30 ngày [E1]', None), ('30 tháng [E1]', 'Thời hạn'),
    ('2 giờ [E1]', None), ('2 năm [E1]', 'Thời hạn'), ('4 tháng [E1]', None),
    ('30 ngày [E2]', 'Thời hạn'), ('30 ngày', None),
    ('30 ngày [E99]', 'Thời hạn'),
])
def test_numbers(corpus, answer, error):
    _, items, _ = corpus
    items[0]['text'] = 'ngày 01 tháng 9 năm 2027; 2%; 30 ngày; 2 giờ; 4 tháng.'
    for text in (answer, unicodedata.normalize('NFD', answer.upper())):
        errors = check_numbers(text, items)
        assert any(error in e for e in errors) if error else not errors


def test_sentences_keep_identifiers_dates_points():
    text = 'Điều 1 [E3.đ]. Theo 134/2025/QH15: 01/09/2027 [E1]; 2.5% [E2]\nHết.'
    assert sentences(text) == ['Điều 1 [E3.đ]', 'Theo 134/2025/QH15', '01/09/2027 [E1]', '2.5% [E2]', 'Hết']


def test_point_markers_order_and_citations(corpus):
    _, items, _ = corpus
    items += [dict(items[0], id='E3', text='b) Ý b\nđ) Ý đ')]
    result = check_answer('Nội dung [E1, E3.b][E3.đ][E3.b]', items)
    assert result['valid'] and result['used'] == ['E1', 'E3']
    assert result['used_points'] == [dict(id='E3', point='b'), dict(id='E3', point='đ')]
    citations = citation_list(result, items)
    assert citations == ['[E1] '+format_citation(items[0]), '[E3.b] '+format_citation(items[2], 'b'),
                         '[E3.đ] '+format_citation(items[2], 'đ')]
    assert 'Khoản 1, Điểm đ' in citations[-1]
    assert check_answer('Nội dung [E3.d]', items)['errors'] == ['Điểm không có trong bằng chứng: [E3.d]']
    assert not check_answer('Nội dung [E99.b]', items)['valid']
    assert not check_answer('Nội dung [E3b]', items)['valid']


def test_optional_index_preserves_old_checks(corpus):
    chunks, items, index = corpus
    answer = 'Khoản 9 Điều 1, hạn 99 ngày [E1]'
    old = check_answer(answer, items)
    assert old['valid'] and old['errors'] == []
    assert not check_answer(answer, items, index, chunks)['valid']


def test_scope_real_sources_and_only_tt05():
    rows = [json.loads(l) for l in (ROOT/'data/processed/parents.jsonl').read_text(encoding='utf-8').splitlines()]
    units = {p['parent_id']: p for p in rows}
    assert 'phục vụ hoạt động quản lý nhà nước hoặc cung cấp dịch vụ công' in units['05-2026-TT-BKHCN_dieu-1_khoan-2']['text']
    assert 'được khuyến khích áp dụng' in units['05-2026-TT-BKHCN_dieu-1_khoan-3']['text']
    with (ROOT/'data/source_registry/documents.csv').open(encoding='utf-8',newline='') as stream:
        items = build_evidence(rows,list(csv.DictReader(stream)))
    for item in items:
        assert ('scope_note' in item) == (item['document_id']=='05-2026-TT-BKHCN')
        if 'scope_note' in item:
            assert item['scope_note']==SCOPE_NOTE
            assert f'Tiêu đề: {item["article_title"]}\n{SCOPE_NOTE}\n' in format_evidence([item])


def test_chat_prints_and_saves_points(tmp_path,monkeypatch,capsys):
    from test_agent_graph import draft_obligations
    draft_obligations(monkeypatch)
    module=load_chat()
    root=cli_root(tmp_path)
    monkeypatch.setattr('legal_rag.agent.runtime.get_llm_settings',lambda: SimpleNamespace(model='fake',base_url='https://example.invalid',api_key='fake'))
    def client(*args):
        return SimpleNamespace(complete=lambda p: json.dumps(analysis()) if 'response_format' in p else 'Nội dung [E1.đ]')
    def pipeline(chunks, units):
        return SimpleNamespace(context_many=lambda qs,q,b:[dict(units[0],clause='1',text='đ) Nội dung')], last_detail={}, last_timing={})
    assert module.main(['--no-rewrite','--message','Hỏi về AI'],root,pipeline,client)==0
    record=json.loads(next((root/'runs/traces').glob('*.json')).read_text(encoding='utf-8'))
    assert record['citations']==['[E1.đ] 134/2025/QH15, Điều 1, Khoản 1, Điểm đ, https://example.invalid/source']
    assert record['citations'][0] in capsys.readouterr().out


def test_sentence_scope_does_not_borrow_from_next_sentence(corpus):
    chunks, items, index = corpus
    assert check_locations('Khoản 2 Điều 1 [E1]. Khoản 2 Điều 1 [E2]', items, index, chunks)
    items[1]['text'] = '30 ngày'
    assert check_numbers('30 ngày [E1]. Không có hạn [E2]', items) == ['Thời hạn ngoài bằng chứng: 30 ngày']
    assert not check_numbers('30 ngày [E1, E2]', items)
    assert not check_locations('Điều 1 [E1, E2]', items, index, chunks)
    assert check_locations('Điều 99 [E1]. Điều 99 [E1]', items, index, chunks) == [
        'Vị trí không tồn tại: Điều 99', 'Vị trí không khớp bằng chứng: Điều 99']


def test_trap_script_and_legacy_traces(tmp_path,capsys):
    import importlib.util
    spec=importlib.util.spec_from_file_location('traps_t20a',ROOT/'scripts/eval_citation_traps.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('data/processed/parents.jsonl','data/processed/chunks.jsonl',
                 'data/source_registry/documents.csv','eval/citation_traps.jsonl'):
        target=tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    with (ROOT/'data/source_registry/documents.csv').open(encoding='utf-8',newline='') as stream:
        docs=list(csv.DictReader(stream))
    units=module.read_jsonl(ROOT/'data/processed/parents.jsonl')
    unit=next(p for p in units if p['parent_id']=='134-2025-QH15_dieu-13_khoan-2')
    item=build_evidence([unit],docs)[0]
    del item['document_id']
    traces=tmp_path/'traces'
    traces.mkdir()
    (traces/'legacy.json').write_text(json.dumps(dict(answer='Trong 999 ngày [E1]. Nội dung [E1].',evidence=[item])),encoding='utf-8')
    (traces/'skip.json').write_text('{"answer": null, "evidence": []}',encoding='utf-8')
    assert module.main(['--traces',str(traces)],root=tmp_path)==0
    report=json.loads((tmp_path/'runs/t20a/traps.json').read_text(encoding='utf-8'))
    traps=module.read_jsonl(ROOT/'eval/citation_traps.jsonl')
    assert report['bat']==dict(caught=sum(r['expect']=='bat' for r in traps),
                               total=sum(r['expect']=='bat' for r in traps))
    assert report['dat']==dict(false_positives=0,total=sum(r['expect']=='dat' for r in traps))
    assert len(report['traces'])==1
    detail=report['traces'][0]['details'][0]
    assert detail==dict(error='Thời hạn ngoài bằng chứng: 999 ngày',sentences=['Trong 999 ngày [E1]'])
    assert '999 ngày' in capsys.readouterr().out


def test_broad_chunks_loaded_lazily_once_without_pipeline():
    from answer_support import composed_answer
    from legal_rag.agent.profile import EMPTY_PROFILE
    from test_broad_frame import real_parents
    created=[]
    def loader():
        created.append('chunks')
        return []
    def forbidden():
        pytest.fail('Không tạo pipeline')
    docs={'134-2025-QH15':DOCUMENTS[0]}
    answer=composed_answer(forbidden,real_parents(),docs,chunks_loader=loader)
    assert created==[]
    for _ in range(2):
        result=answer('Một sản phẩm AI cần có những nghĩa vụ gì?',[],EMPTY_PROFILE,
                      SimpleNamespace(complete=lambda p:'Nội dung [E1]'),'fake')
        assert result['prompt_version']=='answer_v7'
    assert created==['chunks']


def test_two_documents_in_one_sentence_use_nearest_name():
    import json
    from pathlib import Path
    from legal_rag.generation.evidence import build_evidence
    from legal_rag.generation.locations import build_location_index, check_locations
    import csv
    root = Path(__file__).resolve().parents[2]
    read = lambda name: [json.loads(line) for line in (root / "data/processed" / name).read_text(encoding="utf-8").splitlines() if line]
    parents, chunks = read("parents.jsonl"), read("chunks.jsonl")
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))
    lookup = {p["parent_id"]: p for p in parents}
    items = build_evidence([lookup["33-2026-QD-TTg_dieu-2_khoan-1"]], documents)
    index = build_location_index(parents, chunks)
    good = "Theo quy định tại Điều 9 Luật Trí tuệ nhân tạo và khoản 1 Điều 8 của Nghị định số 142/2026/NĐ-CP [E1]."
    assert check_locations(good, items, index, chunks) == []
    bad = "Theo quy định tại Điều 99 Luật Trí tuệ nhân tạo và khoản 9 Điều 8 của Nghị định số 142/2026/NĐ-CP [E1]."
    errors = check_locations(bad, items, index, chunks)
    assert any("Điều 99" in e for e in errors) and any("Khoản 9 Điều 8" in e for e in errors)


ROOT = Path(__file__).resolve().parents[2]


APPENDIX = "05-2026-TT-BKHCN_phu-luc-1_muc-"


CLAUSE = "142-2026-ND-CP_dieu-13_khoan-2"


@pytest.fixture(scope="module")
def corpus_citation_false_alarms():
    def read(name):
        return [json.loads(line) for line in (ROOT / "data/processed" / name)
                .read_text(encoding="utf-8").splitlines() if line.strip()]

    parents, chunks = read("parents.jsonl"), read("chunks.jsonl")
    with (ROOT / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))
    return ({p["parent_id"]: p for p in parents}, documents,
            build_location_index(parents, chunks), chunks)


def evidence(corpus_citation_false_alarms, *ids):
    parents, documents, _, _ = corpus_citation_false_alarms
    return build_evidence([parents[key] for key in ids], documents)


@pytest.mark.parametrize("n,points", [(1, "abcdđe"), (2, "abcdđe"), (3, "abcdđ")])
def test_all_inline_points_in_real_parents(corpus_citation_false_alarms, n, points):
    items = evidence(corpus_citation_false_alarms, APPENDIX + str(n))
    for point in points:
        for answer in (f"Nội dung [E1.{point}]", f"NỘI DUNG [e1.{point.upper()}]"):
            assert check_answer(unicodedata.normalize("NFD", answer), items)["valid"]
    assert not check_answer("Nội dung [E1.z]", items)["valid"]
    if n == 3:
        assert not check_answer("Nội dung [E1.e]", items)["valid"]


@pytest.mark.parametrize("text", [
    "Tham chiếu điểm a) trong văn bản.",
    "Tham chiếu. điểm a) trong văn bản.",
    "Nội dung; a) Không đúng ranh giới.",
    "Nội dung a) Không đúng ranh giới.",
    "1. Tiêu đề khác a) Không đúng tiêu đề.",
])
def test_inline_points_reject_references_and_other_boundaries(corpus_citation_false_alarms, text):
    item = dict(evidence(corpus_citation_false_alarms, APPENDIX + "1")[0], text=text)
    assert not check_answer("Nội dung [E1.a]", [item])["valid"]


def test_inline_rule_only_applies_to_three_parents(corpus_citation_false_alarms):
    item = evidence(corpus_citation_false_alarms, APPENDIX + "1")[0]
    for parent in (APPENDIX + "4", "134-2025-QH15_dieu-13_khoan-2", None):
        changed = dict(item, parent_id=parent)
        assert not check_answer("Nội dung [E1.a]", [changed])["valid"]
        changed["text"] = "a) Điểm đầu dòng vẫn hợp lệ.\nđ) Điểm tiếp theo."
        assert check_answer("Nội dung [E1.a, E1.đ]", [changed])["valid"]


@pytest.mark.parametrize("date", ["ngày 01 tháng 5", "ngày 31 tháng 12", "ngày 1 tháng 01"])
def test_dates_without_year_are_not_compared(corpus_citation_false_alarms, date):
    items = evidence(corpus_citation_false_alarms, CLAUSE)
    for text in (date, unicodedata.normalize("NFD", date.upper())):
        assert number_mentions(text) == []
        assert check_numbers(f"Trước {text} [E1]", items) == []
    # Ngày thiếu năm trong bằng chứng cũng không hỗ trợ thời hạn trùng số.
    assert check_numbers("Trong 01 tháng [E1]", [dict(items[0], text=date)])


@pytest.mark.parametrize("text", [
    "trong 01 tháng", "sau 30 ngày", "không nêu thời hạn 60 ngày",
    "ngày 0 tháng 5", "ngày 32 tháng 5", "ngày 1 tháng 13",
    "ngày 01 tháng 5 năm 2099", "01/05/2099",
])
def test_other_numbers_still_checked(corpus_citation_false_alarms, text):
    assert check_numbers(f"{text} [E1]", evidence(corpus_citation_false_alarms, CLAUSE))


def test_date_does_not_hide_another_duration(corpus_citation_false_alarms):
    assert check_numbers("Trước ngày 01 tháng 5, trong 01 tháng [E1]",
                         evidence(corpus_citation_false_alarms, CLAUSE)) == ["Thời hạn ngoài bằng chứng: 01 tháng"]


@pytest.mark.parametrize("answer,valid", [
    ("khoản 4 Điều 13 [E1]", True),
    ("tổ chức đánh giá sự phù hợp quy định tại khoản 4 Điều 13 [E1.b]", True),
    ("khoản 4 Điều 13 Nghị định 142 [E1]", True),
    ("khoản 9 Điều 13 [E1]", False),
    ("khoản 4 Điều 14 [E1]", False),
    ("khoản 4 Điều 13 Luật 134 [E1]", False),
    ("điểm z khoản 4 Điều 13 [E1]", False),
    ("khoản 4 Điều 13 [E99]", False),
    ("khoản 4 Điều 13 [E2]", False),
    ("khoản 4 Điều 13 [E2]. Nội dung [E1]", False),
])
def test_this_article_only_matches_cited_document_article_clause(corpus_citation_false_alarms, answer, valid):
    items = evidence(corpus_citation_false_alarms, CLAUSE, "134-2025-QH15_dieu-13_khoan-2")
    for text in (answer, unicodedata.normalize("NFD", answer.upper())):
        assert check_answer(text, items, corpus_citation_false_alarms[2], corpus_citation_false_alarms[3])["valid"] is valid


@pytest.mark.parametrize("body", ["khoản 40 Điều này", "khoản 4 Điều nàyx", "khoản 4 Điều khác"])
def test_this_article_requires_exact_phrase_in_body(corpus_citation_false_alarms, body):
    item = dict(evidence(corpus_citation_false_alarms, CLAUSE)[0], text=body, scope_note="khoản 4 Điều này")
    result = check_answer("khoản 4 Điều 13 [E1]", [item], corpus_citation_false_alarms[2], corpus_citation_false_alarms[3])
    assert "Vị trí không khớp bằng chứng: Khoản 4 Điều 13" in result["errors"]


@pytest.mark.parametrize("answer,valid,used,error", [
    ("Kết luận [E3, E5].", True, ["E3", "E5"], None),
    ("Kết luận [E1][E5].", True, ["E1", "E5"], None),
    ("Kết luận [E1, E99].", False, ["E1", "E99"], "Trích dẫn không tồn tại: [E99]"),
    ("Kết luận [E1] và [E1, E99].", False, ["E1", "E99"], "Trích dẫn không tồn tại: [E99]"),
    ("Không liên quan [E1 đến E5].", False, [], "định dạng"),
    ("Kết luận [E1-E5].", False, [], "định dạng"),
    ("Câu hỏi không liên quan đến văn bản.", True, [], None),
    ("Không có thông tin về nội dung này.", True, [], None),
    ("Hệ thống phải làm X.", False, [], "thiếu trích dẫn"),
    ("Theo Điều 1 phải làm X, phần khác không có căn cứ.", False, [], "thiếu trích dẫn"),
    ("Theo 134/2025/QH15, không có thông tin.", False, [], "thiếu trích dẫn"),
    ("Kết luận [ E3 , e5 ] [E3].", True, ["E3", "E5"], None),
    ("Kết luận [E1] và [E2-E5].", False, ["E1"], "định dạng"),
])
def test_citation_table(answer, valid, used, error):
    items = build_evidence_citations_prompt_trace([parents()[0]] * 5, DOCUMENTS)
    for text in (answer, unicodedata.normalize("NFD", answer.upper())):
        result = check_answer(text, items)
        assert result["valid"] is valid
        assert result["used"] == used
        if error:
            assert any(error in message for message in result["errors"])
        else:
            assert result["errors"] == []


def test_prompt_versions_change_payload_and_reject_unknown_version():
    assert build_messages("q", []) != build_messages("q", [], version="answer_v1")
    with pytest.raises(ValueError, match="phiên bản"):
        build_messages("q", [], version="../answer_v2")


FIELDS = {"query", "route", "retrieval_config", "budget", "prompt_version", "messages",
          "evidence", "answer", "check", "llm_calls", "cache_hits", "timing", "model", "llm_attempts"}


EVIDENCE_FIELDS = {"id", "parent_id", "document_number", "article", "article_title",
                   "clause", "text", "source_url"}


def test_write_trace_utf8_unique_names_and_json(tmp_path):
    record = dict(query="Câu hỏi", retrieval_config=asdict(FakePipeline.config))
    first = write_trace(record, tmp_path)
    second = write_trace(record, tmp_path)
    assert first != second
    assert first.name.endswith(hashlib.sha256("Câu hỏi".encode()).hexdigest()[:12] + ".json")
    assert "Câu hỏi" in first.read_text(encoding="utf-8")
    assert json.loads(first.read_text(encoding="utf-8"))["retrieval_config"] == json.loads(
        json.dumps(asdict(FakePipeline.config)))
    with pytest.raises(ValueError):
        write_trace(record | {"budget": float("nan")}, tmp_path)


@pytest.mark.parametrize("evidence_only", [False, True])
def test_cli_trace_exact_messages_cache_and_no_client_secrets(tmp_path, monkeypatch, evidence_only):
    ask, payloads = load_ask(), []
    secret = "t14-private-client-key"
    def settings():
        if evidence_only:
            pytest.fail("Không đọc cấu hình LLM")
        return SimpleNamespace(base_url="https://example.invalid", api_key=secret, model="fake")
    monkeypatch.setattr(ask, "get_llm_settings", settings)
    def client(url, key):
        if evidence_only:
            pytest.fail("Không tạo client LLM")
        return SimpleNamespace(api_key=key, complete=lambda payload:
                               payloads.append(payload) or "Kết luận [E1]")
    root = cli_root(tmp_path)
    trace_dir = root / "custom-traces"
    args = ["--query", "q", "--budget", "123", "--trace-dir", str(trace_dir)]
    if evidence_only:
        args.append("--evidence-only")
    for _ in range(2):
        assert ask.main(args, root, FakePipeline, client) == 0
    paths = sorted(trace_dir.glob("*.json"))
    assert len(paths) == 2
    for index, path in enumerate(paths):
        raw = path.read_text(encoding="utf-8")
        assert secret not in raw and "api_key" not in raw and "base_url" not in raw
        record = json.loads(raw)
        assert set(record) == FIELDS
        assert record["query"] == "q" and record["budget"] == 123
        assert record["retrieval_config"] == json.loads(json.dumps(asdict(FakePipeline.config)))
        assert record["route"] == "retrieval" and record["prompt_version"] == "answer_v9"
        assert record["evidence"] == build_evidence_citations_prompt_trace(parents()[:1], DOCUMENTS)
        assert all(EVIDENCE_FIELDS <= item.keys() for item in record["evidence"])
        assert record["timing"]["bm25"] == FakePipeline.last_timing["bm25"]
        if evidence_only:
            assert record["answer"] is None and record["check"] is None
            assert record["messages"] == []
            assert record["llm_calls"] == record["cache_hits"] == 0
            assert record["model"] is None and record["llm_attempts"] == []
        else:
            assert record["messages"] == payloads[0]["messages"]
            assert record["answer"] == "Kết luận [E1]"
            assert record["check"] == {"valid": True, "errors": [], "used": ["E1"], "warnings": [], "used_points": [], "missing_blocks": []}
            assert record["model"] == "fake"
            assert record["llm_attempts"] == ([{"model": "fake", "status": None}] if index == 0 else [])
            assert (record["llm_calls"], record["cache_hits"]) == ((1, 0) if index == 0 else (0, 1))
    assert len(payloads) == (0 if evidence_only else 1)
