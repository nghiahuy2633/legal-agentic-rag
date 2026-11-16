"""Bộ chạy nối dòng, tiếp tục phiên và chấm từ kết quả đã lưu."""

import argparse
from collections import Counter
import csv
from dataclasses import replace
from functools import partial
import json
import os
from pathlib import Path
import re
from statistics import mean, median
import sys
from time import perf_counter
from uuid import uuid4

from legal_rag.agent.config import AgentConfig, DEFAULT_CONTEXT_BUDGET
from legal_rag.agent.graph import run_turn
from legal_rag.agent.profile import EMPTY_PROFILE
from legal_rag.agent.runtime import build_agent, read_jsonl
from legal_rag.config import get_llm_settings
from legal_rag.evaluation.answers import compare, find_judgment, judge_answer, judgment_key, load_answers, score_answers, valid_judgment
from legal_rag.evaluation.behavior import scenario_rows, score_behavior
from legal_rag.agent.budget import sum_tokens
from legal_rag.evaluation.input_checks import load_input_checks
from legal_rag.generation.citations import check_answer, check_blocks
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.locations import build_location_index
from legal_rag.generation.prompt import build_messages
from legal_rag.knowledge.frame import is_broad_obligation_query, load_frame
from legal_rag.llm import CachedChat, FallbackChat, HTTPChatClient, LLMError, OfflineClient
from legal_rag.retrieval.pipeline import RetrievalPipeline

CONFIGS = {
    "basic": None,
    "full": AgentConfig(),
    "no_rewrite": replace(AgentConfig(), enable_rewrite=False),
    "no_verifier": replace(AgentConfig(), enable_verifier=False),
    "references_on": replace(AgentConfig(), enable_references=True),
    "no_obligations": replace(AgentConfig(), enable_obligations=False),
}
LAYERS = ("answers", "behavior")
ROOT = Path(__file__).resolve().parents[3]


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()


def latest(path, key="id"):
    return {row[key]: row for row in read_jsonl(path)} if Path(path).exists() else {}


class SharedPipeline:
    """Chỉ tạo pipeline khi truy xuất lần đầu, dùng lại giữa mọi cấu hình."""

    def __init__(self, root, factory=RetrievalPipeline):
        self.root, self.factory, self.pipeline = root, factory, None

    def __getattr__(self, name):
        if self.pipeline is None:
            self.pipeline = self.factory(read_jsonl(self.root / "data/processed/chunks.jsonl"),
                                         read_jsonl(self.root / "data/processed/parents.jsonl"))
        return getattr(self.pipeline, name)


class AgentExecutor:
    def __init__(self, root, name, pipeline):
        self.graph, self.chat, self.settings = build_agent(root, CONFIGS[name], pipeline=pipeline,
            client_factory=partial(HTTPChatClient, rate_wait_max=65))

    def restore(self, session, result):
        state = result.get("session_state")
        if state:
            self.graph.update_state({"configurable": {"thread_id": session}}, state, as_node="respond")

    def execute(self, entry, session):
        value = run_turn(self.graph, session, entry["question"])
        calls = [node for node in value["trace"] if node["llm_calls"]]
        state = self.graph.get_state({"configurable": {"thread_id": session}}).values
        degraded = [(node["node"], node[key]) for node in value["trace"]
                    for key in ("grade_error", "high_risk_error", "verify_error", "repair_error")
                    if key in node]
        error = value["error"]
        if degraded:
            error = "; ".join(f"Nút {name} lỗi LLM: {detail}" for name, detail in degraded)
            if value["error"]:
                error = value["error"] + "; " + error
        return dict(answer=value["reply"], route=value["route"], evidence=value["evidence"],
                    check=value["check"], verification=value["verification"], profile=value["profile"],
                    llm_calls=value["llm_calls"], tokens=value.get("tokens"), error=error,
                    degraded_nodes=list(dict.fromkeys(name for name, _ in degraded)),
                    model=calls[-1].get("model") if calls else None,
                    llm_attempts=[a for node in calls for a in node.get("llm_attempts", [])],
                    session_state={key: state[key] for key in
                                   ("profile", "messages", "last_parents", "followup_asked") if key in state})


