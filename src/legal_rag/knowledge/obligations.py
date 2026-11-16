"""Đọc bảng nghĩa vụ và kiểm tra cấu trúc trước khi đưa cho người soát."""

from pathlib import Path
import unicodedata
import re

import yaml

from legal_rag.knowledge.conditions import validate_condition


GROUPS = (
    "cam", "phan_loai_thong_bao", "minh_bach", "su_co", "danh_gia_phu_hop",
    "quan_ly_rui_ro_cao", "nuoc_ngoai", "khu_vuc_cong", "chuyen_tiep",
)
ROLES = (
    "nha_phat_trien", "nha_cung_cap", "ben_trien_khai", "nguoi_su_dung",
    "co_quan_nha_nuoc", "moi_vai_tro",
)
RISK_LEVELS = ("cao", "trung_binh", "thap", "moi_muc")
REVIEW_STATUSES = ("ai_draft", "ai_reviewed", "user_reviewed", "user_rejected")
FIELDS = {"id", "group", "role", "risk_level", "condition", "obligation",
          "citations", "review_status"}
OPTIONAL_FIELDS = {"review_note", "kind", "applies_when", "criteria", "deadline", "review_by"}


def normalize_quote(text: str) -> str:
    """Chuẩn hóa NFC và gộp khoảng trắng để đối chiếu trích dẫn."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def load_obligations(path: str | Path) -> list[dict]:
    """Đọc YAML UTF-8; schema sai gây ValueError kèm dòng và tên trường.

    Hàm chỉ kiểm tra schema. Kiểm tra căn cứ corpus được thực hiện riêng,
    không phụ thuộc vị trí corpus khi nạp bảng.
    """
    try:
        rows = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"YAML không hợp lệ: {error}") from error
    if not isinstance(rows, list) or not rows:
        raise ValueError("Bảng nghĩa vụ phải là danh sách không rỗng")
    ids = set()
    for number, row in enumerate(rows, 1):
        prefix = f"Dòng {number}"
        if (not isinstance(row, dict) or not FIELDS <= set(row)
                or set(row) - FIELDS - OPTIONAL_FIELDS):
            raise ValueError(f"{prefix}: các trường phải đúng {sorted(FIELDS)}")
        for field in (FIELDS | (set(row) & OPTIONAL_FIELDS)) - {
                "citations", "criteria", "applies_when"}:
            value = row[field]
            if not isinstance(value, str) or (field != "condition" and not value.strip()):
                raise ValueError(f"{prefix}.{field}: phải là chuỗi" +
                                 ("" if field == "condition" else " không rỗng"))
        for field, allowed in (("group", GROUPS), ("role", ROLES),
                               ("risk_level", RISK_LEVELS),
                               ("review_status", REVIEW_STATUSES)):
            if row[field] not in allowed:
                raise ValueError(f"{prefix}.{field}: {row[field]!r} không thuộc {allowed}")
        if row["id"] in ids:
            raise ValueError(f"{prefix}.id: trùng {row['id']!r}")
        ids.add(row["id"])
        row.setdefault("kind", "nghia_vu")
        if row["kind"] not in ("nghia_vu", "cam", "thong_tin"):
            raise ValueError(f"{prefix}.kind: giá trị không hợp lệ")
        if "review_by" in row and row["review_by"] not in ("user", "ai"):
            raise ValueError(f"{prefix}.review_by: phải là user hoặc ai")
        validate_condition(row.get("applies_when"), f"{prefix}.applies_when")
        if "criteria" in row:
            if not isinstance(row["criteria"], list):
                raise ValueError(f"{prefix}.criteria: phải là danh sách")
            criterion_ids = set()
            for index, criterion in enumerate(row["criteria"]):
                label = f"{prefix}.criteria[{index}]"
                if (not isinstance(criterion, dict) or not {"id", "text"} <= criterion.keys()
                        or criterion.keys() - {"id", "text", "not_met"}):
                    raise ValueError(f"{label}: sai các trường tiêu chí")
                cid = criterion["id"]
                if not isinstance(cid, str) or not re.fullmatch(r"c[1-9][0-9]*", cid):
                    raise ValueError(f"{label}.id: phải có dạng c1, c2...")
                if cid in criterion_ids:
                    raise ValueError(f"{label}.id: trùng {cid}")
                criterion_ids.add(cid)
                if not isinstance(criterion["text"], str) or not criterion["text"].strip():
                    raise ValueError(f"{label}.text: phải là chuỗi không rỗng")
                if "not_met" in criterion and (not isinstance(criterion["not_met"], list)
                        or any(not isinstance(v, str) or not v.strip() for v in criterion["not_met"])):
                    raise ValueError(f"{label}.not_met: phải là danh sách chuỗi không rỗng")
        if any(term in normalize_quote(row["obligation"]).casefold()
               for term in ("điều này", "khoản này", "luật này")):
            raise ValueError(f"{prefix}.obligation: phải ghi rõ văn bản và vị trí dẫn chiếu")
        if not isinstance(row["citations"], list) or not row["citations"]:
            raise ValueError(f"{prefix}.citations: phải là danh sách không rỗng")
        for index, citation in enumerate(row["citations"], 1):
            label = f"{prefix}.citations[{index}]"
            if not isinstance(citation, dict) or set(citation) != {"chunk_id", "quote"}:
                raise ValueError(f"{label}: phải có đúng chunk_id và quote")
            for field in ("chunk_id", "quote"):
                if not isinstance(citation[field], str) or not citation[field].strip():
                    raise ValueError(f"{label}.{field}: phải là chuỗi không rỗng")
    return rows


def missing_criteria(rows):
    """Liệt kê dòng đã duyệt cần bổ sung tiêu chí, không chặn bảng cũ."""
    return [row["id"] for row in rows
            if row["review_status"] in ("ai_reviewed", "user_reviewed")
            and row.get("kind", "nghia_vu") != "thong_tin" and not row.get("criteria")]


def validate_citations(rows: list[dict], chunks: dict[str, dict]) -> None:
    """Kiểm tra mọi mã chunk và nguyên văn, báo lỗi tại nghĩa vụ liên quan."""
    for row in rows:
        for citation in row["citations"]:
            chunk_id = citation["chunk_id"]
            if chunk_id not in chunks:
                raise ValueError(f"{row['id']}: chunk_id không tồn tại: {chunk_id}")
            quote = normalize_quote(citation["quote"])
            if not quote or quote not in normalize_quote(chunks[chunk_id]["body"]):
                raise ValueError(f"{row['id']}: quote không thuộc body của {chunk_id}")
