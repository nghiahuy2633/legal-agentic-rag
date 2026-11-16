"""Gộp hồ sơ theo các trường và giá trị được phép."""

EMPTY_PROFILE = {"role": None, "sector": None, "is_public_sector": None,
                 "generates_content": None, "product_description": None, "risk_level": None}
RISK_LEVELS = frozenset(("cao", "trung_binh", "thap", "chua_phan_loai"))
ROLES = frozenset(("nha_phat_trien", "nha_cung_cap", "ben_trien_khai", "nguoi_su_dung"))
SECTORS = frozenset(("giao_duc", "y_te", "tai_chinh_ngan_hang", "dan_toc_ton_giao",
                     "to_tung", "giao_thong_van_tai", "thuong_mai", "quang_cao",
                     "an_sinh_xa_hoi", "lam_dep", "lao_dong", "khac"))


def merge_profile(old, update):
    profile = {key: old.get(key) for key in EMPTY_PROFILE}
    ignored = []
    for key, value in update.items():
        if key not in EMPTY_PROFILE:
            ignored.append(key)
            continue
        if value is None:
            continue
        if key in ("role", "sector"):
            valid = isinstance(value, str) and value in (ROLES if key == "role" else SECTORS)
        elif key == "risk_level":
            valid = isinstance(value, str) and value in RISK_LEVELS
        elif key in ("is_public_sector", "generates_content"):
            valid = type(value) is bool
        else:
            valid = isinstance(value, str) and bool(value.strip())
            if valid:
                value = value.strip()[:300]
        if valid:
            profile[key] = value
        else:
            ignored.append(key)
    return profile, ignored


def missing_fields(profile):
    return [key for key in EMPTY_PROFILE if profile.get(key) is None]
