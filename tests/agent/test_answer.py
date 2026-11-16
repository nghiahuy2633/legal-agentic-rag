"""Agent: dựng và trình bày câu trả lời, báo cáo nghĩa vụ, giải thích giới hạn."""

import sys
import re
import pytest
from legal_rag.agent.answer import generate_answer
from legal_rag.agent.blocks import check_blocks, normalize_headings
from legal_rag.agent.config import AgentConfig
from legal_rag.agent.followup import CLOSING
from legal_rag.agent.graph import GraphDeps, build_graph, run_turn
from legal_rag.agent.repair import repair_answer
from legal_rag.agent.report import assemble_report, tidy_citation_lines
from legal_rag.generation.citations import check_answer, normalize_citation_markers
from legal_rag.generation.evidence import build_evidence
from test_agent_graph import FakeChat, analysis
from test_basic_rag import DOCUMENTS, parents
import json
from legal_rag.agent.presentation import answer_first, bound_answer
from legal_rag.agent.report import assemble_report
from legal_rag.evaluation.answers import valid_judgment
from legal_rag.knowledge import high_risk as hr
from legal_rag.llm import LLMError
from copy import deepcopy
from types import SimpleNamespace
from legal_rag.agent.blocks import normalize_headings
from legal_rag.agent.followup import CLOSING, NOTICE
from legal_rag.agent.presentation import (build_context, present_answer, humanize,
    apply_presentation_errors, PREFIX_ERROR)
from legal_rag.generation.citations import check_answer
from legal_rag.knowledge.facts import FACT_LABELS
from legal_rag.knowledge.high_risk import FIXED_PARENTS, PREFIX
from legal_rag.agent import analyze
from legal_rag.agent.explanations import with_rows
from legal_rag.agent.obligation_sources import check_sources, plan_sources, requirements
from legal_rag.agent.presentation import build_context, facts_context, present_answer
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.generation.locations import build_location_index
from legal_rag.knowledge.facts import empty_facts
from test_agent_graph import FakeChat
from test_basic_rag import parents
from test_routing import ROOT
from legal_rag.agent.explanations import with_rows, bind_explanations
from legal_rag.agent.followup import NOTICE
from legal_rag.agent.trace_view import trace_view
from legal_rag.agent.presentation import build_context, facts_context, present_answer, PREFIX_ERROR


def evidence():
    items = build_evidence(parents()[:1], DOCUMENTS)
    items[0]["text"] = "a) Nội dung a.\nđ) Nội dung đ."
    return items


@pytest.mark.parametrize("source,expected", [
    ("[E25.1] [e3.12]", "[E25] [e3]"),
    ("[E1.1, E2.a, E3.12, E4.đ]", "[E1, E2.a, E3, E4.đ]"),
    ("[E1.1][E2.22]", "[E1][E2]"),
    ("[E1-E5] [E1.1-E5.2] [E1.1, E2.xyz]", "[E1-E5] [E1.1-E5.2] [E1.1, E2.xyz]"),
    ("Giá 25.1, https://example.invalid/[E1.1] và [E2.3]", "Giá 25.1, https://example.invalid/[E1.1] và [E2]"),
    ("`[E1.1]` ``[E2.2] `x` `` [E3.3]", "`[E1.1]` ``[E2.2] `x` `` [E3]"),
    ("```text\n[E1.1]\n```\n[E2.2]", "```text\n[E1.1]\n```\n[E2]"),
    ("~~~~\n[E1.1]\n~~~\n[E2.2]\n~~~~\n[E3.3]", "~~~~\n[E1.1]\n~~~\n[E2.2]\n~~~~\n[E3]"),
    ("~~~\n[E1.1]", "~~~\n[E1.1]"),
])
def test_numeric_markers_preserve_other_syntax_and_code(source, expected):
    assert normalize_citation_markers(source) == expected
    assert normalize_citation_markers(expected) == expected


def test_checker_stays_strict_and_points_stay_checked():
    items = evidence()
    assert not check_answer("Nội dung [E1.1].", items)["valid"]
    fixed = normalize_citation_markers("Nội dung [E1.1, E1.a, E1.đ].")
    check = check_answer(fixed, items)
    assert check["valid"] and check["used"] == ["E1"]
    assert check["used_points"] == [{"id": "E1", "point": "a"}, {"id": "E1", "point": "đ"}]
    for source in ("[E99.1]", "[E1.b]", "[E1.1-E5.2]"):
        assert not check_answer(normalize_citation_markers(source), items)["valid"]


@pytest.mark.parametrize("heading", [
    "## Trả lời ngắn: Câu trả lời [E1.1].",
    "## **TRẢ lời ngắn**： Câu trả lời [E1.1].",
    "## **Trả lời ngắn:** Câu trả lời [E1.1].",
    "## __Trả lời ngắn：__ Câu trả lời [E1.1].",
])
def test_generate_normalizes_before_check_and_does_not_add_calls(heading):
    chat = FakeChat(heading + "\n\n## Căn cứ\nCăn cứ [E1.a].\n\n" + CLOSING)
    prepared = dict(evidence=evidence(), prompt_version="answer_v9", question_type="dinh_nghia",
                    route="retrieval", parents_used=["a"], query_used="AI", references_added=[])
    result = generate_answer("AI là gì?", ["AI"], {}, prepared, chat, "fake")
    assert result["reply"].startswith("## Trả lời ngắn\n\nCâu trả lời [E1].")
    assert result["check"]["valid"]
    assert len(chat.payloads) == 1


def test_repair_output_and_shortcut_share_normalizers():
    fixed = "## Trả lời ngắn\n\nCâu sửa [E1].\n\n## Căn cứ\nCăn cứ [E1.a]."
    source = "## Trả lời ngắn: Câu sửa [E1.1].\n\n## Căn cứ\nCăn cứ [E1.a]."
    chat = FakeChat(source)
    result = repair_answer("Sai", ["lỗi nội dung"], [], evidence(), chat, "fake", "answer_v9", "dinh_nghia")
    assert result == fixed and check_answer(result, evidence())["valid"]
    assert len(chat.payloads) == 1
    chat = FakeChat()
    assert repair_answer(source, ["Thiếu mục bắt buộc: Trả lời ngắn"], [], evidence(), chat,
                         "fake", "answer_v9", "dinh_nghia") == fixed
    assert not chat.payloads


def test_graph_skips_repair_for_both_form_errors():
    items = evidence()
    def prepare(*args, **kwargs):
        return dict(evidence=items, prompt_version="answer_v9", route="retrieval", parents_used=["a"],
                    queries=["AI"], query_used="AI", references_added=[], detail={}, timing={})
    chat = FakeChat(analysis(question_type="dinh_nghia"),
                    "## Trả lời ngắn: Câu trả lời [E1.1].\n\n## Căn cứ\nCăn cứ [E1].\n\n" + CLOSING)
    graph = build_graph(GraphDeps(chat, "fake", prepare, AgentConfig(enable_rewrite=False,
                        enable_high_risk=False, enable_obligations=False)))
    result = run_turn(graph, "t45", "AI là gì?")
    assert result["check"]["valid"] and not result["verification"]["repaired"]
    assert result["llm_calls"] == 2 and len(chat.payloads) == 2


def test_duplicate_headings_merge_bodies_without_losing_other_sections():
    source = ("## Trả lời ngắn: Đoạn đầu [E1].\n\n## Căn cứ\nNguồn [E2].\n\n"
              "## **Trả lời ngắn**\nĐoạn sau [E3].\n\n## Giới hạn\nGiới hạn.")
    result = normalize_headings(source, "answer_v9")
    assert result.count("## Trả lời ngắn") == 1
    assert result.index("Đoạn đầu") < result.index("Đoạn sau") < result.index("## Căn cứ")
    assert "## Căn cứ\nNguồn [E2]." in result and "## Giới hạn\nGiới hạn." in result
    assert re.findall(r"\[E\d+\]", result) == ["[E1]", "[E3]", "[E2]"]
    assert normalize_headings(result, "answer_v9") == result
    assert normalize_headings(source, "answer_v8") == source


