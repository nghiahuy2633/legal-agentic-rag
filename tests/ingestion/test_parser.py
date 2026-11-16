"""Tách Điều, Khoản, Điểm và các trường hợp cấu trúc đặc biệt."""

import json
from pathlib import Path
import unicodedata
import pytest
from legal_rag.ingestion.normalize import apply_corrections, normalize_page
from legal_rag.ingestion.parser import POINT_ORDER, parse_articles
from legal_rag.ingestion.normalize import apply_corrections
from legal_rag.ingestion.parser import parse_articles
from legal_rag.ingestion.chunking import build_outputs
from legal_rag.ingestion.supplements import parse_appendices, parse_high_risk_list


ROOT = Path(__file__).resolve().parents[2]


def pages(*texts):
    return [dict(document_id="synthetic", page=i, text=text)
            for i, text in enumerate(texts, 1)]


def real_pages(document="134-2025-QH15"):
    """Trang thật như parser nhận: bản OCR sau chuẩn hóa bố cục và hiệu đính."""
    source = ROOT / f"data/processed/text/{document}.jsonl"
    return apply_corrections([json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()],
                             ROOT / "data/processed/text_corrections.csv")


@pytest.fixture(scope="module")
def real_articles():
    return parse_articles(real_pages())


def test_normalize_page_number_nfc_and_preserve_body():
    text = "\n12\n\nĐiều 1. Dữ liệu\n12\nEmail: nội dung\n"
    normalized = normalize_page(unicodedata.normalize("NFD", text), 12)
    assert normalized == "\n\nĐiều 1. Dữ liệu\n12\nEmail: nội dung"


SIGNATURE = "Người ký: A\nEmail: B\nCơ quan: C\nThời gian ký: D"


@pytest.mark.parametrize("prefix", ["", "\n1\n", "VGP\nCHINHPHU.VN\n"])
def test_signature_only_contiguous_at_start_of_page_one(prefix):
    assert normalize_page(prefix + SIGNATURE + "\nĐiều 1. A", 1).endswith("Điều 1. A")
    assert "Người ký:" not in normalize_page(prefix + SIGNATURE, 1)


@pytest.mark.parametrize("text,page", [
    (SIGNATURE, 2), ("Nội dung\n" + SIGNATURE, 1),
    (SIGNATURE.replace("Email:", "\nEmail:"), 1),
    ("Người ký: A\nEmail: B", 1),
])
def test_keep_non_header_or_incomplete_signature(text, page):
    assert normalize_page(text, page) == text


def test_cross_page_clause_point_title_and_chapter_section():
    result = parse_articles(pages(
        "Chương I\nTÊN CHƯƠNG\nDÒNG HAI\nMục 1\nTên mục\n"
        "Điều 1. Tiêu đề\nđược nối\n1. Câu dẫn:\na) Một phần",
        "2\ncòn lại;\nb) Hai.\n2. Khoản cuối kéo",
        "3\ndài.\nĐiều 2. Không có khoản\nNội dung.\nChương II\nCHƯƠNG MỚI\n"
        "Điều 3. Tiêu đề\nNội dung khác.",
    ))
    first = result[0]
    assert first["title"] == "Tiêu đề được nối"
    assert first["chapter_title"] == "TÊN CHƯƠNG DÒNG HAI"
    assert (first["section"], first["section_title"]) == ("1", "Tên mục")
    assert (first["page_start"], first["page_end"]) == (1, 3)
    assert first["clauses"] == [
        {"clause": "1", "lead_in": "Câu dẫn:", "page": 1, "closing": "", "closing_page": None, "points": [
            {"point": "a", "text": "Một phần còn lại;", "page": 1},
            {"point": "b", "text": "Hai.", "page": 2},
        ]},
        {"clause": "2", "lead_in": "Khoản cuối kéo dài.", "points": [], "closing": "", "closing_page": None, "page": 2},
    ]
    assert result[1]["intro"] == "Nội dung."
    assert result[1]["clauses"] == []
    assert result[2]["section"] is None
    assert result[2]["section_title"] is None


def test_references_and_numeric_sentences_are_content():
    text = ("Điều 1. Tiêu đề\n1. Theo quy định tại khoản 2 Điều 13, năm\n"
            "2026. Đây là câu tiếp theo.\n2.5 triệu đồng theo nội dung.\n"
            "Điều 13 của văn bản;\n2. Khoản tiếp theo.")
    article = parse_articles(pages(text))[0]
    assert len(article["clauses"]) == 2
    assert article["clauses"][0]["lead_in"] == (
        "Theo quy định tại khoản 2 Điều 13, năm 2026. Đây là câu tiếp theo. "
        "2.5 triệu đồng theo nội dung. Điều 13 của văn bản;"
    )


