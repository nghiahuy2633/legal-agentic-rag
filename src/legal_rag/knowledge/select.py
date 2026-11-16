"""Chọn nghĩa vụ đã được người soát, không suy mức rủi ro hoặc vai trò."""


def select_obligations(rows, profile, risk_level=None, accept=("user_reviewed",)) -> dict:
    selected, unreviewed, rejected = [], 0, 0
    for row in rows:
        if row["review_status"] == "user_rejected":
            rejected += 1
            continue
        if row["review_status"] not in accept:
            unreviewed += 1
            continue
        role = row["role"]
        if profile.get("role") is None and role != "moi_vai_tro":
            continue
        if role == "co_quan_nha_nuoc":
            if profile.get("is_public_sector") is not True:
                continue
        elif role not in ("moi_vai_tro", profile.get("role")):
            continue
        if row["risk_level"] not in ("moi_muc", risk_level):
            continue
        selected.append(row)
    return dict(selected=selected, unreviewed_count=unreviewed, rejected_count=rejected)
