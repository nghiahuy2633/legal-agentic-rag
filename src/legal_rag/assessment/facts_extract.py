"""Trích dữ kiện có câu trích, không suy đoán trường chưa biết."""

import json

from legal_rag.assessment.status import PROMPTS, payload, valid_quote
from legal_rag.knowledge.facts import FACT_FIELDS, FACT_LABELS, empty_facts, validate_facts
from legal_rag.llm import LLMError


FACT_DESCRIPTIONS = {
    "content_may_mislead": "nội dung có khả năng gây nhầm lẫn về tính xác thực của sự kiện, nhân vật",
    "roles": "Vai trò người dùng khai theo các định nghĩa bên dưới; có thể nhiều vai trò.",
    "risk_level": "Mức đã được người dùng hoặc nhà cung cấp khai; không tự phân loại.",
    "sectors": "Lĩnh vực sử dụng hệ thống được mô tả cụ thể.",
    "is_public_sector": "Tổ chức sử dụng là cơ quan nhà nước.",
    "is_foreign_provider": "Nhà cung cấp là tổ chức, cá nhân nước ngoài.",
    "interacts_with_humans": "Hệ thống trò chuyện hoặc tương tác trực tiếp với con người, như chatbot hay trợ lý ảo.",
    "generates_content": "Hệ thống tạo hoặc chỉnh sửa nội dung.",
    "simulates_real_person": "Nội dung mô phỏng người thật hoặc sự kiện thật.",
    "public_distribution": "Nội dung hoặc dịch vụ cung cấp ra công chúng, như đăng công khai hay ứng dụng phát hành công khai.",
    "uses_third_party_model": "Hệ thống của chính người dùng tích hợp mô hình bên khác; mua hoặc thuê phần mềm không đủ để xác nhận.",
    "modified_by_deployer": "Bên triển khai sửa đổi hệ thống đã nhận.",
    "uses_personal_data": "Hệ thống xử lý dữ liệu cá nhân.",
    "content_types": "Các loại nội dung mà hệ thống tạo hoặc chỉnh sửa.",
    "operation_start_date": "Ngày bắt đầu hoạt động, kể cả dự kiến hoặc sẽ hoạt động; không lấy ngày dự kiến của việc khác.",
    "requires_conformity_certification": "Người dùng khai hệ thống thuộc diện bắt buộc chứng nhận sự phù hợp trước khi sử dụng.",
    "public_decision_use": "Kết quả hệ thống dùng làm căn cứ quyết định trong quản lý nhà nước hoặc dịch vụ công.",
}


def extract_facts(messages, chat, model, prompt_version="facts_v2"):
    if not isinstance(messages, list) or not all(isinstance(m, str) for m in messages):
        raise ValueError("messages phải là danh sách tin nhắn người dùng")
    if prompt_version not in ("facts_v1", "facts_v2"):
        raise ValueError("Phiên bản prompt dữ kiện không hợp lệ")
    fields = [{"name": name, "label": FACT_LABELS[name], "type": spec["type"],
               "values": sorted(spec["values"]) if "values" in spec else
               [True, False] if spec["type"] == "bool" else "YYYY-MM-DD",
               "description": FACT_DESCRIPTIONS[name]} for name, spec in FACT_FIELDS.items()]
    prompt = (PROMPTS / f"{prompt_version}.txt").read_text(encoding="utf-8")
    prompt += "\nCÁC TRƯỜNG (mọi trường cho phép null):\n" + json.dumps(fields, ensure_ascii=False)
    result = {"facts": empty_facts(), "evidence": {}, "rejected": [], "llm_calls": 1}
    try:
        parsed = json.loads(chat.complete(payload(
            prompt, json.dumps({"messages": messages}, ensure_ascii=False), model, True)))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("facts"), dict):
            raise ValueError("thiếu đối tượng facts")
    except LLMError:
        result["error"] = "LLMError"
        return result
    except (ValueError, TypeError):
        result["error"] = "JSON không hợp lệ"
        return result
    source = "\n".join(messages)
    for name, entry in parsed["facts"].items():
        if name not in FACT_FIELDS or not isinstance(entry, dict) or "value" not in entry:
            result["rejected"].append({"field": name, "reason": "value"})
            continue
        value, quote = entry["value"], entry.get("quote")
        if value is None:
            continue
        if not valid_quote(quote, source):
            result["rejected"].append({"field": name, "reason": "quote"})
            continue
        clean, errors = validate_facts({name: value})
        if errors:
            result["rejected"].append({"field": name, "reason": "value"})
            continue
        result["facts"][name] = clean[name]
        result["evidence"][name] = quote
    return result


def merge_facts(previous, extracted, form=None):
    """Gộp dict dữ kiện; form có quyền ghi đè cả bằng None."""
    sources = []
    for values in (previous, extracted, form):
        clean, errors = validate_facts(values if values is not None else {})
        if errors:
            raise ValueError("; ".join(errors))
        sources.append(clean)
    old, update, selected = sources
    facts = {name: selected[name] if form is not None and name in form else
             update[name] if update[name] is not None else old[name] for name in FACT_FIELDS}
    changes = [{"field": name, "old": old[name], "new": facts[name]}
               for name in FACT_FIELDS if old[name] != facts[name]]
    return facts, changes
