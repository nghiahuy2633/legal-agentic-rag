"""Chấm hành vi bằng luật; nhãn chỉ được đọc tại bước chấm."""

import re
import unicodedata

from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.evaluation.input_checks import score_profile

REFUSALS = {"out_of_scope", "input_rejected"}
FIELD_PATTERNS = {
    "role": r"vai tro|ben nao|nha phat trien|nha cung cap|ben trien khai|mang ten ai",
    "sector": r"linh vuc|nganh nao",
    "product_description": r"mo ta|lam gi|san pham gi|he thong gi",
    "is_public_sector": r"khu vuc cong|co quan nha nuoc|dich vu cong",
    "generates_content": r"tao (?:ra )?noi dung|sinh noi dung",
}


def scenario_rows(scenarios):
    return [dict(turn, id=f"{scenario['id']}.t{turn['turn']}", scenario_id=scenario["id"],
                 question=turn["user"])
            for scenario in scenarios for turn in sorted(scenario["turns"], key=lambda t: t["turn"])]


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
                   if unicodedata.category(c) != "Mn")


def score_behavior(scenarios, questions, input_checks, results):
    turns = scenario_rows(scenarios)
    rows = [*questions, *[dict(row, expected_behavior="tra_loi" if row["should_retrieve"] else "tu_choi")
                            for row in input_checks], *turns]
    predictions = results if isinstance(results, dict) else {r["id"]: r for r in results}
    refused = false_refused = asked = fabricated = 0
    refusals_n = accepts_n = followup_n = numbers_n = 0
    error_ids, known_ids, known_fields = [], [], {}
    for row in rows:
        result = predictions.get(row["id"], {})
        failed = not result or bool(result.get("error"))
        if failed:
            error_ids.append(row["id"])
        expected_refusal = row.get("expected_behavior") == "tu_choi"
        rejection = result.get("route") in REFUSALS
        if expected_refusal:
            refusals_n += 1
            refused += not failed and rejection
        else:
            accepts_n += 1
            false_refused += not failed and rejection
        answer = result.get("answer", "") or ""
        questions_in_reply = re.findall(r"[^?!.\n]*\?", answer)
        if row.get("expected_behavior") in ("hoi_lai", "tra_loi_va_hoi_lai"):
            followup_n += 1
            asked += not failed and bool(questions_in_reply)
        # Hồ sơ chuẩn sau lượt là thông tin đã biết tại thời điểm trả lời.
        # Câu đơn không có nhãn hồ sơ dùng hồ sơ hệ thống lưu ở lượt đó.
        profile = row.get("expected_profile", result.get("profile") or {})
        fields = [field for field, pattern in FIELD_PATTERNS.items()
                  if profile.get(field) is not None
                  and any(re.search(pattern, _fold(q)) for q in questions_in_reply)]
        if fields and not failed:
            known_ids.append(row["id"])
            known_fields[row["id"]] = fields
        if row.get("category") == "thieu_can_cu":
            numbers_n += 1
            fabricated += not failed and any(
                any(token in error for token in ("Số tiền", "Ngày", "Tỷ lệ", "Thời hạn"))
                for error in (result.get("check") or {}).get("errors", []))
    profile_rows = [row for row in turns if "expected_profile" in row]
    # score_profile cũ bỏ lỗi khỏi mẫu số; giữ thống kê trường, đưa lỗi trở lại mẫu số ở đây.
    profile_results = []
    for row in profile_rows:
        result = predictions.get(row["id"], {})
        if result.get("error") or not isinstance(result.get("profile"), dict):
            profile_results.append(dict(id=row["id"], error="Thiếu hồ sơ hoặc lượt lỗi"))
        else:
            profile_results.append(dict(id=row["id"], profile=result["profile"]))
    profile_score = score_profile(profile_rows, profile_results)
    profile_score["n"] = len(profile_rows)
    for counts in profile_score["fields"].values():
        counts["accuracy"] = counts["correct"] / len(profile_rows) if profile_rows else None
    field_count = len(profile_rows) * len(EMPTY_PROFILE)
    profile_score["accuracy"] = (sum(c["correct"] for c in profile_score["fields"].values()) / field_count
                                 if field_count else None)
    return dict(n=len(rows), errors=len(error_ids), error_ids=error_ids,
                correct_refusal=dict(n=refusals_n, correct=refused,
                                     rate=refused / refusals_n if refusals_n else None),
                false_refusal=dict(n=accepts_n, count=false_refused,
                                   rate=false_refused / accepts_n if accepts_n else None),
                followup=dict(n=followup_n, correct=asked, rate=asked / followup_n if followup_n else None),
                asked_known_fields=dict(count=len(known_ids), ids=known_ids, fields=known_fields),
                profile=profile_score,
                fabricated_numbers=dict(n=numbers_n, count=fabricated,
                                        rate=fabricated / numbers_n if numbers_n else None))