@pytest.mark.parametrize("ending", [
    "Luật này được Quốc hội nước ...", "Luật này đã được Quốc hội thông qua.",
    "CHỦ TỊCH QUỐC HỘI", "TM. CHÍNH PHỦ", "KT. BỘ TRƯỞNG", "Nơi nhận:",
])
def test_stop_before_closing_and_signature(ending):
    result = parse_articles(pages("Điều 1. A\n1. Nội dung.", "2\n" + ending + "\nTên người ký"))
    assert result[0]["clauses"][0]["lead_in"] == "Nội dung."
    assert result[0]["page_end"] == 1


@pytest.mark.parametrize("text,number", [
    ("Điều 2. A", "2"),
    ("Điều 1. A\nNội dung.\nĐiều 3. B", "3"),
    ("Điều 1. A\nNội dung.\nĐiều 1. B", "1"),
])
def test_abnormal_articles_raise_with_number(text, number):
    with pytest.raises(ValueError, match=f"Điều {number}.*chờ Điều"):
        parse_articles(pages(text))


@pytest.mark.parametrize("text", [
    "Điều 1. A\n2. Thiếu khoản.",
    "Điều 1. A\n1. Dẫn:\na) A;\nc) Thiếu điểm.",
    "Điều 1. A\na) Không có khoản.",
])
def test_invalid_hierarchy_is_not_silently_accepted(text):
    with pytest.raises(ValueError, match="Điều 1"):
        parse_articles(pages(text))


def test_markdown_heading_keeps_body_punctuation():
    article = parse_articles(pages("**Điều 1. Tên điều**\nNội dung *nguyên văn*;"))[0]
    assert article["title"] == "Tên điều"
    assert article["intro"] == "Nội dung *nguyên văn*;"


def test_real_article_sequence(real_articles):
    assert [article["article"] for article in real_articles] == [str(i) for i in range(1, 36)]


def test_real_key_articles(real_articles):
    seven, eight, nine = real_articles[6:9]
    assert len(seven["clauses"]) == 6
    assert "nhằm mục đích sau đây" in seven["clauses"][1]["lead_in"]
    assert [p["point"] for p in seven["clauses"][1]["points"]] == list("abcd")
    assert eight["title"].startswith("Cổng thông tin điện tử một cửa")
    assert eight["title"].endswith("liệu quốc gia về hệ thống trí tuệ nhân tạo")
    assert len(eight["clauses"]) == 4
    assert eight["page_start"] == 4
    assert "được phân loại theo các mức độ rủi ro sau đây" in nine["clauses"][0]["lead_in"]
    assert [p["point"] for p in nine["clauses"][0]["points"]] == list("abc")
    assert nine["chapter"] == "II"
    assert nine["chapter_title"] == "PHÂN LOẠI VÀ QUẢN LÝ HỆ THỐNG TRÍ TUỆ NHÂN TẠO THEO RỦI RO"


def test_real_all_clauses_points_and_content(real_articles):
    for article in real_articles:
        clauses = article["clauses"]
        assert [c["clause"] for c in clauses] == [str(i) for i in range(1, len(clauses) + 1)]
        assert article["page_start"] <= article["page_end"]
        texts = [article["intro"], article["title"]]
        for clause in clauses:
            assert clause["lead_in"].strip()
            assert article["page_start"] <= clause["page"] <= article["page_end"]
            assert [p["point"] for p in clause["points"]] == list(POINT_ORDER[:len(clause["points"])])
            texts.append(clause["lead_in"])
            for point in clause["points"]:
                assert point["text"].strip()
                assert clause["page"] <= point["page"] <= article["page_end"]
                texts.append(point["text"])
        assert not any(text.strip().isdigit() for text in texts)
        assert not any("\n" in text for text in texts)
    last = json.dumps(real_articles[-1], ensure_ascii=False)
    assert "Luật này được Quốc hội" not in last
    assert "CHỦ TỊCH QUỐC HỘI" not in last
    assert "Trần Thanh Mẫn" not in last
    assert real_articles[-1]["page_end"] == 20


def test_real_deterministic_and_no_mutation():
    input_pages = real_pages()
    before = json.dumps(input_pages, ensure_ascii=False)
    assert parse_articles(input_pages) == parse_articles(input_pages)
    assert json.dumps(input_pages, ensure_ascii=False) == before


