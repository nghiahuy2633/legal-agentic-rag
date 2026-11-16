"""Chạy bộ bẫy trích dẫn và kiểm lại trace, không gọi LLM."""

import argparse
import csv
import json
from pathlib import Path

from legal_rag.generation.citations import check_answer
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.locations import build_location_index, sentences

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def inspect_trace(record, parents, index, chunks):
    items = []
    for item in record["evidence"]:
        item = dict(item)
        if "document_id" not in item:
            item["document_id"] = (parents.get(item["parent_id"], {}).get("document_id")
                                   or item["parent_id"].split("_", 1)[0])
        items.append(item)
    check = check_answer(record["answer"], items, index, chunks)
    details = []
    for error in check["errors"]:
        # Chạy lại theo câu để gắn lỗi với câu gốc, giữ chỉ mục E ban đầu.
        matching = [s for s in sentences(record["answer"])
                    if error in check_answer(s, items, index, chunks)["errors"]]
        details.append(dict(error=error, sentences=matching or [record["answer"]]))
    return dict(check=check, details=details)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path)
    args = parser.parse_args(argv)
    parents = {p["parent_id"]: p for p in read_jsonl(root / "data/processed/parents.jsonl")}
    chunks = read_jsonl(root / "data/processed/chunks.jsonl")
    index = build_location_index(list(parents.values()), chunks)
    with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
        documents = list(csv.DictReader(stream))
    results = []
    for row in read_jsonl(root / "eval/citation_traps.jsonl"):
        items = build_evidence([parents[key] for key in row["parents"]], documents)
        check = check_answer(row["answer"], items, index, chunks)
        caught = not check["valid"]
        mismatch = (row["expect"] == "bat" and not caught) or (row["expect"] == "dat" and caught)
        results.append(dict(row, caught=caught, mismatch=mismatch, errors=check["errors"]))
    bat = [r for r in results if r["expect"] == "bat"]
    dat = [r for r in results if r["expect"] == "dat"]
    report = dict(bat=dict(caught=sum(r["caught"] for r in bat), total=len(bat)),
                  dat=dict(false_positives=sum(r["caught"] for r in dat), total=len(dat)),
                  chua_bat=[dict(id=r["id"], caught=r["caught"], errors=r["errors"])
                            for r in results if r["expect"] == "chua_bat"],
                  mismatches=[r for r in results if r["mismatch"]], results=results, traces=[])
    if args.traces:
        for path in sorted(args.traces.rglob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not isinstance(record.get("answer"), str) or not isinstance(record.get("evidence"), list):
                continue
            result = dict(path=str(path), **inspect_trace(record, parents, index, chunks))
            report["traces"].append(result)
            for detail in result["details"]:
                print(json.dumps(dict(path=str(path), **detail), ensure_ascii=False))
    output = root / "runs/t20a/traps.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("results", "traces")}, ensure_ascii=False, indent=2))
    return int(bool(report["mismatches"]))


if __name__ == "__main__":
    raise SystemExit(main())
