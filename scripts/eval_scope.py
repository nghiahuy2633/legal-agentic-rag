"""Chấm phạm vi và hồ sơ trên đầu vào, câu hỏi và kịch bản."""

import argparse
import json
from pathlib import Path
import sys

from legal_rag.agent.analyze import DEFAULT_ANALYZE_VERSION, decide
from legal_rag.agent.guard import check_input
from legal_rag.agent.profile import EMPTY_PROFILE, merge_profile
from legal_rag.config import get_llm_settings
from legal_rag.evaluation.input_checks import load_input_checks, score_profile, score_scope
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None, root=ROOT, client_factory=HTTPChatClient):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prompt", choices=("analyze_v1", "analyze_v2"), default=DEFAULT_ANALYZE_VERSION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = root / f"runs/t18/scope-{args.prompt}.json"
    datasets = {"input_checks": load_input_checks(root / "eval/input_checks.jsonl")}
    questions = [json.loads(line) for line in
                 (root / "eval/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    datasets["questions"] = [dict(id=row["id"], text=row["question"], kind=row["category"],
                                 should_retrieve=row["expected_behavior"] != "tu_choi")
                             for row in questions]
    scenarios = [json.loads(line) for line in
                 (root / "eval/scenarios.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    datasets["scenarios"] = [dict(id=f"{scenario['id']}.t{turn['turn']}",
                                  scenario_id=scenario["id"], text=turn["user"], kind="kich_ban",
                                  should_retrieve=turn["expected_behavior"] != "tu_choi",
                                  expected_profile=turn["expected_profile"])
                             for scenario in scenarios for turn in scenario["turns"]]
    if args.dry_run:
        for name, rows in datasets.items():
            rules = sum(check_input(row["text"])["status"] != "ok" for row in rows)
            print(json.dumps({"dataset": name, "n": len(rows), "rule": rules,
                              "needs_llm": len(rows) - rules}, ensure_ascii=False))
        return 0
    try:
        settings = get_llm_settings()
        fallback_models = getattr(settings, "fallback_models", ())
        client = (client_factory(settings.base_url, settings.api_key, max_attempts=3)
                  if fallback_models else client_factory(settings.base_url, settings.api_key))
        chat = FallbackChat(CachedChat(client, root / ".cache/llm"), fallback_models)
        output = {}
        fields = ("retrieve", "source", "status", "scope", "out_of_scope_part",
                  "profile_update", "sub_queries", "analysis_ok")
        for name, rows in datasets.items():
            results = []
            scenario_id = None
            profile, recent = EMPTY_PROFILE.copy(), []
            for row in rows:
                if name != "scenarios" or row["scenario_id"] != scenario_id:
                    profile, recent = EMPTY_PROFILE.copy(), []
                    scenario_id = row.get("scenario_id")
                record = dict.fromkeys(fields)
                record.update(id=row["id"], model=None)
                try:
                    result = decide(row["text"], profile, recent, chat, settings.model,
                                    version=args.prompt)
                    record.update({key: result[key] for key in fields})
                    if result["retrieve"]:
                        profile, _ = merge_profile(profile, result["profile_update"])
                    if result["source"] == "llm":
                        record["model"] = chat.last_model
                except LLMError as error:
                    record.update(source="llm", status="error", error=str(error))
                if name == "scenarios":
                    record["profile"] = profile.copy()
                    recent.append(row["text"])
                results.append(record)
            score = score_scope(rows, results)
            output[name] = {"results": results, "score": score}
            print(json.dumps({"dataset": name, **score}, ensure_ascii=False))
            if name == "scenarios":
                profile_score = score_profile(rows, results)
                output[name]["profile_score"] = profile_score
                print(json.dumps({"dataset": name, "profile_score": profile_score}, ensure_ascii=False))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError):
        print("Không thể chấm phạm vi; kiểm tra dữ liệu, prompt và cấu hình LLM.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