class BasicExecutor:
    """RAG một lượt, không phân tích hồ sơ, đồ thị hay kiểm chứng LLM."""

    def __init__(self, root, pipeline, chat=None, settings=None):
        self.root, self.pipeline = Path(root), pipeline
        self.settings = settings or get_llm_settings()
        self.chat = chat
        if self.chat is None:
            fallback = getattr(self.settings, "fallback_models", ())
            client = OfflineClient() if getattr(self.settings, "offline", False) else (
                      HTTPChatClient(self.settings.base_url, self.settings.api_key, max_attempts=3, rate_wait_max=65)
                      if fallback else HTTPChatClient(self.settings.base_url, self.settings.api_key, rate_wait_max=65))
            # Basic chỉ dùng model trả lời, tối đa một lời gọi logic mỗi câu.
            self.chat = FallbackChat(CachedChat(client, self.root / ".cache/llm"), fallback)
        self.parents = read_jsonl(self.root / "data/processed/parents.jsonl")
        self.chunks = read_jsonl(self.root / "data/processed/chunks.jsonl")
        self.index = build_location_index(self.parents, self.chunks)
        with (self.root / "data/source_registry/documents.csv").open(encoding="utf-8", newline="") as stream:
            self.documents = list(csv.DictReader(stream))

    def restore(self, session, result):
        pass  # Basic độc lập từng câu, kể cả lượt kịch bản.

    def execute(self, entry, session):
        question = entry["question"]
        broad = is_broad_obligation_query(question)
        if broad:
            blocks = load_frame(self.root / "src/legal_rag/knowledge/core_frame.yaml", self.parents)
            units = [dict(parent, block=block["label"]) for block in blocks for parent in block["parents"]]
        else:
            units = self.pipeline.context(question, DEFAULT_CONTEXT_BUDGET)
        evidence = build_evidence(units, self.documents)
        payload = dict(build_messages(question, evidence, "answer_v3" if broad else "answer_v2"),
                       model=self.settings.model)
        try:
            answer = self.chat.complete(payload)
        except LLMError as error:
            return dict(answer=None, error=str(error), http_status=error.status,
                        evidence=evidence, llm_calls=1, model=getattr(self.chat, "last_model", None),
                        llm_attempts=list(getattr(self.chat, "attempts", [])))
        check = check_answer(answer, evidence, self.index, self.chunks)
        check["missing_blocks"] = check_blocks(check, evidence)
        check["valid"] = check["valid"] and not check["missing_blocks"]
        usage = getattr(self.chat, "last_usage", None)
        return dict(answer=answer, route="broad_frame" if broad else "retrieval", evidence=evidence,
                    check=check, verification=None, profile=dict(EMPTY_PROFILE), llm_calls=1,
                    tokens=sum_tokens([usage]),
                    model=getattr(self.chat, "last_model", None) or self.settings.model,
                    llm_attempts=list(getattr(self.chat, "attempts", [])), error=None)


def make_executor(root, name, pipeline):
    return BasicExecutor(root, pipeline) if name == "basic" else AgentExecutor(root, name, pipeline)


