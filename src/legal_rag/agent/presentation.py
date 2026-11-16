"""Chiếu dữ liệu đã xử lý sang lời văn; không quyết định lại quy tắc pháp lý."""

from copy import deepcopy
import re

from legal_rag.agent.followup import before_closing
from legal_rag.generation.citations import markdown_code_mask
from legal_rag.knowledge.facts import FACT_LABELS

PREFIX = "33-2026-QD-TTg_linh-vuc-"
REASONS = {
    "no_candidates": "Chưa tìm được ứng viên để xác định mục phù hợp với mô tả sản phẩm.",
    "invalid_response": "Phản hồi đối chiếu chưa đọc được đúng cấu trúc.",
    "unresolved": "Cần mô tả rõ chức năng chính, đầu ra và cách sử dụng để đối chiếu tiếp.",
    "not_relevant": "Các ứng viên đã đối chiếu chưa có mục được xác nhận phù hợp với chức năng đã mô tả.",
}
INTERNAL_LABELS = {
    **FACT_LABELS,
    "ap_dung_neu": "có điều kiện", "ap_dung": "áp dụng",
    "applicability": "mức áp dụng", "missing_facts": "thông tin cần bổ sung",
    "evidence_ids": "căn cứ",
}
TOKEN = re.compile(r"\bob-\d+\b|\b(?:" + "|".join(map(re.escape, INTERNAL_LABELS)) + r")\b", re.I)
PREFIX_ERROR = "Phần diễn giải chưa có mục rõ ràng cần được đối chiếu trước khi sử dụng."
OWNED_SECTIONS = ("Trả lời ngắn", "Nghĩa vụ cần xem xét", "Thông tin còn thiếu và giới hạn")
FACT_VALUES = {
    "nha_phat_trien": "nhà phát triển", "nha_cung_cap": "nhà cung cấp",
    "ben_trien_khai": "bên triển khai", "nguoi_su_dung": "người sử dụng",
    "giao_duc": "giáo dục", "y_te": "y tế", "tai_chinh_ngan_hang": "tài chính, ngân hàng",
    "dan_toc_ton_giao": "dân tộc, tôn giáo", "to_tung": "tố tụng",
    "giao_thong_van_tai": "giao thông vận tải", "thuong_mai": "thương mại",
    "quang_cao": "quảng cáo", "an_sinh_xa_hoi": "an sinh xã hội", "lam_dep": "làm đẹp",
    "lao_dong": "lao động", "khac": "khác", "cao": "cao", "trung_binh": "trung bình",
    "thap": "thấp", "chua_phan_loai": "chưa phân loại", "van_ban": "văn bản",
    "am_thanh": "âm thanh", "hinh_anh": "hình ảnh", "video": "video",
}


def facts_context(context, facts, source, summary):
    """Chiếu đúng snapshot đã lọc; không suy dữ kiện hoặc áp dụng lại quy tắc."""
    result = deepcopy(context)
    known = []
    for key, value in facts.items():
        if value is None:
            continue
        if isinstance(value, list):
            label = "; ".join(FACT_VALUES.get(v, v) for v in value) if value else "danh sách rỗng đã khai"
        elif isinstance(value, bool):
            label = "có" if value else "không"
        else:
            label = FACT_VALUES.get(value, value)
        known.append({"Dữ kiện": "mức rủi ro đã khai trong hồ sơ" if key == "risk_level"
                      else FACT_LABELS.get(key, "thông tin cần xác minh"), "Giá trị": label})
    missing = list(dict.fromkeys(key for row in summary.get("items", [])
        for key in row.get("missing_facts", [])
        if facts.get(key) is None or (key == "risk_level" and facts.get(key) == "chua_phan_loai")))
    known_labels = {FACT_LABELS.get(key) for key, value in facts.items() if value is not None
                    and not (key == "risk_level" and value == "chua_phan_loai")}
    for row in result["data"]["Nghĩa vụ có căn cứ hiện diện"]:
        row["Thông tin cần bổ sung"] = [label for label in row["Thông tin cần bổ sung"] if label not in known_labels]
    count = len(result["data"]["Nghĩa vụ có căn cứ hiện diện"])
    result["data"]["Dữ kiện đã dùng để lọc nghĩa vụ"] = {
        "Nguồn": "hồ sơ rà soát đã nhập hoặc xác nhận" if source == "assessment" else "hồ sơ trích từ hội thoại",
        "Dữ kiện đã có": known,
        "Thông tin còn thiếu theo kết quả lọc": [FACT_LABELS.get(k, "thông tin cần xác minh") for k in missing],
        "Số dòng kết quả lọc": len(summary.get("items", [])), "Số dòng có căn cứ hiện diện": count,
    }
    result["facts_source"] = source
    result["snapshot_rows"] = len(summary.get("items", []))
    result["displayed_rows"] = count
    return result


