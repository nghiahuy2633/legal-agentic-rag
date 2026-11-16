"""Kiểm độ phủ bằng chứng và khuôn trình bày theo phiên bản trả lời."""

import re

from legal_rag.generation.citations import check_blocks as evidence_blocks
from legal_rag.generation.citations import markdown_code_mask
from legal_rag.agent.followup import before_closing

OBLIGATION_BLOCKS = ("Quy định áp dụng", "Nghĩa vụ cần xem xét",
                     "Thông tin còn thiếu và giới hạn")


def required_blocks(question_type="khac"):
    return ("Trả lời ngắn",) + (
        OBLIGATION_BLOCKS if question_type == "nghia_vu" else ("Căn cứ",))


def normalize_headings(answer, version, question_type="khac"):
    if version not in ("answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        return answer

    def key(text):
        return " ".join(re.sub(r"[^\w\s]", "", text.replace("_", "")).casefold().split())

    titles = {key(title): title for title in required_blocks(question_type)}

    lines = answer.splitlines(keepends=True)
    visible = markdown_code_mask(answer).splitlines(keepends=True)
    normalized = []
    for line, masked in zip(lines, visible):
        match = re.match(r"^##[ \t]+([^\r\n]+)", masked)
        if not match:
            normalized.append(line)
            continue
        ending = line[len(line.rstrip("\r\n")):]
        title = titles.get(key(match[1]))
        if title and masked == line:
            normalized.append("## " + title + ending)
            continue
        # V11 sở hữu thêm hai mục; giữ nội dung sau dấu hai chấm trước khi dựng lại.
        colon = re.search(r"[:：]", match[1])
        inline = titles.get(key(match[1][:colon.start()])) if colon else None
        owned = ("Trả lời ngắn", "Nghĩa vụ cần xem xét", "Thông tin còn thiếu và giới hạn")
        if inline == "Trả lời ngắn" or (version == "answer_v11" and inline in owned):
            raw_title = line[match.start(1):match.start(1) + colon.start()]
            body = line[match.start(1) + colon.end():].rstrip("\r\n").lstrip()
            for wrapper in ("**", "__"):
                if raw_title.count(wrapper) % 2 and body.startswith(wrapper):
                    body = body[len(wrapper):].lstrip()
            normalized.append("## " + inline + (ending or "\n")
                              + ((ending or "\n") + body + ending if body else ""))
        else:
            normalized.append(line)
    result = "".join(normalized)
    # Gom nguyên phần thân các mục trùng vào mục đầu, không để nội dung rơi
    # vào mục Căn cứ hoặc làm mất tiêu đề khác nằm giữa hai mục Trả lời ngắn.
    masked = markdown_code_mask(result)
    headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", masked, re.M))
    short = [i for i, match in enumerate(headings) if key(match[1]) == key("Trả lời ngắn")
             and result[match.start():match.end()] == masked[match.start():match.end()]]
    if len(short) < 2:
        return result
    body, closing = before_closing(result)
    if closing and closing in masked:
        result = body
        masked = markdown_code_mask(result)
        headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", masked, re.M))
    else:
        closing = ""
    sections = [result[m.start():headings[i + 1].start() if i + 1 < len(headings) else len(result)]
                for i, m in enumerate(headings)]
    bodies = [sections[i][headings[i].end() - headings[i].start():].strip("\r\n") for i in short]
    first = short[0]
    header = sections[first][:headings[first].end() - headings[first].start()].rstrip("\r\n")
    sections[first] = header + "\n\n" + "\n\n".join(body for body in bodies if body) + "\n\n"
    merged = result[:headings[0].start()] + "".join(section for i, section in enumerate(sections)
                                                  if i not in short[1:])
    return merged.rstrip() + "\n\n" + closing if closing else merged


def check_blocks(check, items, answer, version, question_type="khac"):
    missing = evidence_blocks(check, items)
    if version not in ("answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        return missing
    required = required_blocks(question_type)
    answer = normalize_headings(answer, version, question_type)
    masked = markdown_code_mask(answer)
    # LLM hay viết "## Trả lời ngắn:" hoặc in đậm tiêu đề; chỉ so phần chữ.
    headings = [re.sub(r"[*:：\s]+$", "", re.sub(r"^[*\s]+", "", h))
                for match in re.finditer(r"^##[ \t]+([^\r\n]+?)[ \t]*\r?$", masked, re.MULTILINE)
                if answer[match.start():match.end()] == masked[match.start():match.end()]
                for h in [match[1]]]
    missing.extend(title for title in required if title not in headings)
    return list(dict.fromkeys(missing))


def apply_blocks(check, items, answer, version, question_type="khac"):
    check["missing_blocks"] = check_blocks(check, items, answer, version, question_type)
    if version in ("answer_v9", "answer_v10", "answer_v11", "answer_v12"):
        check["errors"].extend(f"Thiếu mục bắt buộc: {title}"
                               for title in check["missing_blocks"])
    check["valid"] = check["valid"] and not check["missing_blocks"]
    return check
