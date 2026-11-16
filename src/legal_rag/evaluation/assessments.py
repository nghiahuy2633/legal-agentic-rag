"""Chấm tất định luồng tuân thủ và chạy tiếp từ kết quả JSONL."""

import argparse
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
from pathlib import Path
import random
import re
from statistics import mean, median
from time import perf_counter

from legal_rag.assessment.baselines import run_baseline
from legal_rag.assessment.pipeline import prepare_assessment, run_assessment
from legal_rag.config import get_llm_settings
from legal_rag.knowledge.facts import FACT_FIELDS, validate_facts
from legal_rag.knowledge.obligations import load_obligations
from legal_rag.llm import CachedChat, HTTPChatClient, LLMError, OfflineClient, QuotaExhaustedError

ROOT = Path(__file__).resolve().parents[3]
CONFIGS = ("full", "full_msg", "b0", "b1")
METRICS = ("precision", "recall", "status_acc")
PRIORITY = {"chua": 0, "chua_ro": 1, "da": 2}


def citation_units(chunk_id):
    match = re.match(r"(.*?_khoan-[^_]+)(?:_diem-([^_]+))?", chunk_id)
    if match:
        return {match[1]} | ({match[0]} if match[2] else set())
    article = re.match(r"(.*?_dieu-[^_]+)", chunk_id)
    return {article[1] if article else re.sub(r"_(?:cuoi|phan-\d+).*$", "", chunk_id)}


def _units(obligation):
    return set().union(*(citation_units(c) for c in obligation["chunk_ids"]))


def _matched_status(gold, obligations):
    matches = [o for o in obligations if _units(o).intersection(gold["units"])]
    return min((o["status"] for o in matches), key=PRIORITY.get) if matches else None


def _warning_score(predicted, gold, optional=()):
    # Ghép một-một, không đếm đôi khi cùng Khoản có nhiều mã Điểm/hậu tố.
    # Cảnh báo chỉ khớp nhóm "chấp nhận được" (optional) thì không tính đúng, không tính thừa.
    optional = set(optional)
    predicted = [p for p in dict.fromkeys(predicted)
                 if not (citation_units(p) & optional) or citation_units(p) & set(gold)]
    gold = list(dict.fromkeys(gold))
    assigned = {}

    def augment(index, seen):
        for j, unit in enumerate(gold):
            if j in seen or unit not in citation_units(predicted[index]):
                continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = index
                return True
        return False

    for i in range(len(predicted)):
        augment(i, set())
    tp = len(assigned)
    return {"tp": tp, "fp": len(predicted) - tp, "fn": len(gold) - tp}


def score_facts(gold_row, facts):
    expected = gold_row.get("message_facts", {})

    def same(a, b):
        return set(a) == set(b) if isinstance(a, list) and isinstance(b, list) else type(a) is type(b) and a == b

    fields = {name: {"correct": same(facts.get(name), value),
                     "expected": value, "actual": facts.get(name)}
              for name, value in expected.items()}
    hallucinated = [name for name in FACT_FIELDS
                    if expected.get(name) is None and facts.get(name) is not None]
    return {"fact_accuracy": mean(v["correct"] for v in fields.values()) if fields else None,
            "fact_hallucinated": len(hallucinated), "fact_hallucinated_fields": hallucinated,
            "fact_fields": fields}


