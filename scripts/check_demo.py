"""Kiểm tra cache demo bằng đồ thị thật; --fill chỉ chạy khi được gọi rõ ràng."""

import argparse
import os
from pathlib import Path
import sys
from uuid import uuid4

from legal_rag.agent.graph import run_turn
from legal_rag.agent.runtime import build_agent, read_jsonl
from legal_rag.llm import LLMError

ROOT = Path(__file__).resolve().parents[1]
ERROR_KEYS = ("grade_error", "high_risk_error", "verify_error", "repair_error")


def turn_errors(value):
    errors = [(node["node"], node[key]) for node in value["trace"]
              for key in ERROR_KEYS if key in node]
    if value.get("error"):
        node = next((n["node"] for n in reversed(value["trace"]) if n["llm_calls"]), "unknown")
        errors.append((node, value["error"]))
    return errors


def main(argv=None, root=ROOT, agent_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fill", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = Path(root)
    scenarios = read_jsonl(root / "eval/demo_scenarios.jsonl")
    if args.dry_run:
        print(f"{len(scenarios)} kịch bản, {sum(len(s['turns']) for s in scenarios)} lượt.")
        return 0
    previous = {key: os.environ.get(key) for key in
                ("RAG_LLM_OFFLINE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    os.environ["RAG_LLM_OFFLINE"] = "0" if args.fill else "1"
    if not args.fill:
        # Truy xuất chỉ được nạp model có sẵn trên máy demo.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    completed, missing = 0, False
    try:
        graph, _, _ = (agent_factory or build_agent)(root)
        print("id | lượt | route | số lượt LLM | trạng thái")
        for scenario in scenarios:
            session = f"demo:{scenario['id']}:{uuid4().hex}"
            for turn, message in enumerate(scenario["turns"], 1):
                value = run_turn(graph, session, message)
                errors = turn_errors(value)
                misses = list(dict.fromkeys(node for node, error in errors
                                            if error.startswith("CacheMissError:")))
                status = ("thiếu cache ở nút " + ", ".join(misses) if misses else
                          "lỗi: " + "; ".join(error for _, error in errors) if errors else "sẵn sàng")
                print(f"{scenario['id']} | {turn} | {value['route']} | {value['llm_calls']} | {status}")
                missing |= bool(errors)
                completed += not bool(errors)
                if args.fill and any("HTTP 429" in error for _, error in errors):
                    print(f"Dừng vì hết hạn mức; đã xong {completed} lượt.")
                    return 1
        if args.fill:
            print(f"Đã xong {completed} lượt.")
        return int(missing)
    except (OSError, ValueError, LLMError) as error:
        print(f"Lỗi kiểm tra demo: {error}; đã xong {completed} lượt.", file=sys.stderr)
        return 1
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
