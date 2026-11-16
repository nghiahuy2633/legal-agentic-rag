"""Kiểm độ phủ offline hoặc chạy bộ tình huống Danh mục với LLM."""

import argparse
from collections import Counter
import json

from check_high_risk import ROOT, load_data, make_runtime, read_jsonl, run_check
from legal_rag.knowledge.high_risk import BULLET, FIXED_PARENTS, PREFIX, split_conditions, render_assessment


def coverage(items, parents):
    registry = {p["parent_id"]: p for p in parents}
    counts = Counter()
    passed, errors = 0, []
    for item in items:
        try:
            split = split_conditions(item)
            restored = " ".join([split["lead"], *split["conditions"]])
            assert " ".join(restored.split()) == " ".join(BULLET.sub("", item["description"]).split())
            fake = dict(items=[dict(item_id=item["item_id"], conditions=[
                dict(index=i, status="chua_ro", basis=None) for i in range(1, len(split["conditions"]) + 1)])])
            rendered = render_assessment("Mô tả giả để kiểm tra độ phủ", fake, items, registry)
            assert item["item_id"] in rendered["parent_ids"]
            assert all(key in rendered["parent_ids"] for key in FIXED_PARENTS)
            point = {"diem_a": "a", "diem_b": "b"}[item["conformity"]]
            note = f"Đánh giá sự phù hợp theo điểm {point}, khoản 2 Điều 13 Luật Trí tuệ nhân tạo"
            assert registry[item["item_id"]]["context"].splitlines()[-1] == note
            assert note in rendered["text"]
            counts[item["conformity"]] += 1
            passed += 1
        except (AssertionError, KeyError, ValueError) as error:
            errors.append(dict(item_id=item["item_id"], error=type(error).__name__))
    return dict(passed=passed, total=len(items), conformity=dict(counts),
                fixed_parents=sum(key in registry for key in FIXED_PARENTS), errors=errors)


def main(argv=None, root=ROOT, runtime_factory=make_runtime):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cases = read_jsonl(root / "eval/high_risk_cases.jsonl")
    items, parents, chunks = load_data(root)
    # Kiểm tất cả nhãn ứng viên chạm được từ chunk thật trước khi chạy đo.
    available = {i["item_id"] for i in items} & {c["chunk_id"] for c in chunks}
    missing = sorted({PREFIX + key for case in cases for key in case["expect_items"]} - available)
    if missing:
        raise ValueError("Nhãn không chạm được: " + ", ".join(missing))
    covered = coverage(items, parents)
    print(f'Độ phủ: {covered["passed"]}/{covered["total"]} mục; '
          f'diem_a={covered["conformity"].get("diem_a", 0)}, diem_b={covered["conformity"].get("diem_b", 0)}; '
          f'parent cố định={covered["fixed_parents"]}/3')
    print(json.dumps(dict(cases=len(cases), reachable_labels=len({key for c in cases for key in c["expect_items"]}),
                          coverage=covered), ensure_ascii=False))
    if args.dry_run:
        return 0
    if covered["errors"]:
        raise ValueError("Độ phủ chưa đạt; dừng trước phép đo.")
    pipeline, chat, model = runtime_factory(root, parents, chunks)
    results = []
    for case in cases:
        row = dict(case, status_correct=False, items_correct=None, assessment=None)
        try:
            record = run_check(case["description"], items, parents, pipeline, chat, model, root / "runs/t22/traces")
            candidates = record["candidates"]
            row.update(actual_status=record["rendered"]["status"], candidates=candidates,
                       assessment=record["assessment"])
            row["status_correct"] = (record["assessment"]["assess_ok"]
                                     and row["actual_status"] in case["expect_status"])
            if case["expect_items"]:
                row["items_correct"] = any(PREFIX + key in candidates for key in case["expect_items"])
        except (OSError, ValueError, KeyError, RuntimeError):
            row["error"] = "Không thể đối chiếu; xem trace và cấu hình."
            if case["expect_items"]:
                row["items_correct"] = False
        results.append(row)
    report = dict(status_correct=sum(r["status_correct"] for r in results), total=len(results),
                  items_correct=sum(r["items_correct"] is True for r in results),
                  items_total=sum(bool(r["expect_items"]) for r in results), coverage=covered,
                  mismatches=[r for r in results if not r["status_correct"] or r["items_correct"] is False],
                  results=results)
    output = root / "runs/t22/high_risk.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