def test_duplicate_final_short_section_keeps_closing_once_after_other_sections():
    source = ("## Trả lời ngắn\nA [E1].\n\n## Căn cứ\nB [E1].\n\n"
              "## Trả lời ngắn\nC [E1].\n\n" + CLOSING)
    normalized = normalize_headings(source, "answer_v9")
    result = assemble_report(normalized, sources("E1"), None)
    assert normalized.endswith(CLOSING) and normalized.count(CLOSING) == 1
    assert result.endswith(CLOSING) and result.count(CLOSING) == 1
    assert result.index("C [E1]") < result.index("## Căn cứ") < result.index(CLOSING)
    assert normalize_headings(normalized, "answer_v9") == normalized


def test_headings_inside_code_are_unchanged_and_do_not_satisfy_blocks():
    code = "```md\n## Trả lời ngắn: Ví dụ [E1].\n```\n"
    inline = "## `Trả lời ngắn`\n"
    assert normalize_headings(code + inline, "answer_v9") == code + inline
    assert check_blocks({"used": []}, [], code + inline, "answer_v9") == ["Trả lời ngắn", "Căn cứ"]
    source = "## Trả lời ngắn: Giữ `## Trả lời ngắn: [E1.2]` và [E1]."
    assert "`## Trả lời ngắn: [E1.2]`" in normalize_headings(source, "answer_v9")
    extra = "## Trả lời ngắn `[E1]`\nĐoạn giữ nguyên.\n"
    assert normalize_headings(extra, "answer_v9") == extra
    assert "Trả lời ngắn" in check_blocks({"used": []}, [], extra, "answer_v9")
    with_real_heading = "## Trả lời ngắn\nNội dung.\n\n" + extra
    assert normalize_headings(with_real_heading, "answer_v9") == with_real_heading
    actual_heading_with_code_body = "## Trả lời ngắn\n" + code + "\n## Căn cứ\nNguồn."
    assert check_blocks({"used": []}, [], actual_heading_with_code_body, "answer_v9") == []


def sources(*codes):
    return [f"[{code}] Nguồn {code}, https://example.invalid/{code}" for code in codes]


def test_eleven_citation_bullets_removed_only_with_all_exact_sources():
    codes = [f"E{i}" for i in range(1, 12)]
    body = "## Quy định áp dụng\n" + "\n".join(f"- [{code}]" for code in codes)
    citations = sources(*codes)
    result = assemble_report(body + "\n\n" + CLOSING, citations, None)
    main, references = result.split("## Căn cứ pháp lý")
    assert not re.search(r"^- \[E\d+\]", main, re.M)
    assert all(citation in references for citation in citations)
    assert result.endswith(CLOSING) and result.count(CLOSING) == 1
    unsafe = "- [E1, E99]\n- [E1.a]\n- [E1, E2.a]"
    assert tidy_citation_lines(unsafe, sources("E1", "E2")) == unsafe
    assert tidy_citation_lines("- [E1.a, E2.đ]", sources("E1.a", "E2.đ")) == ""


@pytest.mark.parametrize("prefix", ["- Căn cứ: ", "- Luật thử: Điều 7, Điều 10, Điều 35 ",
                                   "Doanh nghiệp phải làm việc này ", ""])
def test_fourteen_trailing_codes_wrap_without_losing_prefix_codes_or_punctuation(prefix):
    codes = [f"E{i}" for i in range(1, 15)]
    line = prefix + ", ".join(f"[{code}]" for code in codes) + "."
    source = "## Quy định áp dụng\n" + line + "\n\n## Nghĩa vụ cần xem xét\nGiữ nguyên."
    result = tidy_citation_lines(source, [])
    assert result.startswith("## Quy định áp dụng\n" + prefix)
    assert re.findall(r"E\d+", result) == codes
    assert all(len(re.findall(r"E\d+", line)) <= 3 for line in result.splitlines())
    assert result.endswith("[E13], [E14].\n\n## Nghĩa vụ cần xem xét\nGiữ nguyên.")
    assert tidy_citation_lines(result, []) == result


def test_mixed_groups_adjacent_codes_and_unknown_codes_stay_visible():
    body = "## Quy định áp dụng\n- Nguồn: [E1, E2.a][E3.đ], [E99]."
    result = tidy_citation_lines(body, sources("E1", "E2.a", "E3.đ"))
    assert "[E1], [E2.a], [E3.đ]\n  [E99]." in result
    assert "[E99]" in result


def test_report_keeps_code_substantive_lines_other_sections_and_high_risk_text():
    code = "```md\n## Quy định áp dụng\n- [E1]\n```\n`- [E1]`\n"
    sentence = "Câu [E1] có nội dung [E2] xen giữa [E3], [E4]."
    other = "## Căn cứ\n- Nguồn: [E1][E2][E3][E4].\n"
    body = code + "## Quy định áp dụng\n" + sentence + "\n" + other
    high_risk = dict(text="Nguyên văn: [E1][E2][E3][E4].\n- [E1]", parent_ids=[])
    result = assemble_report(body, sources("E1", "E2", "E3", "E4"), high_risk)
    assert code in result and sentence in result and other in result
    assert high_risk["text"] in result
    assert result.endswith(CLOSING)


REPORT = ("## Trả lời ngắn\n\nCác mục được giữ để đối chiếu: Lĩnh vực ngân hàng, STT 1.\n\n"
          "## Quy định áp dụng\n\n- [E1] Luật\n\n## Nghĩa vụ cần xem xét\n\n- Nghĩa vụ [E1]\n\n"
          "## Thông tin còn thiếu và giới hạn\n\nNguồn dữ kiện: hồ sơ.\n\n" + CLOSING)


DIRECT = "## Trả lời ngắn\nKhông, một dòng ở footer chưa đủ [E2].\n\n## Căn cứ\n- Người dùng phải nhận biết [E2].\n\n" + CLOSING


def test_answer_first_puts_direct_answer_first_and_moves_catalog_opening_to_limits():
    text, reason = answer_first(REPORT, DIRECT)
    assert reason is None
    short = text.split("## Quy định áp dụng")[0]
    assert "footer chưa đủ [E2]" in short and "Người dùng phải nhận biết [E2]" in short
    assert "STT 1" not in short
    limits = text.split("## Thông tin còn thiếu và giới hạn")[1]
    assert limits.strip().startswith("Đối chiếu Danh mục: Các mục được giữ để đối chiếu")
    assert "Nguồn dữ kiện: hồ sơ." in limits
    assert text.count(CLOSING) == 1 and text.rstrip().endswith(CLOSING)
    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## Trả lời ngắn", "## Quy định áp dụng", "## Nghĩa vụ cần xem xét", "## Thông tin còn thiếu và giới hạn"]


@pytest.mark.parametrize("direct,report,reason", [
    ("Không có heading [E1].", REPORT, "direct_missing_short_answer"),
    ("## Trả lời ngắn\n\n", REPORT, "direct_missing_short_answer"),
    (DIRECT, "## Quy định áp dụng\n\nX [E1].", "report_missing_short_answer"),
])
def test_answer_first_keeps_report_when_it_cannot_merge(direct, report, reason):
    assert answer_first(report, direct) == (report, reason)


def test_answer_first_adds_limits_section_when_missing():
    report = "## Trả lời ngắn\n\nMở đầu Danh mục.\n\n## Quy định áp dụng\n\n- [E1] Luật"
    text, _ = answer_first(report, DIRECT)
    assert text.split("## Thông tin còn thiếu và giới hạn")[1].strip() == "Đối chiếu Danh mục: Mở đầu Danh mục."


def test_obligation_rows_keep_verbatim_conditions_without_explanation():
    ctx, items, index, chunks = fixture()
    text, _ = bound_answer(response(text="Giải thích riêng."), ctx, items, index, chunks)
    blocks = text.split("## Nghĩa vụ cần xem xét")[1].split("## Thông tin còn thiếu")[0].strip().split("\n\n")
    for block, row in zip(blocks, ctx["data"]["Dòng cần giải thích"]):
        assert row["Nghĩa vụ"] in block and all("  Điều kiện: " + c in block for c in row["Điều kiện"])
        assert row["Mức áp dụng"] in block and "Giải thích riêng." not in block


