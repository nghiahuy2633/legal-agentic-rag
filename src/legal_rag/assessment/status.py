"""Chấm từng tiêu chí, kiểm trích dẫn rồi gộp bằng code."""

import json
from pathlib import Path
import unicodedata

from legal_rag.llm import LLMError

PROMPTS = Path(__file__).resolve().parents[3] / "prompts"


def normalize(text):
    text = " ".join(unicodedata.normalize("NFC", text).lower().split())
    while text and unicodedata.category(text[0]).startswith("P"):
        text = text[1:].lstrip()
    while text and unicodedata.category(text[-1]).startswith("P"):
        text = text[:-1].rstrip()
    return text


def valid_quote(quote, *sources):
    return (isinstance(quote, str) and bool(normalize(quote))
            and any(normalize(quote) in normalize(source) for source in sources))


def payload(prompt, content, model, json_mode=False):
    result = {"model": model, "temperature": 0, "messages": [
        {"role": "system", "content": prompt}, {"role": "user", "content": content}]}
    if json_mode:
        result["response_format"] = {"type": "json_object"}
    return result


def validate_checks(items, checks):
    allowed = {(item["row"]["id"], c["id"])
               for item in items if item["row"].get("kind", "nghia_vu") == "nghia_vu"
               for c in item["row"].get("criteria", [])}
    for key, value in (checks or {}).items():
        if key not in allowed or value not in ("da", "chua"):
            raise ValueError("Tự kiểm phải trỏ tới tiêu chí nghĩa vụ và có nhãn da/chua")


def assess_status(items, statement, description, chat, model, checks=None, batch_size=6, verify_da=True):
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size phải là số nguyên dương")
    validate_checks(items, checks)
    checks = checks or {}
    selected = [i["row"] for i in items if i["row"].get("kind", "nghia_vu") in ("nghia_vu", "cam")]
    result = {"rows": [], "downgraded": 0, "errors": [], "llm_calls": 0,
              "rejected_by_check": 0, "checks_log": [],
              "prompt_version": "status_v1,status_check_v1" if verify_da else "status_v1"}
    prompt = (PROMPTS / "status_v1.txt").read_text(encoding="utf-8")
    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        criteria_input = [{"id": r["id"], "kind": r.get("kind", "nghia_vu"),
            "obligation": r["obligation"], "criteria": [
                {"id": c["id"], "text": c["text"],
                 "Các trường hợp KHÔNG đạt": c.get("not_met", [])}
                for c in r.get("criteria", [])]} for r in batch]
        content = (f"SẢN PHẨM: {description}\nLỜI KHAI (giữa hai dấu ###):\n###\n"
                   f"{statement}\n###\nNGHĨA VỤ VÀ TIÊU CHÍ:\n"
                   + json.dumps(criteria_input, ensure_ascii=False))
        request = payload(prompt, content, model, True)
        entries = []
        for attempt in range(2):
            result["llm_calls"] += 1
            try:
                parsed = json.loads(chat.complete(request))
                if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
                    raise ValueError("thiếu danh sách results")
                entries = parsed["results"]
                break
            except LLMError:
                result["errors"].append({"row_ids": [r["id"] for r in batch], "error": "LLMError"})
                break
            except (ValueError, TypeError):
                result["errors"].append({"row_ids": [r["id"] for r in batch], "error": "JSON không hợp lệ", "attempt": attempt + 1})
                # Payload khác để không đọc lại JSON hỏng đã cache.
                request = payload(prompt, content + "\nThử lại: chỉ trả đối tượng JSON có danh sách results.", model, True)
        indexed = {}
        duplicates = set()
        for entry in entries:
            if not isinstance(entry, dict):
                result["errors"].append({"error": "Kết quả tiêu chí không phải đối tượng"})
                continue
            key = (entry.get("obligation"), entry.get("criterion"))
            if not all(isinstance(v, str) for v in key):
                result["errors"].append({"error": "Mã tiêu chí không hợp lệ"})
                continue
            if key in indexed:
                duplicates.add(key)
            indexed[key] = entry
        for row in batch:
            banned = row.get("kind") == "cam"
            default = "khong_phat_hien" if banned else "chua_ro"
            labels = ("co_dau_hieu", "khong_phat_hien") if banned else ("da", "chua", "chua_ro")
            criteria = []
            if not row.get("criteria"):
                result["errors"].append({"row_id": row["id"], "error": "Thiếu tiêu chí"})
            for criterion in row.get("criteria", []):
                key = (row["id"], criterion["id"])
                entry = indexed.get(key, {})
                status, quote, source = entry.get("status"), entry.get("quote", ""), "llm"
                if key in checks:
                    status, quote, source = checks[key], "", "nguoi_dung"
                elif status not in labels or key in duplicates:
                    status, quote = default, ""
                    result["errors"].append({"row_id": key[0], "criterion_id": key[1], "error": "Thiếu, trùng hoặc sai nhãn tiêu chí"})
                elif status in ("da", "chua", "co_dau_hieu"):
                    sources = (statement, description) if banned else (statement,)
                    if not valid_quote(quote, *sources):
                        status, quote = default, ""
                        result["downgraded"] += 1
                else:
                    quote = ""
                criteria.append({"id": criterion["id"], "text": criterion["text"],
                                 "status": status, "quote": quote, "source": source})
            status = _aggregate(criteria, banned)
            result["rows"].append({"row_id": row["id"], "status": status, "criteria": criteria})
    if verify_da:
        _verify_status(result, selected, chat, model)
    return result


