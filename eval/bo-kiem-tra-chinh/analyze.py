"""Phân tích bộ kiểm tra chính theo kế hoạch đặt trước (eval/bo-kiem-tra-chinh/plan.md). Viết và commit trước khi có kết quả.

Chạy trong repo: python eval/bo-kiem-tra-chinh/analyze.py runs/eval/test2 <thư mục kết quả chấm> > runs/eval/test2/analysis.md
Tùy chọn (thêm cho bộ mở rộng, plan-extension.md): tham số thứ ba là danh sách tiền tố bộ đề, phân cách dấu phẩy,
ví dụ eval/bo-kiem-tra-chinh/,eval/bo-kiem-tra-chinh/ext- để gộp t001–t060. Mặc định eval/bo-kiem-tra-chinh/ như ban đầu.
Không gọi LLM.
"""
import json, random, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "src")
from legal_rag.evaluation.answers import find_judgment
from legal_rag.evaluation.behavior import REFUSALS
from legal_rag.evaluation.run import latest

run_dir, judge_dir = Path(sys.argv[1]), Path(sys.argv[2])
read = lambda p: [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
SETS = (sys.argv[3] if len(sys.argv) > 3 else "eval/bo-kiem-tra-chinh/").split(",")
answers = {r["id"]: r for s in SETS for r in read(s + "answers.jsonl")}
questions = {r["id"]: r for s in SETS for r in read(s + "questions.jsonl")}
CONFIGS = ("full", "basic")
LABEL = {"pham_vi": "Phạm vi, định nghĩa", "vai_tro": "Vai trò", "phan_loai": "Phân loại, thông báo",
         "minh_bach": "Minh bạch, gắn nhãn", "rui_ro_cao": "Rủi ro cao", "su_co_che_tai": "Sự cố, chế tài",
         "cam_dao_duc_cong": "Cấm, đạo đức, khu vực công", "chuyen_tiep": "Hiệu lực, chuyển tiếp",
         "tra_cuu": "Tra cứu", "xac_nhan": "Xác nhận", "thu_tuc": "Thủ tục, chi tiết", "tien_de_sai": "Tiền đề sai",
         "tinh_huong": "Tình huống", "nhieu_van_ban": "Nhiều văn bản", "rong": "Câu rộng",
         "de": "Dễ", "trung_binh": "Trung bình", "kho": "Khó"}


def covered(g, pids):
    return any(p == g or g.startswith(p + "_") or p.startswith(g + "_") for p in pids)


def boot(values, reps=2000, seed=7):
    rnd = random.Random(seed)
    m = sorted(sum(rnd.choice(values) for _ in values) / len(values) for _ in range(reps))
    return m[int(.025 * reps)], m[int(.975 * reps)]


# Hành vi: 30 câu.
behavior = {c: latest(run_dir / f"{c}.behavior.jsonl") for c in CONFIGS}
beh = {}
for c in CONFIGS:
    out = [i for i, q in questions.items() if q["expected_behavior"] == "tu_choi"]
    inn = [i for i, q in questions.items() if q["expected_behavior"] != "tu_choi"]
    ref = lambda i: not behavior[c][i].get("error") and behavior[c][i].get("route") in REFUSALS
    beh[c] = dict(refuse=sum(ref(i) for i in out), n_out=len(out), false=[i for i in inn if ref(i)], n_in=len(inn),
                  errors=[i for i in questions if behavior[c].get(i, {}).get("error") or i not in behavior[c]])

# Câu trả lời: 24 câu.
data, per_point = {}, {c: [] for c in CONFIGS}
for c in CONFIGS:
    R = latest(run_dir / f"{c}.answers.jsonl")
    J = latest(judge_dir / f"{c}.judgments.jsonl", "key")
    data[c] = {}
    for i, row in answers.items():
        r = R.get(i)
        jd = find_judgment(row, r, J) if r and not r.get("error") else None
        if not jd or jd.get("judge_error"):
            continue
        pids = [e["parent_id"] for e in r.get("evidence") or [] if e.get("parent_id")]
        gold = row["gold_parents"]
        data[c][i] = dict(cov=sum(p["covered"] for p in jd["points"]) / len(jd["points"]), ok=int(jd["meaning_ok"]),
                          unsup=jd["unsupported_claims"], cite=int(bool(jd["citation_issues"])),
                          recall=sum(covered(g, pids) for g in gold) / len(gold) if gold else None,
                          length=len(r.get("answer") or ""), llm=r.get("llm_calls") or 0,
                          refused=r.get("route") in REFUSALS)
        for src, jp in zip(row["point_sources"], jd["points"]):
            if jp["covered"]:
                kind = "đạt"
            elif src.get("parent_id") is None:
                kind = "thiếu ý 'không có quy định'"
            elif r.get("route") in REFUSALS:
                kind = "lỗi phạm vi (từ chối)"
            elif covered(src["parent_id"], pids):
                kind = "lỗi sinh (căn cứ có trong ngữ cảnh)"
            else:
                kind = "lỗi truy xuất (căn cứ không có trong ngữ cảnh)"
            per_point[c].append((i, kind))
ids = sorted(set(data["full"]) & set(data["basic"]))

print(f"# Kết quả bộ kiểm tra chính ({', '.join(SETS)})\n")
print(f"Câu trả lời chấm được ở cả hai bản: {len(ids)}/{len(answers)}. "
      f"Thiếu: {sorted(set(answers) - set(ids))}\n")
print(f"## Hành vi ({len(questions)} câu)\n")
print("| | full | basic |\n|---|---|---|")
print(f"| Từ chối đúng câu ngoài phạm vi | {beh['full']['refuse']}/{beh['full']['n_out']} | {beh['basic']['refuse']}/{beh['basic']['n_out']} |")
print(f"| Từ chối nhầm câu trong phạm vi | {len(beh['full']['false'])}/{beh['full']['n_in']} {beh['full']['false']} | "
      f"{len(beh['basic']['false'])}/{beh['basic']['n_in']} {beh['basic']['false']} |")
print(f"| Lỗi chạy | {beh['full']['errors']} | {beh['basic']['errors']} |\n")

print("## Câu trả lời (so ghép cặp full − basic, CI95 bootstrap 2000, hạt giống 7)\n")
print("| Chỉ số | full | basic | Chênh [CI95] |\n|---|---:|---:|---|")
diffs = {}
for k, label in (("cov", "Phủ ý (chính)"), ("ok", "Đúng nghĩa"), ("unsup", "Khẳng định thiếu căn cứ TB"),
                 ("cite", "Có lỗi trích dẫn"), ("recall", "Recall ngữ cảnh"), ("length", "Độ dài TB"), ("llm", "Lượt LLM TB")):
    ks = [i for i in ids if data["full"][i][k] is not None and data["basic"][i][k] is not None]
    f = [data["full"][i][k] for i in ks]; b = [data["basic"][i][k] for i in ks]
    d = [x - y for x, y in zip(f, b)]; lo, hi = boot(d); diffs[k] = (sum(d) / len(d), lo, hi)
    print(f"| {label} | {sum(f)/len(f):.3f} | {sum(b)/len(b):.3f} | {sum(d)/len(d):+.3f} [{lo:+.3f}; {hi:+.3f}] |")

print("\n## Giả thuyết đặt trước\n")
f, b = beh["full"], beh["basic"]
d, lo, hi = diffs["cov"]
for name, ok, note in (
        ("H1 full từ chối đúng nhiều hơn basic", f["refuse"] > b["refuse"], f"{f['refuse']}/{f['n_out']} so với {b['refuse']}/{b['n_out']}"),
        (f"H2 full từ chối nhầm ≤ 1/24 (≤ {f['n_in'] // 24}/{f['n_in']})", len(f["false"]) <= f["n_in"] // 24, f"{len(f['false'])}/{f['n_in']}"),
        ("H3 phủ ý không kém quá 0,05", lo > -0.05, f"cận dưới {lo:+.3f}"),
        ("H4 phủ ý hơn basic", lo > 0, f"chênh {d:+.3f}, cận dưới {lo:+.3f}")):
    print(f"- {name}: **{'đạt' if ok else 'không đạt'}** ({note})")

print("\n## Theo tầng (chỉ mô tả)\n")
for field, title in (("topic", "Chủ đề"), ("type", "Dạng câu"), ("difficulty", "Độ khó")):
    groups = defaultdict(list)
    for i in ids:
        groups[answers[i][field]].append(i)
    print(f"| {title} | n | Phủ ý full | Phủ ý basic | Recall full | Recall basic |\n|---|---:|---:|---:|---:|---:|")
    for g, members in groups.items():
        m = lambda c, k: sum(data[c][i][k] or 0 for i in members) / len(members)
        print(f"| {LABEL.get(g, g)} | {len(members)} | {m('full', 'cov'):.2f} | {m('basic', 'cov'):.2f} | "
              f"{m('full', 'recall'):.2f} | {m('basic', 'recall'):.2f} |")
    print()

print("## Phân loại ý bắt buộc\n")
kinds = ["đạt", "lỗi truy xuất (căn cứ không có trong ngữ cảnh)", "lỗi sinh (căn cứ có trong ngữ cảnh)",
         "lỗi phạm vi (từ chối)", "thiếu ý 'không có quy định'"]
print("| Loại | full | basic |\n|---|---:|---:|")
for k in kinds:
    cnt = {c: sum(1 for i, x in per_point[c] if x == k and i in ids) for c in CONFIGS}
    tot = {c: sum(1 for i, _ in per_point[c] if i in ids) for c in CONFIGS}
    print(f"| {k} | {cnt['full']} ({cnt['full']/tot['full']:.0%}) | {cnt['basic']} ({cnt['basic']/tot['basic']:.0%}) |")

print("\n## Từng câu\n")
print("| id | chủ đề | dạng | phủ ý full | phủ ý basic | recall full | recall basic |\n|---|---|---|---:|---:|---:|---:|")
for i in ids:
    F, B = data["full"][i], data["basic"][i]
    print(f"| {i} | {LABEL.get(answers[i]['topic'])} | {LABEL.get(answers[i]['type'])} | {F['cov']:.2f} | {B['cov']:.2f} | "
          f"{F['recall']:.2f} | {B['recall']:.2f} |")
