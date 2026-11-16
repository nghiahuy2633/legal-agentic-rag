"""Tạo chunks, parents, references từ articles và registry, ghi nguyên tử qua file tạm."""

import argparse
import csv
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from legal_rag.ingestion.chunking import build_outputs


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ("chunks", "parents", "references")


def _read_articles(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlap-sentences", type=int, default=0)
    args = parser.parse_args(argv)
    temporary = []
    try:
        with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as source:
            documents = list(csv.DictReader(source))
        folder = root / "data/processed/articles"
        articles = {}
        for document in documents:
            path = folder / f"{document['document_id']}.jsonl"
            if path.exists():
                articles[document["document_id"]] = _read_articles(path)
            else:
                print(f"Bỏ qua {document['document_id']}: chưa có articles")
        if not articles:
            raise ValueError("Không có văn bản nào trong data/processed/articles")
        supplements = {doc: _read_articles(folder / f"{doc}.appendices.jsonl") for doc in articles
                       if (folder / f"{doc}.appendices.jsonl").exists()}
        risk_path = root / "data/processed/high_risk_list.jsonl"
        result = build_outputs(documents, articles, args.overlap_sentences,
                               supplements=supplements,
                               high_risk_items=_read_articles(risk_path) if risk_path.exists() else [])
        target_folder = root / "data/processed"
        for name in OUTPUTS:
            target = target_folder / f"{name}.jsonl"
            with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=target_folder,
                                    prefix=target.name + ".", suffix=".tmp", delete=False) as stream:
                temporary.append((Path(stream.name), target))
                for row in result[name]:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        for path, target in temporary:
            path.replace(target)
        resolved = sum(row["resolved"] for row in result["references"])
        print(f"{len(articles)} văn bản: {len(result['chunks'])} chunk, {len(result['parents'])} parent, "
              f"{result['split_count']} đơn vị bị tách, {resolved} dẫn chiếu giải được, "
              f"{len(result['references']) - resolved} không giải được")
    except (OSError, ValueError, KeyError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    finally:
        for path, _ in temporary:
            path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
