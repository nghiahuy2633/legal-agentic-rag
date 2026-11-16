"""Dữ kiện người dùng khai; None luôn có nghĩa chưa biết."""

from datetime import date
import re

from legal_rag.agent.profile import ROLES, SECTORS


FACT_FIELDS = {
    "roles": {"type": "list", "values": ROLES},
    "risk_level": {"type": "str", "values": ("cao", "trung_binh", "thap", "chua_phan_loai")},
    "sectors": {"type": "list", "values": SECTORS},
    **{name: {"type": "bool"} for name in (
        "is_public_sector", "is_foreign_provider", "interacts_with_humans",
        "generates_content", "simulates_real_person", "public_distribution",
        "uses_third_party_model", "modified_by_deployer", "uses_personal_data")},
    "content_types": {"type": "list", "values": ("van_ban", "am_thanh", "hinh_anh", "video")},
    "operation_start_date": {"type": "date"},
    "requires_conformity_certification": {"type": "bool"},
    "public_decision_use": {"type": "bool"},
    "content_may_mislead": {"type": "bool"},
}
FACT_LABELS = {
    'roles': 'vai trò',
    'risk_level': 'mức rủi ro',
    'sectors': 'lĩnh vực',
    'is_public_sector': 'là cơ quan nhà nước',
    'is_foreign_provider': 'là nhà cung cấp nước ngoài',
    'interacts_with_humans': 'tương tác trực tiếp với con người',
    'generates_content': 'tạo nội dung',
    'simulates_real_person': 'mô phỏng người thật hoặc sự kiện thật',
    'public_distribution': 'cung cấp ra công chúng',
    'uses_third_party_model': 'dùng mô hình bên thứ ba',
    'modified_by_deployer': 'bên triển khai sửa đổi hệ thống',
    'uses_personal_data': 'xử lý dữ liệu cá nhân',
    'content_types': 'loại nội dung',
    'operation_start_date': 'ngày đưa vào hoạt động',
    'requires_conformity_certification': 'thuộc diện bắt buộc chứng nhận sự phù hợp trước khi đưa vào sử dụng',
    'public_decision_use': 'kết quả dùng làm căn cứ quyết định trong quản lý nhà nước, dịch vụ công',
    "content_may_mislead": "nội dung có khả năng gây nhầm lẫn về tính xác thực của sự kiện, nhân vật",
}
EFFECTIVE_DATES = {"luat_134": "2026-03-01", "nd_142": "2026-05-01",
                   "qd_33": "2026-08-15", "tt_05": "2026-03-10"}


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def valid_scalar(spec, value):
    if spec["type"] == "bool":
        return type(value) is bool
    if spec["type"] == "date":
        return valid_date(value)
    return isinstance(value, str) and value in spec["values"]


def empty_facts():
    return dict.fromkeys(FACT_FIELDS)


def validate_facts(facts):
    clean, errors = empty_facts(), []
    for name, value in facts.items():
        if name not in FACT_FIELDS:
            errors.append(f"{name}: trường không được phép")
            continue
        if value is None:
            continue
        spec = FACT_FIELDS[name]
        valid = (isinstance(value, list) and all(valid_scalar(spec, v) for v in value)
                 if spec["type"] == "list" else valid_scalar(spec, value))
        if valid:
            clean[name] = list(dict.fromkeys(value)) if isinstance(value, list) else value
        else:
            errors.append(f"{name}: sai kiểu hoặc giá trị không được phép")
    return clean, errors