def score_product(gold_row, output):
    obligations = [o for o in output.get("obligations", []) if o.get("kind") == "nghia_vu"
                   and o.get("applicability") in ("ap_dung", "ap_dung_neu")]
    gold = gold_row["gold"]
    required = [g for g in gold if not g["optional"]]
    definite = [o for o in obligations if o["applicability"] == "ap_dung"]
    relevant, count = 0, 0
    extra = []
    for obligation in obligations:
        matches = [g for g in gold if _units(obligation).intersection(g["units"])]
        if not matches:
            extra.append(obligation)
        if obligation["applicability"] != "ap_dung":
            continue
        if matches and all(g["optional"] for g in matches):
            continue
        count += 1
        relevant += bool(matches)
    matched = {g["gid"]: _matched_status(g, obligations) for g in required}
    covered = [g for g in required if matched[g["gid"]] is not None]
    correct, false_da = 0, 0
    for g in covered:
        accepted = [g["status"]] if isinstance(g["status"], str) else g["status"]
        status = matched[g["gid"]]
        correct += status in accepted
        false_da += status == "da" and "da" not in accepted
    result = {"precision": relevant / count if count else None,
        "recall": len(covered) / len(required) if required else None,
        "recall_definite": sum(_matched_status(g, definite) is not None for g in required) / len(required) if required else None,
        "status_acc": correct / len(covered) if covered else None,
        "status_correct": correct, "status_total": len(covered), "false_da": false_da,
        "warnings": _warning_score(output.get("warnings", []), gold_row["gold_warnings"],
                                    gold_row.get("gold_warnings_optional", [])),
        "extra": extra, "missed": [g["gid"] for g in required if matched[g["gid"]] is None],
        "matched_status": matched}
    if output.get("error"):
        # Lỗi vẫn nằm trong mẫu số macro, không làm đẹp điểm bằng cách bỏ dòng.
        result.update({name: 0.0 for name in (*METRICS, "recall_definite")})
    if "facts" in output:
        result.update(score_facts(gold_row, output["facts"]))
    return result


def _average(values):
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _bootstrap(values):
    if not values:
        return [None, None]
    rng = random.Random(0)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(1000))
    return [samples[24], samples[974]]


def consistency(rows):
    if len(rows) < 2:
        return {"consistency_obligations": None, "consistency_status": None}
    sets = [{o["key"] for o in r["output"].get("obligations", [])
             if o["applicability"] == "ap_dung" and o["kind"] == "nghia_vu"} for r in rows]
    jaccard = mean(len(a & b) / len(a | b) if a | b else 1.0 for a, b in combinations(sets, 2))
    gids = {gid for r in rows for gid, status in r["score"]["matched_status"].items() if status is not None}
    stable = sum(len({r["score"]["matched_status"].get(gid) for r in rows}) == 1
                 and all(r["score"]["matched_status"].get(gid) is not None for r in rows) for gid in gids)
    return {"consistency_obligations": jaccard,
            "consistency_status": stable / len(gids) if gids else None}


def summarize(rows):
    configs = defaultdict(list)
    for row in rows:
        configs[row["config"]].append(row)
    summary = {}
    for config, records in configs.items():
        products = defaultdict(list)
        for r in records:
            products[r["id"]].append(r)
        product_metrics = [{name: _average(r["score"][name] for r in products[product])
                            for name in (*METRICS, "recall_definite")}
                           for product in sorted(products)]
        item = {name: _average(p[name] for p in product_metrics)
                for name in (*METRICS, "recall_definite")}
        item["ci95"] = {name: _bootstrap([p[name] for p in product_metrics if p[name] is not None]) for name in METRICS}
        item.update(products=len(products), runs=len(records),
            false_da=sum(r["score"]["false_da"] for r in records),
            warnings={key: sum(r["score"]["warnings"][key] for r in records) for key in ("tp", "fp", "fn")},
            status_acc_micro=(sum(r["score"]["status_correct"] for r in records) /
                              sum(r["score"]["status_total"] for r in records)
                              if sum(r["score"]["status_total"] for r in records) else None),
            llm_calls_median=median(r["output"].get("llm_calls", 0) for r in records),
            llm_calls_total=sum(r["output"].get("llm_calls", 0) for r in records),
            total_ms_median=median(r.get("total_ms", 0) for r in records))
        consistency_rows = [consistency(repeats) for repeats in products.values()]
        item.update({name: _average(c[name] for c in consistency_rows)
                     for name in ("consistency_obligations", "consistency_status")})
        if config == "full_msg":
            item.update(fact_accuracy=_average(r["score"].get("fact_accuracy") for r in records),
                        fact_hallucinated=sum(r["score"].get("fact_hallucinated", 0) for r in records))
            item["fact_fields"] = {field: {
                "correct": sum(r["score"].get("fact_fields", {}).get(field, {}).get("correct", False) for r in records),
                "total": sum(field in r["score"].get("fact_fields", {}) for r in records),
                "hallucinated": sum(field in r["score"].get("fact_hallucinated_fields", []) for r in records)}
                for field in FACT_FIELDS}
            for field in item["fact_fields"].values():
                field["accuracy"] = field["correct"] / field["total"] if field["total"] else None
        summary[config] = item
    return summary


