"""Nhãn câu trả lời, phán quyết được cache và thống kê ghép cặp."""

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
import random
import re
import unicodedata

from legal_rag.llm import LLMError
from legal_rag.generation.citations import BRACKET, MARKER_GROUP

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts/judge_v2.txt"
VERSION = "judge_v2"
COVERAGE_THRESHOLD = 0.5
SEED = 23


def cited_codes(answer):
    codes = set()
    for content in BRACKET.findall(answer.lower()):
        if MARKER_GROUP.fullmatch(content.strip()):
            codes.update(code.upper() for code in re.findall(r"e\d+", content))
    return codes


def load_answers(path, parents_path=None):
    path = Path(path)
    parents_path = (Path(parents_path) if parents_path is not None else
                    path.parent.parent / "data/processed/parents.jsonl")
    rows, ids = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise ValueError(f"id=<dòng {number}>: trường JSON không hợp lệ") from error
        ident = row.get("id", f"<dòng {number}>") if isinstance(row, dict) else f"<dòng {number}>"
        for field in ("id", "question", "reference_answer", "expected_behavior", "review_status"):
            if not isinstance(row, dict) or not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"id={ident}: trường {field} phải là chuỗi không rỗng")
        for field in ("required_points", "gold_parents"):
            value = row.get(field)
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError(f"id={ident}: trường {field} phải là danh sách chuỗi không rỗng")
        if ident in ids:
            raise ValueError(f"id={ident}: trường id bị trùng")
        ids.add(ident)
        rows.append(row)
    parents = {parent["parent_id"]: parent for line in
               parents_path.read_text(encoding="utf-8").splitlines() if line.strip()
               for parent in [json.loads(line)]}
    for row in rows:
        for parent in row["gold_parents"]:
            if parent not in parents:
                raise ValueError(f"id={row['id']}: trường gold_parents không chạm được: {parent}")
        if "review_note" in row and (not isinstance(row["review_note"], str)
                                     or not row["review_note"].strip()):
            raise ValueError(f"id={row['id']}: trường review_note phải là chuỗi không rỗng")
        if "point_sources" in row:
            _validate_point_sources(row, parents)
    return rows


