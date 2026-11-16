"""Bổ sung văn bản cho câu hỏi vị trí có ngữ cảnh duy nhất."""

from legal_rag.retrieval.exact import document_candidates, parse_location


def disambiguate_location(message, query, last_parents, graph, chunks):
    locations = parse_location(message)
    if not locations or document_candidates(message, chunks)[0]:
        return query
    documents = set()
    for location in locations:
        article = location["article"]
        documents.update(graph.articles_mentioned(last_parents, article))
        documents.update(parent["document_id"] for pid in last_parents
                         if (parent := graph.parents.get(pid)) and parent.get("article") == article)
    if len(documents) == 1:
        return query + " " + next(iter(documents)).replace("-", "/", 2)
    return query
