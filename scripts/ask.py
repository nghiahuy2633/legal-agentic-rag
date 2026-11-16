"""Hỏi một lượt với bằng chứng và kiểm tra trích dẫn."""

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter

from legal_rag.config import get_llm_settings
from legal_rag.generation.citations import check_answer, check_blocks, citation_list
from legal_rag.generation.evidence import build_evidence, format_evidence
from legal_rag.generation.prompt import BROAD_VERSION, DEFAULT_VERSION, build_messages
from legal_rag.generation.trace import write_trace
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError
from legal_rag.knowledge.frame import is_broad_obligation_query, load_frame
from legal_rag.retrieval.pipeline import RetrievalPipeline
from legal_rag.retrieval.references import ReferenceGraph

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None, root=ROOT, pipeline_factory=RetrievalPipeline, client_factory=HTTPChatClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--budget", type=int, default=3000)
    parser.add_argument("--evidence-only", action="store_true")
    parser.add_argument("--trace-dir", type=Path, default=root / "runs/traces")
    args = parser.parse_args(argv)
    if args.budget < 0:
        parser.error("--budget phải không âm")
    if not args.query.strip():
        parser.error("--query không được rỗng")
    record = None
    chat = None
    start = None
    try:
        settings = None if args.evidence_only else get_llm_settings()
        parents = read_jsonl(root / "data/processed/parents.jsonl")
        with (root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
            documents = list(csv.DictReader(stream))
        chunks = read_jsonl(root / "data/processed/chunks.jsonl")
        graph = ReferenceGraph(read_jsonl(root / "data/processed/references.jsonl"), parents, chunks)
        route = "broad_frame" if is_broad_obligation_query(args.query) else "retrieval"
        version = BROAD_VERSION if route == "broad_frame" else DEFAULT_VERSION
        if route == "broad_frame":
            frame_start = perf_counter()
            blocks = load_frame(root / "src/legal_rag/knowledge/core_frame.yaml", parents)
            units = [dict(parent, block=block["label"])
                     for block in blocks for parent in block["parents"]]
            items = build_evidence(units, documents)
            timing = {"frame": {"query_ms": (perf_counter() - frame_start) * 1000}}
            retrieval_config = None
        else:
            pipeline = pipeline_factory(chunks, parents)
            items = build_evidence(pipeline.context(args.query, args.budget), documents)
            timing = dict(pipeline.last_timing)
            retrieval_config = asdict(pipeline.config)
        for item in items:
            external = graph.external(item["parent_id"])
            if external:
                item["external_refs"] = external
        calls = cache_hits = 0
        answer = check = None
        messages = []
        record = {
            "query": args.query, "route": route, "retrieval_config": retrieval_config,
            "budget": args.budget, "prompt_version": version,
            "messages": messages, "evidence": items, "answer": None, "check": None,
            "llm_calls": calls, "cache_hits": cache_hits, "timing": timing,
            "model": None, "llm_attempts": [],
        }
        if args.evidence_only:
            print(format_evidence(items))
        else:
            fallback_models = getattr(settings, "fallback_models", ())
            client = (client_factory(settings.base_url, settings.api_key, max_attempts=3)
                      if fallback_models else client_factory(settings.base_url, settings.api_key))
            chat = FallbackChat(CachedChat(client, root / ".cache/llm"), fallback_models)
            payload = dict(build_messages(args.query, items, version), model=settings.model)
            messages = payload["messages"]
            record["messages"] = messages
            start = perf_counter()
            answer = chat.complete(payload)
            timing["llm"] = {"query_ms": (perf_counter() - start) * 1000}
            calls, cache_hits = chat.request_count, chat.cache_hits
            print(answer)
            from legal_rag.generation.locations import build_location_index
            check = check_answer(answer, items, build_location_index(parents, chunks), chunks)
            check["missing_blocks"] = check_blocks(check, items)
            check["valid"] = check["valid"] and not check["missing_blocks"]
            print(json.dumps(check, ensure_ascii=False))
        record.update(answer=answer, check=check, llm_calls=calls, cache_hits=cache_hits)
        if chat is not None:
            record.update(model=chat.last_model, llm_attempts=chat.attempts)
        write_trace(record, args.trace_dir)
        record = None
        print("Trích dẫn:")
        for citation in citation_list(check or {"used": [i["id"] for i in items]}, items):
            print(citation)
        print(json.dumps({"llm_calls": calls, "cache_hits": cache_hits,
                          "timing": timing}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, LLMError) as error:
        # Không xuất lỗi tùy ý của nhà cung cấp vì có thể chứa cấu hình bí mật.
        if isinstance(error, LLMError):
            message = str(error)
        elif isinstance(error, FileNotFoundError):
            message = "Thiếu dữ liệu hoặc cache vector; chạy scripts/build_index.py --model jina (hoặc model được cấu hình)."
        elif isinstance(error, ValueError) and str(error).startswith("Thiếu biến môi trường:"):
            message = str(error)
        else:
            message = "Không thể xử lý câu hỏi; kiểm tra dữ liệu, cache vector và cấu hình LLM."
        if record is not None:
            record.update(answer=None, check=None, error=message, model=None)
            if chat is not None:
                record.update(llm_calls=chat.request_count, cache_hits=chat.cache_hits,
                              llm_attempts=chat.attempts)
            if start is not None:
                timing["llm"] = {"query_ms": (perf_counter() - start) * 1000}
            try:
                write_trace(record, args.trace_dir)
            except (OSError, ValueError):
                print("Lỗi: Không thể ghi trace.", file=sys.stderr)
        print("Lỗi: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
