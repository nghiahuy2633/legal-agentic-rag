"""Phụ lục theo mục thật và bảng Danh mục; không tạo Điều giả."""

import re

from legal_rag.ingestion.normalize import normalize_page


APPENDIX = re.compile(r"^PHỤ LỤC (I|II)$", re.I)


def parse_appendices(pages: list[dict]) -> list[dict]:
    rows = []
    appendix = None
    item = None
    heading_lines = []
    skip_columns = False
    for page in pages:
        for raw in normalize_page(page["text"], page["page"]).splitlines():
            line = raw.strip()
            if not line:
                continue
            match = APPENDIX.fullmatch(line)
            if match:
                appendix = str(len({row['appendix'] for row in rows}) + 1)
                item = None
                heading_lines = []
                continue
            if appendix is None:
                continue
            if line == "Nội dung đánh giá":
                skip_columns = True
                continue
            if skip_columns:
                if line == "& thời hạn":
                    skip_columns = False
                continue
            match = re.match(r"^(\d+)\. (.+)$" if appendix == "1" else r"^([A-ZĐ])\. (.+)$", line)
            if match:
                number, title = match.groups()
                item = dict(document_id=page['document_id'], appendix=appendix,
                            appendix_title=" ".join(heading_lines), item=number,
                            title=title, body="", pages=[page['page']])
                rows.append(item)
            elif item is None:
                heading_lines.append(line)
            else:
                # Mục I có tiêu đề xuống dòng trước Điểm a; II giữ các hàng con trong body.
                marker = r"^[a-zđ]\) " if appendix == "1" else r"^\d+\. "
                if not item['body'] and not re.match(marker, line):
                    item['title'] += " " + line
                else:
                    item['body'] = (item['body'] + " " + line).strip()
                if page['page'] not in item['pages']:
                    item['pages'].append(page['page'])
    return rows


def _cell(value: str) -> str:
    return " ".join(re.sub(r"<br\s*/?>", " ", value, flags=re.I).split())


def parse_high_risk_list(pages: list[dict]) -> list[dict]:
    rows = []
    sector_number = sector = None
    marks = []
    for page in pages:
        for line in page['text'].splitlines():
            if not line.strip().startswith('|'):
                continue
            cells = [_cell(c) for c in line.strip().strip('|').split('|')]
            if len(cells) != 5:
                raise ValueError(f"Bảng trang {page['page']}: cần 5 cột")
            stt, name, description, first, second = cells
            if all(not c or re.fullmatch(r'[-:]+', c) for c in cells):
                continue
            if stt == 'STT' or any('Theo quy định tại điểm' in c for c in cells):
                continue
            if re.fullmatch(r'[IVXLCDM]+', stt):
                sector_number, sector = stt, name
                continue
            if stt.isdigit():
                if sector is None:
                    raise ValueError('Mục không có lĩnh vực')
                row = dict(item_id=f"{page['document_id']}_linh-vuc-{sector_number}_stt-{stt}",
                           sector_number=sector_number, sector=sector, stt=stt,
                           name=name, description=description, conformity='khac', pages=[page['page']])
                rows.append(row)
                marks.append([first, second])
            elif not stt and (name or description or first or second):
                if not rows:
                    raise ValueError('Hàng nối không có mục trước')
                row = rows[-1]
                row['name'] = (row['name'] + ' ' + name).strip()
                row['description'] = (row['description'] + ' ' + description).strip()
                if page['page'] not in row['pages']:
                    row['pages'].append(page['page'])
                marks[-1] += [first, second]
            else:
                raise ValueError(f"Không nhận diện hàng trang {page['page']}: {stt}")
    for row, values in zip(rows, marks):
        crosses = [(i % 2) for i, value in enumerate(values) if value.lower() == 'x']
        row['conformity'] = ('diem_b' if crosses[0] == 0 else 'diem_a') if len(crosses) == 1 else 'khac'
    return rows


def build_supplement(document: dict, items: list[dict], level: str,
                     max_chars: int, overlap_sentences: int) -> tuple[list[dict], list[dict], int]:
    from legal_rag.ingestion.chunking import split_text

    chunks, parents = [], []
    split_count = 0
    for item in items:
        if level == 'appendix_item':
            identifier = f"{document['document_id']}_phu-luc-{item['appendix']}_muc-{item['item']}"
            title = f"Mục {item['item']}. {item['title']}"
            context = f"Phụ lục {item['appendix']}. {item['appendix_title']}\n{title}"
            body = f"{item['title']} {item['body']}".strip()
        else:
            identifier = item['item_id']
            title = f"{item['sector']}, STT {item['stt']}"
            meaning = {'diem_a': 'Đánh giá sự phù hợp theo điểm a, khoản 2 Điều 13 Luật Trí tuệ nhân tạo',
                       'diem_b': 'Đánh giá sự phù hợp theo điểm b, khoản 2 Điều 13 Luật Trí tuệ nhân tạo',
                       'khac': 'Chưa xác định loại đánh giá sự phù hợp (không có đúng một dấu x)'}
            context = f"Phụ lục. DANH MỤC HỆ THỐNG TRÍ TUỆ NHÂN TẠO CÓ RỦI RO CAO\n{title}\n{meaning[item['conformity']]}"
            body = f"{item['name']} {item['description']}".strip()
        context = f"{document['document_title']} (số {document['document_number']})\n{context}"
        parts = split_text(body, max_chars, overlap_sentences)
        split_count += len(parts) > 1
        ids = []
        for i, part in enumerate(parts, 1):
            chunk_id = identifier if i == 1 else f'{identifier}_phan-{i}'
            ids.append(chunk_id)
            chunks.append(dict(chunk_id=chunk_id, document_id=document['document_id'],
                               document_number=document['document_number'], document_title=document['document_title'],
                               article=None, clause=None, point=None, level=level, body=part,
                               context=context, index_text=f'{context}\n\n{part}', parent_id=identifier,
                               article_id=None, page=item['pages'][0], effective_from=document['effective_from'],
                               delegates=False))
        parents.append(dict(parent_id=identifier, level=level, document_id=document['document_id'],
                            article=None, clause=None, title=title, pages=item['pages'], context=context,
                            text=f"{item['item']}. {body}" if level == 'appendix_item' else body,
                            chunk_ids=ids))
    return chunks, parents, split_count
