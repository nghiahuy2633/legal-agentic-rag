"""Phân tích cấu trúc pháp lý từ dòng và giữ nguồn trang PDF."""

import re

from legal_rag.ingestion.normalize import normalize_page


ARTICLE = re.compile(r"^Điều\s+(\d+)\.\s+(.+)$")
CHAPTER = re.compile(r"^Chương\s+([IVXLCDM]+|\d+)(?:\.\s*|\s+)?(.*)$")
SECTION = re.compile(r"^Mục\s+(\d+)(?:\.\s*|\s+)?(.*)$")
CLAUSE = re.compile(r"^(\d+)\.\s+(.+)$")
POINT = re.compile(r"^([a-zđ])\)\s+(.+)$")
ENDING = re.compile(
    r"^(?:Luật này (?:đã )?được Quốc hội\b|"
    r"(?:TM\.\s*)?CHÍNH PHỦ$|(?:KT\.\s*)?THỦ TƯỚNG|"
    r"CHỦ TỊCH QUỐC HỘI|(?:KT\.\s*)?BỘ TRƯỞNG|Nơi nhận:)"
)
POINT_ORDER = "abcdđ eghiklmnopqrstuvxy".replace(" ", "")


def _valid_next_point(points: list[dict], number: str) -> bool:
    """Dãy Điểm có `đ` hoặc bỏ `đ` (d rồi e) đều hợp lệ; nhảy chữ khác thì không."""
    if not points:
        return number == POINT_ORDER[0]
    previous = points[-1]["point"]
    position = POINT_ORDER.index(previous) + 1
    return number == POINT_ORDER[position:position + 1] or (previous == "d" and number == "e")


def _heading_text(line: str) -> str:
    # OCR có thể bọc tiêu đề bằng Markdown; không bỏ dấu * trong phần thân.
    return line[2:-2].strip() if line.startswith("**") and line.endswith("**") else line


def _join(old: str, line: str) -> str:
    return f"{old} {line}" if old else line


def parse_articles(pages: list[dict]) -> list[dict]:
    """Nhận các trang theo hợp đồng text; lỗi dãy số không được tự sửa."""
    if not pages:
        raise ValueError("Không có trang đầu vào")
    document_id = pages[0]["document_id"]
    previous_page = 0
    lines = []
    for page in pages:
        number = page["page"]
        if page["document_id"] != document_id or number != previous_page + 1:
            raise ValueError(f"Văn bản hoặc dãy trang không hợp lệ tại trang {number}")
        previous_page = number
        lines.extend((number, line.strip()) for line in
                     normalize_page(page["text"], number).splitlines() if line.strip())

    articles = []
    article = clause = point = None
    chapter = chapter_title = section = section_title = None
    heading = None
    title_open = False
    for page, line in lines:
        clean = _heading_text(line)
        if article is not None and ENDING.match(clean):
            break
        match_chapter = CHAPTER.fullmatch(clean)
        match_section = SECTION.fullmatch(clean)
        if match_chapter or match_section:
            match = match_chapter or match_section
            if match_chapter:
                chapter, chapter_title = match.groups()
                section = section_title = None
                heading = "chapter"
            else:
                section, section_title = match.groups()
                heading = "section"
            article = clause = point = None
            title_open = False
            continue
        match = ARTICLE.fullmatch(clean)
        if match:
            number, title = match.groups()
            expected = len(articles) + 1
            if int(number) != expected:
                raise ValueError(f"Điều {number} tại trang {page}: chờ Điều {expected}")
            article = dict(document_id=document_id, article=number, title=title,
                           chapter=chapter, chapter_title=chapter_title,
                           section=section, section_title=section_title,
                           intro="", clauses=[], page_start=page, page_end=page)
            articles.append(article)
            clause = point = None
            heading = None
            title_open = True
            continue
        if heading:
            if heading == "chapter":
                chapter_title = _join(chapter_title, clean)
            else:
                section_title = _join(section_title, clean)
            continue
        if article is None:
            continue
        article["page_end"] = page
        match = CLAUSE.fullmatch(line)
        # Câu tiếp nối như "2026. Đây ..."/"2.5 ..." không phải Khoản.
        # Khoản pháp lý bắt đầu bằng chữ hoa, với số thứ tự ngắn.
        if match and len(match[1]) <= 2 and match[2][0].isupper():
            number, text = match.groups()
            expected = len(article["clauses"]) + 1
            if int(number) != expected:
                raise ValueError(f"Điều {article['article']}, Khoản {number}, trang {page}: "
                                 f"chờ Khoản {expected}")
            clause = dict(clause=number, lead_in=text, points=[], closing="", closing_page=None, page=page)
            article["clauses"].append(clause)
            point = None
            title_open = False
            continue
        match = POINT.fullmatch(line)
        if match:
            if clause is None:
                raise ValueError(f"Điều {article['article']}, trang {page}: Điểm không có Khoản")
            number, text = match.groups()
            if not _valid_next_point(clause["points"], number):
                raise ValueError(f"Điều {article['article']}, Khoản {clause['clause']}, "
                                 f"Điểm {number}, trang {page}: dãy Điểm không liên tục")
            if clause["closing"]:
                point["text"] = _join(point["text"], clause["closing"])
                clause["closing"] = ""
                clause["closing_page"] = None
            point = dict(point=number, text=text, page=page)
            clause["points"].append(point)
            title_open = False
            continue
        # Dòng tiêu đề bị ngắt giữa cụm từ tiếp tục bằng chữ thường.
        # Dòng mở đầu nội dung độc lập bắt đầu bằng chữ hoa.
        if title_open and line[0].islower():
            article["title"] = _join(article["title"], clean)
        else:
            title_open = False
            if point is not None:
                if clause["closing"]:
                    clause["closing"] = _join(clause["closing"], line)
                elif line[0].isupper() and point["text"].endswith((".", ";")):
                    clause["closing"] = line
                    clause["closing_page"] = page
                else:
                    point["text"] = _join(point["text"], line)
            elif clause is not None:
                clause["lead_in"] = _join(clause["lead_in"], line)
            else:
                article["intro"] = _join(article["intro"], line)
    if not articles:
        raise ValueError("Không tìm thấy Điều nào")
    return articles
