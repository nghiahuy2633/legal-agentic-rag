"""Đối chiếu từng điều kiện Danh mục; kết luận và câu chữ do code tạo."""

import json
from pathlib import Path
import re
import unicodedata

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts/high_risk_v1.txt"
PROMPT_V2_PATH = PROMPT_PATH.with_name("high_risk_v2.txt")
BULLET = re.compile(r"(?<!\S)-(?=\s)|^-")
STATUSES = ("dap_ung", "khong_dap_ung", "chua_ro")
FIXED_PARENTS = ("33-2026-QD-TTg_dieu-2", "142-2026-ND-CP_dieu-8_khoan-1",
                 "142-2026-ND-CP_dieu-8_khoan-2")
CONNECTOR_NOTE = ("Các điều kiện trong một mục Danh mục được hiểu là phải đáp ứng đồng thời, vì mỗi mục mở đầu bằng "
                  "\"Chỉ áp dụng…\" hoặc \"khi đáp ứng các điều kiện sau\" và không ghi \"một trong các\". "
                  "Một điều kiện chỉ được ghi là không đáp ứng khi mô tả nêu rõ dữ kiện trái với điều kiện đó.")
PREFIX = "33-2026-QD-TTg_linh-vuc-"


STATUS_LABELS = {"dap_ung": "đáp ứng", "khong_dap_ung": "không đáp ứng", "chua_ro": "chưa rõ"}


def split_conditions(item):
    description = item["description"]
    parts = BULLET.split(description)
    if len(parts) == 1:
        return dict(lead="", conditions=[description.strip()])
    return dict(lead=parts[0].strip(), conditions=[p.strip() for p in parts[1:]])


def _index(rows, key):
    return rows if isinstance(rows, dict) else {row[key]: row for row in rows}


def candidate_items(hits, items, limit=5):
    registry = _index(items, "item_id")
    selected, seen = [], set()
    for hit in hits:
        key = hit.get("chunk_id")
        if len(selected) >= limit:
            break
        if key in registry and key not in seen:
            selected.append(registry[key])
            seen.add(key)
    return selected


def _normalize(candidates, response):
    """Giữ đủ điều kiện nguồn, không tin text hoặc ID ngoài ứng viên."""
    rows = response.get("items", []) if isinstance(response, dict) else []
    rows = rows if isinstance(rows, list) else []
    result = []
    for candidate in candidates:
        matches = [r for r in rows if isinstance(r, dict) and r.get("item_id") == candidate["item_id"]]
        conditions = matches[0].get("conditions", []) if len(matches) == 1 else []
        conditions = conditions if isinstance(conditions, list) else []
        checked = []
        for index, text in enumerate(split_conditions(candidate)["conditions"], 1):
            matches = [c for c in conditions if isinstance(c, dict)
                       and type(c.get("index")) is int and c["index"] == index]
            condition = matches[0] if len(matches) == 1 else {}
            status = condition.get("status")
            status = status if status in STATUSES else "chua_ro"
            basis = condition.get("basis")
            basis = basis if isinstance(basis, str) else None
            # Thiếu căn cứ không được coi là đã xác định đáp ứng/trái điều kiện.
            if not basis or not basis.strip():
                status, basis = "chua_ro", None
            if status == "chua_ro":
                basis = None
            checked.append(dict(index=index, text=text, status=status, basis=basis))
        result.append(dict(item_id=candidate["item_id"], conditions=checked))
    return result


