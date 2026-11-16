"""Chat nhiều lượt; trạng thái phiên chỉ sống trong tiến trình hiện tại."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

from legal_rag.agent.config import AgentConfig
from legal_rag.agent.graph import run_turn
from legal_rag.agent.runtime import build_agent
from legal_rag.generation.trace import write_trace
from legal_rag.generation.citations import citation_list
from legal_rag.llm import HTTPChatClient, LLMError
from legal_rag.retrieval.pipeline import RetrievalPipeline

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None, root=ROOT, pipeline_factory=RetrievalPipeline, client_factory=HTTPChatClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="demo")
    parser.add_argument("--message", action="append")
    parser.add_argument("--references", action="store_true")
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--no-verifier", action="store_true")
    parser.add_argument("--no-high-risk", action="store_true")
    parser.add_argument("--no-obligations", action="store_true")
    parser.add_argument("--budget", type=int, default=3000)
    parser.add_argument("--trace-dir", type=Path, default=root / "runs/traces")
    args = parser.parse_args(argv)
    try:
        config = AgentConfig(enable_references=args.references, enable_rewrite=not args.no_rewrite,
                             budget=args.budget, enable_verifier=not args.no_verifier,
                             enable_high_risk=not args.no_high_risk, enable_obligations=not args.no_obligations)
        graph, chat, settings = build_agent(root, config, client_factory, pipeline_factory)
        messages = args.message if args.message is not None else (line.rstrip("\r\n") for line in sys.stdin)
        for message in messages:
            start = perf_counter()
            result = run_turn(graph, args.session, message)
            total_ms = (perf_counter() - start) * 1000
            state = graph.get_state({"configurable": {"thread_id": args.session}}).values
            calls = [node for node in result["trace"] if node["llm_calls"]]
            citations = citation_list(result["check"] or {}, result["evidence"])
            record = dict(
                citations=citations,
                query=message, session_id=args.session, route=result["route"],
                prompt_version=state["prompt_version"],
                model=calls[-1].get("model") if calls and not result["error"] else None,
                profile=result["profile"], messages=state["llm_messages"],
                conversation=state["messages"][-2:],
                evidence=result["evidence"], answer=result["answer"], reply=result["reply"], check=result["check"],
                high_risk=result["high_risk"], map_obligations=result["map_obligations"],
                llm_calls=result["llm_calls"], verification=result["verification"],
                llm_attempts=[attempt for node in calls for attempt in node.get("llm_attempts", [])],
                nodes=result["trace"], error=result["error"], total_ms=total_ms,
            )
            write_trace(record, args.trace_dir)
            print(result["reply"])
            print("Trích dẫn:")
            for citation in citations:
                print(citation)
            print(json.dumps(dict(route=result["route"], profile=result["profile"],
                                  used=(result["check"] or {}).get("used", []),
                                  llm_calls=result["llm_calls"], total_ms=total_ms), ensure_ascii=False))
    except (OSError, ValueError, KeyError, LLMError) as error:
        if isinstance(error, LLMError):
            message = str(error)
        elif isinstance(error, ValueError) and str(error).startswith("Thiếu biến môi trường:"):
            message = str(error)
        else:
            message = "Không thể chạy chat; kiểm tra dữ liệu, cache vector, cấu hình LLM và thư mục trace."
        print("Lỗi: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