def normalize_quote(text):
    """So khớp nguyên văn sau NFC và gộp mọi khoảng trắng."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _validate_point_sources(row, parents):
    def invalid(message):
        raise ValueError(f"id={row['id']}: trường point_sources {message}")

    sources = row["point_sources"]
    points = row["required_points"]
    if (not isinstance(sources, list) or len(sources) != len(points)
            or len(set(points)) != len(points)):
        invalid("phải có đúng một phần tử cho mỗi ý bắt buộc")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            invalid("phải gồm các đối tượng")
        point = source.get("point")
        if not isinstance(point, str) or point not in points or point in seen:
            invalid("point thừa, trùng hoặc không khớp required_points")
        seen.add(point)
        if "parent_id" not in source or "quote" not in source:
            invalid("thiếu parent_id hoặc quote")
        parent, quote = source["parent_id"], source["quote"]
        if parent is None or quote is None:
            reason = source.get("absence_reason")
            if (parent is not None or quote is not None
                    or not isinstance(reason, str) or not reason.strip()):
                invalid("null phải đồng thời có parent_id, quote null và absence_reason không rỗng")
        else:
            if not isinstance(parent, str) or parent not in parents:
                invalid(f"parent_id không tồn tại: {parent}")
            if (not isinstance(quote, str) or not normalize_quote(quote)
                    or normalize_quote(quote) not in normalize_quote(parents[parent].get("text", ""))):
                invalid(f"quote không khớp parent_id={parent}")


def judgment_key(row, result, model=None, version=VERSION):
    content = [result.get("answer", ""), row["reference_answer"], version]
    if version != "judge_v1":
        content.append(model if model is not None else requested_judge_model(result))
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()


def requested_judge_model(result):
    return os.environ.get("RAG_JUDGE_MODEL", "").strip() or result.get("model") or os.environ.get("RAG_LLM_MODEL", "").strip()


def answer_key(row, result):
    content = [result.get("answer", ""), row["reference_answer"], VERSION]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()


def find_judgment(row, result, judgments):
    """Chấm điểm không phụ thuộc biến môi trường: ưu tiên model đang yêu cầu, rồi phán quyết đã lưu."""
    value = judgments.get(judgment_key(row, result))
    if value is not None:
        return value
    target = answer_key(row, result)
    stored = [item for item in judgments.values() if item.get("answer_key") == target]
    valid = [item for item in stored if valid_judgment(item, row)]
    if valid or stored:
        return (valid or stored)[-1]
    old = judgments.get(judgment_key(row, result, version="judge_v1"))
    return old if old is not None and old.get("judge_version", "judge_v1") == "judge_v1" else None


def valid_judgment(value, row):
    if not isinstance(value, dict) or value.get("judge_error"):
        return False
    issues = value.get("citation_issues")
    if value.get("judge_version") == "judge_v2" or "citation_issues" in value:
        if not isinstance(issues, list) or any(
                not isinstance(issue, dict) or set(issue) != {"code", "reason"}
                or not isinstance(issue["code"], str) or not re.fullmatch(r"E\d+(?:\.[a-zđ])?", issue["code"])
                or not isinstance(issue["reason"], str) or not issue["reason"].strip()
                for issue in issues):
            return False
    points = value.get("points")
    return (type(value.get("meaning_ok")) is bool
            and type(value.get("citations_relevant")) is bool
            and type(value.get("unsupported_claims")) is int and value["unsupported_claims"] >= 0
            and isinstance(value.get("reason"), str)
            and isinstance(points, list) and len(points) == len(row["required_points"])
            and all(isinstance(p, dict) and p.get("point") == point
                    and type(p.get("covered")) is bool
                    for p, point in zip(points, row["required_points"])))


def judge_answer(row, result, chat, model):
    key = judgment_key(row, result, model)
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        if prompt.splitlines()[0] != f"Phiên bản: {VERSION}":
            raise ValueError("Sai phiên bản prompt chấm")
        codes = cited_codes(result.get("answer", ""))
        data = dict(question=row["question"], answer=result.get("answer", ""),
                    reference_answer=row["reference_answer"], required_points=row["required_points"],
                    evidence=[item for item in result.get("evidence", []) if item.get("id") in codes])
        payload = dict(model=model, temperature=0, response_format={"type": "json_object"}, messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)}])
        value = json.loads(chat.complete(payload))
        if isinstance(value, dict):
            value["judge_version"] = VERSION
        if not valid_judgment(value, row):
            raise ValueError("Sai schema phán quyết")
        return dict(value, key=key, answer_key=answer_key(row, result), id=row["id"],
                    judge_model=getattr(chat, "last_model", None) or model)
    except (ValueError, TypeError, OSError, LLMError) as error:
        return dict(key=key, answer_key=answer_key(row, result), id=row["id"], judge_model=model,
                    judge_version=VERSION, judge_error=str(error),
                    http_status=getattr(error, "status", None), judge_retryable=isinstance(error, LLMError))


def _mean(values):
    return sum(values) / len(values) if values else None


def bootstrap(values):
    """Khoảng phần trăm 95%, 2000 mẫu, seed cố định; rỗng trả null."""
    if not values:
        return None
    rng = random.Random(SEED)
    samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000))
    # Phân vị nội suy tuyến tính, không cần thư viện bổ sung.
    def percentile(p):
        position = (len(samples) - 1) * p
        index = int(position)
        return samples[index] + (samples[min(index + 1, len(samples) - 1)] - samples[index]) * (position - index)
    return [percentile(.025), percentile(.975)]


def _indexed(rows):
    return rows if isinstance(rows, dict) else {row["id"]: row for row in rows}


def score_answers(rows, results, judgments):
    predictions = _indexed(results)
    judgments = judgments if isinstance(judgments, dict) else {j["key"]: j for j in judgments}
    samples = {}
    errors, missing, judge_errors, missing_judgments = [], [], [], []
    inconsistent, issues, invalid = [], [], []
    versions, models = Counter(), Counter()
    for row in rows:
        ident = row["id"]
        result = predictions.get(ident)
        metrics = dict.fromkeys(("correct", "correct_covered", "meaning_ok", "citation_rule",
                                 "citation_relevant", "required_points", "citation_valid", "unsupported_claims"), 0)
        if result is not None and (result.get("verification") or {}).get("final_valid") is False:
            invalid.append(ident)
        if result is None:
            missing.append(ident)
        elif result.get("error"):
            errors.append(ident)
        else:
            judge = find_judgment(row, result, judgments)
            if judge is None:
                missing_judgments.append(ident)
            elif not valid_judgment(judge, row):
                judge_errors.append(ident)
            else:
                versions[judge.get("judge_version", "judge_v1")] += 1
                models[judge.get("judge_model") or "không rõ"] += 1
                rule = bool(cited_codes(result.get("answer", ""))) and (result.get("check") or {}).get("valid") is True
                citation = rule and judge["citations_relevant"]
                coverage = _mean([int(p["covered"]) for p in judge["points"]]) if judge["points"] else 0
                covered = not row["required_points"] or coverage >= COVERAGE_THRESHOLD
                correct = judge["meaning_ok"] and citation
                metrics.update(correct=int(correct), correct_covered=int(correct and covered),
                               meaning_ok=int(judge["meaning_ok"]), citation_rule=int(rule),
                               citation_relevant=int(judge["citations_relevant"]), citation_valid=int(citation),
                               required_points=coverage, unsupported_claims=judge["unsupported_claims"])
                if judge["meaning_ok"] and not covered:
                    inconsistent.append(ident)
                if judge.get("citation_issues"):
                    issues.append(ident)
        samples[ident] = metrics
    names = dict(correct="correct_rate", required_points="required_points_rate",
                 citation_valid="citation_valid_rate", unsupported_claims="unsupported_claims_mean",
                 meaning_ok="meaning_ok_rate", citation_rule="citation_rule_rate",
                 citation_relevant="citation_relevant_rate", correct_covered="correct_covered_rate")
    output = dict(n=len(rows), errors=len(errors), error_ids=errors, missing_results=len(missing),
                  missing_result_ids=missing, judge_errors=len(judge_errors),
                  judge_error_ids=judge_errors, missing_judgments=len(missing_judgments),
                  missing_judgment_ids=missing_judgments, inconsistent_ids=inconsistent,
                  citation_issue_ids=issues, final_invalid_ids=invalid,
                  judge_versions=dict(sorted(versions.items())), judge_models=dict(sorted(models.items())),
                  samples=samples, confidence_intervals={})
    for field, name in names.items():
        values = [m[field] for m in samples.values()]
        output[name] = _mean(values)
        output["confidence_intervals"][name] = bootstrap(values)
    return output


def compare(a, b):
    """Hiệu a - b theo câu, cùng tập ID; không ghép các tập khác nhau."""
    if set(a["samples"]) != set(b["samples"]):
        raise ValueError("So sánh cần cùng tập id")
    metrics = {}
    for field in ("correct", "correct_covered", "required_points"):
        differences = [a["samples"][ident][field] - b["samples"][ident][field]
                       for ident in sorted(a["samples"])]
        interval = bootstrap(differences)
        overlaps = interval[0] <= 0 <= interval[1] if interval is not None else None
        metrics[field] = dict(n=len(differences), difference=_mean(differences), confidence_interval=interval,
                             overlaps_zero=overlaps,
                             conclusion="chưa đủ để kết luận" if overlaps is not False else "khoảng tin cậy không chồng lấn 0")
    return dict(metrics["correct"], metrics=metrics)
