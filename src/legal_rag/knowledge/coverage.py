"""Độ phủ các khoản có dấu hiệu nghĩa vụ trong tập Điều cốt lõi."""

from pathlib import Path
import re
import unicodedata

import yaml

from legal_rag.retrieval.context import clause_unit


CORE_ARTICLES = {
    "134-2025-QH15": ("7", "10", "11", "12", "13", "14", "15", "27", "35"),
    "142-2026-ND-CP": tuple(map(str, range(6, 21))) + ("46",),
    "33-2026-QD-TTg": ("4",),
}
OBLIGATION_PATTERN = re.compile(
    r"\b(?:phải|có trách nhiệm|có nghĩa vụ|nghiêm cấm|không được)\b", re.IGNORECASE)


def candidate_clauses(chunks):
    values = chunks.values() if isinstance(chunks, dict) else chunks
    return list(dict.fromkeys(clause_unit(chunk) for chunk in values
        if str(chunk.get("article")) in CORE_ARTICLES.get(chunk.get("document_id"), ())
        and OBLIGATION_PATTERN.search(unicodedata.normalize("NFC", chunk["body"]))))


def point_unit(chunk):
    match = re.match(r"(.*_diem-[^_]+)", chunk["chunk_id"])
    return match[1] if match else None


def candidate_units(chunks):
    values = list(chunks.values() if isinstance(chunks, dict) else chunks)
    candidates = candidate_clauses(values)
    introductions = {clause_unit(c) for c in values if point_unit(c) is None
                     and c.get("level", "clause") == "clause"
                     and not re.search(r"_cuoi(?:_|$)", c["chunk_id"])
                     and OBLIGATION_PATTERN.search(unicodedata.normalize("NFC", c["body"]))}
    for chunk in values:
        unit = point_unit(chunk)
        if (unit and str(chunk.get("article")) in CORE_ARTICLES.get(chunk.get("document_id"), ())
                and (clause_unit(chunk) in introductions or OBLIGATION_PATTERN.search(
                    unicodedata.normalize("NFC", chunk["body"])))):
            candidates.append(unit)
    return list(dict.fromkeys(candidates))


def _validate_exclusions(exclusions, candidates):
    if not isinstance(exclusions, list):
        raise ValueError("Loại trừ phải là danh sách")
    seen = set()
    for index, item in enumerate(exclusions):
        if not isinstance(item, dict) or set(item) != {"clause_id", "reason"}:
            raise ValueError(f"exclusions[{index}]: cần clause_id và reason")
        cid, reason = item["clause_id"], item["reason"]
        if not isinstance(cid, str) or cid not in candidates:
            raise ValueError(f"exclusions[{index}].clause_id: không phải ứng viên")
        if cid in seen:
            raise ValueError(f"exclusions[{index}].clause_id: trùng {cid}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"exclusions[{index}].reason: phải không rỗng")
        seen.add(cid)
    return seen


def load_exclusions(path, candidates):
    try:
        exclusions = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"YAML loại trừ không hợp lệ: {error}") from error
    _validate_exclusions(exclusions, candidates)
    return exclusions


def coverage_report(rows, chunks, exclusions, level="clause"):
    if level not in ("clause", "point"):
        raise ValueError("level phải là clause hoặc point")
    chunks = chunks if isinstance(chunks, dict) else {c["chunk_id"]: c for c in chunks}
    all_candidates = candidate_units(chunks)
    candidates = candidate_clauses(chunks) if level == "clause" else all_candidates
    excluded_ids = _validate_exclusions(exclusions, all_candidates)
    cited = set()
    for row in rows:
        if row["review_status"] == "user_rejected":
            continue
        for citation in row["citations"]:
            cid = citation["chunk_id"]
            if cid not in chunks:
                raise ValueError(f"{row['id']}: chunk_id không tồn tại: {cid}")
            cited.add(clause_unit(chunks[cid]))
            if level == "point" and point_unit(chunks[cid]):
                cited.add(point_unit(chunks[cid]))
    covered = [cid for cid in candidates if cid in cited]
    # Khoản đã có căn cứ chỉ đếm một lần, kể cả nằm trong file loại trừ.
    excluded = [cid for cid in candidates if cid in excluded_ids and cid not in cited]
    missing = [cid for cid in candidates if cid not in cited and cid not in excluded_ids]
    return dict(candidates=candidates, covered=covered, excluded=excluded, missing=missing,
                rate=(len(covered) + len(excluded)) / len(candidates) if candidates else 1.0)
