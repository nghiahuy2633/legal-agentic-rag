"""Điều kiện có cấu trúc, đánh giá bằng logic ba trị."""

from legal_rag.knowledge.facts import (
    EFFECTIVE_DATES, FACT_FIELDS, FACT_LABELS, valid_date, valid_scalar,
)


def validate_condition(expr, path="$"):
    def fail(message):
        raise ValueError(f"{path}: {message}")

    if expr is None:
        return
    if not isinstance(expr, dict):
        fail("phải là biểu thức hoặc None")
    for key in ("all", "any", "not"):
        if key in expr:
            if set(expr) != {key}:
                fail("thừa khóa")
            if key == "not":
                validate_condition(expr[key], f"{path}.not")
            else:
                if not isinstance(expr[key], list):
                    fail(f"{key} phải là danh sách")
                for i, child in enumerate(expr[key]):
                    validate_condition(child, f"{path}.{key}[{i}]")
            return
    name, op = expr.get("fact"), expr.get("op")
    if not isinstance(name, str) or name not in FACT_FIELDS:
        fail("tên fact không hợp lệ")
    spec = FACT_FIELDS[name]
    allowed = {"bool": ("eq", "ne", "in", "is_true", "is_false"),
               "str": ("eq", "ne", "in"),
               "list": ("eq", "ne", "in", "contains", "overlaps"),
               "date": ("eq", "ne", "in", "lt", "lte", "gt", "gte")}[spec["type"]]
    if op not in allowed:
        fail("op không hợp kiểu trường")
    expected = {"fact", "op"} if op in ("is_true", "is_false") else {"fact", "op", "value"}
    if set(expr) != expected:
        fail("thiếu hoặc thừa khóa")
    if "value" not in expr:
        return
    value = expr["value"]
    if op in ("lt", "lte", "gt", "gte"):
        valid = isinstance(value, str) and (value in EFFECTIVE_DATES or valid_date(value))
    else:
        def scalar(v):
            return valid_scalar(spec, v)

        def field_value(v):
            return (isinstance(v, list) and all(scalar(x) for x in v)
                    if spec["type"] == "list" else scalar(v))

        if op == "contains":
            valid = scalar(value)
        elif op == "overlaps":
            valid = isinstance(value, list) and all(scalar(v) for v in value)
        elif op == "in":
            valid = isinstance(value, list) and all(field_value(v) for v in value)
        else:
            valid = field_value(value)
    if not valid:
        fail("value sai kiểu hoặc ngoài tập cho phép")


def evaluate(expr, facts):
    validate_condition(expr)
    return _evaluate(expr, facts)


def _evaluate(expr, facts):
    if expr is None:
        return True
    for key, decisive, identity in (("all", False, True), ("any", True, False)):
        if key in expr:
            values = [_evaluate(child, facts) for child in expr[key]]
            if decisive in values:
                return decisive
            return None if None in values else identity
    if "not" in expr:
        value = _evaluate(expr["not"], facts)
        return None if value is None else not value
    actual = facts.get(expr["fact"])
    if actual is None:
        return None
    op, value = expr["op"], expr.get("value")
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "in":
        return actual in value
    if op == "contains":
        return value in actual
    if op == "overlaps":
        return bool(set(actual) & set(value))
    value = EFFECTIVE_DATES.get(value, value)
    if op == "lt":
        return actual < value
    if op == "lte":
        return actual <= value
    if op == "gt":
        return actual > value
    return actual >= value


def missing_facts(expr, facts):
    validate_condition(expr)
    def visit(node):
        if node is None or _evaluate(node, facts) is not None:
            return []
        if "fact" in node:
            return [node["fact"]]
        if "not" in node:
            return visit(node["not"])
        return [name for child in node.get("all", node.get("any", [])) for name in visit(child)]
    return list(dict.fromkeys(visit(expr)))


def describe(expr):
    validate_condition(expr)
    if expr is None:
        return "luôn áp dụng"
    for key, joiner in (("all", " và "), ("any", " hoặc ")):
        if key in expr:
            return joiner.join(f"({describe(child)})" for child in expr[key]) or (
                "luôn áp dụng" if key == "all" else "không áp dụng")
    if "not" in expr:
        return f"không ({describe(expr['not'])})"
    label, op = FACT_LABELS[expr["fact"]], expr["op"]
    if op in ("is_true", "is_false"):
        return f"{label}: {'có' if op == 'is_true' else 'không'}"
    value = expr["value"]
    if op in ("lt", "lte", "gt", "gte"):
        key = value
        year, month, day = EFFECTIVE_DATES.get(key, key).split("-")
        value = f"{day}/{month}/{year}"
        if key in EFFECTIVE_DATES:
            title = {"luat_134": "Luật 134", "nd_142": "NĐ 142", "qd_33": "QĐ 33", "tt_05": "TT 05"}[key]
            value += f" ({title} có hiệu lực)"
    elif isinstance(value, list):
        value = ", ".join(map(str, value)) or "danh sách rỗng"
    elif type(value) is bool:
        value = "có" if value else "không"
    operator = {"eq": "bằng", "ne": "khác", "in": "thuộc", "contains": "chứa",
                "overlaps": "có phần chung với", "lt": "trước", "lte": "vào hoặc trước",
                "gt": "sau", "gte": "vào hoặc sau"}[op]
    return f"{label} {operator} {value}"