def test_fixed_bases_are_named_and_linked_once_in_legal_bases():
    parents = [dict(parent_id=key, document_id="d", article="2", clause=None, title="Tiêu chí",
                    context="Quyết định (số 33/2026/QĐ-TTg)\nĐiều 2. Tiêu chí", text="Nguyên văn dài")
               for key in hr.FIXED_PARENTS]
    documents = [dict(document_id="d", document_number="33/2026/QĐ-TTg", document_title="QĐ",
                      official_source_url="https://x.invalid")]
    high = dict(version="high_risk_v2", status="chua_du_co_so", text="Khối", parent_ids=list(hr.FIXED_PARENTS))
    text = assemble_report("## Trả lời ngắn\n\nĐáp.", [], high, (), parents, documents)
    legal = text.split("## Căn cứ pháp lý")[1]
    assert legal.count("33/2026/QĐ-TTg, Điều 2") == len(hr.FIXED_PARENTS) and "https://x.invalid" in legal
    # Thiếu văn bản trong sổ đăng ký: bỏ qua, không bịa nguồn, không lỗi.
    assert "## Căn cứ pháp lý" not in assemble_report("## Trả lời ngắn\n\nĐáp.", [], high, (), parents, [])


def test_fixed_label_has_document_article_and_clause():
    parent = dict(context="Nghị định (số 142/2026/NĐ-CP)\nChương II\nĐiều 8. Tiêu chí", text="x")
    assert hr.fixed_label("142-2026-ND-CP_dieu-8_khoan-2", parent) == "142/2026/NĐ-CP Điều 8. Tiêu chí, khoản 2"
    assert hr.fixed_label("33-2026-QD-TTg_dieu-2", dict(parent, context="QĐ (số 33/2026/QĐ-TTg)\nĐiều 2. A")) == \
        "33/2026/QĐ-TTg Điều 2. A"


def test_graph_report_path_answers_first_with_one_extra_call_on_same_evidence():
    result, graph, chat = graph_case()
    generated = next(n for n in result["trace"] if n["node"] == "generate")
    assert generated["effective_prompt_version"] == "answer_v10"
    assert generated["answer_first"] == dict(status="ok", question_type="khac", direct_valid=True)
    assert result["llm_calls"] == len(chat.payloads) == 4
    direct_payload = chat.payloads[3]
    assert direct_payload["messages"][0]["content"].startswith("Phiên bản: answer_v9")
    assert "Trả lời trực tiếp [E1]." in result["reply"].split("## Quy định áp dụng")[0]
    assert result["check"]["valid"]


def test_graph_direct_answer_error_keeps_report(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "DIRECT_answer_consistency", LLMError("lỗi giả"))
    result, _, chat = graph_case()
    generated = next(n for n in result["trace"] if n["node"] == "generate")
    assert generated["answer_first"] == dict(status="loi", reason="lỗi giả")
    assert "STT 1" in result["reply"].split("## Quy định áp dụng")[0]
    assert result["llm_calls"] == len(chat.payloads) == 4


def test_judgment_accepts_point_level_citation_codes():
    row = dict(required_points=["Ý"])
    value = dict(meaning_ok=True, citations_relevant=True, unsupported_claims=0, reason="r", judge_version="judge_v2",
                 points=[dict(point="Ý", covered=True)], citation_issues=[dict(code="E13.e", reason="lý do")])
    assert valid_judgment(value, row)
    assert not valid_judgment(dict(value, citation_issues=[dict(code="E13.ee", reason="x")]), row)
    assert json.dumps(value, ensure_ascii=False)


ITEM_ID = PREFIX + 'IV_stt-1'


RISK_ITEM = dict(item_id=ITEM_ID, name='Hệ thống thực hiện giao dịch', sector='Lĩnh vực ngân hàng',
                 stt='1', description='Điều kiện nguyên văn')


BODY = ('## Quy định áp dụng\nQuy định [E1].\n\n## Nghĩa vụ cần xem xét\n'
        'Nghĩa vụ [E1].\n\n## Thông tin còn thiếu và giới hạn\nKhông có.')


# T57: khuôn báo cáo gọi thêm một lần trả lời trực tiếp ngay sau lượt sinh báo cáo.
DIRECT_answer_consistency = '## Trả lời ngắn\nTrả lời trực tiếp [E1].\n\n## Căn cứ\n- Căn cứ trực tiếp [E1].'


def source():
    return build_evidence(parents()[:1], DOCUMENTS)


def bases():
    return [dict(id='ob-001', applicability='ap_dung', obligation='Nghĩa vụ nguyên văn A.',
                 conditions=[], missing_facts=[], evidence_ids=['E1']),
            dict(id='ob-002', applicability='ap_dung_neu', obligation='Nghĩa vụ nguyên văn B.',
                 conditions=['Nếu có điều kiện nguyên văn.'], missing_facts=list(FACT_LABELS),
                 evidence_ids=['E1', 'E99'])]


def risk(reason=None):
    return dict(version='high_risk_v2', parent_ids=[ITEM_ID] + list(FIXED_PARENTS) if reason is None else list(FIXED_PARENTS),
                status='co_the_khop' if reason is None else 'chua_du_co_so',
                label='còn điều kiện chưa rõ' if reason is None else 'Chưa đủ cơ sở đề xuất mục Danh mục',
                selection_reason=reason)


def context(reason=None):
    return build_context(bases(), source(), risk(reason), [RISK_ITEM],
        [dict(item_id=ITEM_ID, conditions=[dict(index=1, text='Điều kiện nguyên văn', status='chua_ro', basis=None)])])


def prepared(ctx=None, version='answer_v10'):
    return dict(evidence=source(), prompt_version=version, question_type='nghia_vu',
                route='retrieval', parents_used=['a'], query_used='AI', references_added=[],
                presentation_context=ctx if ctx is not None else context())


def test_projection_is_separate_exact_and_has_only_present_evidence():
    canonical, evidence = bases(), source()
    before = deepcopy((canonical, evidence))
    ctx = build_context(canonical, evidence)
    projected = ctx['data']['Nghĩa vụ có căn cứ hiện diện']
    assert (canonical,evidence)==before
    assert len(projected)==2 and projected[0]['Nghĩa vụ']!=projected[1]['Nghĩa vụ']
    assert [r['Căn cứ'] for r in projected]==[['E1'],['E1']]
    assert projected[1]['Điều kiện']==canonical[1]['conditions']
    assert projected[1]['Thông tin cần bổ sung']==list(FACT_LABELS.values())
    data=json.dumps(ctx['data'],ensure_ascii=False)
    assert all(token not in data for token in ('ob-001','ob-002','missing_facts','ap_dung',*FACT_LABELS))
    projected[1]['Điều kiện'].append('đổi snapshot')
    assert canonical==before[0]


def test_unknown_field_has_neutral_label_and_rows_without_evidence_are_not_invented():
    rows=bases();rows[0]['missing_facts']=['future_field'];rows[1]['evidence_ids']=['E99']
    ctx=build_context(rows,source())
    assert len(ctx['data']['Nghĩa vụ có căn cứ hiện diện'])==1
    assert ctx['data']['Nghĩa vụ có căn cứ hiện diện'][0]['Thông tin cần bổ sung']==['thông tin cần xác minh']
    assert ctx['obligation_labels']=={'ob-001':rows[0]['obligation']}


@pytest.mark.parametrize('reason',[None,'no_candidates','unresolved','not_relevant','invalid_response'])
def test_owned_opening_from_frozen_result_not_wrong_llm_short(reason):
    ctx=context(reason)
    bad='## Trả lời ngắn\nBằng chứng không nêu mục cụ thể [E1].\n\n'+BODY+'\n\n'+CLOSING
    text,audit=present_answer(normalize_headings(bad,'answer_v10','nghia_vu'),ctx,'answer_v10')
    short=text.split('## Quy định áp dụng')[0]
    assert 'Bằng chứng không nêu mục cụ thể' not in text
    assert audit['opening_source']=='code' and not audit['errors']
    assert text.count('## Trả lời ngắn')==1 and BODY in text and text.endswith(CLOSING)
    if reason is None:
        assert 'STT 1' in short and RISK_ITEM['name'] in short
        assert 'còn điều kiện chưa rõ' in short
    else:
        assert 'Chưa đủ cơ sở' in short and 'không phải kết luận sản phẩm không thuộc' in short
    assert present_answer(text,ctx,'answer_v10')[0]==text