def _aggregate(criteria, banned):
    statuses = [c["status"] for c in criteria]
    if banned:
        return "co_dau_hieu" if "co_dau_hieu" in statuses else "khong_phat_hien"
    return ("chua" if "chua" in statuses else
            "da" if statuses and all(s == "da" for s in statuses) else "chua_ro")


def _verify_status(result, selected, chat, model):
    definitions = {row["id"]: row for row in selected}
    pending = []
    for row in result["rows"]:
        definition = definitions[row["row_id"]]
        banned = definition.get("kind") == "cam"
        originals = {c["id"]: c for c in definition.get("criteria", [])}
        for criterion in row["criteria"]:
            if criterion["source"] != "llm" or criterion["status"] != ("co_dau_hieu" if banned else "da"):
                continue
            entry = {"id": f"{row['row_id']}/{criterion['id']}",
                     "text": criterion["text"], "not_met": originals[criterion["id"]].get("not_met", []),
                     "quote": criterion["quote"], "kind": "cam" if banned else "nghia_vu"}
            pending.append((entry, criterion, banned))
    if not pending:
        return
    prompt = (PROMPTS / "status_check_v1.txt").read_text(encoding="utf-8")
    for start in range(0, len(pending), 40):
        batch = pending[start:start + 40]
        indexed, duplicates = {}, set()
        failure = "Thiếu hoặc sai kết quả kiểm ý"
        # JSON hỏng thì thử lại một lần; lỗi gọi LLM thì không thử lại ở đây.
        for attempt in range(2):
            result["llm_calls"] += 1
            try:
                parsed = json.loads(chat.complete(payload(prompt, json.dumps(
                    [entry for entry, _, _ in batch], ensure_ascii=False), model, True)))
                if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
                    raise ValueError("thiếu results")
                for entry in parsed["results"]:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        continue
                    if entry["id"] in indexed:
                        duplicates.add(entry["id"])
                    indexed[entry["id"]] = entry
                break
            except (LLMError, ValueError, TypeError) as error:
                failure = "LLMError" if isinstance(error, LLMError) else "JSON không hợp lệ"
                result["errors"].append({"error": failure, "stage": "status_check_v1", "attempt": attempt + 1})
                if isinstance(error, LLMError):
                    break
        for entry, criterion, banned in batch:
            checked = indexed.get(entry["id"], {})
            positive, negative = ("co_dau_hieu", "khong") if banned else ("ho_tro", "khong_ho_tro")
            verdict, reason = checked.get("verdict"), checked.get("reason")
            if (entry["id"] in duplicates or verdict not in (positive, negative)
                    or not isinstance(reason, str) or not reason.strip()):
                if banned:
                    # Không kiểm được thì giữ cảnh báo: lỗi kỹ thuật không được làm mất dấu hiệu hành vi bị cấm.
                    result["checks_log"].append({"id": entry["id"], "verdict": "giu_canh_bao", "reason": failure})
                    continue
                verdict, reason = negative, failure
            result["checks_log"].append({"id": entry["id"], "verdict": verdict, "reason": reason})
            if verdict != positive:
                criterion.update(status="khong_phat_hien" if banned else "chua_ro", quote="")
                result["rejected_by_check"] += 1
    for row in result["rows"]:
        row["status"] = _aggregate(row["criteria"], definitions[row["row_id"]].get("kind") == "cam")
