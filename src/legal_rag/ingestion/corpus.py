"""Trích đúng phần thân được registry cho phép, chỉ chuẩn hóa Unicode NFC."""

import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
import unicodedata

import pymupdf

from legal_rag.ingestion.ocr import page_cache_path, read_page_cache, recognize_page
from legal_rag.ingestion.registry import verify_pdf_hashes
from legal_rag.llm import FinishReasonError


class RequestPacer:
    """Chờ giữa từng lần gửi HTTP thật, kể cả retry; cache không đi qua đây."""

    def __init__(self, delay: float, sleep=None):
        if delay < 0:
            raise ValueError("delay không được âm")
        self.delay = delay
        self.sleep = sleep if sleep is not None else time.sleep
        self.called = False

    def __call__(self):
        if self.called:
            self.sleep(self.delay)
        self.called = True


def load_plan(root: Path) -> list[dict]:
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as source:
        documents = list(csv.DictReader(source))
    verify_pdf_hashes(documents, root)
    with (root / "data/processed/page_inventory.csv").open(encoding="utf-8", newline="") as source:
        inventory = {}
        for row in csv.DictReader(source):
            key = (row["document_id"], int(row["page"]))
            if key in inventory:
                raise ValueError(f"Inventory trùng trang: {key[0]} trang {key[1]}")
            inventory[key] = row["kind"]
    plan = []
    seen = set()
    for document in documents:
        document_id = document["document_id"]
        if document_id in seen:
            raise ValueError(f"Registry trùng văn bản: {document_id}")
        seen.add(document_id)
        last_page = int(document["body_last_page"])
        pdf = root / document["pdf_path"]
        with pymupdf.open(pdf) as source:
            if not 1 <= last_page <= len(source):
                raise ValueError(f"{document_id}: body_last_page ngoài PDF")
        pages = []
        for page in range(1, last_page + 1):
            kind = inventory.get((document_id, page))
            if kind not in ("scan", "text"):
                raise ValueError(f"{document_id} trang {page}: thiếu trang hoặc kind không hợp lệ trong inventory")
            pages.append((page, kind))
        plan.append({"document_id": document_id, "pdf": pdf, "pages": pages})
    return plan


def cache_counts(document, engine, cache_root):
    scans = [page for page, kind in document["pages"] if kind == "scan"]
    cached = sum(read_page_cache(page_cache_path(engine, document["pdf"], page,
                                                cache_root=cache_root)) is not None
                 for page in scans)
    return len(scans), cached


def _write_document(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=path.parent, prefix=path.name + ".", suffix=".tmp",
                                delete=False) as stream:
            temporary = Path(stream.name)
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


BLOCKED_COLUMNS = ("document_id", "page", "finish_reason", "model")