@pytest.mark.parametrize('raw',[
    'Bằng chứng không nêu mục cụ thể.\n\n'+BODY,
    'Mở đầu chưa có mục riêng.',
    '```text\n## Trả lời ngắn\nkhông được sửa code\n```\n\n'+BODY,
])
def test_unstructured_prefix_kept_outside_owned_section_and_not_silently_valid(raw):
    text,audit=present_answer(raw,context(),'answer_v10')
    assert PREFIX_ERROR in audit['errors']
    short=text.split('## Nội dung cần đối chiếu')[0]
    assert 'Bằng chứng không nêu' not in short and 'Mở đầu chưa' not in short
    assert raw.strip() in text
    check=apply_presentation_errors(check_answer(text,source()),audit['errors'])
    assert not check['valid']


def test_missing_short_heading_but_valid_sections_gets_only_code_opening():
    text,audit=present_answer(BODY,context(),'answer_v10')
    assert text.startswith('## Trả lời ngắn') and BODY in text
    assert not audit['errors']


@pytest.mark.parametrize('heading',['## Trả lời ngắn: sai [E1].','## **TRẢ LỜI NGẮN**： sai [E1].'])
def test_normalized_inline_and_duplicate_short_sections(heading):
    raw=heading+'\n\n'+BODY+'\n\n## Trả lời ngắn\nsai khác [E1].'
    text,audit=present_answer(normalize_headings(raw,'answer_v10','nghia_vu'),context(),'answer_v10')
    assert text.count('## Trả lời ngắn')==1 and 'sai khác' not in text
    assert BODY in text and not audit['errors']


@pytest.mark.parametrize('raw',['- ob-001: [E1]','- ob-001:','ob-001 [E1]','- ob-001: https://x.invalid/a [E1]'])
def test_id_only_or_citation_only_keeps_full_obligation(raw):
    text,changes,errors=humanize(raw,context())
    assert 'Nghĩa vụ nguyên văn A.' in text and 'ob-001' not in text
    assert ('[E1]' in raw)==('[E1]' in text) and not errors
    if 'https://' in raw:assert 'https://x.invalid/a' in text


def test_label_before_existing_body_is_removed_without_duplication():
    text,_,errors=humanize('- ob-001: Nội dung diễn giải [E1].',context())
    assert text=='- Nội dung diễn giải [E1].' and not errors


def test_humanization_preserves_quotes_code_urls_and_citations():
    protected=('`ob-001 risk_level`\n```text\nob-001: risk_level\n```\n'
               '> ob-001 risk_level\n“ob-001 risk_level” "ob-001 risk_level"\n'
               'https://x.invalid/ob-001/risk_level [link](../ob-001/risk_level)')
    text,_,errors=humanize(protected+'\nob-001 [E1.a] risk_level.',context())
    assert protected in text and '[E1.a]' in text and 'mức rủi ro' in text
    assert text.endswith('Nghĩa vụ nguyên văn A. [E1.a] mức rủi ro.') and not errors


def test_unknown_id_is_neutral_and_has_error():
    text,_,errors=humanize('ob-999 [E1] risk_level',context())
    assert text=='nghĩa vụ cần đối chiếu [E1] mức rủi ro'
    assert errors and 'ob-999' in errors[0]
    assert not apply_presentation_errors(check_answer(text,source()),errors)['valid']


def test_generate_and_repair_use_identical_human_snapshot_and_code_opening():
    ctx=context();before=deepcopy(ctx)
    chat=FakeChat('## Trả lời ngắn\nKhông có mục [E1].\n\n'+BODY)
    generated=generate_answer('AI cần làm gì?',['AI'],{},prepared(ctx),chat,'fake')
    audit={};fix=FakeChat('## Trả lời ngắn\nKhông có mục lần nữa [E1].\n\n'+BODY)
    repaired=repair_answer(generated['reply'],['lỗi'],[],source(),fix,'fake','answer_v10','nghia_vu',
        presentation_context=ctx,presentation_audit=audit)
    assert generated['reply']==repaired and generated['check']['valid'] and ctx==before
    assert generated['raw_reply'].startswith('## Trả lời ngắn\nKhông có mục')
    assert audit['presentation']['opening_source']=='code'
    sent=json.loads(fix.payloads[0]['messages'][1]['content'])
    assert sent['Kết quả xử lý dùng để trình bày']==ctx['data']
    assert json.dumps(ctx['data'],ensure_ascii=False) in chat.payloads[0]['messages'][1]['content']
    assert fix.payloads[0]['messages'][0]['content'].startswith('Phiên bản: repair_v3\n')
    assert len(chat.payloads)==len(fix.payloads)==1


def graph_case(*, version='answer_v9', extra_responses=(), bad='## Trả lời ngắn\nKhông có mục [E1].\n\n'+BODY):
    regular=parents()[:1]
    risk_parents=[dict(regular[0],parent_id=key,title='Mục danh mục',text='Điều kiện',context='Nguồn\nGhi chú')
                  for key in [ITEM_ID,*FIXED_PARENTS]]
    allparents=regular+risk_parents
    chat=FakeChat(analysis(request_kinds=['nghia_vu'],profile_update={'product_description':'hệ thống giao dịch'},sub_queries=['truy vấn đầy đủ']),
        dict(items=[dict(item_id=ITEM_ID,object_match=dict(status='phu_hop',basis='hệ thống giao dịch',missing_info=[]),
                        conditions=[dict(index=1,status='chua_ro',basis=None)])]),bad,DIRECT_answer_consistency,*extra_responses)
    def prepare(message,queries,**kwargs):
        return dict(evidence=build_evidence(regular,DOCUMENTS),queries=queries,query_used=queries[0],
            references_added=[],detail={},timing={},route='broad_frame' if version=='answer_v7' else 'retrieval',
            prompt_version=version,parents_used=[regular[0]['parent_id']])
    graph=build_graph(GraphDeps(chat,'fake',prepare,config=AgentConfig(enable_rewrite=False,enable_obligations=False),
        pipeline_factory=lambda:SimpleNamespace(search=lambda q:[dict(chunk_id=ITEM_ID)]),parents=allparents,
        documents=DOCUMENTS,high_risk_loader=lambda:[RISK_ITEM]))
    result=run_turn(graph,'s','Nghĩa vụ AI?')
    return result,graph,chat


@pytest.mark.parametrize('version',['answer_v9','answer_v7'])
def test_graph_optin_and_repair_share_snapshot_without_extra_calls(version):
    result,graph,chat=graph_case(version=version,bad='## Trả lời ngắn\nKhông có mục [E99].\n\n'+BODY)
    generated=next(n for n in result['trace'] if n['node']=='generate')
    assert generated['effective_prompt_version']=='answer_v10'
    # T57: Trả lời ngắn là lời trả lời trực tiếp; kết quả đối chiếu Danh mục chuyển xuống mục giới hạn.
    assert 'Trả lời trực tiếp [E1].' in result['reply'].split('## Quy định áp dụng')[0]
    assert result['reply'].split('## Thông tin còn thiếu và giới hạn')[1].count('Đối chiếu Danh mục:')==1
    assert 'Không có mục' not in result['reply']
    assert result['llm_calls']==len(chat.payloads)==4
    assert graph.get_state({'configurable':{'thread_id':'s'}}).values['prepared']['presentation_context']['opening']


def test_graph_unknown_id_keeps_warning_through_single_repair():
    result,graph,chat=graph_case(bad='## Trả lời ngắn\nSai [E1].\n\n'+BODY.replace('Nghĩa vụ [E1].','ob-999 [E1].'),
        extra_responses=['## Trả lời ngắn\nSai lần hai [E1].\n\n'+BODY])
    assert result['llm_calls']==len(chat.payloads)==5
    assert result['verification']['repaired'] and not result['verification']['final_valid']
    assert NOTICE in result['reply'] and result['check']['presentation_errors']
    assert next(n for n in result['trace'] if n['node']=='repair_answer')['presentation']['opening_source']=='code'


def test_prefix_layout_error_can_be_repaired_without_losing_owned_summary():
    result,_,chat=graph_case(bad='Không có mục trong bằng chứng.\n\n'+BODY,
        extra_responses=['## Trả lời ngắn\nVẫn không có mục [E1].\n\n'+BODY])
    assert result['llm_calls']==len(chat.payloads)==5
    assert result['verification']['repaired'] and result['verification']['final_valid']
    assert 'STT 1' in result['reply'].split('## Thông tin còn thiếu và giới hạn')[1]
    assert 'Trả lời trực tiếp [E1].' in result['reply'].split('## Quy định áp dụng')[0]
    assert 'Không có mục trong bằng chứng' not in result['reply']
    assert not result['check']['presentation_errors'] and NOTICE not in result['reply']