def _quote_text(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def _valid_basis(description, basis):
    return (isinstance(basis, str) and bool(_quote_text(basis))
            and _quote_text(basis) in _quote_text(description))


def _relevance(description, candidates, response, ok):
    rows = response.get("items", []) if ok else []
    decisions = []
    for candidate in candidates:
        key = candidate["item_id"]
        matches = [r for r in rows if isinstance(r, dict) and r.get("item_id") == key]
        match = matches[0].get("object_match") if len(matches) == 1 else None
        status, basis, missing = "chua_ro", None, []
        if not ok:
            reason = "invalid_response"
        elif not matches:
            reason = "missing_item"
        elif len(matches) != 1:
            reason = "duplicate_item"
        elif not isinstance(match, dict):
            reason = "invalid_object_match"
        else:
            info = match.get("missing_info")
            if isinstance(info, list):
                missing = [s.strip()[:200] for s in info if isinstance(s, str) and s.strip()][:3]
            value = match.get("status")
            if value not in ("phu_hop", "khong_phu_hop", "chua_ro"):
                reason = "invalid_status"
            elif value == "chua_ro":
                reason = "unresolved"
            elif not _valid_basis(description, match.get("basis")):
                reason = "invalid_basis"
            else:
                status, basis = value, match["basis"].strip()
                reason = "matched" if value == "phu_hop" else "not_matched"
        decisions.append(dict(item_id=key, status=status, basis=basis,
                              missing_info=missing, reason=reason))
    return decisions


def assess_items(description, candidates, chat, model, *, version="high_risk_v1"):
    if version not in ("high_risk_v1", "high_risk_v2"):
        raise ValueError("Sai phiên bản prompt đối chiếu Danh mục")
    candidates = list(candidates)
    if not candidates:
        return (dict(items=[], assess_ok=True) if version == "high_risk_v1" else
                dict(items=[], assess_ok=True, version=version, relevance=[]))
    path = PROMPT_PATH if version == "high_risk_v1" else PROMPT_V2_PATH
    prompt = path.read_text(encoding="utf-8")
    if not prompt.splitlines() or prompt.splitlines()[0] != f"Phiên bản: {version}":
        raise ValueError(f"Sai phiên bản prompt: cần {version}")
    data = dict(description=description, items=[dict(item_id=c["item_id"], name=c["name"],
        lead=split_conditions(c)["lead"], conditions=[dict(index=i, text=text)
        for i, text in enumerate(split_conditions(c)["conditions"], 1)]) for c in candidates])
    answer = chat.complete(dict(model=model, temperature=0, response_format={"type": "json_object"},
        messages=[dict(role="system", content=prompt),
                  dict(role="user", content=json.dumps(data, ensure_ascii=False))]))
    try:
        response = json.loads(answer)
    except (TypeError, ValueError):
        response = None
    ok = isinstance(response, dict) and isinstance(response.get("items"), list)
    if version == "high_risk_v2":
        decisions = _relevance(description, candidates, response, ok)
        eligible = {row["item_id"] for row in decisions if row["status"] == "phu_hop"}
        return dict(items=_normalize([c for c in candidates if c["item_id"] in eligible], response),
                    assess_ok=ok, version=version, relevance=decisions)
    return dict(items=_normalize(candidates, response), assess_ok=ok)


def item_status(item):
    # Các gạch đầu dòng của một mục phải đáp ứng đồng thời: một điều kiện không đáp ứng là đủ loại mục.
    statuses = [c.get("status") for c in item.get("conditions", [])]
    if "khong_dap_ung" in statuses:
        return "khong_khop"
    if statuses and all(s == "dap_ung" for s in statuses):
        return "khop"
    return "co_the_khop"


def excluded_note(item):
    failed = [str(c["index"]) for c in item.get("conditions", []) if c.get("status") == "khong_dap_ung"]
    if not failed:
        return ""
    return "Mục này không khớp vì điều kiện " + ", ".join(failed) + " không đáp ứng theo mô tả sản phẩm."


def overall_status(items):
    statuses = [item_status(item) for item in items]
    if "khop" in statuses:
        return "khop"
    return "co_the_khop" if "co_the_khop" in statuses else "khong_thay"


def fixed_label(key, parent):
    """Tên ngắn của căn cứ cố định: số văn bản, Điều, khoản."""
    lines = parent["context"].splitlines()
    number = re.search(r"\(số ([^)]+)\)", lines[0])
    clause = re.search(r"_khoan-(\d+)$", key)
    return " ".join(filter(None, (number[1] if number else "", lines[-1].strip()))) + (
        f", khoản {clause[1]}" if clause else "")


def render_assessment(description, result, items, parents):
    registry, parents = _index(items, "item_id"), _index(parents, "parent_id")
    v2 = result.get("version") == "high_risk_v2"
    decisions = result.get("relevance", []) if v2 else []
    eligible = set()
    for key in registry if v2 else ():
        matches = [r for r in decisions if isinstance(r, dict) and r.get("item_id") == key]
        if (len(matches) == 1 and matches[0].get("status") == "phu_hop"
                and _valid_basis(description, matches[0].get("basis"))):
            eligible.add(key)
    # Khôi phục text từ corpus ngay cả khi caller truyền kết quả giả có text khác.
    candidates = [registry[r["item_id"]] for r in result["items"] if r.get("item_id") in registry
                  and (not v2 or r["item_id"] in eligible)]
    assessed = _normalize(candidates, result)
    status = overall_status(assessed)
    labels = dict(khop="đã đối chiếu điều kiện", co_the_khop="còn điều kiện chưa rõ",
                  khong_thay="chưa có điều kiện khớp")
    lines, ids = [], []
    reason = None
    if v2 and not assessed:
        status = "chua_du_co_so"
        labels[status] = "Chưa đủ cơ sở đề xuất mục Danh mục"
        if not decisions:
            reason = "no_candidates"
            lines.append("Chưa tìm được ứng viên để xác định mục Danh mục phù hợp với mô tả sản phẩm.")
        elif not result.get("assess_ok"):
            reason = "invalid_response"
            lines.append("Chưa đủ cơ sở đề xuất mục Danh mục vì phản hồi đối chiếu chưa đọc được đúng cấu trúc.")
        elif any(r.get("status") == "chua_ro" for r in decisions):
            reason = "unresolved"
            lines.append("Chưa đủ thông tin để chọn mục Danh mục phù hợp. Cần mô tả rõ chức năng chính, đầu ra và cách sử dụng của sản phẩm để đối chiếu tiếp.")
        else:
            reason = "not_relevant"
            lines.append("Các ứng viên đã đối chiếu chưa có mục được xác nhận phù hợp với chức năng sản phẩm đã mô tả.")
        lines.append("Kết quả này không phải kết luận sản phẩm không thuộc Danh mục.")
    for row in assessed[:3]:
        item = registry[row["item_id"]]
        ids.append(item["item_id"])
        lines.append(f'### {item["sector"]}, STT {item["stt"]}\n\n{item["name"]}')
        split = split_conditions(item)
        if split["lead"]:
            lines.append(split["lead"])
        lines.extend(f'{c["index"]}. {c["text"]}\n\n   Trạng thái: {STATUS_LABELS[c["status"]]}.' for c in row["conditions"])
        if excluded_note(row):
            lines.append(excluded_note(row))
        lines.append(parents[item["item_id"]]["context"].splitlines()[-1])
    # T57: không chèn nhận định pháp lý không gắn mã nguồn (tự phân loại, cách đọc đồng thời).
    # Cách đọc đồng thời vẫn áp dụng trong item_status; CONNECTOR_NOTE giữ làm tài liệu, không hiển thị.
    lines.append("Danh sách trên chỉ để tham khảo.")
    # Chỉ nêu tên căn cứ; nguyên văn và đường dẫn nằm ở Căn cứ pháp lý (T57).
    lines.append("Căn cứ cần xem xét; chưa đánh giá các tiêu chí tại:\n"
                 + "\n".join("- " + fixed_label(key, parents[key]) for key in FIXED_PARENTS))
    ids.extend(FIXED_PARENTS)
    rendered = dict(status=status, label=labels[status], text="\n\n".join(lines), parent_ids=ids)
    if v2:
        rendered.update(version="high_risk_v2", selection_reason=reason)
    return rendered