def _read_blocked(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(BLOCKED_COLUMNS):
            raise ValueError("ocr_blocked.csv không đúng các cột đã quy định")
        rows = {}
        for row in reader:
            if not row["finish_reason"].startswith("content_filter"):
                raise ValueError("ocr_blocked.csv chứa finish_reason không phải content_filter")
            rows[(row["document_id"], int(row["page"]), row["model"])] = row
        return rows


def _write_blocked(path: Path, blocked: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=BLOCKED_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for key in sorted(blocked):
                writer.writerow(blocked[key])
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _blocked_reason(error: FinishReasonError) -> str:
    message = str(error)
    if not message.startswith("finish_reason="):
        return ""
    return message.removeprefix("finish_reason=").partition(";")[0]


def _print_summary(plan, engine, cache_root, blocked, model, pdf_text_done, attempted, fallback_done=()):
    print("| Văn bản | Tổng trang | Có text | Bị chặn | Trang bị chặn | Lỗi OCR chưa có text | Chưa thử OCR |", flush=True)
    print("|---|---:|---:|---:|---|---:|---:|", flush=True)
    totals = [0, 0, 0, 0, 0]
    for document in plan:
        document_id = document["document_id"]
        scans = {page for page, kind in document["pages"] if kind == "scan"}
        cached = {page for page in scans if read_page_cache(page_cache_path(
            engine, document["pdf"], page, cache_root=cache_root)) is not None}
        cached |= {page for doc, page in fallback_done if doc == document_id and page in scans}
        blocked_pages = sorted(page for page in scans - cached
                               if (document_id, page, model) in blocked)
        with_text = len(cached) + sum((document_id, page) in pdf_text_done
                                     for page, kind in document["pages"] if kind == "text")
        unresolved = scans - cached - set(blocked_pages)
        failed = sum((document_id, page) in attempted for page in unresolved)
        untried = len(unresolved) - failed
        values = [len(document["pages"]), with_text, len(blocked_pages), failed, untried]
        totals = [a + b for a, b in zip(totals, values)]
        pages = ", ".join(map(str, blocked_pages)) or "—"
        print(f"| {document_id} | {values[0]} | {with_text} | {len(blocked_pages)} | {pages} | {failed} | {untried} |", flush=True)
    print(f"| Tổng | {totals[0]} | {totals[1]} | {totals[2]} | — | {totals[3]} | {totals[4]} |", flush=True)


def extract_corpus(engine, root: Path, *, dry_run=False, on_block="stop",
                   retry_blocked=False, model=None, no_api=False, fallback=None) -> None:
    """Trích corpus. Trang scan dùng `engine`; trang bị bộ lọc nội dung chặn dùng `fallback`
    (OCR cục bộ, thường là Tesseract) nếu có. Mỗi trang ghi engine đã đọc nó."""
    if on_block not in ("stop", "skip"):
        raise ValueError("on_block phải là stop hoặc skip")
    if on_block == "skip" and not model:
        raise ValueError("Cần tên model để ghi và đọc danh sách trang bị chặn")
    if retry_blocked and on_block != "skip":
        raise ValueError("retry_blocked cần on_block=skip")
    started = time.perf_counter()
    initial_calls = getattr(engine, "request_count", 0)
    cache_root = root / ".cache/ocr"
    plan = load_plan(root)
    blocked_path = root / "runs/ocr_blocked.csv"
    blocked = _read_blocked(blocked_path) if on_block == "skip" else {}
    if on_block == "skip" and not dry_run and not blocked_path.exists():
        _write_blocked(blocked_path, blocked)
    pdf_text_done = set()
    attempted = set()
    fallback_done = set()

    def read_fallback(pdf, page):
        result = recognize_page(fallback, pdf, page, cache_root=cache_root)
        return result.text, f"dự phòng {fallback.name}, cached={str(result.cached).lower()}"

    if dry_run:
        if no_api:
            total = cached_total = fallback_total = missing_total = 0
            for document in plan:
                scans, cached = cache_counts(document, engine, cache_root)
                fallback_count = scans - cached if fallback is not None else 0
                missing = scans - cached - fallback_count
                total += len(document["pages"])
                cached_total += cached
                fallback_total += fallback_count
                missing_total += missing
                print(f"{document['document_id']}: {len(document['pages'])} trang; cache={cached}; "
                      f"dự phòng={fallback_count}; thiếu={missing}; sẽ gọi API=0", flush=True)
            print(f"Tổng: {total} trang; cache={cached_total}; dự phòng={fallback_total}; "
                  f"thiếu={missing_total}; sẽ gọi API=0", flush=True)
            return
        total = scans_total = cached_total = skipped_total = 0
        for document in plan:
            scans, cached = cache_counts(document, engine, cache_root)
            count = len(document["pages"])
            skipped = sum(
                (document["document_id"], page, model) in blocked
                and read_page_cache(page_cache_path(engine, document["pdf"], page,
                                                    cache_root=cache_root)) is None
                for page, kind in document["pages"] if kind == "scan"
            ) if not retry_blocked else 0
            print(f"{document['document_id']}: {count} trang; pdf_text={count - scans}; "
                  f"cache={cached}; sẽ gọi API={scans - cached - skipped}; đã chặn={skipped}", flush=True)
            total += count
            scans_total += scans
            cached_total += cached
            skipped_total += skipped
        print(f"Tổng: {total} trang; OCR={scans_total}; pdf_text={total - scans_total}; "
              f"cache={cached_total}; sẽ gọi API={scans_total - cached_total - skipped_total}; đã chặn={skipped_total}", flush=True)
        return
    try:
        for document in plan:
            document_id, pdf = document["document_id"], document["pdf"]
            rows = []
            for page, kind in document["pages"]:
                print(f"Đang xử lý {document_id} trang {page}/{len(document['pages'])}", flush=True)
                try:
                    if kind == "scan":
                        if no_api:
                            text = read_page_cache(page_cache_path(engine, pdf, page,
                                                                  cache_root=cache_root))
                            if text is not None:
                                tool, detail = engine.name, "cached=true"
                            elif fallback is not None:
                                text, detail = read_fallback(pdf, page)
                                tool = fallback.name
                                fallback_done.add((document_id, page))
                            else:
                                raise RuntimeError(f"Thiếu cache {engine.name}; --no-api không gọi mạng")
                            rows.append({"document_id": document_id, "page": page, "source": "ocr",
                                         "engine": tool, "text": unicodedata.normalize("NFC", text)})
                            print(f"Xong {document_id} trang {page}: {detail}", flush=True)
                            continue
                        key = (document_id, page, model)
                        if key in blocked and not retry_blocked and read_page_cache(page_cache_path(
                            engine, pdf, page, cache_root=cache_root
                        )) is None:
                            if fallback is None:
                                print(f"Bỏ qua {document_id} trang {page}: đã ghi content_filter, model={model}", flush=True)
                                continue
                            text, detail = read_fallback(pdf, page)
                            fallback_done.add((document_id, page))
                            rows.append({"document_id": document_id, "page": page, "source": "ocr",
                                         "engine": fallback.name, "text": unicodedata.normalize("NFC", text)})
                            print(f"Xong {document_id} trang {page}: {detail}", flush=True)
                            continue
                        if read_page_cache(page_cache_path(engine, pdf, page,
                                                           cache_root=cache_root)) is None:
                            attempted.add((document_id, page))
                        result = recognize_page(engine, pdf, page, cache_root=cache_root)
                        if key in blocked:
                            del blocked[key]
                            _write_blocked(blocked_path, blocked)
                        text, source, tool = result.text, "ocr", engine.name
                        detail = f"cached={str(result.cached).lower()}"
                    else:
                        with pymupdf.open(pdf) as source_pdf:
                            text = source_pdf[page - 1].get_text()
                        source, tool, detail = "pdf_text", "pymupdf", "pdf_text"
                        pdf_text_done.add((document_id, page))
                    rows.append({"document_id": document_id, "page": page, "source": source,
                                 "engine": tool, "text": unicodedata.normalize("NFC", text)})
                    print(f"Xong {document_id} trang {page}: {detail}", flush=True)
                except FinishReasonError as error:
                    reason = _blocked_reason(error)
                    if not reason.startswith("content_filter") or (on_block != "skip" and fallback is None):
                        raise RuntimeError(f"{document_id} trang {page}: {error}") from None
                    blocked[(document_id, page, model)] = {
                        "document_id": document_id, "page": str(page),
                        "finish_reason": reason, "model": model,
                    }
                    _write_blocked(blocked_path, blocked)
                    print(f"Bị chặn {document_id} trang {page}: {reason}, model={model}", flush=True)
                    if fallback is not None:
                        try:
                            text, detail = read_fallback(pdf, page)
                        except (OSError, ValueError, RuntimeError) as fallback_error:
                            raise RuntimeError(f"{document_id} trang {page}: {fallback_error}") from None
                        fallback_done.add((document_id, page))
                        rows.append({"document_id": document_id, "page": page, "source": "ocr",
                                     "engine": fallback.name, "text": unicodedata.normalize("NFC", text)})
                        print(f"Xong {document_id} trang {page}: {detail}", flush=True)
                except (OSError, ValueError, RuntimeError) as error:
                    raise RuntimeError(f"{document_id} trang {page}: {error}") from None
            if len(rows) != len(document["pages"]):
                print(f"Không ghi JSONL {document_id}: chỉ có {len(rows)}/{len(document['pages'])} trang", flush=True)
                continue
            try:
                _write_document(root / "data/processed/text" / f"{document_id}.jsonl", rows)
            except OSError as error:
                raise RuntimeError(f"{document_id} trang {page}: không ghi được JSONL: {error}") from None
    except (OSError, ValueError, RuntimeError):
        for document in plan:
            scans, cached = cache_counts(document, engine, cache_root)
            done = sum(doc == document["document_id"] for doc, _ in fallback_done)
            print(f"Còn thiếu OCR {document['document_id']}: {scans - cached - done} trang", flush=True)
        raise
    finally:
        _print_summary(plan, engine, cache_root, blocked, model, pdf_text_done, attempted, fallback_done)
        calls = getattr(engine, "request_count", 0) - initial_calls
        print(f"Tổng số lần gọi API thật: {calls}", flush=True)
        print(f"Tổng thời gian: {time.perf_counter() - started:.3f} giây", flush=True)
