"""Nhánh trả lời RAG cơ bản dùng lại prompt và bộ kiểm tra hiện có."""

import json
from pathlib import Path

from legal_rag.agent.config import MAX_QUERIES, AgentConfig
from legal_rag.agent.references import disambiguate_location
from legal_rag.retrieval.references import ReferenceGraph, expand_references

from legal_rag.generation.locations import build_location_index

from legal_rag.generation.citations import check_answer, normalize_citation_markers
from legal_rag.agent.blocks import apply_blocks, normalize_headings
from legal_rag.agent.presentation import present_answer, apply_presentation_errors
from legal_rag.generation.evidence import build_evidence
from legal_rag.generation.prompt import BROAD_VERSION, build_messages
from legal_rag.knowledge.frame import is_broad_obligation_query, load_frame
from legal_rag.llm import LLMError

PROFILE_LABELS = {"role": "Vai trò", "sector": "Lĩnh vực", "is_public_sector": "Thuộc khu vực công",
                  "generates_content": "Tạo nội dung", "product_description": "Mô tả sản phẩm",
                  "risk_level": "Mức rủi ro tự khai"}
VALUE_LABELS = {
    "nha_phat_trien": "nhà phát triển", "nha_cung_cap": "nhà cung cấp",
    "ben_trien_khai": "bên triển khai", "nguoi_su_dung": "người sử dụng",
    "giao_duc": "giáo dục", "y_te": "y tế", "tai_chinh_ngan_hang": "tài chính, ngân hàng",
    "dan_toc_ton_giao": "dân tộc, tôn giáo", "to_tung": "tố tụng",
    "giao_thong_van_tai": "giao thông vận tải", "thuong_mai": "thương mại",
    "quang_cao": "quảng cáo", "an_sinh_xa_hoi": "an sinh xã hội", "lam_dep": "làm đẹp",
    "lao_dong": "lao động", "khac": "khác",
    "cao": "cao", "trung_binh": "trung bình", "thap": "thấp", "chua_phan_loai": "chưa phân loại",
}


def profile_question(message, profile):
    lines = []
    for key, label in PROFILE_LABELS.items():
        value = profile.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            value = "có" if value else "không"
        elif key in ("role", "sector", "risk_level"):
            value = VALUE_LABELS[value]
        lines.append(f"- {label}: {value}")
    return message + ("\n\nThông tin đã biết về tình huống:\n" + "\n".join(lines) if lines else "")


# T61: câu trả lời thường của agent dùng cùng prompt với basic. Khuôn answer_v9 (Trả lời ngắn, Căn cứ, Giới hạn)
# bỏ sót ý dù căn cứ có trong ngữ cảnh. Câu hỏi nghĩa vụ cụ thể vì vậy không vào khuôn báo cáo V10–V12;
# câu rộng vẫn đi đường khung nghĩa vụ (BROAD_VERSION).
AGENT_ANSWER_VERSION = "answer_v2"


def prepare_evidence(pipeline_factory, parents, documents, chunks_loader=None,
                     config=AgentConfig(), references=()):
    pipeline = None
    chunks = index = graph = None
    if chunks_loader is None:
        def chunks_loader():
            path = Path(__file__).resolve().parents[3] / "data/processed/chunks.jsonl"
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def prepare(message, sub_queries, *, last_parents=(), rewritten=()):
        nonlocal pipeline, chunks, index, graph
        if chunks is None:
            chunks = chunks_loader()
            index = build_location_index(parents, chunks)
            graph = ReferenceGraph(references, parents, chunks)
        planned = (sub_queries or [message])[:1] if config.rerank_mode == "first" else (sub_queries or [message])
        # T59: câu gốc luôn là một truy vấn, sau truy vấn con, để không mất căn cứ mà câu gốc tìm được.
        queries = list(dict.fromkeys(disambiguate_location(message, q, last_parents, graph, chunks)
                                     for q in [*planned, message, *rewritten]))[:MAX_QUERIES]
        rerank_query = (message if config.rerank_mode == "message" else
                        " ".join(queries) if config.rerank_mode == "joined" else queries[0])
        detail, timing = {}, {}
        extra = []
        if is_broad_obligation_query(message):
            route, version = "broad_frame", BROAD_VERSION
            blocks = load_frame(Path(__file__).resolve().parents[1] / "knowledge/core_frame.yaml", parents)
            units = [dict(parent, block=block["label"]) for block in blocks for parent in block["parents"]]
        else:
            route, version = "retrieval", AGENT_ANSWER_VERSION
            if pipeline is None:
                pipeline = pipeline_factory()
            units = pipeline.context_many(queries, rerank_query, config.budget)
            detail, timing = pipeline.last_detail, pipeline.last_timing
            if config.enable_references:
                extra = expand_references(units, graph, parents, config.reference_budget,
                                          config.reference_top_units)
        items = build_evidence(units, documents, extra)
        for item in items:
            external = graph.external(item["parent_id"])
            if external:
                item["external_refs"] = external
        return dict(route=route, evidence=items, prompt_version=version,
                    parents_used=[item["parent_id"] for item in items],
                    query_used=queries[0], queries=queries, rerank_query=rerank_query,
                    references_added=[unit["parent_id"] for unit in extra],
                    detail=detail, timing=timing, index=index, chunks=chunks)

    return prepare


def generate_answer(message, sub_queries, profile, prepared, chat, model):
    question = profile_question(message, profile)
    if len(message.split()) < 8 and sub_queries:
        question += "\nCâu hỏi đầy đủ: " + sub_queries[0]
    items = prepared["evidence"]
    payload = dict(build_messages(question, items, prepared["prompt_version"],
                                  question_type=prepared.get("question_type", "khac"),
                                  presentation_context=prepared.get("presentation_context")), model=model)
    reply = chat.complete(payload)
    if not isinstance(reply, str) or not reply.strip():
        raise LLMError("Phản hồi sinh câu trả lời rỗng.")
    raw_reply = reply
    if prepared["prompt_version"] != "answer_v12":
        reply = normalize_citation_markers(reply)
        reply = normalize_headings(reply, prepared["prompt_version"], prepared.get("question_type", "khac"))
    reply, presentation = present_answer(reply, prepared.get("presentation_context"), prepared["prompt_version"],
        **(dict(items=items, index=prepared.get("index"), chunks=prepared.get("chunks"))
           if prepared["prompt_version"] == "answer_v12" else {}))
    check = check_answer(reply, items, prepared.get("index"), prepared.get("chunks"))
    apply_blocks(check, items, reply, prepared["prompt_version"], prepared.get("question_type", "khac"))
    if prepared.get("presentation_context") is not None:
        apply_presentation_errors(check, presentation["errors"])
    return dict(reply=reply, route=prepared["route"], evidence=items, check=check,
                prompt_version=prepared["prompt_version"], parents_used=prepared["parents_used"],
                query_used=prepared["query_used"], references_added=prepared["references_added"],
                messages=payload["messages"], raw_reply=raw_reply, presentation=presentation)