def test_failed_citation_repair_is_still_invalid_and_keeps_warning():
    bad=BODY.replace('Nghĩa vụ [E1].','Nghĩa vụ [E99].')
    result,_,chat=graph_case(bad='## Trả lời ngắn\nSai [E1].\n\n'+bad,
        extra_responses=['## Trả lời ngắn\nSai nữa [E1].\n\n'+bad])
    assert result['llm_calls']==len(chat.payloads)==5 and not result['verification']['final_valid']
    assert '[E99]' in result['reply'] and NOTICE in result['reply']
    assert 'STT 1' in result['reply'].split('## Thông tin còn thiếu và giới hạn')[1]


def test_snapshot_only_lists_the_three_displayed_items_not_the_whole_registry():
    items=[dict(RISK_ITEM,item_id=PREFIX+f'X_stt-{i}',name=f'Loại chức năng {i}',stt=str(i)) for i in range(5)]
    high=risk();high['parent_ids']=[i['item_id'] for i in items[2:]]+list(FIXED_PARENTS)
    ctx=build_context([],source(),high,items)
    shown=ctx['data']['Kết quả đối chiếu Danh mục đã xử lý']['Mục được giữ để đối chiếu']
    assert [r['Tên mục'] for r in shown]==[i['name'] for i in items[2:]]
    assert all(i['name'] not in ctx['opening'] for i in items[:2])


def test_risk_snapshot_keeps_condition_status_without_reinjecting_removed_item_text():
    decision=dict(item_id=ITEM_ID,conditions=[dict(index=1,text='Nội dung mục riêng '+ITEM_ID,status='chua_ro',basis=None)])
    ctx=build_context([],source(),risk(),[RISK_ITEM],[decision])
    rows=ctx['data']['Kết quả đối chiếu Danh mục đã xử lý']['Mục được giữ để đối chiếu']
    assert rows[0]['Điều kiện đã đối chiếu']==[{'Điều kiện thứ':1,'Kết quả':'chưa rõ'}]
    payload=json.dumps(ctx['data'],ensure_ascii=False)
    assert ITEM_ID not in payload and 'Nội dung mục riêng' not in payload
    assert decision['conditions'][0]['text'].endswith(ITEM_ID)


def test_graph_snapshot_resets_next_turn_and_legacy_prepared_is_not_upgraded():
    result,graph,chat=graph_case()
    chat.responses=iter([analysis(request_kinds=['kien_thuc']),'## Trả lời ngắn\nĐịnh nghĩa [E1].\n\n## Căn cứ\nNguồn [E1].'])
    second=run_turn(graph,'s','Khái niệm là gì?')
    state=graph.get_state({'configurable':{'thread_id':'s'}}).values
    assert 'presentation_context' not in state['prepared'] and second['high_risk'] is None
    legacy,_,_=graph_case(version='answer_v8',bad='Nội dung [E1].')
    assert next(n for n in legacy['trace'] if n['node']=='generate')['effective_prompt_version']=='answer_v8'


SITUATION = 'Khi hệ thống xảy ra sự cố nghiêm trọng'


DECISIONS = [dict(item_id=ITEM_ID, conditions=[
    dict(index=1, text='Hệ thống có khả năng tự phê duyệt giao dịch;', status='dap_ung', basis='x'),
    dict(index=2, text='Giao dịch có mức giá trị cao;', status='chua_ro', basis=None),
    dict(index=3, text='Không có kiểm soát của con người.', status='chua_ro', basis=None)])]


def rows_with_situation():
    rows = bases()
    rows[0]['situation'] = SITUATION
    rows[1]['situation'] = ''
    return rows


def context_answer_content_fixes(rows=None, decisions=DECISIONS, high_risk=None):
    rows = rows_with_situation() if rows is None else rows
    ctx = build_context(rows, source(), high_risk or risk(), [RISK_ITEM], decisions)
    return with_rows(facts_context(ctx, empty_facts(), 'profile', {'items': rows}))


def render(ctx, explanations=None):
    cs = [dict(chunk_id='ca', parent_id='a', document_id='d', article='1', clause=None, point=None)]
    n = len(ctx['data']['Dòng cần giải thích'])
    raw = json.dumps({'explanations': explanations or [dict(row=i, text='Giải thích theo căn cứ.')
                                                         for i in range(1, n + 1)]}, ensure_ascii=False)
    return present_answer(raw, ctx, 'answer_v12', items=source(),
                          index=build_location_index(parents(), cs), chunks=cs)


def section(text, title):
    return text.split('## ' + title, 1)[1].split('\n## ', 1)[0]


def test_analyze_v6_defines_content_and_parses_like_v5():
    prompt = (ROOT / 'prompts/analyze_v6.txt').read_text(encoding='utf-8')
    v5 = (ROOT / 'prompts/analyze_v5.txt').read_text(encoding='utf-8')
    assert prompt.startswith('Phiên bản: analyze_v6\n')
    assert 'văn bản, âm thanh, hình ảnh, video' in prompt and 'giao dịch' in prompt
    # Chỉ thêm định nghĩa, phần còn lại giữ nguyên chữ của v5.
    assert prompt.replace('Phiên bản: analyze_v6', 'Phiên bản: analyze_v5').count('\n') == v5.count('\n') + 1
    # Đo trên eval/scenarios.jsonl: v6 giảm role 27→25/38, nên mặc định giữ v5; v6 là tùy chọn.
    assert AgentConfig().analyze_prompt == analyze.DEFAULT_ANALYZE_VERSION == 'analyze_v7'
    assert AgentConfig(analyze_prompt='analyze_v6').analyze_prompt == 'analyze_v6'
    answer = json.dumps(dict(scope='trong', profile_update={'generates_content': False}, sub_queries=['q'],
                             question_type='nghia_vu', request_kinds=['nghia_vu', 'sai']))
    results = {}
    for version in ('analyze_v5', 'analyze_v6'):
        chat = FakeChat(answer)
        results[version] = analyze.analyze_turn('câu', EMPTY_PROFILE, [], chat, 'fake', version=version)
        assert chat.payloads[0]['messages'][0]['content'].startswith(f'Phiên bản: {version}\n')
    assert results['analyze_v5'] == results['analyze_v6']
    assert results['analyze_v6']['request_kinds'] == ['nghia_vu']
    assert results['analyze_v6']['request_kinds_discarded'] == ['sai']


def test_unclear_catalog_conditions_lead_missing_section_verbatim():
    text, audit = render(context_answer_content_fixes())
    missing = section(text, 'Thông tin còn thiếu và giới hạn')
    first = missing.strip().splitlines()[:3]
    assert first == ['Điều kiện Danh mục chưa rõ, cần bổ sung thông tin để đối chiếu:',
                     '- Lĩnh vực ngân hàng, STT 1: Giao dịch có mức giá trị cao.',
                     '- Lĩnh vực ngân hàng, STT 1: Không có kiểm soát của con người.']
    assert 'tự phê duyệt giao dịch' not in missing
    assert missing.index('Không có kiểm soát') < missing.index('Nguồn dữ kiện')
    assert not audit['errors']


def test_no_unclear_or_no_catalog_keeps_t51_missing_section():
    met = [dict(item_id=ITEM_ID, conditions=[dict(index=1, text='Đáp ứng', status='dap_ung', basis='x')])]
    for ctx in (context_answer_content_fixes(decisions=met), context_answer_content_fixes(decisions=[], high_risk=risk('no_candidates'))):
        text, _ = render(ctx)
        assert section(text, 'Thông tin còn thiếu và giới hạn').strip().startswith('Nguồn dữ kiện:')
        assert 'Điều kiện Danh mục chưa rõ' not in text


