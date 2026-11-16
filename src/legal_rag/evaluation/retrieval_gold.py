"""Chuyển nguồn dự kiến thành ID thật; chỉ dùng lúc tạo nhãn đánh giá."""

from legal_rag.retrieval.exact import document_candidates, parse_location

ROLES = {"nha_cung_cap": "nhà cung cấp", "ben_trien_khai": "bên triển khai",
         "nha_phat_trien": "nhà phát triển"}
SECTORS = {"giao_duc": "giáo dục", "thuong_mai": "thương mại", "quang_cao": "quảng cáo",
           "tai_chinh_ngan_hang": "tài chính ngân hàng", "an_sinh_xa_hoi": "an sinh xã hội",
           "lao_dong": "lao động", "y_te": "y tế", "lam_dep": "làm đẹp"}


def profile_text(profile: dict) -> str:
    """Chỉ lấy giá trị, không thêm nhãn trường để tránh token nhiễu như "hồ sơ"."""
    parts = [ROLES.get(profile.get("role")), SECTORS.get(profile.get("sector")),
             "khu vực công" if profile.get("is_public_sector") else None,
             "tạo nội dung" if profile.get("generates_content") else None,
             profile.get("product_description")]
    return "; ".join(p for p in parts if p)


def resolve_sources(sources: list[str], parent_ids: set[str], chunks: list[dict]) -> dict:
    result = {"gold_parents": [], "gold_articles": [], "gold_points": [], "errors": []}
    for source in sources:
        docs, _ = document_candidates(source, chunks)
        locations = parse_location(source)
        if len(docs) != 1 or not locations:
            result["errors"].append(f"Không giải được nguồn: {source}")
            continue
        for loc in locations:
            article = f"{next(iter(docs))}_dieu-{loc['article']}"
            parent = article + (f"_khoan-{loc['clause']}" if loc["clause"] else "")
            point_exists = not loc["point"] or any(
                c["document_id"] in docs and c.get("article") == loc["article"]
                and c.get("clause") == loc["clause"]
                and (c.get("point") or "").lower() == loc["point"] for c in chunks)
            if parent not in parent_ids or not point_exists:
                result["errors"].append(f"Vị trí không tồn tại: {source} ({parent})")
                continue
            result["gold_articles"].append(article)
            if loc["clause"]:
                result["gold_parents"].append(parent)
            if loc["point"]:
                result["gold_points"].append(f"{parent}_diem-{loc['point']}")
    return result


def check_ids(override: dict, parent_ids: set[str]) -> None:
    for field in ("gold_parents", "secondary_parents"):
        for parent in override.get(field, []):
            if parent not in parent_ids:
                raise ValueError(f"Override không có parent: {parent}")
    for field in ("gold_articles", "secondary_articles"):
        for article in override.get(field, []):
            if article not in parent_ids or "_dieu-" not in article or "_khoan-" in article:
                raise ValueError(f"Override không có Điều: {article}")


def apply_labels(result: dict, override: dict) -> None:
    """Bỏ nhãn trước, thêm sau; nhãn phụ không vào mẫu số Recall."""
    for field in ("gold_parents", "gold_articles"):
        removed = override.get(field.replace("gold_", "remove_"), [])
        missing = sorted(set(removed) - set(result[field]))
        if missing:
            raise ValueError(f"Override bỏ nhãn không có của {result['id']}: {missing}")
        result[field] = [x for x in result[field] if x not in removed] + override.get(field, [])
    result["gold_secondary"] = [*override.get("secondary_parents", []), *override.get("secondary_articles", [])]
    if override.get("gold_blocks"):
        result["gold_blocks"] = override["gold_blocks"]


