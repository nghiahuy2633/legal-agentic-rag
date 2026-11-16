"""Đối chiếu mô tả với Danh mục, lưu trace để kiểm tra từng điều kiện."""

import argparse
import json
from pathlib import Path

from legal_rag.knowledge.high_risk import candidate_items, assess_items, render_assessment
from legal_rag.generation.trace import write_trace

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_data(root):
    return (read_jsonl(root / "data/processed/high_risk_list.jsonl"),
            read_jsonl(root / "data/processed/parents.jsonl"),
            read_jsonl(root / "data/processed/chunks.jsonl"))


def make_runtime(root, parents, chunks):
    # Nạp lười: đường dry-run không đọc cấu hình, không tạo model/client.
    from legal_rag.config import get_llm_settings
    from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient
    from legal_rag.retrieval.pipeline import RetrievalPipeline
    settings = get_llm_settings()
    fallback = getattr(settings, "fallback_models", ())
    client = HTTPChatClient(settings.base_url, settings.api_key, **({"max_attempts": 3} if fallback else {}))
    chat = FallbackChat(CachedChat(client, root / ".cache/llm"), fallback)
    return RetrievalPipeline(chunks, parents), chat, settings.model


def run_check(description, items, parents, pipeline, chat, model, trace_dir):
    record = dict(query=description, prompt_version="high_risk_v1")
    try:
        hits = pipeline.search(description)
        candidates = candidate_items(hits, items)
        record.update(hits=hits, candidates=[i["item_id"] for i in candidates])
        result = assess_items(description, candidates, chat, model)
        rendered = render_assessment(description, result, items, parents)
        record.update(assessment=result, rendered=rendered)
        return record
    except Exception:
        record["error"] = "Không thể đối chiếu; kiểm tra dữ liệu, cache và cấu hình."
        raise
    finally:
        write_trace(record, trace_dir)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--description", required=True)
    parser.add_argument("--trace-dir", type=Path, default=root / "runs/t22/traces")
    args = parser.parse_args(argv)
    if not args.description.strip():
        parser.error("--description không được rỗng")
    items, parents, chunks = load_data(root)
    pipeline, chat, model = make_runtime(root, parents, chunks)
    record = run_check(args.description, items, parents, pipeline, chat, model, args.trace_dir)
    print(record["rendered"]["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