def test_situation_shown_once_under_level_only_for_rows_that_have_it():
    ctx = context_answer_content_fixes()
    rows = ctx['data']['Dòng cần giải thích']
    assert rows[0]['Phạm vi theo bảng nghĩa vụ'] == SITUATION and 'Phạm vi theo bảng nghĩa vụ' not in rows[1]
    text, _ = render(ctx)
    blocks = section(text, 'Nghĩa vụ cần xem xét').strip().split('\n\n')
    lines = blocks[0].splitlines()
    assert lines[1] == '  Mức áp dụng: Áp dụng.'
    assert lines[2] == '  Phạm vi theo bảng nghĩa vụ: ' + SITUATION + '.'
    assert text.count('Phạm vi theo bảng nghĩa vụ') == 1
    # Không đổi mức áp dụng, không trộn vào Điều kiện.
    assert rows[0]['Mức áp dụng'] == 'Áp dụng' and rows[0]['Điều kiện'] == []


def test_explanation_cannot_remove_or_override_situation():
    ctx = context_answer_content_fixes()
    text, audit = render(ctx, [dict(row=1, text='Áp dụng trong mọi trường hợp.'),
                               dict(row=2, text='Giải thích theo căn cứ.')])
    assert '  Phạm vi theo bảng nghĩa vụ: ' + SITUATION + '.' in text
    bad, bad_audit = render(ctx, [dict(row=1, text='a', situation='khác')])
    assert '  Phạm vi theo bảng nghĩa vụ: ' + SITUATION + '.' in bad and bad_audit['errors']


def test_situation_stays_out_of_llm_data_for_older_callers():
    rows = rows_with_situation()
    plain = build_context([{k: v for k, v in row.items() if k != 'situation'} for row in rows],
                          source(), risk(), [RISK_ITEM], DECISIONS)
    ctx = build_context(rows, source(), risk(), [RISK_ITEM], DECISIONS)
    assert ctx['data'] == plain['data'] and SITUATION not in json.dumps(ctx['data'], ensure_ascii=False)
    assert ctx['situations'] == [SITUATION, '']


def test_sources_list_urls_only_once_in_v12():
    text, _ = render(context_answer_content_fixes())
    url = source()[0]['source_url']
    assert url not in section(text, 'Quy định áp dụng')
    assert '[E1]' in section(text, 'Quy định áp dụng')


def test_table_condition_flows_through_source_rows():
    chunk = dict(chunk_id='chunk-a', parent_id=parents()[0]['parent_id'], document_id='d', article='1',
                 clause=None, point=None)
    item = dict(row=dict(id='ob-021', obligation='Nghĩa vụ.', condition='  ' + SITUATION + ' ',
                         citations=[dict(chunk_id='chunk-a')]),
                applicability='ap_dung', conditions=[], missing_facts=[])
    empty = deepcopy(item); empty['row']['condition'] = ''
    rows = requirements([item, empty], [chunk], parents())
    assert [row['situation'] for row in rows] == [SITUATION, '']
    plan = plan_sources([item], [chunk], parents(), source(), 1000)
    _, eligible = check_sources(plan, source(), build_location_index(parents(), [chunk]), [chunk])
    assert eligible and all(row["situation"] == SITUATION for row in eligible)




def fixture(rows=None):
    rows = deepcopy(bases() if rows is None else rows)
    items = source()
    cs = [dict(chunk_id='ca', parent_id='a', document_id='d', article='1', clause=None, point=None)]
    index = build_location_index(parents(), cs)
    ctx = with_rows(facts_context(build_context(rows, items, risk(), [RISK_ITEM]),
        empty_facts(), 'profile', {'items': rows}))
    return ctx, items, index, cs


def response(n=2, text='Nội dung giải thích có căn cứ.'):
    return json.dumps({'explanations':[dict(row=i,text=text) for i in range(1,n+1)]},ensure_ascii=False)


def render_bound_explanations(raw, ctx=None):
    default,items,index,chunks=fixture()
    return present_answer(raw,ctx or default,'answer_v12',items=items,index=index,chunks=chunks)


def test_same_source_rows_keep_separate_full_conditions_and_bound_explanations():
    ctx,items,index,chunks=fixture();before=deepcopy(ctx)
    raw=json.dumps({'explanations':[dict(row=1,text='Giải thích riêng thứ nhất.'),
                                  dict(row=2,text='Giải thích riêng thứ hai.')]},ensure_ascii=False)
    text,audit=render_bound_explanations(raw,ctx)
    assert ctx==before and audit['explanations']['accepted_keys']==[1,2]
    assert audit['owned_sections']==['Trả lời ngắn','Quy định áp dụng','Nghĩa vụ cần xem xét','Thông tin còn thiếu và giới hạn']
    rules=text.split('## Quy định áp dụng',1)[1].split('## Nghĩa vụ cần xem xét',1)[0]
    assert 'Giải thích riêng' not in rules and 'Nghĩa vụ nguyên văn' not in rules
    blocks=text.split('## Nghĩa vụ cần xem xét',1)[1].split('## Thông tin còn thiếu',1)[0].strip().split('\n\n')
    assert len(blocks)==2
    for i,(block,row) in enumerate(zip(blocks,ctx['data']['Dòng cần giải thích']),1):
        assert row['Nghĩa vụ'] in block and row['Mức áp dụng'] in block
        assert all('  Điều kiện: '+value in block for value in row['Điều kiện'])
        # T57: dòng có điều kiện không kèm lời giải thích; điều kiện vẫn nguyên văn.
        # T57: lời giải thích được kiểm và ghi audit nhưng không hiển thị.
        assert 'thứ nhất' not in block and 'thứ hai' not in block
    assert not audit['errors'] and '"row"' not in text and 'ob-001' not in text


@pytest.mark.parametrize('data',[
    '## Quy định áp dụng\nSai.', '{', '{}', '{"explanations":[],"explanations":[]}',
    '{"explanations":[{"row":1,"text":"a","conditions":[] }]}',
    '{"explanations":[{"row":true,"text":"a"}]}',
    '{"explanations":[{"row":2,"text":"a"},{"row":1,"text":"b"}]}',
    '{"explanations":[{"row":1,"text":"a"},{"row":1,"text":"b"}]}',
    '{"explanations":[{"row":99,"text":"a"},{"row":2,"text":"b"}]}',
    '{"explanations":[{"row":1,"text":"a"}]}',
])
def test_schema_failure_does_not_become_free_unscoped_prose(data):
    text,audit=render_bound_explanations(data)
    assert audit['errors'] and not audit['explanations']['accepted_keys']
    assert 'Giải thích trong phạm vi trên' not in text  # T57: không hiển thị lời giải thích
    assert text.count('## Quy định áp dụng')==1
    assert '"conditions"' not in text and '## Quy định áp dụng\nSai.' not in text


@pytest.mark.parametrize('text',[
    '', 'x'*1201, '## Tiêu đề', 'a\nb', '`mã`', 'https://x.invalid',
    '[liên kết](https://x.invalid)', '> câu', '<script>x</script>', 'ftp://x.invalid/a',
    'ob-059', 'risk_level', 'Nguồn [E99].', 'Nguon E99.', 'Ngày 15/02/2027.', 'Quy định Điều 2.',
])
def test_invalid_content_is_audited_and_not_shown_as_accepted_explanation(text):
    rendered,audit=render_bound_explanations(response(text=text))
    assert audit['errors'] and not audit['explanations']['accepted_keys']
    assert 'Giải thích trong phạm vi trên' not in rendered  # T57: không hiển thị lời giải thích
    if text.strip(): assert 'Giải thích trong phạm vi trên: '+text not in rendered


def test_quote_is_checked_as_plain_content_not_masked_escape():
    _,audit=render_bound_explanations(response(text='“Ngày 15/02/2027.”'))
    assert any('Ngày ngoài bằng chứng' in e for e in audit['errors'])


def test_empty_rows_have_empty_protocol_and_honest_code_layout():
    ctx,_,_,_=fixture([])
    text,audit=render_bound_explanations(response(0),ctx)
    assert not audit['errors'] and audit['explanations']['expected_keys']==[]
    assert 'Không có căn cứ hiện diện đủ' in text and 'không có nghĩa vụ' not in text


