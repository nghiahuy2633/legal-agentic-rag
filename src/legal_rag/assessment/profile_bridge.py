"""Ánh xạ dữ kiện đánh giá sang hồ sơ hỏi đáp."""
ROLE_PRIORITY = ("nha_cung_cap", "ben_trien_khai", "nha_phat_trien", "nguoi_su_dung")


def facts_from_profile(profile):
    """Chỉ chép dữ kiện có trường tương ứng; không suy từ mô tả."""
    from legal_rag.knowledge.facts import validate_facts
    values = {name: profile.get(name) for name in
              ("risk_level", "is_public_sector", "generates_content")}
    values.update(roles=[profile["role"]] if profile.get("role") is not None else None,
                  sectors=[profile["sector"]] if profile.get("sector") is not None else None)
    return validate_facts(values)[0]


def profile_override(facts, description=""):
    roles = facts.get("roles") or []
    return dict(role=next((r for r in ROLE_PRIORITY if r in roles), None),
                sector=next(iter(facts.get("sectors") or []), None),
                **{k: facts.get(k) for k in ("is_public_sector", "generates_content", "risk_level")},
                product_description=description + "\nVai trò: " + ", ".join(roles))