def load_datasets(root, layers, limit):
    datasets = dict(answers=[], questions=[], scenarios=[], input_checks=[])
    if "answers" in layers:
        path = root / "eval/answers.jsonl"
        if path.exists():
            datasets["answers"] = load_answers(path)
        else:
            print(f"Thiếu {path}: bỏ qua lớp answers; các lớp khác vẫn chạy.")
    if "behavior" in layers:
        datasets.update(questions=read_jsonl(root / "eval/questions.jsonl"),
                        scenarios=read_jsonl(root / "eval/scenarios.jsonl"),
                        input_checks=load_input_checks(root / "eval/input_checks.jsonl"))
    # Cắt cùng tập ở mọi cấu hình; giới hạn tổng số câu/lượt của mỗi lớp.
    selected = {
        "answers": datasets["answers"],
        "behavior": [*datasets["questions"],
                     *[dict(row, question=row["text"]) for row in datasets["input_checks"]],
                     *scenario_rows(datasets["scenarios"])],
    }
    plan = {layer: [
        {key: row[key] for key in ("id", "question", "scenario_id", "turn") if key in row}
        for row in selected[layer][:limit]] for layer in layers}
    answer_ids = {row["id"] for row in plan.get("answers", [])}
    behavior_ids = {row["id"] for row in plan.get("behavior", [])}
    datasets["answers"] = [r for r in datasets["answers"] if r["id"] in answer_ids]
    datasets["questions"] = [r for r in datasets["questions"] if r["id"] in behavior_ids]
    datasets["input_checks"] = [r for r in datasets["input_checks"] if r["id"] in behavior_ids]
    datasets["scenarios"] = [dict(s, turns=[t for t in s["turns"]
        if f"{s['id']}.t{t['turn']}" in behavior_ids]) for s in datasets["scenarios"]]
    return datasets, plan


def is_429(result):
    if not result.get("error"):
        return False
    if result.get("http_status") is not None:
        return result["http_status"] == 429
    if statuses := re.findall(r"\bHTTP (\d{3})\b", result["error"]):
        return "429" in statuses
    attempts = result.get("llm_attempts", [])
    return bool(attempts and attempts[-1].get("status") == 429)


def result_record(entry, name, layer):
    return dict(entry, config=name, layer=layer, answer=None, route=None, evidence=[], check=None,
                verification=None, profile={}, llm_calls=0, latency_ms=0, model=None,
                llm_attempts=[], error=None)


def run_config(directory, name, plan, executor_factory, streak=0):
    executor = None
    completed = 0
    invocation = uuid4().hex
    for layer, entries in plan.items():
        path = directory / f"{name}.{layer}.jsonl"
        saved = latest(path)
        # Chỉ giữ tiền tố thành công; kết quả phía sau điểm chạy lại không còn hợp lệ.
        prefixes, retrying = {}, set()
        for entry in sorted((e for e in entries if "scenario_id" in e), key=lambda e: e["turn"]):
            scenario = entry["scenario_id"]
            old = saved.get(entry["id"])
            if scenario not in retrying and old is not None and not old.get("error"):
                prefixes.setdefault(scenario, []).append(old)
            else:
                retrying.add(scenario)
        kept = {row["id"] for prefix in prefixes.values() for row in prefix}
        started, failed = set(), {}
        for entry in entries:
            session = f"{name}:{layer}:" + entry.get("scenario_id", entry["id"])
            scenario = entry.get("scenario_id")
            old = saved.get(entry["id"])
            if (entry["id"] in kept if scenario is not None else old is not None and not old.get("error")):
                continue
            record = result_record(entry, name, layer)
            if scenario in failed:
                record.update(error=f"Bỏ qua vì lượt {failed[scenario]} lỗi", http_status=None)
                record.pop("llm_attempts")
                append_jsonl(path, record)
                continue
            executor = executor or executor_factory(name)
            if scenario is not None:
                session += f":{invocation}"
                if scenario not in started:
                    prefix = prefixes.get(scenario, [])
                    if prefix:
                        executor.restore(session, prefix[-1])
                    started.add(scenario)
            start = perf_counter()
            try:
                record.update(executor.execute(entry, session))
            except Exception as error:
                # Một câu lỗi không được làm mất kết quả các câu khác.
                record.update(error=str(error), http_status=getattr(error, "status", None))
            record["latency_ms"] = (perf_counter() - start) * 1000
            append_jsonl(path, record)
            if scenario is not None and record["error"]:
                failed[scenario] = entry["id"]
            completed += not bool(record["error"])
            streak = streak + 1 if is_429(record) else 0
            if streak == 5:
                return 3, completed, streak, executor
    return 0, completed, streak, executor


