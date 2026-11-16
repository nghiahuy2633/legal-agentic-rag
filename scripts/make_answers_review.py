"""Xuất bản duyệt nháp T27 từ nhãn và corpus, không gọi hệ thống sinh."""

import argparse
import json
from pathlib import Path

from legal_rag.evaluation.answers import load_answers


ROOT = Path(__file__).resolve().parents[1]


def render_review(rows, parents):
    lines = ["# Duyệt bộ câu chấm nháp T27", "",
             "Trạng thái: ai_draft — chưa được người duyệt; số liệu chấm chỉ là sơ bộ.", "",
             "Các câu có ghi chú cần soát được đặt trước, giữ thứ tự đầu vào trong mỗi nhóm.", ""]
    for row in sorted(rows, key=lambda row: not bool(row.get("review_note"))):
        lines.extend([f"## {row['id']}", "", f"**Câu hỏi:** {row['question']}", "",
                      f"**Câu tham chiếu:** {row['reference_answer']}", "",
                      f"**Hành vi mong đợi:** {row['expected_behavior']}", ""])
        if row.get("review_note"):
            lines.extend([f"**Cần người soát:** {row['review_note']}", ""])
        sources = {source["point"]: source for source in row.get("point_sources", [])}
        for number, point in enumerate(row["required_points"], 1):
            lines.extend([f"### Ý {number}", "", point, ""])
            source = sources.get(point)
            if source is None:
                lines.extend(["Chưa có point_sources cho ý này.", ""])
            elif source["parent_id"] is None:
                lines.extend(["**Căn cứ:** Không có trích đoạn khẳng định nội dung vắng mặt.", "",
                              f"**Phạm vi đã tìm:** {source['absence_reason']}", ""])
            else:
                parent = parents[source["parent_id"]]
                # Context của corpus đã chứa tên và số hiệu văn bản, kể cả mục Danh mục.
                location = [parent.get("context", "").split("\n")[0]
                            or parent["document_id"]]
                if parent.get("article"):
                    location.append(f"Điều {parent['article']}")
                if parent.get("clause"):
                    location.append(f"Khoản {parent['clause']}")
                location.append(parent["parent_id"])
                lines.extend(["**Căn cứ:** " + " — ".join(location), "",
                              "**Nguyên văn quote:**", ""])
                lines.extend("> " + line for line in source["quote"].splitlines())
                lines.append("")
            lines.extend(["- [ ] Duyệt ý và căn cứ", "- [ ] Cần sửa", "", "Ghi chú: …", ""])
        lines.extend(["- [ ] Duyệt toàn câu", "", "Người duyệt: …", "", "Ghi chú chung: …", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, default=ROOT / "eval/answers.jsonl")
    parser.add_argument("--parents", type=Path, default=ROOT / "data/processed/parents.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/answers-review.md")
    args = parser.parse_args(argv)
    rows = load_answers(args.answers, args.parents)
    parents = {parent["parent_id"]: parent for line in
               args.parents.read_text(encoding="utf-8").splitlines() if line.strip()
               for parent in [json.loads(line)]}
    content = render_review(rows, parents)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8", newline="\n")
    print(f"Đã ghi {len(rows)} câu vào {args.output.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
