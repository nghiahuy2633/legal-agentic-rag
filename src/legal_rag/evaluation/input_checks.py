"""Nạp và chấm bộ kiểm tra đầu vào; chỉ dùng trong đánh giá."""

import json
from pathlib import Path

from legal_rag.agent.profile import EMPTY_PROFILE


def load_input_checks(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [dict(row, text=row["text"] * row.get("repeat", 1) + row.get("suffix", ""))
            for row in rows]


def _score(rows, predictions):
    wrong, errors = [], []
    analysis_failed = []
    false_refusals = false_accepts = correct = 0
    positive = sum(row["should_retrieve"] for row in rows)
    scope_rows = [row for row in rows if "expected_scope" in row]
    scope_correct = 0
    for row in rows:
        result = predictions.get(row["id"], {})
        if result.get("analysis_ok") is False:
            analysis_failed.append(row["id"])
        failed = "error" in result or type(result.get("retrieve")) is not bool
        if failed:
            errors.append(row["id"])
        if not failed and result["retrieve"] == row["should_retrieve"]:
            correct += 1
        else:
            wrong.append(row["id"])
        if not failed:
            false_refusals += row["should_retrieve"] and not result["retrieve"]
            false_accepts += not row["should_retrieve"] and result["retrieve"]
            if "expected_scope" in row and result.get("scope") == row["expected_scope"]:
                scope_correct += 1
    negative = len(rows) - positive
    return {"n": len(rows), "correct": correct, "incorrect": len(wrong), "wrong_ids": wrong,
            "errors": len(errors), "error_ids": errors,
            "analysis_failed": len(analysis_failed), "analysis_failed_ids": analysis_failed,
            "false_refusal_rate": false_refusals / positive if positive else None,
            "false_accept_rate": false_accepts / negative if negative else None,
            "scope_match": {"n": len(scope_rows), "correct": scope_correct,
                            "rate": scope_correct / len(scope_rows) if scope_rows else None}}


def score_scope(rows, results):
    predictions = {result["id"]: result for result in results}
    return dict(_score(rows, predictions), by_kind={
        kind: _score([row for row in rows if row["kind"] == kind], predictions)
        for kind in dict.fromkeys(row["kind"] for row in rows)
    })


def score_profile(rows, results):
    """Chấm từng trường hồ sơ sau lượt; lỗi gọi LLM không vào mẫu số."""
    predictions = {result["id"]: result for result in results}
    fields = {key: dict(correct=0, wrong_value=0, guessed=0, missed=0)
              for key in EMPTY_PROFILE}
    error_ids, mistakes = [], []
    n = 0
    for row in rows:
        result = predictions.get(row["id"], {})
        if "error" in result or not isinstance(result.get("profile"), dict):
            error_ids.append(row["id"])
            continue
        n += 1
        for field, counts in fields.items():
            expected = row["expected_profile"].get(field)
            predicted = result["profile"].get(field)
            if field == "product_description":
                same = (expected is None) == (predicted is None)
            else:
                same = expected == predicted
            outcome = ("correct" if same else "guessed" if expected is None
                       else "missed" if predicted is None else "wrong_value")
            counts[outcome] += 1
            if outcome != "correct":
                mistakes.append(dict(id=row["id"], field=field, expected=expected,
                                     predicted=predicted))
    for field, counts in fields.items():
        counts["accuracy"] = counts["correct"] / n if n else None
        if field == "product_description":
            del counts["wrong_value"]
    return dict(n=n, fields=fields, mistakes=mistakes, errors=len(error_ids), error_ids=error_ids)
