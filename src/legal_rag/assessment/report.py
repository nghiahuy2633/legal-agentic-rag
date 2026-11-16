"""Tính bản đánh giá và kết xuất ổn định; LLM chỉ viết phần tóm tắt."""

from collections import Counter
from copy import deepcopy
import json
import re

from legal_rag.assessment.status import PROMPTS, payload
from legal_rag.knowledge.facts import FACT_LABELS
from legal_rag.llm import LLMError

DISCLAIMER = "Bản đánh giá hỗ trợ tự rà soát dựa trên thông tin bạn cung cấp, không thay thế ý kiến pháp lý."
DOCUMENTS = {"134-2025-QH15": "Luật 134/2025/QH15",
             "142-2026-ND-CP": "Nghị định 142/2026/NĐ-CP",
             "33-2026-QD-TTg": "Quyết định 33/2026/QĐ-TTg",
             "05-2026-TT-BKHCN": "Thông tư 05/2026/TT-BKHCN"}
STATUS_LABELS = {"da": "Đã đáp ứng", "chua": "Chưa đáp ứng", "chua_ro": "Chưa rõ",
                 "co_dau_hieu": "Có dấu hiệu", "khong_phat_hien": "Không phát hiện"}


def citation_label(chunk_id):
    document, *parts = chunk_id.split("_")
    labels = [DOCUMENTS.get(document, document)]
    for part in parts:
        for prefix, label in (("dieu-", "Điều"), ("khoan-", "khoản"), ("diem-", "điểm"),
                              ("phu-luc-", "Phụ lục"), ("muc-", "mục")):
            if part.startswith(prefix):
                labels.append(f"{label} {part[len(prefix):]}")
                break
        else:
            labels.append(part)
    return ", ".join(labels)


def build_report(facts, items, status, meta):
    report = {"summary": {"total": 0, "da": 0, "chua": 0, "chua_ro": 0,
                           "rate": None, "conditional_total": 0},
              "obligations": [], "warnings": [], "info": [], "todo": [],
              "meta": {**deepcopy(meta), "facts": deepcopy(facts),
                       "prompt_version": status.get("prompt_version", "status_v1"), "disclaimer": DISCLAIMER}}
    statuses = {r["row_id"]: r for r in status["rows"]}
    missing = Counter()
    for item in items:
        row = item["row"]
        missing.update(list(dict.fromkeys(item["missing_facts"])))
        state = statuses.get(row["id"], {"status": "chua_ro", "criteria": []})
        entry = {key: deepcopy(row[key]) for key in ("id", "group", "obligation")}
        entry.update(applicability=item["applicability"], conditions=list(item["conditions"]),
                     deadline=row.get("deadline"), status=state["status"],
                     criteria=deepcopy(state["criteria"]), citations=[
                         {"chunk_id": c["chunk_id"], "label": citation_label(c["chunk_id"])}
                         for c in row["citations"]])
        kind = row.get("kind", "nghia_vu")
        if kind == "thong_tin":
            entry.pop("status")
            entry.pop("criteria")
            report["info"].append(entry)
        elif kind == "cam":
            if state["status"] == "co_dau_hieu":
                entry["quotes"] = [c["quote"] for c in state["criteria"] if c["status"] == "co_dau_hieu"]
                report["warnings"].append(entry)
        else:
            report["obligations"].append(entry)
            if item["applicability"] == "ap_dung":
                report["summary"]["total"] += 1
                report["summary"][state["status"]] += 1
            else:
                report["summary"]["conditional_total"] += 1
    summary = report["summary"]
    summary["rate"] = summary["da"] / summary["total"] if summary["total"] else None
    applicable = [o for o in report["obligations"] if o["applicability"] == "ap_dung"]
    undone = sorted((o for o in applicable if o["status"] == "chua"),
                    key=lambda o: "trước khi đưa" not in (o["deadline"] or "").lower())
    report["todo"].extend({"type": "thuc_hien", "row_id": o["id"],
                           "text": o["obligation"], "deadline": o["deadline"]} for o in undone)
    for obligation in applicable:
        if obligation["status"] == "chua_ro":
            report["todo"].extend({"type": "tu_kiem", "row_id": obligation["id"],
                "criterion_id": c["id"], "text": f"Đã đáp ứng chưa: {c['text'].rstrip(' .;:')}?"}
                for c in obligation["criteria"] if c["status"] == "chua_ro")
    for field, count in sorted(missing.items(), key=lambda p: -p[1]):
        report["todo"].append({"type": "bo_sung_du_kien", "field": field,
            "affected_rows": count, "text": f"Bổ sung dữ kiện: {FACT_LABELS.get(field, field)}"})
    return report


def fallback_summary(report):
    summary = report["summary"]
    return f"Đã đáp ứng {summary['da']}/{summary['total']} nghĩa vụ áp dụng. Có {summary['chua_ro']} nghĩa vụ chưa rõ hiện trạng."


