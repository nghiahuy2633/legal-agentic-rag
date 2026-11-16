"""Chọn câu hỏi theo số nghĩa vụ còn phụ thuộc dữ kiện thiếu."""

from legal_rag.assessment.applicable import applicable_obligations
from legal_rag.knowledge.facts import FACT_FIELDS, FACT_LABELS


FACT_QUESTIONS = {
    name: {"question": f"Hệ thống có {FACT_LABELS[name]} không?" if spec["type"] == "bool"
           else f"Bạn cho biết {FACT_LABELS[name]} của hệ thống?",
           "options": [True, False] if spec["type"] == "bool" else
           sorted(spec["values"]) if "values" in spec else []}
    for name, spec in FACT_FIELDS.items()
}
FACT_QUESTIONS["roles"]["question"] = (
    "Doanh nghiệp của bạn đóng vai trò nào với hệ thống: tự phát triển, cung cấp dưới tên mình, "
    "hay sử dụng hệ thống của bên khác trong hoạt động kinh doanh?")
FACT_QUESTIONS["risk_level"]["question"] = (
    "Hệ thống đã được phân loại rủi ro chưa, và ở mức nào (cao, trung bình, thấp)?")
FACT_QUESTIONS["operation_start_date"]["question"] = "Hệ thống được đưa vào hoạt động từ ngày nào?"
for name, question in {
    "content_may_mislead": "Nội dung có khả năng gây nhầm lẫn về tính xác thực của sự kiện, nhân vật không?",
    "sectors": "Hệ thống được sử dụng trong những lĩnh vực nào?",
    "content_types": "Hệ thống tạo hoặc chỉnh sửa những loại nội dung nào?",
    "is_public_sector": "Tổ chức của bạn có phải là cơ quan nhà nước không?",
    "is_foreign_provider": "Nhà cung cấp hệ thống có phải là tổ chức, cá nhân nước ngoài không?",
    "interacts_with_humans": "Hệ thống có tương tác trực tiếp với con người không?",
    "generates_content": "Hệ thống có tạo hoặc chỉnh sửa nội dung không?",
    "simulates_real_person": "Nội dung có mô phỏng người thật hoặc sự kiện thật không?",
    "public_distribution": "Nội dung hoặc dịch vụ có được cung cấp ra công chúng không?",
    "uses_third_party_model": "Hệ thống có dùng mô hình của bên thứ ba không?",
    "modified_by_deployer": "Bên triển khai có sửa đổi hệ thống không?",
    "uses_personal_data": "Hệ thống có xử lý dữ liệu cá nhân không?",
    "requires_conformity_certification": "Hệ thống có thuộc diện bắt buộc chứng nhận sự phù hợp trước khi sử dụng không?",
    "public_decision_use": "Kết quả có dùng làm căn cứ quyết định trong quản lý nhà nước hoặc dịch vụ công không?",
}.items():
    FACT_QUESTIONS[name]["question"] = question


def followup_questions(rows, facts, max_questions=3):
    if type(max_questions) is not int or max_questions < 0:
        raise ValueError("max_questions phải là số nguyên không âm")
    items = applicable_obligations(rows, facts)["items"]
    affected = dict.fromkeys(FACT_FIELDS, 0)
    for item in items:
        if item["applicability"] == "ap_dung_neu":
            for name in set(item["missing_facts"]):
                if name in affected and facts.get(name) is None:
                    affected[name] += 1
    priority = [name for name in ("roles", "risk_level") if facts.get(name) is None]
    remaining = [name for name in FACT_FIELDS if affected[name] and name not in priority]
    remaining.sort(key=lambda name: -affected[name])
    return [{"field": name, "question": FACT_QUESTIONS[name]["question"],
             "options": list(FACT_QUESTIONS[name]["options"]), "affected": affected[name]}
            for name in (priority + remaining)[:max_questions]]


def ready_for_assessment(facts):
    return facts.get("roles") is not None and facts.get("risk_level") is not None
