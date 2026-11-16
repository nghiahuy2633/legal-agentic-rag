"""Lọc nghĩa vụ bằng dữ kiện và logic ba trị, không suy đoán dữ kiện."""

from legal_rag.knowledge.conditions import describe, evaluate, missing_facts


ROLE_LABELS = {"nha_phat_trien": "nhà phát triển", "nha_cung_cap": "nhà cung cấp",
               "ben_trien_khai": "bên triển khai"}
RISK_LABELS = {"cao": "cao", "trung_binh": "trung bình", "thap": "thấp"}


def applicable_obligations(rows, facts, accept=("user_reviewed", "ai_reviewed")):
    result = {"items": [], "skipped": dict.fromkeys(
        ("not_accepted", "rejected", "role", "risk", "condition"), 0)}
    for row in rows:
        reasons, missing = [], []
        if row["review_status"] == "user_rejected":
            result["skipped"]["rejected"] += 1
            continue
        if row["review_status"] not in accept:
            result["skipped"]["not_accepted"] += 1
            continue
        role, roles = row["role"], facts.get("roles")
        if role == "co_quan_nha_nuoc":
            role_ok = facts.get("is_public_sector")
            if role_ok is None:
                reasons.append("Nếu là cơ quan nhà nước.")
                missing.append("is_public_sector")
        elif role == "moi_vai_tro" or (roles is not None and role in roles):
            role_ok = True
        elif roles is None and role in ROLE_LABELS:
            role_ok = None
            reasons.append(f"Nếu bạn là {ROLE_LABELS[role]}.")
            missing.append("roles")
        else:
            role_ok = False
        if role_ok is False:
            result["skipped"]["role"] += 1
            continue
        risk, actual = row["risk_level"], facts.get("risk_level")
        if actual in RISK_LABELS and risk not in ("moi_muc", actual):
            result["skipped"]["risk"] += 1
            continue
        if actual in (None, "chua_phan_loai") and risk != "moi_muc":
            reasons.append(f"Nếu hệ thống được phân loại rủi ro {RISK_LABELS[risk]}.")
            missing.append("risk_level")
        expr = row.get("applies_when")
        condition = evaluate(expr, facts)
        if condition is False:
            result["skipped"]["condition"] += 1
            continue
        if condition is None:
            reasons.append(f"Nếu {describe(expr)}.")
            missing.extend(missing_facts(expr, facts))
        result["items"].append({"row": row,
            "applicability": "ap_dung_neu" if reasons else "ap_dung",
            "conditions": reasons, "missing_facts": list(dict.fromkeys(missing))})
    return result