def summarize(report, chat, model):
    content = {"summary": report["summary"], "todo": report["todo"],
               "obligations": [o["obligation"] for o in report["obligations"]]}
    result = {"text": fallback_summary(report), "summary_rejected": False, "errors": [], "llm_calls": 1}
    try:
        answer = chat.complete(payload((PROMPTS / "summary_v1.txt").read_text(encoding="utf-8"),
                                       json.dumps(content, ensure_ascii=False), model))
    except LLMError:
        result.update(summary_rejected=True, errors=["LLMError"])
        return result
    # Tách cả số thập phân, không cho phép 3.5 chỉ vì có 3 và 5.
    def numbers(text):
        return set(re.findall(r"\d+(?:[.,]\d+)?", text))
    allowed = numbers(json.dumps({"summary": report["summary"], "todo": report["todo"]}, ensure_ascii=False))
    for item in report["obligations"] + report["warnings"] + report["info"]:
        for citation in item["citations"]:
            allowed.update(re.findall(r"(?:Điều|khoản)\s+(\d+)", citation["label"]))
    if (not isinstance(answer, str) or not answer.strip() or numbers(answer) - allowed
            or len(re.split(r"(?<=[.!?])\s+", answer.strip())) > 5):
        result["summary_rejected"] = True
    else:
        result["text"] = answer.strip()
    return result


def render_markdown(report):
    def escape(value):
        import html
        return html.escape(str(value), quote=False).replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")

    def evidence(entry):
        return "; ".join(f"{c['text']}: {c['quote']}" if c["quote"] else
                         f"{c['text']}: người dùng tự kiểm" for c in entry["criteria"]
                         if c["quote"] or c["source"] == "nguoi_dung") or "Chưa có"

    def table(entries):
        lines = ["| Nghĩa vụ | Căn cứ | Hiện trạng | Bằng chứng |", "|---|---|---|---|"]
        for o in entries:
            lines.append("| " + " | ".join(escape(v) for v in (
                o["obligation"], "; ".join(c["label"] for c in o["citations"]),
                STATUS_LABELS[o["status"]], evidence(o))) + " |")
            if o["conditions"]:
                lines.append("\nĐiều kiện: " + escape(" ".join(o["conditions"])) + "\n")
        return lines if entries else ["Chưa có."]

    meta, summary = report["meta"], report["summary"]
    lines = ["# Bản đánh giá tuân thủ", "", "## Thông tin chung", "",
             f"Thời điểm: {escape(meta['created'])}", f"Model: {escape(meta['model'])}",
             f"Phiên bản prompt: {escape(meta['prompt_version'])}",
             f"SHA-256 bảng nghĩa vụ: {escape(meta['table_sha256'])}",
             "Dữ kiện: " + escape(json.dumps(meta["facts"], ensure_ascii=False, sort_keys=True)), "",
             f"Đã đáp ứng {summary['da']}/{summary['total']} nghĩa vụ áp dụng", "",
             f"Nghĩa vụ có điều kiện: {summary['conditional_total']}", ""]
    if report.get("narrative"):
        lines.extend([escape(report["narrative"]), ""])
    lines.extend(["## Cảnh báo hành vi bị cấm", ""])
    for warning in report["warnings"]:
        lines.append(f"- {escape(warning['obligation'])} Bằng chứng: {escape('; '.join(warning['quotes']))}. Căn cứ: {escape('; '.join(c['label'] for c in warning['citations']))}")
        if warning["conditions"]:
            lines.append("  Điều kiện: " + escape(" ".join(warning["conditions"])))
    if not report["warnings"]:
        lines.append("Không phát hiện dấu hiệu từ thông tin đã cung cấp.")
    lines.extend(["", "## Nghĩa vụ áp dụng", ""])
    lines.extend(table([o for o in report["obligations"] if o["applicability"] == "ap_dung"]))
    lines.extend(["", "## Nghĩa vụ áp dụng có điều kiện", ""])
    # Mỗi bảng có điều kiện riêng để không làm ngắt bảng của nghĩa vụ kế tiếp.
    conditional = [o for o in report["obligations"] if o["applicability"] == "ap_dung_neu"]
    for o in conditional:
        lines.extend(table([o]))
    if not conditional:
        lines.append("Chưa có.")
    lines.extend(["", "## Việc cần làm", ""])
    for task in report["todo"]:
        suffix = (f" ({task['affected_rows']} dòng bị ảnh hưởng)" if task["type"] == "bo_sung_du_kien"
                  else f" [{task['row_id']}" + (f"/{task['criterion_id']}" if "criterion_id" in task else "") + "]")
        if task.get("deadline"):
            suffix += f"; Hạn: {task['deadline']}"
        lines.append("- " + escape(task["text"] + suffix))
    if not report["todo"]:
        lines.append("Chưa có.")
    lines.extend(["", "## Thông tin, hạn chuyển tiếp", ""])
    for entry in report["info"]:
        lines.append("- " + escape(entry["obligation"]) + "; Hạn: " + escape(entry["deadline"] or "Không nêu")
                     + "; Điều kiện: " + escape(" ".join(entry["conditions"]) or "Áp dụng")
                     + "; Căn cứ: " + escape("; ".join(c["label"] for c in entry["citations"])))
    if not report["info"]:
        lines.append("Chưa có.")
    return "\n".join(lines + ["", meta["disclaimer"], ""])