def compare(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[row["config"]][row["id"]].append(row["score"])
    result = {}
    for a, b in (("full", "b0"), ("full", "b1"), ("b1", "b0")):
        metrics = {}
        for name in METRICS:
            differences = []
            for product in sorted(grouped[a].keys() & grouped[b].keys()):
                left = _average(r[name] for r in grouped[a][product])
                right = _average(r[name] for r in grouped[b][product])
                if left is not None and right is not None:
                    differences.append(left - right)
            metrics[name] = {"difference": _average(differences),
                             "ci95": _bootstrap(differences), "n": len(differences)}
        result[f"{a}-{b}"] = metrics
    return result


def load_products(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in seen:
            raise ValueError("ID sản phẩm thiếu hoặc trùng")
        seen.add(row["id"])
        for field in ("message", "description", "statement"):
            if not isinstance(row.get(field), str):
                raise ValueError(f"{row['id']}: sai {field}")
        for field in ("facts", "message_facts"):
            if not isinstance(row.get(field), dict) or validate_facts(row[field])[1]:
                raise ValueError(f"{row['id']}: sai {field}")
        if not isinstance(row.get("gold"), list) or not isinstance(row.get("gold_warnings"), list):
            raise ValueError(f"{row['id']}: thiếu nhãn")
        gids = set()
        for gold in row["gold"]:
            if not isinstance(gold, dict) or not isinstance(gold.get("gid"), str) or gold["gid"] in gids:
                raise ValueError(f"{row['id']}: sai gid")
            gids.add(gold["gid"])
            neutral = gold.get("neutral") is True
            labels = gold.get("status")
            labels = [labels] if isinstance(labels, str) else labels
            # Nhóm trung tính (căn cứ chỉ dẫn chiếu): luôn optional, không có hiện trạng.
            if neutral and (gold.get("optional") is not True or labels is not None):
                raise ValueError(f"{row['id']}: sai nhãn trung tính {gold['gid']}")
            if ((not neutral and (not isinstance(labels, list) or not labels or any(s not in PRIORITY for s in labels)))
                    or type(gold.get("optional")) is not bool
                    or not isinstance(gold.get("units"), list) or not gold["units"]
                    or any(not isinstance(u, str) or not u for u in gold["units"])):
                raise ValueError(f"{row['id']}: sai nhãn {gold['gid']}")
        if not isinstance(row.get("gold_warnings_optional", []), list) or any(
                not isinstance(u, str) or not u for u in row.get("gold_warnings_optional", [])):
            raise ValueError(f"{row['id']}: sai gold_warnings_optional")
        if any(not isinstance(u, str) or not u for u in row["gold_warnings"]):
            raise ValueError(f"{row['id']}: sai gold_warnings")
    if not rows:
        raise ValueError("Bộ sản phẩm rỗng")
    return rows


INPUT_FIELDS = ("id", "message", "description", "statement", "facts")


def check_reachability(products, chunks, table=None, configs=()):
    """Nhãn ngoài corpus là lỗi; nhãn không có trong bảng là kết quả cần đo, chỉ trả về để ghi lại."""
    available = set().union(*(citation_units(c["chunk_id"]) for c in chunks))
    missing = [f"{r['id']}/{g['gid']}" for r in products for g in r["gold"]
               if not available.intersection(g["units"])]
    missing += [f"{r['id']}/warning/{u}" for r in products for u in r["gold_warnings"] if u not in available]
    if missing:
        raise ValueError("Nhãn không chạm được từ corpus: " + ", ".join(missing))
    if table is not None and set(configs).intersection(("full", "full_msg")):
        accepted = [r for r in table if r["review_status"] in ("ai_reviewed", "user_reviewed")]
        obligation_units = set().union(*(citation_units(c["chunk_id"]) for r in accepted
            if r.get("kind", "nghia_vu") == "nghia_vu" for c in r["citations"]))
        warning_units = set().union(*(citation_units(c["chunk_id"]) for r in accepted
            if r.get("kind") == "cam" for c in r["citations"]))
        missing = [f"{r['id']}/{g['gid']}" for r in products for g in r["gold"]
                   if not g.get("neutral") and not obligation_units.intersection(g["units"])]
        missing += [f"{r['id']}/warning/{u}" for r in products for u in r["gold_warnings"] if u not in warning_units]
        return missing
    return []


class _ObservedChat:
    """T34/T35 bắt LLMError; giữ lỗi/hạn mức để runner vẫn dừng đúng."""

    def __init__(self, chat):
        self.chat, self.calls, self.errors = chat, 0, []

    def complete(self, request):
        if self.errors and isinstance(self.errors[-1], QuotaExhaustedError):
            raise self.errors[-1]
        self.calls += 1
        try:
            return self.chat.complete(request)
        except LLMError as error:
            self.errors.append(error)
            raise


def execute(config, product, chat, model, pipeline_factory):
    if config in ("b0", "b1"):
        return run_baseline(config, product["facts"], product["description"],
                            product["statement"], chat, model, pipeline_factory)
    facts, prepared = product["facts"], None
    if config == "full_msg":
        prepared = prepare_assessment([product["message"]], chat, model)
        facts = prepared["facts"]
    assessed = run_assessment(facts, product["statement"], product["description"],
                              chat, model, summarize_report=False)
    kinds = {i["row"]["id"]: i["row"].get("kind", "nghia_vu")
             for i in assessed["trace"]["applicable"]["items"]}
    report = assessed["report"]
    output = {"obligations": [{"key": o["id"], "text": o["obligation"],
        "chunk_ids": [c["chunk_id"] for c in o["citations"]], "kind": kinds[o["id"]],
        "applicability": o["applicability"], "status": o["status"], "criteria": o["criteria"]}
        for o in report["obligations"]],
        "warnings": list(dict.fromkeys(c["chunk_id"] for w in report["warnings"] for c in w["citations"])),
        "llm_calls": assessed["trace"]["llm_calls"] + (1 if prepared else 0),
        "trace": assessed["trace"]}
    if prepared is not None:
        output.update(facts=facts, preparation=prepared)
    status_errors = assessed["trace"]["status"]["errors"]
    output["status_errors"] = status_errors
    # Tiêu chí thiếu hoặc sai nhãn đã được hạ về chưa rõ: đó là hành vi cần chấm, không phải lỗi chạy.
    # Chỉ coi là lỗi chạy khi lời gọi LLM thất bại.
    if any("LLMError" in str(e.get("error")) or "llm" in str(e.get("type", "")).lower() for e in status_errors)             or prepared and prepared.get("error"):
        output["error"] = "Lỗi trích dữ kiện hoặc chấm hiện trạng"
    return output


def valid_output(output, config):
    if not isinstance(output, dict) or output.get("error"):
        return False
    if (not isinstance(output.get("obligations"), list) or not isinstance(output.get("warnings"), list)
            or type(output.get("llm_calls")) is not int or output["llm_calls"] < 0):
        return False
    for o in output["obligations"]:
        if (not isinstance(o, dict) or not all(isinstance(o.get(k), str) for k in ("key", "text"))
                or o.get("kind") != "nghia_vu" or not isinstance(o.get("status"), str) or o["status"] not in PRIORITY
                or o.get("applicability") not in ("ap_dung", "ap_dung_neu")
                or not isinstance(o.get("chunk_ids"), list) or not o["chunk_ids"]
                or any(not isinstance(c, str) or not c for c in o["chunk_ids"])
                or not isinstance(o.get("criteria"), list)):
            return False
    return (all(isinstance(c, str) and c for c in output["warnings"])
            and (config != "full_msg" or isinstance(output.get("facts"), dict)
                 and not validate_facts(output["facts"])[1]))


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main(argv=None, *, root=ROOT, client_factory=HTTPChatClient, pipeline_factory=None,
         settings_factory=get_llm_settings):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path(root)
    try:
        configs = args.configs.split(",")
        if (not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id)
                or not configs or len(set(configs)) != len(configs) or set(configs) - set(CONFIGS)
                or args.repeat < 1 or args.limit is not None and args.limit < 1):
            raise ValueError("Đối số không hợp lệ")
        products = load_products(root / "eval/assessments.jsonl")
        if args.ids:
            ids = args.ids.split(",")
            if set(ids) - {r["id"] for r in products}:
                raise ValueError("ID sản phẩm không tồn tại")
            products = [r for r in products if r["id"] in ids]
        if args.limit:
            products = products[:args.limit]
        chunks = _read_jsonl(root / "data/processed/chunks.jsonl")
        check_reachability(products, chunks)
        table_path = root / "src/legal_rag/knowledge/obligations.yaml"
        table = load_obligations(table_path)
        unreachable = check_reachability(products, chunks, table, configs)
        context = {"unreachable_from_table": unreachable, "table_sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
                   "table_review_status": dict(Counter(r["review_status"] for r in table)),
                   "gold_ai_draft": any(r.get("review_status") == "ai_draft" for r in products)}
        folder = root / "runs/eval" / args.run_id / "assessments"
        saved = {}
        for config in configs:
            path = folder / f"{config}.jsonl"
            saved[config] = _read_jsonl(path) if path.exists() else []
        latest = {(c, r.get("id"), r.get("repeat")): r for c in configs for r in saved[c]}
        # Chỉ băm phần đầu vào: sửa đáp án thì chấm lại, không phải sinh lại.
        fingerprints = {p["id"]: hashlib.sha256(json.dumps(
            {k: p[k] for k in INPUT_FIELDS}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                        for p in products}
        for (config, product_id, repeat), record in latest.items():
            if product_id in fingerprints and repeat in range(args.repeat):
                if (record.get("input_sha256") != fingerprints[product_id]
                        or record.get("table_sha256") != context["table_sha256"]):
                    raise ValueError("Đầu vào hoặc bảng đã đổi; dùng run-id mới")
        if pipeline_factory is None:
            pipelines = []

            def pipeline_factory():
                if not pipelines:
                    from legal_rag.retrieval.pipeline import RetrievalPipeline
                    pipelines.append(RetrievalPipeline(chunks, _read_jsonl(root / "data/processed/parents.jsonl")))
                return pipelines[0]

        settings, chats, quota = None, {}, False
        for repeat in range(args.repeat):
            for product in products:
                for config in configs:
                    key = (config, product["id"], repeat)
                    previous = latest.get(key)
                    if previous and valid_output(previous.get("output"), config):
                        continue
                    if args.score_only:
                        continue
                    if settings is None:
                        settings = settings_factory()
                        if any(r.get("model") != settings.model for r in latest.values()):
                            raise ValueError("Model sinh đã đổi; dùng run-id mới")
                    if repeat not in chats:
                        client = OfflineClient() if settings.offline else client_factory(settings.base_url, settings.api_key)
                        cache_dir = root / ".cache" / ("llm" if repeat == 0 else f"llm-repeat-{repeat}")
                        chats[repeat] = CachedChat(client, cache_dir)
                    observed = _ObservedChat(chats[repeat])
                    start = perf_counter()
                    try:
                        output = execute(config, product, observed, settings.model, pipeline_factory)
                    except (LLMError, ValueError) as error:
                        output = {"obligations": [], "warnings": [], "error": type(error).__name__}
                    output["llm_calls"] = observed.calls
                    if observed.errors:
                        output["error"] = type(observed.errors[-1]).__name__
                    quota = any(isinstance(e, QuotaExhaustedError) for e in observed.errors)
                    if not valid_output(output, config):
                        output.setdefault("error", "Đầu ra không hợp lệ")
                    record = {"id": product["id"], "config": config, "repeat": repeat,
                        "input_sha256": fingerprints[product["id"]],
                        "model": settings.model, "table_sha256": context["table_sha256"],
                        "total_ms": (perf_counter() - start) * 1000, "output": output}
                    latest[key] = record
                    saved[config].append(record)
                    _write(folder / f"{config}.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in saved[config]))
                    if quota:
                        break
                if quota:
                    break
            if quota:
                break
        rows, incomplete = [], []
        for repeat in range(args.repeat):
            for product in products:
                for config in configs:
                    key = (config, product["id"], repeat)
                    record = latest.get(key)
                    if not record or not valid_output(record.get("output"), config):
                        incomplete.append({"config": config, "id": product["id"], "repeat": repeat})
                        old_output = record.get("output", {}) if record else {}
                        record = dict(record or {"id": product["id"], "config": config, "repeat": repeat},
                            output={"obligations": [], "warnings": [],
                                    "llm_calls": old_output.get("llm_calls", 0),
                                    "error": old_output.get("error", "Thiếu kết quả hợp lệ")})
                        if config == "full_msg":
                            record["output"]["facts"] = old_output.get("facts", {})
                    record = dict(record, score=score_product(product, record["output"]))
                    rows.append(record)
        models = sorted({r["model"] for r in rows if "model" in r})
        if len(models) > 1:
            raise ValueError("Run có nhiều model sinh; dùng run-id riêng cho cùng một model")
        summary = {"complete": not incomplete, "incomplete": incomplete, "context": dict(context, models=models),
                   "configs": summarize(rows), "compare": compare(rows), "rows": rows}
        _write(folder / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        markdown = ["# Đánh giá luồng tuân thủ", "", f"Đủ kết quả: {summary['complete']}",
            "Model sinh: " + (", ".join(models) or "chưa có"),
            f"table_sha256: {context['table_sha256']}",
            "Số dòng bảng theo trạng thái duyệt: " + json.dumps(context["table_review_status"], ensure_ascii=False), ""]
        if context["gold_ai_draft"]:
            markdown += ["Đáp án `ai_draft`, chưa được người dùng soát", ""]
        if context["unreachable_from_table"]:
            markdown += ["Nghĩa vụ chuẩn không có căn cứ nào trong bảng (full không thể tìm thấy): "
                         + ", ".join(context["unreachable_from_table"]), ""]
        markdown += ["Số liệu sơ bộ; chấm khớp mã căn cứ, không xác nhận nội dung pháp lý.", "",
                     "```json", json.dumps({"configs": summary["configs"], "compare": summary["compare"]}, ensure_ascii=False, indent=2), "```", ""]
        _write(folder / "summary.md", "\n".join(markdown))
        print(f"Sản phẩm: {len(products)}; số lần lặp: {args.repeat}; thiếu/lỗi: {len(incomplete)}")
        return 3 if quota else 0 if summary["complete"] else 4
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Lỗi cấu hình/dữ liệu: {error}")
        return 2
