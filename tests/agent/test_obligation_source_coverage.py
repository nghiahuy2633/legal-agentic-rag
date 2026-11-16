"""Nguồn gắn đúng dòng, nguyên tử và kiểm trước trình bày; không nhãn pháp lý mới."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from legal_rag.agent.obligation_sources import plan_sources, check_sources
from legal_rag.agent.presentation import build_context, facts_context, present_answer
from legal_rag.agent.repair import repair_answer
from legal_rag.agent.trace_view import trace_view
from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.locations import build_location_index
from legal_rag.knowledge.facts import empty_facts
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.retrieval.context import estimate_tokens
from test_agent_graph import FakeChat
from test_basic_rag import DOCUMENTS, parents
from test_answer import risk, RISK_ITEM, BODY
from test_answer import graph_case_facts_obligation_presentation as graph_case


def corpus():
    ps = parents()
    cs = [dict(chunk_id='c'+p['parent_id'], parent_id=p['parent_id'],
               document_id='d', article=p['article'], clause=None, point=None) for p in ps]
    return ps, cs, build_location_index(ps, cs)


def item(key='ob-001', refs=('ca',), *, status='ap_dung', text='Nghĩa vụ nguyên văn.', conditions=()):
    return dict(row=dict(id=key, obligation=text, citations=[dict(chunk_id=c) for c in refs]),
                applicability=status, conditions=list(conditions), missing_facts=['risk_level'] if conditions else [])


def completed(items, evidence=None, budget=1000):
    ps, cs, index = corpus()
    evidence = build_evidence(ps, DOCUMENTS) if evidence is None else evidence
    plan = plan_sources(items, cs, ps, evidence, budget)
    return check_sources(plan, evidence, index, cs)


def test_one_parent_does_not_prove_whole_row_and_decisions_are_immutable():
    ps, cs, index = corpus()
    original = [item(refs=('ca','cb','ca'))]
    evidence = build_evidence(ps[:1], DOCUMENTS)
    before = deepcopy((original, evidence))
    plan = plan_sources(original, cs, ps, evidence, 0)
    audit, eligible = check_sources(plan, evidence, index, cs)
    assert plan['added_parent_ids'] == [] and plan['allocations']['ob-001'] == 'budget'
    assert audit['rows'][0]['required_parents'] == ['a','b']
    assert audit['rows'][0]['present_parents'] == ['a'] and audit['rows'][0]['missing_parents'] == ['b']
    assert audit['counts'] == dict(core=1,complete=0,partial=1,none=0,eligible=0,withheld=1)
    assert not eligible and (original,evidence)==before


def test_atomic_budget_skips_large_group_then_adds_later_group_without_partial_leak():
    ps, cs, _ = corpus()
    budget = estimate_tokens(ps[0]['text'])
    plan = plan_sources([item(refs=('ca','cb')), item('ob-002',('cc',))], cs, ps, [], budget)
    assert plan['added_parent_ids'] == ['c'] and plan['allocations']['ob-001']=='budget'
    assert plan['added_tokens'] == estimate_tokens(ps[2]['text']) <= budget


def test_priority_shared_parents_are_charged_once_and_rows_stay_canonical_order():
    ps, cs, _ = corpus()
    values = [item('ob-001',('cb',),status='ap_dung_neu'), item('ob-002',('ca',)), item('ob-003',('ca','cb'))]
    plan = plan_sources(values, cs, ps, [], 1000)
    assert plan['added_parent_ids'] == ['a','b']
    assert plan['added_tokens'] == sum(estimate_tokens(p['text']) for p in ps[:2])
    assert [r['id'] for r in plan['rows']]==['ob-001','ob-002','ob-003']


@pytest.mark.parametrize('mode',['missing_chunk','missing_parent','empty_citations','blocked_list'])
def test_invalid_registry_or_separate_list_item_never_becomes_complete(mode):
    ps, cs, index = corpus()
    values = [item()]
    if mode=='missing_chunk': values[0]['row']['citations'] += [dict(chunk_id='missing')]
    if mode=='missing_parent': ps=ps[1:]
    if mode=='empty_citations': values[0]['row']['citations']=[]
    if mode=='blocked_list': cs[0]['parent_id']='list-x'; ps[0]['parent_id']='list-x'
    plan=plan_sources(values,cs,ps,[],1000,blocked_prefix='list-')
    audit, eligible=check_sources(plan,[],index,cs)
    assert not plan['added_parent_ids'] and not eligible and audit['counts']['withheld']==1


@pytest.mark.parametrize('index_value,chunks_value',[(None,[]),(set(),None),(None,None)])
def test_missing_location_resources_fail_closed(index_value,chunks_value):
    ps,cs,_=corpus(); evidence=build_evidence(ps[:1],DOCUMENTS)
    plan=plan_sources([item()],cs,ps,evidence,0)
    audit,eligible=check_sources(plan,evidence,index_value,chunks_value)
    assert audit['counts']['complete']==1 and not eligible
    assert audit['rows'][0]['reason']=='missing_location_data'


def test_other_rows_source_cannot_validate_date_or_location():
    ps,cs,index=corpus()
    ps[1]['text']='Có hiệu lực từ ngày 15 tháng 8 năm 2026.'
    evidence=build_evidence(ps,DOCUMENTS)
    values=[item(conditions=['Nếu ngày đưa vào hoạt động trước 15/08/2026.']),
            item('ob-002',('cb',),text='Quy định Điều 2.')]
    plan=plan_sources(values,cs,ps,evidence,0)
    audit,eligible=check_sources(plan,evidence,index,cs)
    assert [r['id'] for r in eligible]==['ob-002']
    assert 'Ngày ngoài bằng chứng: 15/08/2026' in audit['rows'][0]['fragment_check']['errors']
    assert audit['rows'][0]['evidence_ids']==['E1']


def test_bound_source_location_error_is_not_silently_complete():
    audit,eligible=completed([item(text='Quy định Điều 2.')])
    assert not eligible and audit['rows'][0]['reason']=='fragment_errors'
    assert audit['rows'][0]['fragment_check']['errors']


def test_complete_conditional_row_keeps_conditions_missing_and_exact_sources():
    value=item(refs=('ca','cb'),status='ap_dung_neu',conditions=['Nếu mức rủi ro chưa rõ.'])
    audit,eligible=completed([value])
    assert audit['counts']['eligible']==1 and eligible[0]['applicability']=='ap_dung_neu'
    assert eligible[0]['conditions']==value['conditions'] and eligible[0]['missing_facts']==['risk_level']
    assert eligible[0]['evidence_ids']==['E1','E2']


def test_held_fragment_stays_private_and_is_not_restored_after_repair():
    ps,cs,index=corpus(); evidence=build_evidence(ps[:1],DOCUMENTS)
    value=item(text='Nghĩa vụ cần chứng minh ngày 15/02/2027.')
    audit,eligible=check_sources(plan_sources([value],cs,ps,evidence,0),evidence,index,cs)
    ctx=facts_context(build_context(eligible,evidence,risk(),[RISK_ITEM]),empty_facts(),'profile',
                      {'items':[dict(id='ob-001',missing_facts=['risk_level'])]})
    ctx['data']['Độ đủ căn cứ để trình bày']={
        'Tổng số dòng':1,'Đủ tập nguồn đã gắn':1,'Có căn cứ một phần':0,'Chưa có căn cứ hiện diện':0,
        'Đủ điều kiện trình bày chi tiết':0,'Cần đối chiếu căn cứ trước khi trình bày chi tiết':1}
    raw='## Trả lời ngắn\nSai.\n\n'+BODY.replace('Nghĩa vụ [E1].',value['row']['obligation'])
    text,presentation=present_answer(raw,ctx,'answer_v11')
    assert '15/02/2027' not in text and 'Cần đối chiếu căn cứ trước khi trình bày chi tiết' in text
    fix=FakeChat(raw); meta={}
    repaired=repair_answer(text,['lỗi'],[],evidence,fix,'fake','answer_v11','nghia_vu',
                           presentation_context=ctx,presentation_audit=meta)
    assert repaired==text and audit['rows'][0]['obligation']==value['row']['obligation']
    assert value['row']['obligation'] not in json.dumps(ctx['data'],ensure_ascii=False)
    public=trace_view({'nodes':[dict(node='map_obligations',obligation_source_coverage=audit)]})
    assert 'obligation' not in public['nodes'][0]['obligation_source_coverage']['rows'][0]
    assert public['nodes'][0]['obligation_source_coverage']['rows'][0]['fragment_check']['errors']


def test_graph_source_gate_keeps_existing_e_codes_core_calls_and_resets():
    result,graph,chat=graph_case()
    state=graph.get_state({'configurable':{'thread_id':'s'}}).values
    audit=next(n['obligation_source_coverage'] for n in result['trace'] if n['node']=='map_obligations')
    assert audit['counts']==dict(core=1,complete=1,partial=0,none=0,eligible=1,withheld=0)
    assert audit['rows'][0]['evidence_ids']==['E1']
    assert state['applicability_bases'][0]['obligation']=='Nghĩa vụ riêng không được gộp.'
    assert state['prepared']['presentation_context']['displayed_rows']==1
    assert result['llm_calls']==len(chat.payloads)==4  # T57: +1 trả lời trực tiếp
    legacy,oldgraph,_=graph_case('answer_v10')
    assert all('obligation_source_coverage' not in n for n in legacy['trace'])


def test_real_corpus_all_citations_still_does_not_prove_literal_condition_dates():
    root=Path(__file__).resolve().parents[2]
    data=root/'data/processed'
    if not (data/'parents.jsonl').exists():
        pytest.skip('Cần corpus đã xử lý để kiểm chỉ đọc.')
    ps=[json.loads(l) for l in (data/'parents.jsonl').read_text(encoding='utf-8').splitlines()]
    cs=[json.loads(l) for l in (data/'chunks.jsonl').read_text(encoding='utf-8').splitlines()]
    rows=load_obligations(root/'src/legal_rag/knowledge/obligations.yaml')
    decisions=applicable_obligations(rows,empty_facts())['items']
    # Không hardcode ID để cấp nguồn: lấy các dòng có đúng literal ngày trong điều kiện hiện có.
    subset=[i for i in decisions if any('15/02/2027' in c for c in i['conditions'])]
    assert subset
    plan=plan_sources(subset,cs,ps,[],100000)
    # Chỉ cần metadata gốc của document để dựng evidence giả nội dung thật.
    ids={p['document_id'] for p in ps}
    fake_docs=[dict(document_id=k,document_number=k.replace('-','/'),document_title=k,official_source_url='https://example.invalid') for k in ids]
    evidence=build_evidence([p for p in ps if p['parent_id'] in plan['added_parent_ids']],fake_docs)
    audit,eligible=check_sources(plan,evidence,build_location_index(ps,cs),cs)
    assert audit['counts']['complete']==len(subset) and not eligible
    assert all(any('15/02/2027' in error for error in r['fragment_check']['errors']) for r in audit['rows'])
