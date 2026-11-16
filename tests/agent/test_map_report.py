"""T22b: khóa soát, đồ thị và báo cáo, chỉ dùng phản hồi giả."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from legal_rag.agent.budget import BudgetChat, LLMBudgetExceeded
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.followup import CLOSING
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.report import assemble_report
from legal_rag.agent.trace_view import trace_view
from legal_rag.generation.evidence import append_evidence, build_evidence
from legal_rag.generation.prompt import DEFAULT_VERSION, BROAD_VERSION
from legal_rag.knowledge.high_risk import FIXED_PARENTS
from legal_rag.knowledge.obligations import load_obligations, ROLES, RISK_LEVELS
from legal_rag.knowledge.select import select_obligations
from legal_rag.llm import LLMError
from legal_rag.retrieval.context import estimate_tokens
from test_agent_graph import FakeChat, analysis

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / 'src/legal_rag/knowledge/obligations.yaml'


def row(id='A', review_status='user_reviewed', role='moi_vai_tro', risk_level='moi_muc'):
    return dict(id=id, review_status=review_status, role=role, risk_level=risk_level,
                citations=[dict(chunk_id='d_dieu-1_khoan-1_diem-a', quote='x')])


@pytest.mark.parametrize('rows,profile,risk,selected,draft,rejected', [
    ([row(review_status='ai_draft', role='nha_cung_cap')], {'role': 'nha_cung_cap'}, None, [], 1, 0),
    ([row('B', role='nha_cung_cap', risk_level='cao')], {'role': 'nha_cung_cap'}, None, [], 0, 0),
    ([row('B', role='nha_cung_cap', risk_level='cao')], {'role': 'nha_cung_cap'}, 'cao', ['B'], 0, 0),
    ([row('B', role='nha_cung_cap', risk_level='cao')], {'role': 'ben_trien_khai'}, 'cao', [], 0, 0),
    ([row('C')], {'role': None}, None, ['C'], 0, 0),
    ([row('D', review_status='user_rejected')], {'role': None}, None, [], 0, 1),
    ([row('E', role='co_quan_nha_nuoc')], {'is_public_sector': False}, None, [], 0, 0),
])
def test_selection_table(rows, profile, risk, selected, draft, rejected):
    result = select_obligations(rows, profile, risk)
    assert [r['id'] for r in result['selected']] == selected
    assert result['unreviewed_count'] == draft and result['rejected_count'] == rejected


@pytest.mark.parametrize('role', ['nguoi_su_dung', 'ben_trien_khai', 'co_quan_nha_nuoc'])
@pytest.mark.parametrize('public', [True, False, None])
def test_public_sector_gate(role, public):
    rows = [row('A'), row('E', role='co_quan_nha_nuoc')]
    selected = select_obligations(rows, dict(role=role, is_public_sector=public))['selected']
    assert [r['id'] for r in selected] == (['A', 'E'] if public is True else ['A'])


def test_real_table_coverage():
    rows = load_obligations(TABLE)
    assert len(rows) >= 85 and {r['review_status'] for r in rows} <= {'ai_draft', 'ai_reviewed', 'user_reviewed', 'user_rejected'}
    drafts = [dict(r, review_status='ai_draft') for r in rows]
    for role in ROLES[:5]:
        for risk in RISK_LEVELS:
            assert select_obligations(drafts, dict(role=role), risk) == dict(
                selected=[], unreviewed_count=len(rows), rejected_count=0)
    reviewed = [dict(r, review_status='user_reviewed') for r in rows]
    groups = [select_obligations(reviewed, dict(role=role), risk)['selected']
              for role, risk in [('nha_cung_cap', 'cao'), ('ben_trien_khai', 'cao'), ('nguoi_su_dung', None)]]
    assert len({frozenset(r['id'] for r in group) for group in groups}) == 3
    assert rows == load_obligations(TABLE)


def test_null_role_only_universal_even_public():
    rows = [row(), row('E', role='co_quan_nha_nuoc')]
    assert select_obligations(rows, dict(role=None, is_public_sector=True))['selected'] == rows[:1]


@pytest.mark.parametrize('status', ['ai_draft', 'user_reviewed', 'user_rejected'])
def test_loader_review_status(tmp_path, status):
    import yaml
    rows = load_obligations(TABLE)[:1]
    rows[0]['review_status'] = status
    path = tmp_path / 'table.yaml'
    path.write_text(yaml.safe_dump(rows, allow_unicode=True), encoding='utf-8')
    assert load_obligations(path)[0]['review_status'] == status


def test_prompt_exact_lines():
    lines = (ROOT / 'prompts/answer_v6.txt').read_text(encoding='utf-8').splitlines()
    lines[0] = 'Phiên bản: answer_v8'
    rule = ('Trình bày bằng Markdown đúng ba mục sau, đúng thứ tự, mục nào không có nội dung thì ghi "Không có": '
            '"## Quy định áp dụng", "## Nghĩa vụ cần xem xét", "## Thông tin còn thiếu và giới hạn". '
            'Câu kết về hướng dẫn sơ bộ nằm sau các mục này.')
    lines.insert(next(i for i, line in enumerate(lines) if line.startswith('Trả lời bằng tiếng Việt')), rule)
    assert (ROOT / 'prompts/answer_v8.txt').read_text(encoding='utf-8').splitlines() == lines
    assert (DEFAULT_VERSION, BROAD_VERSION) == ('answer_v9', 'answer_v7')


@pytest.mark.parametrize('heading', [True, False])
@pytest.mark.parametrize('closing', [True, False])
@pytest.mark.parametrize('risk', [None, {'text': 'Đối chiếu riêng.'}])
def test_assemble_report(heading, closing, risk):
    reply = '## Quy định áp dụng\n\nNội dung.'
    if heading:
        reply += '\n\n## Nghĩa vụ cần xem xét\n\nKhông có'
    if closing:
        reply += '\n\n' + CLOSING
    result = assemble_report(reply, ['[E1] Căn cứ'], risk)
    assert result.endswith(CLOSING) and result.count(CLOSING) == 1
    assert result.index('## Căn cứ pháp lý') < result.index(CLOSING)
    if risk:
        assert result.index('## Gợi ý tham khảo: các mục Danh mục rủi ro cao có thể liên quan') < result.index(
            '## Nghĩa vụ cần xem xét' if heading else '## Căn cứ pháp lý')
    assert assemble_report('Nội dung', [], None) == 'Nội dung\n\n' + CLOSING


def fixture_data():
    keys = ['d_dieu-1', 'd_dieu-1_khoan-1', 'item', *FIXED_PARENTS]
    parents = [dict(parent_id=key, document_id='d', article='1', clause=None, title='Tiêu đề',
                    text='Nguyên văn ' + key, context='Nguồn\nĐánh giá sự phù hợp theo điểm a, khoản 2 Điều 13 Luật Trí tuệ nhân tạo') for key in keys]
    documents = [dict(document_id='d', document_number='1/2026', document_title='Văn bản', official_source_url='https://example.invalid')]
    items = [dict(item_id='item', name='Sản phẩm', sector='Y tế', stt='1', description='Điều kiện nguyên văn')]
    chunks = [dict(chunk_id='d_dieu-1_khoan-1_diem-a', parent_id='d_dieu-1_khoan-1')]
    return parents, documents, items, chunks


def make_case(*responses, rows=None, config=None, profile=None, hits=True, request_kinds=("nghia_vu",)):
    parents, documents, items, chunks = fixture_data()
    # Fixture này dành riêng nút bảng/Danh mục; ca tra cứu truyền G1 rõ ràng.
    chat = FakeChat(analysis(request_kinds=list(request_kinds), profile_update={'product_description': 'AI y tế'} if profile is None else profile, sub_queries=['gốc']), *responses)
    searches = []
    pipeline = SimpleNamespace(search=lambda q: searches.append(q) or ([{'chunk_id': 'item'}] if hits else []))
    def prepare(message, queries, **kwargs):
        evidence = build_evidence(parents[:1], documents)
        return dict(evidence=evidence, queries=queries, query_used=queries[0], references_added=[],
                    detail={}, timing={}, route='retrieval', prompt_version='answer_v8',
                    parents_used=[p['parent_id'] for p in parents[:1]])
    graph = build_graph(GraphDeps(chat, 'fake', prepare, config=config or AgentConfig(enable_rewrite=False, enable_verifier=False),
        pipeline_factory=lambda: pipeline, parents=parents, documents=documents,
        high_risk_loader=lambda: items, chunks_loader=lambda: chunks,
        obligations_loader=lambda: rows if rows is not None else [row(review_status='ai_draft')]))
    return graph, chat, searches


def assessment(status='dap_ung', *, basis='AI y tế'):
    return dict(items=[dict(item_id='item', object_match=dict(status='phu_hop', basis=basis, missing_info=[]),
                           conditions=[dict(index=1, status=status, basis='Mô tả')])])


@pytest.mark.parametrize('message,profile,enabled,expected', [
    ('AI có rủi ro cao không?', {'product_description': 'AI y tế'}, True, 'AI y tế'),
    ('AI thuộc DANH MỤC nào?', {'product_description': 'AI y tế'}, True, 'AI y tế'),
    ('Các mức phân loại rủi ro gồm những mức nào?', {}, True, None),
    ('Phan loai AI giúp tôi', {'product_description': 'AI y tế'}, True, 'AI y tế'),
    ('Nghĩa vụ AI là gì?', {'product_description': 'AI y tế'}, True, 'AI y tế'),
    ('AI có rủi ro cao không?', {}, False, None),
])
def test_high_risk_trigger(message, profile, enabled, expected):
    responses = [assessment(), 'Nội dung [E1].'] if expected else ['Nội dung [E1].']
    graph, chat, searches = make_case(*responses, profile=profile,
        request_kinds=('kien_thuc',) if message.startswith('Các mức') else ('nghia_vu',),
        config=AgentConfig(enable_rewrite=False, enable_verifier=False, enable_high_risk=enabled, enable_obligations=False))
    result = run_turn(graph, 's', message)
    assert searches == ([expected] if expected else [])
    assert bool(result['high_risk']) == bool(expected)
    if expected:
        assert 'Phần gợi ý Danh mục đã được trình bày riêng.' in chat.payloads[-1]['messages'][1]['content']
        assert 'không nhận xét về mức rủi ro của sản phẩm' in chat.payloads[-1]['messages'][1]['content']
        assert any(e['source'] == 'high_risk' for e in result['evidence'])
        assert result['reply'].endswith(CLOSING)
    assert result['answer'] != result['reply']
    values = graph.get_state({'configurable': {'thread_id': 's'}}).values
    assert values['messages'][-1]['content'] == result['reply']
    assert not any(e['source'] == 'obligation' for e in result['evidence'])


@pytest.mark.parametrize('status,risk,expected', [
    ('dap_ung', None, []), ('chua_ro', 'cao', ['A']),
    ('dap_ung', 'cao', ['A']), ('dap_ung', 'thap', []),
    ('dap_ung', 'trung_binh', []), ('dap_ung', 'chua_phan_loai', [])])
def test_risk_mapping_and_review_gate(status, risk, expected):
    rows = [row(risk_level='cao'), row('draft', review_status='ai_draft'), row('rejected', review_status='user_rejected')]
    graph, _, _ = make_case(assessment(status), 'Nội dung [E1].', rows=rows,
        profile={'product_description': 'AI y tế', 'risk_level': risk})
    result = run_turn(graph, 's', 'AI có rủi ro cao không?')
    mapped = result['map_obligations']
    assert mapped['selected'] == expected
    assert mapped['unreviewed_count'] == mapped['rejected_count'] == 1
    assert bool(mapped['items']) == (risk not in ('thap', 'trung_binh'))
    if risk in (None, 'chua_phan_loai'):
        assert mapped['items'][0]['applicability'] == 'ap_dung_neu'
    assert [e['parent_id'] for e in result['evidence'] if e['source'] == 'obligation'] == (['d_dieu-1_khoan-1'] if expected else [])
    view = trace_view(result)
    mapped = next(n for n in view['nodes'] if n['node'] == 'map_obligations')
    assert mapped['selected'] == expected
    assert next(n for n in view['nodes'] if n['node'] == 'check_high_risk')['high_risk'] == result['high_risk']


@pytest.mark.parametrize('error', [LLMError('lỗi đối chiếu'), LLMBudgetExceeded('hết ngân sách')])
def test_high_risk_error_continues(error):
    graph, _, _ = make_case(error, 'Nội dung [E1].')
    result = run_turn(graph, 's', 'AI có rủi ro cao không?')
    assert result['error'] is None and result['high_risk'] is None
    assert result['high_risk_error'] == str(error)
    assert result['map_obligations']['unreviewed_count'] == 1
    assert result['route'] == 'retrieval'


def test_no_candidates_uses_no_assessment_call():
    graph, chat, _ = make_case('Nội dung [E1].', hits=False)
    result = run_turn(graph, 's', 'AI có rủi ro cao không?')
    assert result['high_risk']['status'] == 'chua_du_co_so'
    assert result['llm_calls'] == len(chat.payloads) == 2


def test_real_draft_full_equals_no_obligations():
    rows = [dict(r, review_status='ai_draft') for r in load_obligations(TABLE)]
    results = []
    for enabled in (True, False):
        graph, _, _ = make_case(assessment(), 'Nội dung [E1].', rows=rows,
            config=AgentConfig(enable_obligations=enabled, enable_rewrite=False, enable_verifier=False))
        result = run_turn(graph, 's', 'AI có rủi ro cao không?')
        results.append(result)
        assert not any(e['source'] == 'obligation' for e in result['evidence'])
    assert results[0]['map_obligations']['unreviewed_count'] == len(rows)
    for key in ('answer', 'reply', 'evidence', 'high_risk', 'llm_calls'):
        assert results[0][key] == results[1][key]


def test_extra_budget_shared_in_graph_and_state_resets():
    parents, _, _, _ = fixture_data()
    # Chỉ đủ cho mục Danh mục đầu tiên; căn cứ nghĩa vụ không còn chỗ.
    budget = estimate_tokens(parents[2]['text'])
    graph, chat, _ = make_case(assessment(), 'Nội dung [E1].', rows=[row()],
        config=AgentConfig(enable_rewrite=False, enable_verifier=False, extra_budget=budget))
    result = run_turn(graph, 's', 'AI có rủi ro cao không?')
    assert result['map_obligations']['selected'] == ['A']
    assert [e['source'] for e in result['evidence']] == ['retrieval', 'high_risk']
    chat.responses = iter([analysis(), 'Nội dung [E1].'])
    result = run_turn(graph, 's', 'Nghĩa vụ AI là gì?')
    assert result['high_risk'] is None and result['high_risk_error'] is None
    assert '## Gợi ý tham khảo: các mục Danh mục rủi ro cao có thể liên quan' not in result['reply']


def test_broad_frame_unchanged_with_obligations_switch():
    from test_basic_rag import DOCUMENTS
    from test_broad_frame import real_parents
    from legal_rag.agent.answer import prepare_evidence
    def forbidden():
        pytest.fail('Câu rộng không truy xuất hoặc đối chiếu Danh mục')
    prepare = prepare_evidence(forbidden, real_parents(), {'134-2025-QH15': DOCUMENTS[0]}, chunks_loader=lambda: [])
    results = []
    for enabled in (True, False):
        graph = build_graph(GraphDeps(FakeChat(analysis(request_kinds=['nghia_vu']), 'Nội dung [E1].'), 'fake', prepare,
            config=AgentConfig(enable_obligations=enabled, enable_verifier=False), pipeline_factory=forbidden,
            obligations_loader=lambda: [dict(r, review_status='ai_draft') for r in load_obligations(TABLE)]))
        result = run_turn(graph, 's', 'Một sản phẩm AI cần có những nghĩa vụ gì?')
        results.append(result)
        names = [n['node'] for n in result['trace']]
        assert names[names.index('plan_queries')+1] == 'check_high_risk'
        assert 'check_high_risk' in names and 'retrieve' not in names
        assert result['route'] == 'broad_frame' and all(e['source'] == 'frame' for e in result['evidence'])
    assert results[0]['reply'] == results[1]['reply']


def test_budget_shared_and_duplicates():
    parents, documents, _, _ = fixture_data()
    original = build_evidence(parents[:1], documents)
    budget = estimate_tokens(parents[1]['text'])
    result, used = append_evidence(original, [parents[0]['parent_id'], parents[1]['parent_id'], parents[1]['parent_id']], parents, documents, 'high_risk', budget)
    final, more = append_evidence(result, [parents[2]['parent_id']], parents, documents, 'obligation', budget-used)
    assert final == result and more == 0 and used == budget
    assert final[0] == original[0] and [e['id'] for e in final] == ['E1', 'E2']
    assert append_evidence(original, [parents[1]['parent_id']], parents, documents, 'obligation', 0) == (original, 0)


def test_default_seven_calls_and_budget_no_ninth():
    from test_verify_repair_followup import ISSUE
    graph, chat, _ = make_case(
        dict(status='thieu_mot_phan', rewrite=['một']), dict(status='thieu_mot_phan', rewrite=['hai']),
        assessment(), 'Sai [E1].', dict(issues=[ISSUE]), 'Đúng [E1].', config=AgentConfig(verifier_mode="rule_llm"))
    result = run_turn(graph, 's', 'AI có rủi ro cao không?')
    assert result['llm_calls'] == len(chat.payloads) == 7
    assert result['verification']['repaired'] and result['error'] is None
    assert [n['node'] for n in result['trace']].count('check_high_risk') == 1
    budget = BudgetChat(FakeChat(*['ok'] * 8))
    for _ in range(8):
        budget.complete({'model': 'fake'})
    with pytest.raises(LLMBudgetExceeded):
        budget.complete({'model': 'fake'})
    assert budget.calls == 8 and len(budget.chat.payloads) == 8


@pytest.mark.parametrize('message,response', [('xin chào', None), ('Hỏi thời tiết', analysis('ngoai'))])
def test_refusals_skip_report(message, response):
    graph, _, _ = make_case()
    # Đổi lời phân tích đầu tiên của fixture cho nhánh ngoài phạm vi.
    if response:
        graph, _, _ = make_case()
        from test_agent_graph import fake_prepare
        graph = build_graph(GraphDeps(FakeChat(response), 'fake', fake_prepare))
    result = run_turn(graph, 's', message)
    assert '## Căn cứ pháp lý' not in result['reply'] and result['high_risk'] is None
