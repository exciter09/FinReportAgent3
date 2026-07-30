from __future__ import annotations

from pathlib import Path
from typing import Any

from fin_report_agent.eval.dataset import read_jsonl
from fin_report_agent.eval.fixtures import write_fixture_filings
from fin_report_agent.eval.memory import KeywordReranker, build_eval_store, noop_reranker
from fin_report_agent.eval.metrics import mean, mrr_at_k, ndcg_at_k, recall_at_k
from fin_report_agent.retrieval.search import FilingSearcher


def run_retrieval_eval(eval_dir: Path) -> dict[str, Any]:
    """运行第一层检索评测：vector baseline、metadata filter 和 full pipeline。"""

    filing_paths = write_fixture_filings(eval_dir)
    cases = read_jsonl(eval_dir / "retrieval_cases.jsonl")
    variants = {
        "vector_only": {"use_context": False, "use_filters": False, "reranker": noop_reranker()},
        "metadata_filter": {"use_context": False, "use_filters": True, "reranker": noop_reranker()},
        "full_context_rerank": {"use_context": True, "use_filters": True, "reranker": KeywordReranker()},
    }

    summary: dict[str, Any] = {}
    details: dict[str, list[dict[str, Any]]] = {}
    for name, settings in variants.items():
        store, embedding_model = build_eval_store(filing_paths, use_context=bool(settings["use_context"]))
        searcher = FilingSearcher(store, embedding_model, settings["reranker"])
        rows: list[dict[str, Any]] = []

        for case in cases:
            payload = case.payload
            result = searcher.search(
                payload["query"],
                companies=payload.get("companies") if settings["use_filters"] else None,
                years=payload.get("years") if settings["use_filters"] else None,
                forms=payload.get("forms") if settings["use_filters"] else None,
                top_k=10,
            )
            gold_terms = [term.lower() for term in payload["gold_terms"]]
            relevant = lambda item: _is_relevant(item, gold_terms)
            rows.append(
                {
                    "id": case.case_id,
                    "recall_at_5": recall_at_k(result["results"], relevant, 5),
                    "mrr_at_10": mrr_at_k(result["results"], relevant, 10),
                    "ndcg_at_10": ndcg_at_k(result["results"], relevant, 10),
                    "metadata_match_at_5": _metadata_match_at_k(result["results"], payload, 5),
                    "top_chunk": result["results"][0]["chunk_id"] if result["results"] else None,
                    "applied_filters": result["filters"],
                }
            )

        details[name] = rows
        summary[name] = {
            "case_count": len(rows),
            "recall_at_5": mean([row["recall_at_5"] for row in rows]),
            "mrr_at_10": mean([row["mrr_at_10"] for row in rows]),
            "ndcg_at_10": mean([row["ndcg_at_10"] for row in rows]),
            "metadata_match_at_5": mean([row["metadata_match_at_5"] for row in rows]),
        }

    return {"summary": summary, "details": details}


def _is_relevant(result: dict[str, Any], gold_terms: list[str]) -> bool:
    """判断结果是否包含任一人工标注 gold term。"""

    haystack = f"{result.get('context_text', '')}\n{result.get('text', '')}".lower()
    return any(term in haystack for term in gold_terms)


def _metadata_match_at_k(results: list[dict[str, Any]], payload: dict[str, Any], k: int) -> float:
    """计算 top k 中 metadata 与标注公司、年份、表单一致的比例。"""

    top = results[:k]
    if not top:
        return 0.0
    companies = {company.upper() for company in payload.get("companies", [])}
    years = set(payload.get("years", []))
    forms = {form.upper() for form in payload.get("forms", [])}
    matches = 0
    for result in top:
        if companies and result.get("ticker") not in companies:
            continue
        if years and result.get("requested_year") not in years:
            continue
        if forms and result.get("form") not in forms:
            continue
        matches += 1
    return matches / len(top)