def sections(text):
    """Các mục ## theo thứ tự; bỏ phần trước heading đầu tiên."""
    headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", markdown_code_mask(text), re.M))
    return [(h[1].strip(), text[h.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip())
            for i, h in enumerate(headings)]


def answer_first(report, direct):
    """Trả lời ngắn của báo cáo lấy từ lời trả lời trực tiếp; câu mở đầu cũ chuyển xuống mục giới hạn (T57).

    Trả về (văn bản, None) khi ghép được, hoặc (report, lý do) khi giữ khuôn cũ.
    """
    parts = dict(sections(before_closing(direct)[0]))
    short = parts.get("Trả lời ngắn", "").strip()
    if not short:
        return report, "direct_missing_short_answer"
    basis = parts.get("Căn cứ", "").strip()
    body, closing = before_closing(report)
    current = sections(body)
    if not current or current[0][0] != "Trả lời ngắn":
        return report, "report_missing_short_answer"
    old = current[0][1].strip()
    old = "" if old in ("", "None") else old
    limits = "Thông tin còn thiếu và giới hạn"
    out = []
    for title, text in current:
        if title == "Trả lời ngắn":
            text = short + ("\n\n" + basis if basis else "")
        elif title == limits and old:
            text = "Đối chiếu Danh mục: " + old + ("\n\n" + text if text else "")
        out.append("## " + title + "\n\n" + text)
    if old and limits not in dict(current):
        out.append("## " + limits + "\n\nĐối chiếu Danh mục: " + old)
    return "\n\n".join(part for part in ("\n\n".join(out), closing) if part), None


def prohibition_line(rows, context):
    """T59: gộp các dòng hành vi bị cấm không kèm điều kiện thành một dòng, giữ đủ mã nguồn.

    Trả về (dòng gộp hoặc None, các dòng còn lại). Dòng cấm có điều kiện hoặc cần bổ sung thông tin giữ nguyên.
    """
    kinds = context.get("row_kinds") or []
    banned = [row for i, row in enumerate(rows, 1)
              if kinds[row.get("row", i) - 1:row.get("row", i)] == ["cam"]
              and not row["Điều kiện"] and not row["Thông tin cần bổ sung"]]
    if len(banned) < 2:
        return None, rows
    ids = {id(row) for row in banned}
    codes = list(dict.fromkeys(code for row in banned for code in row["Căn cứ"]))
    names = []
    for row in banned:
        text = row["Nghĩa vụ"].split("nhằm mục đích:", 1)[-1].strip().rstrip(";.")
        words = text.removeprefix("Không được ").split()
        names.append(" ".join(words[:12]) + ("…" if len(words) > 12 else ""))
    line = (f"- Không thực hiện {len(banned)} nhóm hành vi bị cấm, áp dụng cho mọi bên: "
            + "; ".join(names) + ". " + "".join(f"[{code}]" for code in codes)
            + "\n  Mức áp dụng: Áp dụng. Nguyên văn từng hành vi xem tại căn cứ đã dẫn.")
    return line, [row for row in rows if id(row) not in ids]


def owned_bodies(context):
    """Nội dung ba mục được dựng từ kết quả sẵn có, không diễn giải lại luật."""
    rows = context["data"]["Nghĩa vụ có căn cứ hiện diện"]
    banned, rows = prohibition_line(rows, context)
    obligations = [banned] if banned else []
    for row in rows:
        lines = ["- " + row["Nghĩa vụ"] + " " + "".join(f"[{code}]" for code in row["Căn cứ"]),
                 "  Mức áp dụng: " + row["Mức áp dụng"] + "."]
        lines.extend("  Điều kiện: " + value for value in row["Điều kiện"])
        if row["Thông tin cần bổ sung"]:
            lines.append("  Thông tin cần bổ sung: " + "; ".join(row["Thông tin cần bổ sung"]) + ".")
        obligations.append("\n".join(lines))
    facts = context["data"]["Dữ kiện đã dùng để lọc nghĩa vụ"]
    limits = ["Nguồn dữ kiện: " + facts["Nguồn"] + ". Đây là thông tin trong hồ sơ, chưa phải kết quả xác minh pháp lý."]
    limits.extend("- Đã có: " + row["Dữ kiện"] + ": " + row["Giá trị"] + "." for row in facts["Dữ kiện đã có"])
    if not facts["Dữ kiện đã có"]:
        limits.append("- Chưa có dữ kiện hồ sơ để trình bày.")
    limits.extend("- Cần bổ sung theo kết quả lọc: " + label + "." for label in facts["Thông tin còn thiếu theo kết quả lọc"])
    if not facts["Thông tin còn thiếu theo kết quả lọc"]:
        limits.append("- Không có trường cần bổ sung được ghi nhận trong kết quả lọc hiện tại.")
    limits.append("- Mức rủi ro đã khai không phải kết luận sản phẩm thuộc hoặc không thuộc Danh mục; "
                  "kết quả đối chiếu Danh mục được trình bày riêng.")
    total, count = facts["Số dòng kết quả lọc"], facts["Số dòng có căn cứ hiện diện"]
    coverage = context["data"].get("Độ đủ căn cứ để trình bày")
    if coverage is not None:
        limits.append(f"- Độ đủ căn cứ trình bày: {count}/{total} dòng đủ điều kiện trình bày chi tiết; "
            f'{coverage["Đủ tập nguồn đã gắn"]} dòng đủ tập nguồn đã gắn; '
            f'{coverage["Có căn cứ một phần"]} dòng có căn cứ một phần; '
            f'{coverage["Chưa có căn cứ hiện diện"]} dòng chưa có căn cứ hiện diện. '
            "Có đủ tập nguồn vẫn cần kiểm nội dung và điều kiện của từng dòng.")
        withheld = coverage["Cần đối chiếu căn cứ trước khi trình bày chi tiết"]
        if withheld:
            obligations.append(f"Có {withheld} dòng: Cần đối chiếu căn cứ trước khi trình bày chi tiết. "
                "Các dòng này vẫn giữ kết quả lọc ban đầu; chưa đủ căn cứ trình bày không có nghĩa không áp dụng.")
            limits.append(f"- {withheld} dòng chưa được trình bày chi tiết vì căn cứ chưa đủ; "
                "đây là giới hạn nguồn, không phải kết luận thiếu dữ kiện sản phẩm hoặc không áp dụng.")
        limits.append("- Kiểm nguồn và cấu trúc không chứng minh nội dung đúng pháp lý hoặc đã bao phủ mọi nghĩa vụ pháp luật.")
    else:
        limits.append(f"- Độ phủ trình bày: {count}/{total} dòng kết quả lọc có căn cứ hiện diện; "
                      f"{total - count} dòng chưa có căn cứ hiện diện trong câu trả lời. "
                      "Thiếu căn cứ hiển thị không có nghĩa nghĩa vụ không áp dụng. "
                      "Kết quả chỉ phản ánh bảng và bằng chứng hiện có, không bảo đảm đã bao phủ mọi nghĩa vụ pháp luật.")
    return {"Trả lời ngắn": context["opening"],
            "Nghĩa vụ cần xem xét": "\n\n".join(obligations) or "Chưa có dòng nghĩa vụ đủ căn cứ hiện diện để trình bày.",
            "Thông tin còn thiếu và giới hạn": "\n".join(limits)}


def _registry(rows, key):
    return rows if isinstance(rows, dict) else {row[key]: row for row in rows}


def build_context(bases, evidence, high_risk=None, risk_items=(), decisions=(), parents=(), documents=()):
    """Snapshot riêng; data là phần duy nhất gửi LLM, ánh xạ mã chỉ dùng nội bộ."""
    available = {item["id"] for item in evidence}
    obligations, labels, situations, kinds = [], {}, [], []
    for basis in bases:
        codes = [code for code in basis.get("evidence_ids", []) if code in available]
        if not codes:
            continue
        text = basis.get("obligation", "")
        obligations.append({"Nghĩa vụ": text,
            "Mức áp dụng": "Áp dụng" if basis.get("applicability") == "ap_dung" else "Có điều kiện",
            "Điều kiện": deepcopy(basis.get("conditions", [])),
            "Thông tin cần bổ sung": [FACT_LABELS.get(key, "thông tin cần xác minh")
                                       for key in basis.get("missing_facts", [])],
            "Căn cứ": codes})
        situations.append(basis.get("situation", ""))
        kinds.append(basis.get("kind", "nghia_vu"))
        if basis.get("id") and text:
            labels[basis["id"].lower()] = text
    data = {"Nghĩa vụ có căn cứ hiện diện": obligations}
    # Phạm vi theo bảng nghĩa vụ và điều kiện Danh mục chưa rõ chỉ khuôn V12 dùng, không vào data của V10/V11.
    context = dict(data=data, obligation_labels=labels, opening=None, situations=situations, catalog_unclear=[],
                   row_kinds=kinds)
    if not high_risk or high_risk.get("version") != "high_risk_v2":
        return context
    registry, source_parents = _registry(risk_items, "item_id"), _registry(parents, "parent_id")
    source_docs = _registry(documents, "document_id")
    checked = _registry(decisions, "item_id")
    selected = []
    for key in high_risk.get("parent_ids", []):
        if key not in registry:
            continue
        item, decision = registry[key], checked.get(key, {})
        parent = source_parents.get(key, {})
        doc = source_docs.get(parent.get("document_id"), {})
        # Mục đã có điều kiện không đáp ứng thì bị loại (đọc đồng thời), không hỏi thêm điều kiện chưa rõ.
        excluded = any(row.get("status") == "khong_dap_ung" for row in decision.get("conditions", []))
        context["catalog_unclear"].extend(
            f'{item["sector"]}, STT {item["stt"]}: {row["text"].strip().rstrip(";.").strip()}'
            for row in decision.get("conditions", [])
            if not excluded and row.get("status", "chua_ro") == "chua_ro" and (row.get("text") or "").strip())
        selected.append({"Tên mục": item["name"], "Lĩnh vực": item["sector"], "STT": str(item["stt"]),
            "Điều kiện đã đối chiếu": [{"Điều kiện thứ": row["index"],
                "Kết quả": {"dap_ung": "đáp ứng", "khong_dap_ung": "không đáp ứng",
                             "chua_ro": "chưa rõ"}.get(row.get("status"), "chưa rõ")}
                for row in decision.get("conditions", [])],
            "Nguồn": doc.get("document_number", "xem khối Danh mục bên dưới")})
    reason = REASONS.get(high_risk.get("selection_reason"), "")
    data["Kết quả đối chiếu Danh mục đã xử lý"] = {"Mục được giữ để đối chiếu": selected,
        "Kết quả": high_risk.get("label", ""), "Lý do chưa đủ cơ sở": reason}
    if selected:
        names = "; ".join(f'{r["Lĩnh vực"]}, STT {r["STT"]}: {r["Tên mục"]}' for r in selected)
        context["opening"] = ("Các mục được giữ để đối chiếu: " + names + ". "
            + "Kết quả đối chiếu: " + high_risk.get("label", "") + ". "
            + "Xem từng điều kiện trong khối Danh mục bên dưới. Đây chưa phải kết luận sản phẩm "
              "thuộc Danh mục hoặc có rủi ro cao.")
    elif any(key.startswith(PREFIX) for key in high_risk.get("parent_ids", [])):
        # Giữ sự thật có mục, không bịa tên khi registry thiếu.
        context["opening"] = ("Có mục được giữ để đối chiếu; xem tên và các điều kiện trong khối Danh mục bên dưới. "
                              "Đây chưa phải kết luận sản phẩm thuộc Danh mục hoặc có rủi ro cao.")
    else:
        context["opening"] = ("Chưa đủ cơ sở đề xuất mục Danh mục. " + reason
                              + " Kết quả này không phải kết luận sản phẩm không thuộc Danh mục.")
    return context


def narrative_mask(text):
    """Không đổi code, URL, đích liên kết hoặc phần trích dẫn nguyên văn."""
    masked = list(markdown_code_mask(text))
    visible = "".join(masked)
    patterns = (r"\b[a-z][a-z0-9+.-]*://[^\s<>]+", r"\]\([^\n)]*\)",
                r'"[^"\n]*"', r"“[^”]*”", r"‘[^’]*’", r"'[^'\n]*'", r"(?m)^\s*>[^\n]*")
    for pattern in patterns:
        for match in re.finditer(pattern, visible, re.I):
            for pos in range(match.start(), match.end()):
                if text[pos] not in "\r\n":
                    masked[pos] = " "
    return "".join(masked)


def humanize(text, context):
    visible = narrative_mask(text)
    labels, edits, errors, changes = context.get("obligation_labels", {}), [], [], []
    for match in TOKEN.finditer(visible):
        key = match[0].lower()
        if key.startswith("ob-"):
            replacement = labels.get(key)
            if replacement is None:
                replacement = "nghĩa vụ cần đối chiếu"
                errors.append("Chưa giải được mã nghĩa vụ trong phần trình bày: " + key)
            else:
                # ID là nhãn trước nội dung: bỏ riêng nhãn, giữ câu/nguồn đã sinh.
                suffix = re.match(r"\s*:\s*(?=\S)", visible[match.end():])
                start = visible.rfind("\n", 0, match.start()) + 1
                prefix = visible[start:match.start()]
                rest = visible[match.end() + suffix.end():].splitlines()[0] if suffix else ""
                # Mã nguồn/đường dẫn không phải nội dung diễn giải của nghĩa vụ.
                content = re.sub(r"\[[^\]\n]*\]", "", rest)
                has_body = bool(re.search(r"[^\W_]{2,}", content, re.UNICODE))
                if suffix and has_body and re.fullmatch(r"\s*(?:[-*+]\s+|\d+[.)]\s+)?", prefix):
                    edits.append((match.start(), match.end() + suffix.end(), ""))
                    changes.append("internal_label_removed")
                    continue
            changes.append("obligation_id_projected")
        else:
            replacement = INTERNAL_LABELS[key]
            changes.append("fact_label_projected")
        edits.append((match.start(), match.end(), replacement))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text, list(dict.fromkeys(changes)), list(dict.fromkeys(errors))


def owned_opening(text, opening):
    body, closing = before_closing(text)
    if closing and closing not in markdown_code_mask(text):
        body, closing = text, ""
    visible = markdown_code_mask(body)
    headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", visible, re.M))
    prefix_end = headings[0].start() if headings else len(body)
    prefix, errors = body[:prefix_end], []
    if prefix.strip():
        # Giữ nội dung nhưng tách khỏi phần do code sở hữu, buộc kiểm/sửa.
        body = "## Nội dung cần đối chiếu\n\n" + prefix.strip() + "\n\n" + body[prefix_end:]
        visible = markdown_code_mask(body)
        headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", visible, re.M))
    if any(h[1].strip() == "Nội dung cần đối chiếu" for h in headings):
        errors.append(PREFIX_ERROR)
    removed = []
    for i, heading in enumerate(headings):
        if heading[1].strip() == "Trả lời ngắn":
            removed.append((heading.start(), headings[i + 1].start() if i + 1 < len(headings) else len(body)))
    for start, end in reversed(removed):
        body = body[:start] + body[end:]
    return "\n\n".join(part for part in ("## Trả lời ngắn\n\n" + opening, body.strip(), closing) if part), errors


def catalog_missing(context):
    """Điều kiện Danh mục còn chưa rõ, nguyên văn từ kết quả đối chiếu, đặt trước các trường hồ sơ."""
    unclear = list(dict.fromkeys(context.get("catalog_unclear", [])))
    if not unclear:
        return ""
    return ("Điều kiện Danh mục chưa rõ, cần bổ sung thông tin để đối chiếu:\n"
            + "\n".join("- " + line + "." for line in unclear) + "\n\n")


def bound_answer(raw, context, items=(), index=None, chunks=None):
    from legal_rag.agent.explanations import bind_explanations
    from legal_rag.agent.followup import CLOSING
    from legal_rag.generation.citations import format_citation

    accepted, binding = bind_explanations(raw, context, items, index, chunks)
    bodies = owned_bodies(context)
    rows = context["data"]["Dòng cần giải thích"]
    banned, shown = prohibition_line(rows, context)
    obligations = [banned] if banned else []
    for row in shown:
        lines = ["- " + row["Nghĩa vụ"] + " " + "".join(f"[{code}]" for code in row["Căn cứ"]),
                 "  Mức áp dụng: " + row["Mức áp dụng"] + "."]
        if row.get("Phạm vi theo bảng nghĩa vụ"):
            lines.append("  Phạm vi theo bảng nghĩa vụ: " + row["Phạm vi theo bảng nghĩa vụ"].rstrip(";.") + ".")
        lines.extend("  Điều kiện: " + value for value in row["Điều kiện"])
        if row["Thông tin cần bổ sung"]:
            lines.append("  Thông tin cần bổ sung: " + "; ".join(row["Thông tin cần bổ sung"]) + ".")
        # T57: chỉ trình bày nguyên văn nghĩa vụ, mức áp dụng, điều kiện và mã nguồn. Lời giải thích của LLM
        # vẫn được kiểm và ghi audit (explanations) nhưng không hiển thị, để mọi dòng đều có nguồn trực tiếp.
        obligations.append("\n".join(lines))
    coverage = context["data"].get("Độ đủ căn cứ để trình bày", {})
    withheld = coverage.get("Cần đối chiếu căn cứ trước khi trình bày chi tiết", 0)
    if withheld:
        obligations.append(f"Có {withheld} dòng: Cần đối chiếu căn cứ trước khi trình bày chi tiết. "
            "Các dòng này vẫn giữ kết quả lọc ban đầu; chưa đủ căn cứ trình bày không có nghĩa không áp dụng.")
    available = {item["id"]: item for item in items}
    codes = list(dict.fromkeys(code for row in rows for code in row["Căn cứ"]))
    # URL chỉ ở Căn cứ pháp lý cuối câu; chỉ mục này giữ vị trí.
    sources = [f'- [{code}] {format_citation(available[code]).rsplit(", ", 1)[0]}' for code in codes if code in available]
    parts = {"Trả lời ngắn": bodies["Trả lời ngắn"],
             "Quy định áp dụng": "\n".join(sources) or "Không có căn cứ hiện diện đủ để trình bày chi tiết nghĩa vụ.",
             "Nghĩa vụ cần xem xét": "\n\n".join(obligations) or "Chưa có dòng nghĩa vụ đủ căn cứ hiện diện để trình bày.",
             "Thông tin còn thiếu và giới hạn": catalog_missing(context) + bodies["Thông tin còn thiếu và giới hạn"]}
    text = "\n\n".join("## " + title + "\n\n" + body for title, body in parts.items()) + "\n\n" + CLOSING
    audit = dict(has_snapshot=True, opening_source="code", changes=["bound_explanations"],
        errors=binding["errors"], facts_source=context["facts_source"], snapshot_rows=context["snapshot_rows"],
        displayed_rows=context["displayed_rows"], owned_sections=list(parts), explanations=binding)
    if coverage:
        audit["source_coverage"] = deepcopy(coverage)
    return text, audit


def present_answer(text, context=None, version=None, *, items=(), index=None, chunks=None):
    if version == "answer_v12" and context is not None:
        return bound_answer(text, context, items, index, chunks)
    audit = dict(has_snapshot=context is not None, opening_source="llm", changes=[], errors=[])
    if context is None:
        return text, audit
    text, audit["changes"], audit["errors"] = humanize(text, context)
    if version in ("answer_v10", "answer_v11") and context.get("opening"):
        text, errors = owned_opening(text, context["opening"])
        audit["errors"] = list(dict.fromkeys([*audit["errors"], *errors]))
        audit["opening_source"] = "code"
        audit["changes"].append("code_opening")
    if version == "answer_v11" and "Dữ kiện đã dùng để lọc nghĩa vụ" in context["data"]:
        body, closing = before_closing(text)
        if closing and closing not in markdown_code_mask(text):
            body, closing = text, ""
        headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)(?:\r?\n|$)", markdown_code_mask(body), re.M))
        for i in reversed(range(len(headings))):
            heading = headings[i]
            if heading[1].strip() in OWNED_SECTIONS:
                end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
                body = body[:heading.start()] + body[end:]
        bodies = owned_bodies(context)
        text = "\n\n".join(part for part in ("## Trả lời ngắn\n\n" + bodies["Trả lời ngắn"],
            body.strip(), *("## " + title + "\n\n" + bodies[title] for title in OWNED_SECTIONS[1:]), closing) if part)
        audit.update(facts_source=context["facts_source"], snapshot_rows=context["snapshot_rows"],
                     displayed_rows=context["displayed_rows"], owned_sections=list(OWNED_SECTIONS))
        if "Độ đủ căn cứ để trình bày" in context["data"]:
            audit["source_coverage"] = deepcopy(context["data"]["Độ đủ căn cứ để trình bày"])
        audit["changes"].append("code_obligations_and_limits")
    return text, audit


def apply_presentation_errors(check, errors):
    check["presentation_errors"] = list(dict.fromkeys(errors))
    check["errors"] = list(dict.fromkeys([*check["errors"], *errors]))
    check["valid"] = check["valid"] and not errors
    return check