def collect_judgments(directory, name, rows, executor_factory, executor=None, streak=0):
    path = directory / f"{name}.judgments.jsonl"
    cached = latest(path, "key")
    results = latest(directory / f"{name}.answers.jsonl")
    for row in rows:
        result = results.get(row["id"])
        if result is None or result.get("error"):
            continue
        judge_model = os.environ.get("RAG_JUDGE_MODEL", "").strip()
        # Chỉ bỏ qua khi đúng phiên bản prompt và model đang yêu cầu; phán quyết khác chỉ dùng để chấm lại số cũ.
        model = judge_model or result.get("model")
        if not model:
            executor = executor or executor_factory(name)
            model = executor.settings.model
        if valid_judgment(cached.get(judgment_key(row, result, model)), row):
            continue
        executor = executor or executor_factory(name)
        # Judge không dùng các fallback của model sinh để tránh đổi model chấm âm thầm.
        chat = FallbackChat(executor.chat.chat) if isinstance(executor.chat, FallbackChat) else executor.chat
        value = judge_answer(row, result, chat, model)
        value["judge_same_model"] = model == (result.get("model") or executor.settings.model)
        append_jsonl(path, value)
        cached[value["key"]] = value
        streak = streak + 1 if value.get("http_status") == 429 else 0
        if streak == 5:
            return 3, streak
    return 0, streak


def summarize(directory, names, layers, datasets, plan, limit=None):
    # Luôn đọc lại mọi lớp/cấu hình có kết quả, không phụ thuộc lệnh vừa chạy.
    available = {name: [layer for layer in LAYERS
                       if (directory / f"{name}.{layer}.jsonl").exists()] for name in CONFIGS}
    summary = dict(configs={}, comparisons={}, comparability={}, complete=True)
    for name, saved_layers in available.items():
        if not saved_layers:
            continue
        all_results, value = [], {}
        for layer in saved_layers:
            records = latest(directory / f"{name}.{layer}.jsonl")
            ids = {e["id"] for e in plan[layer]}
            all_results.extend(r for ident, r in records.items() if ident in ids)
            if layer == "answers":
                value[layer] = score_answers(datasets["answers"], records,
                                             latest(directory / f"{name}.judgments.jsonl", "key"))
                scores = value[layer]
                print(f"{name}: thiếu phán quyết {scores['missing_judgments']} câu "
                      f"{scores['missing_judgment_ids']}; lỗi chấm {scores['judge_errors']} câu "
                      f"{scores['judge_error_ids']}")
                if any(scores[field] for field in ("errors", "missing_results", "judge_errors", "missing_judgments")):
                    summary["complete"] = False
                generation = sorted({records[i].get("model") for i in ids
                                     if i in records and records[i].get("model")})
                same = 0
                judgments = latest(directory / f"{name}.judgments.jsonl", "key")
                for row in datasets["answers"]:
                    result = records.get(row["id"])
                    if result and not result.get("error"):
                        judge = find_judgment(row, result, judgments)
                        if valid_judgment(judge, row):
                            same += bool(judge.get("judge_model") and judge["judge_model"] == result.get("model"))
                warnings = []
                if len(generation) > 1:
                    warnings.append("Trộn nhiều model sinh trong cấu hình.")
                if same:
                    warnings.append("Model chấm trùng model sinh.")
                if any(row.get("review_status") == "ai_draft" for row in datasets["answers"]):
                    warnings.append("Nhãn còn ai_draft.")
                summary["comparability"][name] = dict(generation_models=generation,
                    judge_models=sorted(scores["judge_models"]), judge_same_model=same,
                    mixed_models=len(generation) > 1, warnings=warnings)
            else:
                value[layer] = score_behavior(datasets["scenarios"], datasets["questions"],
                                               datasets["input_checks"], records)
                if value[layer]["errors"]:
                    summary["complete"] = False
        value["operational"] = dict(
            n=sum(len(plan[layer]) for layer in saved_layers), saved=len(all_results),
            llm_calls_mean=mean([r.get("llm_calls", 0) for r in all_results]) if all_results else None,
            latency_median_ms=median([r.get("latency_ms", 0) for r in all_results]) if all_results else None,
            errors=sum(bool(r.get("error")) for r in all_results),
            models=dict(sorted(Counter(r.get("model") or "không có model trả lời" for r in all_results).items())))
        summary["configs"][name] = value
    # Thiếu cả file cũng là chưa hoàn tất, nhưng không bịa lớp toàn số 0.
    for name in names:
        if any(plan[layer] and layer not in available[name] for layer in layers):
            summary["complete"] = False
    answer_names = [name for name, value in summary["configs"].items() if "answers" in value]
    for i, a in enumerate(answer_names):
        for b in answer_names[i + 1:]:
            summary["comparisons"][f"{a}-{b}"] = compare(summary["configs"][a]["answers"],
                                                         summary["configs"][b]["answers"])
    model_sets = {tuple(value["generation_models"]) for value in summary["comparability"].values()
                  if value["generation_models"]}
    if len(model_sets) > 1:
        for value in summary["comparability"].values():
            value["mixed_models"] = True
            value["warnings"].append("Model sinh khác giữa các cấu hình.")
    directory.mkdir(parents=True, exist_ok=True)
    filename = "summary.json" if limit is None else f"summary.limit-{limit}.json"
    (directory / filename).write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Cấu hình | Chỉ số (CI 95%) | LLM TB | Trung vị ms | Lỗi | Model")
    for name, value in summary["configs"].items():
        op = value["operational"]
        metrics = {}
        if "answers" in value:
            scores = value["answers"]
            metrics["answers"] = {field: dict(value=scores[field], ci=scores["confidence_intervals"][field])
                                  for field in scores["confidence_intervals"]}
        if "behavior" in value:
            scores = value["behavior"]
            metrics["behavior"] = {field: scores[field]["rate"]
                for field in ("correct_refusal", "false_refusal", "followup", "fabricated_numbers")}
            metrics["behavior"].update(profile_accuracy=scores["profile"]["accuracy"],
                                      asked_known_fields=scores["asked_known_fields"]["count"])
        print(f"{name} | {json.dumps(metrics, ensure_ascii=False, sort_keys=True)} | "
              f"{op['llm_calls_mean']} | {op['latency_median_ms']} | {op['errors']} | {op['models']}")
    for pair, comparison in summary["comparisons"].items():
        print(f"{pair}: CI={comparison['confidence_interval']}; "
              f"chồng lấn 0={comparison['overlaps_zero']}; {comparison['conclusion']}")
    for name, value in summary["comparability"].items():
        for warning in value["warnings"]:
            print(f"Cảnh báo {name}: {warning}")
    return summary


