import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from gold import gold_items, CAM, G, NEUTRAL
from products import PRODUCTS, MESSAGE_FACTS
chunks = {json.loads(l)["chunk_id"] for l in open("data/processed/chunks.jsonl", encoding="utf-8")}
bad = sorted({x for g in G.values() for x in g[3] if x not in chunks} | {x for x in CAM.values() if x not in chunks}
             | {x for units, _ in NEUTRAL.values() for x in units if x not in chunks})
assert not bad, bad
out = []
for p in PRODUCTS:
    items = gold_items(p["facts"], p.get("optional"))
    ids = {i["gid"] for i in items}
    extra = set(p["status"]) - ids
    assert not extra, (p["id"], extra)
    for i in items:
        if not i.get("neutral"):
            i["status"] = p["status"].get(i["gid"], "chua_ro")
    out.append(dict(id=p["id"], kind=p["kind"], message=p["message"], description=p["description"],
                    statement=p["statement"], facts=p["facts"], message_facts=MESSAGE_FACTS[p["id"]], gold=items,
                    gold_warnings=[CAM[c] for c in p.get("warnings", [])],
                    gold_warnings_optional=[CAM[c] for c in p.get("warnings_optional", [])],
                    decisions=p.get("decisions", []), notes=p["notes"], review_status="user_reviewed"))
    print(p["id"], sum(not i.get("neutral") for i in items), "nghĩa vụ chuẩn,", sum(not i["optional"] for i in items), "bắt buộc")
Path("eval/assessments.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8", newline="\n")
