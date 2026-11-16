"""Sinh bản duyệt nghĩa vụ theo nhóm cùng toàn văn căn cứ, chờ người soát."""

import argparse
import json
from pathlib import Path
import sys

from legal_rag.knowledge.obligations import GROUPS, load_obligations, validate_citations
from legal_rag.knowledge.conditions import describe
from legal_rag.knowledge.coverage import candidate_units, coverage_report, load_exclusions


ROOT = Path(__file__).resolve().parents[1]


def render_review(rows: list[dict], chunks: dict[str, dict]) -> str:
    validate_citations(rows, chunks)
    lines = ["# Duyệt bảng nghĩa vụ nháp", "",
             "Đối chiếu căn cứ và trạng thái duyệt của từng dòng trước khi dùng.",
             "", "Ô dưới đây dành cho người duyệt; sinh lại file sẽ đặt lại các ô.", ""]
    sections = [("Cần người soát xem kỹ", [r for r in rows if "review_note" in r])]
    sections.extend((group, [r for r in rows if r["group"] == group and "review_note" not in r])
                    for group in GROUPS)
    for heading, section_rows in sections:
        lines.extend([f"## {heading}", ""])
        for row in sorted(section_rows, key=lambda r: r["id"]):
            lines.extend([f"### {row['id']}", "", "- [ ] Đã đối chiếu toàn bộ căn cứ",
                          "- [ ] Chấp nhận nội dung", "- Ghi chú/sửa đề nghị: ", "",
                          f"- Vai trò: `{row['role']}`",
                          f"- Mức rủi ro: `{row['risk_level']}`",
                          f"- Điều kiện: {row['condition'] or '(không có điều kiện riêng)'}",
                          f"- Nghĩa vụ: {row['obligation']}",
                          f"- Trạng thái: `{row['review_status']}`", ""])
            lines.extend([f"- Loại: `{row.get('kind', 'nghia_vu')}`",
                          f"- Áp dụng khi: {describe(row.get('applies_when'))}",
                          f"- Hạn: {row.get('deadline', '(chưa khai)')}",
                          f"- Người soát: {row.get('review_by', '(chưa khai)')}",
                          "- Tiêu chí đáp ứng:"])
            for index, criterion in enumerate(row.get("criteria", []), 1):
                lines.append(f"  {index}. `{criterion['id']}`: {criterion['text']}")
                lines.extend(f"     - Không đạt: {text}" for text in criterion.get("not_met", []))
            lines.append("")
            if "review_note" in row:
                lines.extend([f"- Nhóm: `{row['group']}`",
                              f"- Lưu ý cần soát: {row['review_note']}", ""])
            for citation in row["citations"]:
                chunk = chunks[citation["chunk_id"]]
                position = ", ".join(f"{label} {chunk[field]}" for field, label in
                                     (("article", "Điều"), ("clause", "Khoản"), ("point", "Điểm"))
                                     if chunk.get(field) is not None)
                lines.extend([f"**Căn cứ:** {chunk['document_number']} — {position}", "",
                              f"Mã chunk: `{chunk['chunk_id']}`", "",
                              f"Trích dẫn ngắn: {citation['quote']}", "", "Toàn văn body:", ""])
                lines.extend("> " + line for line in chunk["body"].splitlines())
                lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", action="store_true", help="In độ phủ dạng JSON UTF-8")
    parser.add_argument("--level", choices=("clause", "point"), default="clause")
    args = parser.parse_args(argv)
    try:
        rows = load_obligations(root / "src/legal_rag/knowledge/obligations.yaml")
        with (root / "data/processed/chunks.jsonl").open(encoding="utf-8") as stream:
            chunks = {chunk["chunk_id"]: chunk for line in stream if line.strip()
                      for chunk in [json.loads(line)]}
        if args.coverage:
            exclusions = load_exclusions(root / "src/legal_rag/knowledge/coverage_exclusions.yaml",
                                         candidate_units(chunks))
            print(json.dumps(coverage_report(rows, chunks, exclusions, level=args.level), ensure_ascii=False, indent=2))
            return 0
        content = render_review(rows, chunks)
        output = root / "runs/obligations-review.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content.encode("utf-8"))
        print(f"Đã ghi runs/obligations-review.md: {len(rows)} dòng, "
              f"{len({row['group'] for row in rows})} nhóm; xem trạng thái duyệt từng dòng.")
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