def test_generate_repair_same_snapshot_and_legacy_repair_return_type():
    ctx,items,index,chunks=fixture();before=deepcopy(ctx)
    prep=dict(evidence=items,index=index,chunks=chunks,prompt_version='answer_v12',question_type='nghia_vu',
              route='retrieval',parents_used=['a'],query_used='AI',references_added=[],presentation_context=ctx)
    bad=response(text='Nguồn [E99].');chat=FakeChat(bad)
    generated=generate_answer('Cần làm gì?',['AI'],{},prep,chat,'fake')
    assert not generated['check']['valid'] and generated['raw_reply']==bad
    fix=FakeChat(response());audit={}
    result=repair_answer(generated['reply'],generated['check']['errors'],[],items,fix,'fake','answer_v12','nghia_vu',
        presentation_context=ctx,presentation_audit=audit,presentation_index=index,presentation_chunks=chunks)
    assert isinstance(result,str) and ctx==before and not audit['presentation']['errors']
    assert len(chat.payloads)==len(fix.payloads)==1 and audit['raw_reply']==response()
    assert chat.payloads[0]['response_format']==fix.payloads[0]['response_format']=={'type':'json_object'}
    assert fix.payloads[0]['messages'][0]['content'].startswith('Phiên bản: repair_v5\n')
    assert json.loads(fix.payloads[0]['messages'][1]['content'])['Kết quả xử lý dùng để trình bày']==ctx['data']
    public=trace_view({'nodes':[dict(node='generate',raw_reply=bad,presentation=generated['presentation'])]})
    assert 'raw_reply' not in public['nodes'][0]


def test_graph_auto_v12_one_repair_keeps_binding_errors_notice_and_canonical_conditions():
    bad=response(1,text='Nguồn [E99].')
    result,graph,chat=graph_case_facts_obligation_presentation(bad=bad,repairs=(bad,))
    state=graph.get_state({'configurable':{'thread_id':'s'}}).values
    assert state['prompt_version']=='answer_v12' and result['llm_calls']==len(chat.payloads)==5  # T57: +1 trả lời trực tiếp
    assert NOTICE in result['reply'] and not result['check']['valid']
    assert '[E99]' not in result['reply'] and '[E99]' in json.dumps(result['trace'],ensure_ascii=False)
    for node in result['trace']:
        if node['node'] in ('generate','repair_answer','recheck'):
            assert node['presentation']['explanations']['expected_keys']==[1]
            assert len(node['presentation']['owned_sections'])==4


def test_v11_direct_caller_keeps_markdown_protocol():
    ctx,_,_,_=fixture()
    raw='## Trả lời ngắn\nCâu cũ.\n\n## Quy định áp dụng\nNguồn [E1].'
    text,audit=present_answer(raw,ctx,'answer_v11')
    assert 'Nguồn [E1].' in text and 'explanations' not in audit


def test_v11_direct_generation_keeps_invalid_markdown_for_legacy_check():
    ctx,items,index,chunks=fixture()
    raw='## Trả lời ngắn\nCũ.\n\n## Quy định áp dụng\nNguồn [E99].'
    prep=dict(evidence=items,index=index,chunks=chunks,prompt_version='answer_v11',question_type='nghia_vu',
              route='retrieval',parents_used=['a'],query_used='AI',references_added=[],presentation_context=ctx)
    result=generate_answer('AI?',['AI'],{},prep,FakeChat(raw),'fake')
    assert '[E99]' in result['reply'] and not result['check']['valid']
    assert result['raw_reply']==raw and 'explanations' not in result['presentation']




def snapshot(facts=None, rows=None):
    rows = deepcopy(bases() if rows is None else rows)
    facts = dict(empty_facts(), risk_level='trung_binh', is_public_sector=False,
                 roles=['nha_cung_cap', 'ben_trien_khai'], content_types=[] if facts is None else None) if facts is None else facts
    return facts_context(build_context(rows, source(), risk(), [RISK_ITEM]), facts, 'assessment', {'items': rows})


def render_facts_obligation_presentation(ctx, text=None):
    return present_answer(normalize_headings(text or '## Trả lời ngắn\nSai.\n\n'+BODY+'\n\n'+CLOSING,
                                            'answer_v11', 'nghia_vu'), ctx, 'answer_v11')


def test_owned_rows_are_exact_separate_and_do_not_mutate_canonical():
    rows = bases(); before = deepcopy(rows)
    ctx = snapshot(rows=rows); frozen = deepcopy(ctx)
    text, audit = render_facts_obligation_presentation(ctx)
    for row in rows:
        assert text.count(row['obligation']) == 1
        assert all(condition in text for condition in row['conditions'])
    assert text.count('[E1]') == 3 and '[E99]' not in text
    assert text.index(rows[0]['obligation']) < text.index(rows[1]['obligation'])
    assert 'Mức áp dụng: Áp dụng.' in text and 'Mức áp dụng: Có điều kiện.' in text
    assert 'ob-001' not in text and rows == before and ctx == frozen
    assert audit['facts_source'] == 'assessment' and audit['snapshot_rows'] == audit['displayed_rows'] == 2
    assert len(audit['owned_sections']) == 3 and render_facts_obligation_presentation(ctx, text)[0] == text


def test_known_false_empty_multiple_roles_and_unknown_are_distinct():
    ctx = snapshot(); data = ctx['data']['Dữ kiện đã dùng để lọc nghĩa vụ']
    text, _ = render_facts_obligation_presentation(ctx)
    assert 'nhà cung cấp; bên triển khai' in text
    assert 'là cơ quan nhà nước: không' in text and 'loại nội dung: danh sách rỗng đã khai' in text
    assert 'mức rủi ro đã khai trong hồ sơ: trung bình' in text
    assert 'Cần bổ sung theo kết quả lọc: mức rủi ro' not in text
    assert 'là cơ quan nhà nước' not in data['Thông tin còn thiếu theo kết quả lọc']
    assert 'loại nội dung' not in data['Thông tin còn thiếu theo kết quả lọc']
    assert 'chưa phải kết quả xác minh pháp lý' in text


@pytest.mark.parametrize('risk_level', [None, 'chua_phan_loai', 'thap', 'cao', 'trung_binh'])
def test_missing_risk_is_from_core_and_not_confused_with_catalogue(risk_level):
    rows = bases(); rows[1]['missing_facts'] = ['risk_level']
    ctx = snapshot(dict(empty_facts(), risk_level=risk_level), rows)
    text, _ = render_facts_obligation_presentation(ctx)
    missing = ctx['data']['Dữ kiện đã dùng để lọc nghĩa vụ']['Thông tin còn thiếu theo kết quả lọc']
    assert ('mức rủi ro' in missing) == (risk_level in (None, 'chua_phan_loai'))
    assert 'Mức rủi ro đã khai không phải kết luận sản phẩm thuộc hoặc không thuộc Danh mục' in text
    if risk_level == 'chua_phan_loai':
        assert 'mức rủi ro đã khai trong hồ sơ: chưa phân loại' in text


def test_missing_covers_core_without_evidence_and_coverage_does_not_invent_rows():
    rows = bases(); rows[1]['evidence_ids'] = ['E99']; rows[1]['missing_facts'] = ['operation_start_date']
    ctx = snapshot(rows=rows)
    text, audit = render_facts_obligation_presentation(ctx)
    assert rows[1]['obligation'] not in text and 'Cần bổ sung theo kết quả lọc: ngày đưa vào hoạt động' in text
    assert '1/2 dòng' in text and '1 dòng chưa có căn cứ hiện diện' in text
    assert audit['snapshot_rows'] == 2 and audit['displayed_rows'] == 1
    empty, _ = render_facts_obligation_presentation(snapshot(rows=[]))
    assert 'Chưa có dòng nghĩa vụ đủ căn cứ hiện diện' in empty and '0/0 dòng' in empty
    assert 'sản phẩm không có nghĩa vụ' not in empty


@pytest.mark.parametrize('heading', ['## Nghĩa vụ cần xem xét: gộp sai [E99].',
                                   '## **NGHĨA VỤ CẦN XEM XÉT**： gộp sai [E99].'])
