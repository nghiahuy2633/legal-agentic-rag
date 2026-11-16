"""Chọn tài nguyên theo nhu cầu; không suy nhu cầu từ hồ sơ hay từ khóa."""

REQUEST_KINDS = ("kien_thuc", "nghia_vu", "hien_trang", "huong_dan")
# Dạng câu cần câu trả lời trực tiếp, không thay bằng báo cáo nghĩa vụ (T55).
DIRECT_QUESTION_TYPES = ("xac_nhan", "su_kien", "dinh_nghia")


def normalize_request_kinds(value):
    if not isinstance(value, list):
        return [], ["missing_or_invalid_list"]
    kept, discarded = [], []
    for item in value:
        if isinstance(item, str) and item in REQUEST_KINDS:
            if item not in kept:
                kept.append(item)
        else:
            discarded.append(item)
    return kept, discarded


def request_plan(analysis, profile, context, config):
    version = config.analyze_prompt
    discarded = analysis.get("request_kinds_discarded", [])
    if version in ("analyze_v5", "analyze_v6", "analyze_v7"):
        kinds, extra = normalize_request_kinds(analysis.get("request_kinds"))
        discarded = [*discarded, *extra]
        reason = "explicit_needs" if kinds else "v5_lookup_fallback"
    elif version == "analyze_v4":
        kinds = ["nghia_vu" if analysis.get("question_type") == "nghia_vu" else "kien_thuc"]
        reason = "v4_compatibility"
    else:
        kinds, reason = ["kien_thuc"], "legacy_lookup"
    if not kinds:
        kinds = ["kien_thuc"]
    resolved = bool((context or {}).get("assessment"))
    if resolved and "huong_dan" not in kinds:
        kinds.append("huong_dan")
    blocked = analysis.get("scope") == "ngoai"
    requested = "nghia_vu" in kinds and not blocked
    if version in ("analyze_v5", "analyze_v6", "analyze_v7"):
        # Báo cáo nghĩa vụ chỉ khi câu hỏi đúng là hỏi nghĩa vụ chung; câu xác nhận,
        # sự kiện hoặc lẫn nhu cầu khác được trả lời trực tiếp bằng truy xuất (T55).
        obligations = (requested and set(kinds) <= {"nghia_vu", "huong_dan"}
                       and analysis.get("question_type") not in DIRECT_QUESTION_TYPES)
    else:
        obligations = requested
    table = obligations and config.enable_obligations
    high_risk = obligations and config.enable_high_risk and bool(profile.get("product_description"))
    skipped = "answer_first" if requested else "not_requested"
    return dict(request_kinds=kinds, use_table=table, use_high_risk=high_risk, obligation_report=obligations,
                context_mode="blocked" if blocked else "assessment" if resolved else "none",
                reason="out_of_scope" if blocked else reason,
                table_reason="enabled" if table else "disabled" if obligations else skipped,
                high_risk_reason="enabled" if high_risk else "disabled_or_no_product" if obligations else skipped,
                discarded=discarded,
                effective_question_type="nghia_vu" if obligations else
                analysis.get("question_type") if analysis.get("question_type") in
                ("su_kien", "dinh_nghia", "xac_nhan") else "khac")