def test_real_reconstructs_complete_body_without_page_numbers(real_articles):
    """Ghép cấu trúc phải khôi phục toàn bộ thân, không mất chữ/dấu câu."""
    normalized_lines = []
    for page in real_pages():
        for line in normalize_page(page["text"], page["page"]).splitlines():
            line = line.strip()
            if line.startswith("**") and line.endswith("**"):
                line = line[2:-2]
            normalized_lines.append(line)
    expected = " ".join(" ".join(normalized_lines).split())
    expected = expected[expected.index("Điều 1. "):]
    expected = expected[:expected.index("Luật này được Quốc hội")].strip()
    reconstructed = []
    chapter = real_articles[0]["chapter"]
    for article in real_articles:
        if chapter != article["chapter"]:
            reconstructed.extend(["Chương " + article["chapter"], article["chapter_title"]])
            chapter = article["chapter"]
        reconstructed.extend([f"Điều {article['article']}. {article['title']}", article["intro"]])
        for clause in article["clauses"]:
            reconstructed.append(f"{clause['clause']}. {clause['lead_in']}")
            for point in clause["points"]:
                reconstructed.append(f"{point['point']}) {point['text']}")
            if clause["closing"]:
                reconstructed.append(clause["closing"])
    assert " ".join(" ".join(reconstructed).split()) == expected


def _points_text(*letters):
    return "Điều 1. A\n1. Câu dẫn:\n" + "\n".join(f"{letter}) Nội dung;" for letter in letters)


@pytest.mark.parametrize("letters", ["abcdđe", "abcde", "abcdeg", "abcdđeg", "abcd"])
def test_point_sequences_with_or_without_d_stroke(letters):
    result = parse_articles(pages(_points_text(*letters)))
    assert [p["point"] for p in result[0]["clauses"][0]["points"]] == list(letters)


@pytest.mark.parametrize("letters", ["b", "ac", "abd", "abcdg", "abcdđg", "abcdeđ", "abcdđđ", "aa"])
def test_other_point_jumps_still_fail(letters):
    with pytest.raises(ValueError, match="dãy Điểm không liên tục"):
        parse_articles(pages(_points_text(*letters)))


ROOT = Path(__file__).resolve().parents[2]


def pages_structure_fixes(*texts, doc='nd'):
    return [dict(document_id=doc, page=i, text=t) for i, t in enumerate(texts, 1)]


def read(name):
    rows = [json.loads(l) for l in (ROOT / f'data/processed/{name}.jsonl').read_text(encoding='utf8').splitlines()]
    # Trang text được đọc như parser nhận: sau chuẩn hóa bố cục OCR và hiệu đính.
    return apply_corrections(rows, ROOT / 'data/processed/text_corrections.csv') if name.startswith('text/') else rows


def test_closing_is_only_after_last_point_and_keeps_page():
    rows = parse_articles(pages_structure_fixes('Điều 1. Tên\n1. Câu dẫn:\na) Một.\nVẫn thuộc điểm a;\nb) Hai.',
                                'Đoạn cuối Khoản\ntiếp tục.\n2. Khác.'))
    c = rows[0]['clauses'][0]
    assert c['points'][0]['text'] == 'Một. Vẫn thuộc điểm a;'
    assert c['points'][-1]['text'] == 'Hai.'
    assert (c['closing'], c['closing_page']) == ('Đoạn cuối Khoản tiếp tục.', 2)
    assert rows[0]['clauses'][1]['closing'] == ''


def test_reference_inherits_explicit_lead_only():
    law = dict(document_id='law', document_number='1/2025/QH15', document_title='Luật Mẫu',
               document_type='luat', effective_from='2026-01-01')
    decree = dict(law, document_id='nd', document_title='Nghị định Mẫu', document_type='nghi_dinh')
    for lead, expected in [('Quy định chi tiết một số điều của Luật Mẫu bao gồm:', 'law'),
                            ('Các nội dung theo Luật Mẫu:', 'law'),
                            ('Các nội dung sau:', None),
                            ('Theo Luật Mẫu và Nghị định số 9/2020/NĐ-CP:', None)]:
        result = build_outputs([law, decree], {
            'law': parse_articles(pages_structure_fixes('Điều 1. Tên\n1. Nội dung.', doc='law')),
            'nd': parse_articles(pages_structure_fixes(f'Điều 1. Tên\n1. {lead}\na) Khoản 1 Điều 1.'))})
        row = next(r for r in result['references'] if r['raw_text'] == 'Khoản 1 Điều 1')
        assert row['target_document_id'] == expected
        assert row['resolved'] == (expected is not None)


@pytest.mark.parametrize('marks,expected', [('x |','diem_b'), ('| x','diem_a'), ('|','khac'), ('x | x','khac')])
def test_list_headers_continuation_and_conformity(marks, expected):
    header = '| STT | Tên hệ thống | Mô tả hệ thống | Đánh giá sự phù hợp | |\n|---|---|---|---|---|'
    result = parse_high_risk_list(pages_structure_fixes(header + '\n| I | Lĩnh vực mẫu | | | |\n' +
        f'| 1 | Hệ<br>thống | Chỉ áp dụng khi | {marks} |',
        header + '\n| | | | | |\n| | | được xác nhận. | | |'))
    assert len(result) == 1
    assert result[0]['name'] == 'Hệ thống'
    assert result[0]['description'] == 'Chỉ áp dụng khi được xác nhận.'
    assert result[0]['pages'] == [1, 2]
    assert result[0]['conformity'] == expected