def test_inline_duplicate_owned_sections_replaced_and_fenced_headings_kept(heading):
    raw = ('## Trả lời ngắn\nSai.\n\n## Quy định áp dụng\nNguồn [E1].\n'
           '```text\n## Nghĩa vụ cần xem xét\nNội dung mã giữ nguyên\n```\n\n'+heading+
           '\n\n## Nghĩa vụ cần xem xét\nSai lần hai.\n\n## Thông tin còn thiếu và giới hạn: thiếu risk_level.')
    text, audit = render_facts_obligation_presentation(snapshot(), raw)
    assert 'gộp sai' not in text and 'Sai lần hai' not in text and 'thiếu mức rủi ro' not in text
    assert '```text\n## Nghĩa vụ cần xem xét\nNội dung mã giữ nguyên\n```' in text
    assert not audit['errors'] and text.count('## Nghĩa vụ cần xem xét') == 2


def test_outside_sections_errors_and_prefix_remain_visible_not_silently_valid():
    raw = 'Prefix chưa phân mục.\n\n## Quy định áp dụng\nNguồn [E99] ob-999.\n\n'+BODY.split('## Nghĩa vụ')[1]
    text, audit = render_facts_obligation_presentation(snapshot(), raw)
    assert PREFIX_ERROR in audit['errors'] and any('ob-999' in error for error in audit['errors'])
    assert 'Prefix chưa phân mục.' in text and '[E99]' in text
    assert not check_answer(text, source())['valid']


def test_generate_repair_share_snapshot_raw_reply_and_keep_citation_failures():
    ctx = snapshot(); before = deepcopy(ctx)
    bad = '## Trả lời ngắn\nSai.\n\n'+BODY.replace('Quy định [E1].', 'Quy định [E99].')
    prep = dict(evidence=source(), prompt_version='answer_v11', question_type='nghia_vu', route='retrieval',
                parents_used=['a'], query_used='AI', references_added=[], presentation_context=ctx)
    chat = FakeChat(bad)
    generated = generate_answer('Cần làm gì?', ['AI'], {}, prep, chat, 'fake')
    fix = FakeChat(bad); audit = {}
    repaired = repair_answer(generated['reply'], generated['check']['errors'], [], source(), fix, 'fake',
        'answer_v11', 'nghia_vu', presentation_context=ctx, presentation_audit=audit)
    assert generated['raw_reply'] == audit['raw_reply'] == bad
    assert generated['reply'] == repaired and ctx == before and not generated['check']['valid']
    assert json.loads(fix.payloads[0]['messages'][1]['content'])['Kết quả xử lý dùng để trình bày'] == ctx['data']
    assert json.dumps(ctx['data'], ensure_ascii=False) in chat.payloads[0]['messages'][1]['content']
    assert fix.payloads[0]['messages'][0]['content'].startswith('Phiên bản: repair_v4\n')
    assert len(chat.payloads) == len(fix.payloads) == 1
    public = trace_view({'nodes': [dict(node='generate', raw_reply=bad, presentation=audit['presentation'])]})
    assert 'raw_reply' not in public['nodes'][0] and public['nodes'][0]['presentation']['owned_sections']


def graph_case_facts_obligation_presentation(version='answer_v9', facts=None, *, question_type='nghia_vu', bad=None, repairs=()):
    regular = parents()[:1]
    allparents = regular + [dict(regular[0], parent_id=k, title='Mục Danh mục', text='Điều kiện', context='Nguồn')
                            for k in [ITEM_ID, *FIXED_PARENTS]]
    row = dict(id='ob-001', role='moi_vai_tro', risk_level='moi_muc', review_status='user_reviewed',
               obligation='Nghĩa vụ riêng không được gộp.', citations=[{'chunk_id': 'chunk-a'}])
    chat = FakeChat(analysis(request_kinds=['nghia_vu'], question_type=question_type,
        profile_update=dict(role='nha_phat_trien', risk_level='cao', product_description='hệ thống giao dịch')),
        dict(items=[dict(item_id=ITEM_ID, object_match=dict(status='phu_hop', basis='hệ thống giao dịch', missing_info=[]),
             conditions=[dict(index=1, status='chua_ro', basis=None)])]),
        bad or (json.dumps({'explanations':[{'row':1,'text':'Giải thích theo căn cứ.'}]},ensure_ascii=False)
                if version in ('answer_v9','answer_v7') else '## Trả lời ngắn\nSai.\n\n'+BODY), DIRECT_answer_consistency, *repairs)
    def prepare(message, queries, **kwargs):
        location_chunks = [dict(chunk_id='chunk-a', parent_id=regular[0]['parent_id'],
                               document_id='d', article='1', clause=None, point=None)]
        return dict(evidence=build_evidence(regular, DOCUMENTS), queries=queries, query_used=queries[0],
            references_added=[], detail={}, timing={}, route='retrieval', prompt_version=version,
            parents_used=[regular[0]['parent_id']], chunks=location_chunks,
            index=build_location_index(allparents, location_chunks))
    graph = build_graph(GraphDeps(chat, 'fake', prepare, AgentConfig(enable_rewrite=False),
        pipeline_factory=lambda: SimpleNamespace(search=lambda q: [dict(chunk_id=ITEM_ID)]),
        parents=allparents, documents=DOCUMENTS, high_risk_loader=lambda: [RISK_ITEM], obligations_loader=lambda: [row],
        chunks_loader=lambda: [dict(chunk_id='chunk-a', parent_id=regular[0]['parent_id'])]))
    result = run_turn(graph, 's', 'Nghĩa vụ AI?', facts_override=facts)
    return result, graph, chat


@pytest.mark.parametrize('version', ['answer_v9', 'answer_v7'])
def test_graph_optin_exact_facts_override_and_core_rows_no_extra_calls(version):
    facts = dict(empty_facts(), roles=['nha_cung_cap', 'ben_trien_khai'], sectors=[], risk_level='trung_binh',
                 is_public_sector=False, content_types=[])
    before = deepcopy(facts)
    result, graph, chat = graph_case_facts_obligation_presentation(version, facts)
    state = graph.get_state({'configurable': {'thread_id': 's'}}).values
    assert state['prompt_version'] == 'answer_v12' and result['llm_calls'] == len(chat.payloads) == 4  # T57: +1 trả lời trực tiếp
    assert facts == before == state['prepared']['presentation_facts']
    assert result['map_obligations']['items'][0]['applicability'] == 'ap_dung'
    assert state['prepared']['presentation_context']['facts_source'] == 'assessment'
    assert 'mức rủi ro đã khai trong hồ sơ: trung bình' in result['reply']
    assert 'Nghĩa vụ riêng không được gộp.' in result['reply'] and result['check']['valid']
    generated = next(n for n in result['trace'] if n['node'] == 'generate')
    assert generated['presentation']['snapshot_rows'] == generated['presentation']['displayed_rows'] == 1
    chat.responses = iter([analysis(request_kinds=['kien_thuc']), '## Trả lời ngắn\nĐáp [E1].\n\n## Căn cứ\nNguồn [E1].'])
    second = run_turn(graph, 's', 'Định nghĩa là gì?')
    reset = graph.get_state({'configurable': {'thread_id': 's'}}).values['prepared']
    assert next(n for n in second['trace'] if n['node'] == 'generate')['effective_prompt_version'] == 'answer_v9'
    assert 'presentation_facts' not in reset


@pytest.mark.parametrize('version', ['answer_v10', 'answer_v8'])
def test_explicit_legacy_versions_are_not_upgraded(version):
    result, graph, _ = graph_case_facts_obligation_presentation(version)
    assert next(n for n in result['trace'] if n['node'] == 'generate')['effective_prompt_version'] == version
    ctx = graph.get_state({'configurable': {'thread_id': 's'}}).values['prepared']['presentation_context']
    assert 'facts_source' not in ctx and 'Dữ kiện đã dùng để lọc nghĩa vụ' not in ctx['data']


def test_graph_recheck_keeps_outside_citation_error_and_notice_after_one_repair():
    bad = json.dumps({'explanations':[{'row':1,'text':'Quy định [E99].'}]},ensure_ascii=False)
    result, _, chat = graph_case_facts_obligation_presentation(bad=bad, repairs=(bad,))
    assert result['llm_calls'] == len(chat.payloads) == 5
    assert not result['check']['valid'] and NOTICE in result['reply'] and '[E99]' not in result['reply']
    assert '[E99]' in json.dumps(result['trace'],ensure_ascii=False)
    for node in result['trace']:
        if node['node'] in ('generate', 'repair_answer', 'recheck'):
            assert node['presentation']['facts_source'] == 'profile'
            assert len(node['presentation']['owned_sections']) == 4