def finish(result: dict, errors: list[str]) -> dict:
    for field in ("gold_parents", "gold_articles", "gold_points", "gold_secondary"):
        result[field] = sorted(set(result[field]))
    if errors or not (result["gold_parents"] or result["gold_articles"]):
        result["gold_status"] = "unresolved"
        result["unresolved_sources"] = sorted(set(errors))
        result["notes"] = "; ".join(filter(None, [result["notes"], *errors,
            "Không có nhãn" if not (result["gold_parents"] or result["gold_articles"]) else ""]))
    return result


def build_row(row_id: str, question: str, row: dict, sources: list[str], parent_ids: set[str],
              chunks: list[dict]) -> tuple[dict, list[str]]:
    resolved = resolve_sources(sources, parent_ids, chunks)
    return ({"id": row_id, "question": question, "category": row["category"], "priority": row["priority"],
             "gold_parents": resolved["gold_parents"], "gold_articles": resolved["gold_articles"],
             "gold_points": resolved["gold_points"], "gold_secondary": [], "gold_status": "auto",
             "notes": "", "unresolved_sources": []}, resolved["errors"])


def build_gold(rows: list[dict], parents: list[dict], chunks: list[dict],
               overrides: list[dict] = ()) -> list[dict]:
    parent_ids = {p["parent_id"] for p in parents}
    overrides_by_id = {o["id"]: o for o in overrides}
    if len(overrides_by_id) != len(overrides):
        raise ValueError("Override trùng id")
    output = []
    for row in rows:
        # Chỉ câu phải từ chối mới không có nhãn; in_corpus không quyết định việc này.
        if row.get("expected_behavior") == "tu_choi":
            if row["id"] in overrides_by_id:
                raise ValueError(f"Override cho câu từ chối: {row['id']}")
            continue
        override = overrides_by_id.pop(row["id"], None)
        if override:
            if override["gold_status"] not in {"manual_ai", "ai_reviewed"} or not override.get("notes"):
                raise ValueError("Override phải ghi manual_ai hoặc ai_reviewed và căn cứ trong notes")
            check_ids(override, parent_ids)
        if "turns" in row:
            output += build_turns(row, override, parent_ids, chunks)
            continue
        result, errors = build_row(row["id"], row["question"], row, row["expected_sources"], parent_ids, chunks)
        if override:
            apply_labels(result, override)
            result["gold_status"] = override["gold_status"]
            result["notes"] = override["notes"]
        output.append(finish(result, errors))
    if overrides_by_id:
        raise ValueError(f"Override không có câu hợp lệ: {sorted(overrides_by_id)}")
    return output


def build_turns(row: dict, override: dict | None, parent_ids: set[str], chunks: list[dict]) -> list[dict]:
    """Mỗi lượt là một truy vấn: câu hiện tại cộng hồ sơ chuẩn của lượt đó."""
    output = []
    turn_overrides = (override or {}).get("turns", {})
    known = {str(t["turn"]) for t in row["turns"]}
    if set(turn_overrides) - known:
        raise ValueError(f"Override lượt không tồn tại: {row['id']} {sorted(set(turn_overrides) - known)}")
    for turn in row["turns"]:
        if turn["expected_behavior"] == "tu_choi":
            continue
        profile = profile_text(turn["expected_profile"])
        question = turn["user"] + (f"\n{profile}" if profile else "")
        result, errors = build_row(f"{row['id']}.t{turn['turn']}", question, row, turn["expected_sources"],
                                   parent_ids, chunks)
        result |= {"scenario_id": row["id"], "turn": turn["turn"], "turn_text": turn["user"]}
        extra = turn_overrides.get(str(turn["turn"]))
        if extra:
            check_ids(extra, parent_ids)
            apply_labels(result, extra)
        if override:
            # Nhãn cấp kịch bản đã rà soát, chưa rà soát cách chia nhãn theo lượt.
            result["gold_status"] = "ai_reviewed_scenario" if override["gold_status"] == "ai_reviewed" else override["gold_status"]
            result["notes"] = override["notes"]
        output.append(finish(result, errors))
    return output