def test_real_known_closings_and_last_points():
    articles = read('articles/142-2026-ND-CP')
    for a, c, last, prefix in [(13,1,'đ','Các hoạt động cập nhật'),
                                (40,8,'c','Việc thanh toán'),
                                (41,3,'d','Việc tiếp nhận')]:
        clause = articles[a-1]['clauses'][c-1]
        assert clause['closing'].startswith(prefix)
        assert clause['points'][-1]['point'] == last
        assert prefix not in clause['points'][-1]['text']
        assert clause['points'][-1]['text'].endswith('.')
    points = { (13,1): 'Các thay đổi khác làm ảnh hưởng đáng kể đến việc đáp ứng các yêu cầu quy định tại Điều 14 của Luật Trí tuệ nhân tạo.',
               (40,8): 'Hoá đơn và chứng từ kế toán chứng minh việc hoàn thành cung cấp dịch vụ theo quy định của pháp luật.',
               (41,3): 'Các nội dung khác theo quy định của Nghị định này.' }
    for (a,c), text in points.items():
        assert articles[a-1]['clauses'][c-1]['points'][-1]['text'] == text


def test_real_all_fifteen_references():
    rows = [r for r in read('references') if r['source_chunk_id'].startswith('142-2026-ND-CP_dieu-1_khoan-1_diem-')]
    assert len(rows) == 15
    assert all(r['target_document_id'] == '134-2025-QH15' and r['resolved'] for r in rows)


def test_real_appendices_and_list_have_exact_sources_and_sectors():
    raw = read('text/05-2026-TT-BKHCN')
    items = read('articles/05-2026-TT-BKHCN.appendices')
    assert parse_appendices(raw) == items
    assert [(r['appendix'], r['item']) for r in items] == [('1',str(i)) for i in range(1,4)] + [('2',i) for i in 'ABCDEG']
    risks = read('high_risk_list')
    assert risks == parse_high_risk_list(read('text/33-2026-QD-TTg'))
    assert len(risks) == 46
    assert {r['sector_number'] for r in risks} == {'I','II','III','IV','V','VI'}
    assert all(r['sector'] and r['stt'].isdigit() for r in risks)
    six = next(r for r in risks if r['sector_number'] == 'VI' and r['stt'] == '6')
    assert six['pages'] == [10,11]
    assert 'kết quả được sử dụng trực tiếp' in six['description']
    chunks = read('chunks'); parents = {r['parent_id']: r for r in read('parents')}
    for row in chunks:
        if row['level'] in ('appendix_item','list_item'):
            assert row['article'] is row['clause'] is row['article_id'] is None
            assert row['chunk_id'] in parents[row['parent_id']]['chunk_ids']


def test_closing_chunks_follow_points_and_parent_restores_labels():
    chunks = read('chunks')
    parents = {r['parent_id']: r for r in read('parents')}
    articles = read('articles/142-2026-ND-CP')
    for article in articles:
        for clause in article['clauses']:
            if not clause['closing']:
                continue
            base = f"142-2026-ND-CP_dieu-{article['article']}_khoan-{clause['clause']}"
            closing = next(r for r in chunks if r['chunk_id'] == base + '_cuoi')
            assert closing['level'] == 'clause_closing'
            assert closing['page'] == clause['closing_page']
            assert f"Khoản {clause['clause']}: {clause['lead_in']}" in closing['context']
            parent = parents[base]
            assert parent['chunk_ids'][-1] == closing['chunk_id']
            expected = [f"{clause['clause']}. {clause['lead_in']}"]
            expected += [f"{p['point']}) {p['text']}" for p in clause['points']]
            expected.append(clause['closing'])
            assert parent['text'] == '\n'.join(expected)


def test_appendix_items_and_repeated_form_header():
    header = 'Nội dung đánh giá\nMức độ đáp\nứng\n& thời hạn'
    result = parse_appendices(pages_structure_fixes('PHỤ LỤC I\nTên phụ lục\n1. Đối với người dùng\na) Nội dung.',
                                    'PHỤ LỤC II\nTên mẫu\n' + header + '\nA. Thông tin\nchung\nB. Nguyên tắc\n1. Một.',
                                    header + '\n2. Hai.\nG. Kết luận'))
    assert [r['item'] for r in result] == ['1','A','B','G']
    assert result[1]['title'] == 'Thông tin chung'
    assert result[2]['body'] == '1. Một. 2. Hai.'
    assert result[2]['pages'] == [2,3]