def summary_datasets(root, directory, layers, limit):
    discovered = [layer for layer in LAYERS if layer in layers or
                  any((directory / f"{name}.{layer}.jsonl").exists() for name in CONFIGS)]
    return load_datasets(root, discovered, limit)


def finish_summary(args, directory, root, names, layers):
    datasets, plan = summary_datasets(root, directory, layers, args.limit)
    summary = summarize(directory, names, layers, datasets, plan, args.limit)
    mixed = args.official and any(v["mixed_models"] for v in summary["comparability"].values())
    if args.generate_only:
        # Thiếu phán quyết là dự kiến; lỗi sinh hoặc thiếu kết quả vẫn phải lộ.
        failures = any(v["operational"]["errors"] or v["operational"]["saved"] < v["operational"]["n"]
                       for v in summary["configs"].values())
        summary["complete"] = False
        filename = "summary.json" if args.limit is None else f"summary.limit-{args.limit}.json"
        (directory / filename).write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True,
            indent=2, allow_nan=False) + "\n", encoding="utf-8")
    else:
        failures = not summary["complete"]
    if failures or mixed:
        print(f"Đánh giá chưa hoàn tất hoặc chưa so sánh được. Chạy lại: "
              f"scripts/run_eval.py --run-id {args.run_id} --configs {args.configs} --layers {args.layers}"
              + (f" --limit {args.limit}" if args.limit is not None else "")
              + (" --official" if args.official else ""))
        return 4
    return 0


