"""Chấm riêng từng nhóm và ghép kết quả, giữ kiểm ý T40."""
from copy import deepcopy
from legal_rag.assessment.claims import chat_claims
from legal_rag.assessment.groups import status_groups
from legal_rag.assessment.status import assess_status, valid_quote


def empty_status(items):
    return dict(rows=[dict(row_id=i["row"]["id"],
        status="khong_phat_hien" if i["row"].get("kind") == "cam" else "chua_ro",
        criteria=[dict(id=c["id"], text=c["text"], status="khong_phat_hien" if i["row"].get("kind") == "cam" else "chua_ro", quote="",
                       source="llm", evidence_source=None) for c in i["row"].get("criteria", [])])
        for i in items], errors=[], llm_calls=0, prompt_version="status_v1,status_check_v1")


def evidence_sources(status, group_text="", claims="", group=None):
    for row in status["rows"]:
        for criterion in row["criteria"]:
            if criterion["source"] == "nguoi_dung":
                source = "nguoi_dung"
            elif valid_quote(criterion.get("quote"), group_text):
                source = "nhom:" + group if group else "nguoi_dung"
            elif valid_quote(criterion.get("quote"), claims):
                source = "hoi_thoai"
            else:
                source = None
            criterion["evidence_source"] = source
    return status


def score_group(session, items, group, chat, model):
    answer = session["answers"].get(group)
    if not answer or answer["unknown"]:
        result = empty_status(items)
    else:
        claims = chat_claims(session["messages"])
        statement = answer["text"] + "\nLời khai trong hội thoại:\n" + claims
        allowed = {i["row"]["id"] for i in items}
        checks = {k: v for k, v in session["checks"].items() if k[0] in allowed}
        result = assess_status(items, statement, session["description"], chat, model, checks)
        evidence_sources(result, answer["text"], claims, group)
    session["group_status"][group] = result
    return result


def combined_status(session, items):
    rows = []
    for group, entries in status_groups(items).items():
        rows.extend(deepcopy(session["group_status"].get(group, empty_status(entries))["rows"]))
    banned = [i for i in items if i["row"].get("kind") == "cam"]
    rows.extend(deepcopy((session["banned_status"] or empty_status(banned))["rows"]))
    return dict(rows=rows, prompt_version="status_v1,status_check_v1")


def score_banned(session, items, chat, model):
    banned = [i for i in items if i["row"].get("kind") == "cam"]
    claims = chat_claims(session["messages"])
    texts = "\n".join(a["text"] for a in session["answers"].values() if not a["unknown"])
    result = assess_status(banned, texts + "\n" + claims,
                           claims, chat, model)
    banned_sources(session, result)
    session["banned_status"] = result
    return result


def retain_banned(session):
    """Không gọi LLM khi không biết; bỏ cảnh báo mất nguồn sau thay lời khai."""
    from legal_rag.assessment.status import _aggregate
    claims = chat_claims(session["messages"])
    sources = [claims] + [a["text"] for a in session["answers"].values() if not a["unknown"]]
    if session["banned_status"]:
        for row in session["banned_status"]["rows"]:
            for c in row["criteria"]:
                if c["quote"] and not valid_quote(c["quote"], *sources):
                    c.update(status="khong_phat_hien", quote="", evidence_source=None)
            row["status"] = _aggregate(row["criteria"], True)
        banned_sources(session, session["banned_status"])


def banned_sources(session, result):
    claims = chat_claims(session["messages"])
    evidence_sources(result, claims=claims)
    for row in result["rows"]:
        for c in row["criteria"]:
            for group, answer in session["answers"].items():
                if not answer["unknown"] and valid_quote(c["quote"], answer["text"]):
                    c["evidence_source"] = "nhom:" + group
                    break
