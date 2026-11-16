"""T22: dữ liệu thật, phản hồi giả; không tải model hoặc gọi dịch vụ."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from legal_rag.knowledge import high_risk as hr

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding="utf-8").splitlines() if line.strip()]


ITEMS = read("data/processed/high_risk_list.jsonl")
PARENTS = read("data/processed/parents.jsonl")
ROBOT = next(i for i in ITEMS if i["item_id"] == hr.PREFIX + "III_stt-2")


class Chat:
    def __init__(self, response):
        self.response = response if isinstance(response, str) else json.dumps(response)
        self.payloads = []

    def complete(self, payload):
        self.payloads.append(payload)
        return self.response


def response(statuses, key=ROBOT["item_id"]):
    return dict(items=[dict(item_id=key, conditions=[dict(index=i, status=s, basis="dữ kiện", text="chữ bịa")
                 for i, s in enumerate(statuses, 1)])])


def script(name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_corpus():
    assert len(ITEMS) == 46
    assert sum(bool(hr.BULLET.search(i["description"])) for i in ITEMS) == 38
    assert sum(not hr.BULLET.search(i["description"]) for i in ITEMS) == 8
    for item in ITEMS:
        split = hr.split_conditions(item)
        assert " ".join(" ".join([split["lead"], *split["conditions"]]).split()) == " ".join(
            hr.BULLET.sub("", item["description"]).split())
    for key, count in [("III_stt-2", 2), ("I_stt-2", 3), ("I_stt-3", 1), ("IV_stt-2", 3)]:
        item = next(i for i in ITEMS if i["item_id"] == hr.PREFIX + key)
        assert len(hr.split_conditions(item)["conditions"]) == count
    assert hr.split_conditions(dict(description="- rô-bốt - dòng hai")) == dict(lead="", conditions=["rô-bốt", "dòng hai"])
    assert hr.split_conditions(dict(description="rô-bốt")) == dict(lead="", conditions=["rô-bốt"])


def test_candidates():
    a, b = ITEMS[:2]
    hits = [dict(chunk_id="ngoài"), dict(chunk_id=b["item_id"]), dict(chunk_id=b["item_id"]), dict(chunk_id=a["item_id"])]
    assert hr.candidate_items(hits, ITEMS) == [b, a]
    assert hr.candidate_items(hits, ITEMS, 1) == [b]
    assert hr.candidate_items(hits, ITEMS, 0) == []


@pytest.mark.parametrize("statuses,expected", [
    (["dap_ung", "dap_ung"], "khop"), (["dap_ung", "chua_ro"], "co_the_khop"),
    (["dap_ung", "khong_dap_ung"], "khong_khop"),
    (["khong_dap_ung", "chua_ro"], "khong_khop"),
    (["khong_dap_ung", "khong_dap_ung"], "khong_khop")])
def test_rules(statuses, expected):
    row = response(statuses)["items"][0]
    assert hr.item_status(row) == expected
    assert hr.overall_status([row]) == ("khong_thay" if expected == "khong_khop" else expected)


def test_overall_priority():
    yes = response(["dap_ung"])["items"][0]
    maybe = response(["chua_ro"])["items"][0]
    assert hr.overall_status([maybe, yes]) == "khop"
    assert hr.overall_status([]) == "khong_thay"
    assert hr.item_status(dict(conditions=[])) == "co_the_khop"


def test_payload_and_original_text():
    chat = Chat(response(["dap_ung", "dap_ung"]))
    result = hr.assess_items("dữ kiện", [ROBOT], chat, "fake")
    payload = chat.payloads[0]
    assert payload["temperature"] == 0
    assert payload["response_format"] == dict(type="json_object")
    assert payload["model"] == "fake"
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["description"] == "dữ kiện"
    assert sent["items"][0]["lead"] == hr.split_conditions(ROBOT)["lead"]
    assert [c["index"] for c in sent["items"][0]["conditions"]] == [1, 2]
    assert result["assess_ok"]
    assert [c["text"] for c in result["items"][0]["conditions"]] == hr.split_conditions(ROBOT)["conditions"]


@pytest.mark.parametrize("value,ok", [("hỏng", False), ("[]", False), ("null", False),
    ({"items": None}, False), ({"items": []}, True),
    (response(["lạ"]), True), (response(["dap_ung"], "ngoài"), True)])
def test_invalid_missing_unknown(value, ok):
    chat = Chat(value)
    result = hr.assess_items("dữ kiện", [ROBOT], chat, "fake")
    assert result["assess_ok"] is ok
    assert len(chat.payloads) == 1
    assert len(result["items"]) == 1
    assert [c["status"] for c in result["items"][0]["conditions"]] == ["chua_ro", "chua_ro"]


def test_missing_basis_condition_and_extra_item():
    value = response(["dap_ung"])
    value["items"][0]["conditions"][0].pop("basis")
    value["items"].append(dict(item_id="ngoài", conditions=[]))
    result = hr.assess_items("dữ kiện", [ROBOT], Chat(value), "fake")
    assert [c["status"] for c in result["items"][0]["conditions"]] == ["chua_ro", "chua_ro"]
    assert all(c["basis"] is None for c in result["items"][0]["conditions"])
    assert len(result["items"]) == 1
    partial = hr.assess_items("dữ kiện", [ROBOT], Chat(response(["dap_ung"])), "fake")
    assert [c["status"] for c in partial["items"][0]["conditions"]] == ["dap_ung", "chua_ro"]


def test_no_candidates_and_prompt_version(tmp_path, monkeypatch):
    chat = Chat("hỏng")
    assert hr.assess_items("x", [], chat, "fake") == dict(items=[], assess_ok=True)
    assert not chat.payloads
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Sai phiên bản", encoding="utf-8")
    monkeypatch.setattr(hr, "PROMPT_PATH", prompt)
    with pytest.raises(ValueError, match="Sai phiên bản"):
        hr.assess_items("x", [ROBOT], chat, "fake")
    assert not chat.payloads


@pytest.mark.parametrize("statuses", [[], ["dap_ung", "dap_ung"], ["chua_ro", "chua_ro"],
                                      ["khong_dap_ung", "khong_dap_ung"]])
def test_render(statuses):
    result = response(statuses) if statuses else dict(items=[])
    rendered = hr.render_assessment("sản phẩm", result, ITEMS, PARENTS)
    text = rendered["text"]
    assert hr.CONNECTOR_NOTE not in text  # T57: không chèn nhận định không gắn nguồn
    for key in hr.FIXED_PARENTS:
        assert key in rendered["parent_ids"]
        # T57: căn cứ cố định chỉ nêu tên; nguyên văn và đường dẫn ở Căn cứ pháp lý.
        parent = next(p for p in PARENTS if p["parent_id"] == key)
        assert "- " + hr.fixed_label(key, parent) in text and parent["text"] not in text
    assert "Danh sách trên chỉ để tham khảo." in text and "Mức rủi ro do doanh nghiệp tự phân loại" not in text
    assert "Sản phẩm khớp" not in text and "Sản phẩm có thể khớp" not in text
    assert "không thấy trong Danh mục" not in text
    if statuses:
        assert ROBOT["name"] in text
        split = hr.split_conditions(ROBOT)
        assert split["lead"] in text
        # Giữa hai nguyên văn điều kiện chỉ có nhãn trạng thái và số thứ tự.
        between = text.split(split["conditions"][0], 1)[1].split(split["conditions"][1], 1)[0]
        assert "và" not in between and "hoặc" not in between
        assert "chữ bịa" not in text


def test_render_max_three():
    result = dict(items=[dict(item_id=i["item_id"], conditions=[]) for i in ITEMS[:5]])
    rendered = hr.render_assessment("x", result, ITEMS, PARENTS)
    assert rendered["parent_ids"] == [i["item_id"] for i in ITEMS[:3]] + list(hr.FIXED_PARENTS)


def test_coverage_and_dry_run(monkeypatch, capsys):
    module = script("eval_high_risk", monkeypatch)
    def forbidden(*args):
        pytest.fail("dry-run không được tạo runtime")
    assert module.main(["--dry-run"], runtime_factory=forbidden) == 0
    assert "46/46" in capsys.readouterr().out
    covered = module.coverage(ITEMS, PARENTS)
    assert covered == dict(passed=46, total=46, conformity=dict(diem_a=6, diem_b=40), fixed_parents=3, errors=[])


def test_cli_trace_and_eval_fake(tmp_path, monkeypatch):
    module = script("eval_high_risk", monkeypatch)
    cli = sys.modules["check_high_risk"]
    for name in ["data/processed/high_risk_list.jsonl", "data/processed/parents.jsonl",
                 "data/processed/chunks.jsonl", "eval/high_risk_cases.jsonl"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    class Pipeline:
        def search(self, description):
            return [dict(chunk_id=ROBOT["item_id"], score=1)]
    runtime = lambda *args: (Pipeline(), Chat(response(["dap_ung", "dap_ung"])), "fake")
    assert module.main([], root=tmp_path, runtime_factory=runtime) == 0
    report = json.loads((tmp_path / "runs/t22/high_risk.json").read_text(encoding="utf-8"))
    assert report["total"] == 10
    assert report["items_total"] == 5
    assert report["mismatches"]
    assert all(r["assessment"]["items"][0]["conditions"] for r in report["mismatches"])
    monkeypatch.setattr(cli, "make_runtime", runtime)
    assert cli.main(["--description", "robot", "--trace-dir", str(tmp_path / "trace")], root=tmp_path) == 0
    trace = json.loads(next((tmp_path / "trace").glob("*.json")).read_text(encoding="utf-8"))
    assert trace["candidates"] == [ROBOT["item_id"]]
    assert trace["rendered"]["status"] == "khop"