def main(argv=None, root=ROOT, executor_factory=None):
    root = Path(root)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--configs", default="full,basic")
    parser.add_argument("--layers", default="answers,behavior")
    parser.add_argument("--limit", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--score-only", action="store_true")
    mode.add_argument("--generate-only", action="store_true")
    parser.add_argument("--official", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[\w-]+", args.run_id) or args.run_id in (".", ".."):
        parser.error("--run-id chỉ nhận chữ, số, dấu gạch dưới hoặc gạch ngang")
    requested = args.configs.split(",")
    if any(name not in CONFIGS for name in requested):
        parser.error("Cấu hình không hợp lệ")
    names = [name for name in CONFIGS if name in requested]
    if any(layer not in LAYERS for layer in args.layers.split(",")):
        parser.error("Lớp không hợp lệ")
    layers = [layer for layer in LAYERS if layer in args.layers.split(",")]
    if args.limit is not None and args.limit < 0:
        parser.error("--limit phải không âm")
    if not args.dry_run or args.official:
        # Chỉ đọc .env, không yêu cầu khóa/model cho score-only.
        from dotenv import load_dotenv
        from legal_rag.config import ENV_FILE
        load_dotenv(ENV_FILE, override=False)
    if args.official:
        judge_model = os.environ.get("RAG_JUDGE_MODEL", "").strip()
        if (not judge_model or judge_model == os.environ.get("RAG_LLM_MODEL", "").strip()
                or os.environ.get("RAG_LLM_FALLBACK_MODELS", "").strip()):
            print("--official cần RAG_JUDGE_MODEL khác RAG_LLM_MODEL và RAG_LLM_FALLBACK_MODELS rỗng.", file=sys.stderr)
            return 2
    directory = root / "runs/eval" / args.run_id
    try:
        datasets, plan = load_datasets(root, layers, args.limit)
        if args.dry_run:
            for name in names:
                done = total = 0
                for layer, entries in plan.items():
                    saved = latest(directory / f"{name}.{layer}.jsonl")
                    total += len(entries)
                    done += sum(e["id"] in saved and not saved[e["id"]].get("error") for e in entries)
                remaining = total - done
                print(f"{name}: đã xong={done}; còn lại={remaining}; "
                      f"LLM tối đa còn lại={remaining * (1 if name == 'basic' else 8)}; "
                      f"ước lượng phổ biến={remaining * (1 if name == 'basic' else 3)}")
            return 0
        if args.score_only:
            return finish_summary(args, directory, root, names, layers)
        pipeline = SharedPipeline(root)
        factory = executor_factory or (lambda name: make_executor(root, name, pipeline))
        completed = streak = 0
        for name in names:
            status, count, streak, executor = run_config(directory, name, plan, factory, streak)
            completed += count
            if status == 3:
                print(f"Dừng sau 5 câu HTTP 429 liên tiếp; đã xong {completed} câu mới. "
                      f"Chạy tiếp cùng --run-id {args.run_id} --configs {args.configs} --layers {args.layers}"
                      + (f" --limit {args.limit}" if args.limit is not None else ""))
                finish_summary(args, directory, root, names, layers)
                return 3
            if "answers" in layers and not args.generate_only:
                status, streak = collect_judgments(directory, name, datasets["answers"], factory, executor, streak)
                if status == 3:
                    print(f"Dừng sau 5 câu HTTP 429 liên tiếp khi chấm; đã xong {completed} câu mới. "
                          f"Chạy tiếp cùng --run-id {args.run_id} --configs {args.configs} --layers {args.layers}"
                          + (f" --limit {args.limit}" if args.limit is not None else ""))
                    finish_summary(args, directory, root, names, layers)
                    return 3
        return finish_summary(args, directory, root, names, layers)
    except (OSError, ValueError, KeyError, LLMError) as error:
        print(f"Lỗi đánh giá: {error}", file=sys.stderr)
        return 2
    return 0
