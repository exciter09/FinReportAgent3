from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fin_report_agent.retrieval.embeddings import EmbeddingModel
from fin_report_agent.retrieval.rerank import Reranker
from fin_report_agent.retrieval.store import LanceDBChunkStore, SearchCandidate

COMPANY_ALIASES = {
    "APPLE": "AAPL",
    "APPLE INC": "AAPL",
    "苹果": "AAPL",
    "MICROSOFT": "MSFT",
    "MICROSOFT CORPORATION": "MSFT",
    "微软": "MSFT",
    "NVIDIA": "NVDA",
    "NVIDIA CORPORATION": "NVDA",
    "英伟达": "NVDA",
    "TESLA": "TSLA",
    "TESLA INC": "TSLA",
    "特斯拉": "TSLA",
    "AMAZON": "AMZN",
    "AMAZON.COM": "AMZN",
    "AMAZON.COM INC": "AMZN",
    "亚马逊": "AMZN",
}


@dataclass
class FilingSearcher:
    """执行 metadata filter、向量召回和 rerank 的检索服务。"""

    store: LanceDBChunkStore
    embedding_model: EmbeddingModel
    reranker: Reranker

    def search(
        self,
        query: str,
        *,
        companies: list[str] | None = None,
        years: list[int] | None = None,
        forms: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """检索财报 chunks，并返回 Agent 可直接阅读的结构化结果。"""

        filters = _build_filters(companies or [], years or [], forms or [])
        query_vector = self.embedding_model.embed_texts([query])[0]
        candidates = self.store.search(query_vector, filters=filters, limit=max(top_k * 5, 30))
        reranked = self.reranker.rerank(query, candidates, top_k=top_k)
        return {
            "query": query,
            "filters": filters,
            "results": [_format_candidate(candidate) for candidate in reranked],
        }


def _build_filters(companies: list[str], years: list[int], forms: list[str]) -> dict[str, list[Any]]:
    """把 tool 参数标准化成 LanceDB metadata filters。"""

    filters: dict[str, list[Any]] = {}
    normalized_companies = [_normalize_company(company) for company in companies if company]
    tickers = [company for company in normalized_companies if len(company) <= 8 and not company.isdigit()]
    ciks = [company for company in normalized_companies if company.isdigit()]
    if tickers:
        filters["ticker"] = tickers
    if ciks:
        filters["cik"] = ciks
    if years:
        filters["requested_year"] = years
    if forms:
        filters["form"] = [form.upper() for form in forms]
    return filters


def _normalize_company(company: str) -> str:
    """把常见公司名、中英文别名和 ticker 标准化为 ticker。"""

    value = company.strip().upper().replace(".", "")
    return COMPANY_ALIASES.get(value, value)


def _format_candidate(candidate: SearchCandidate) -> dict[str, Any]:
    """控制检索 tool 输出长度，同时保留回答需要的来源字段。"""

    row = candidate.record
    text = str(row.get("text", ""))
    if len(text) > 2500:
        text = text[:2500].rstrip() + "\n\n... (truncated)"
    return {
        "chunk_id": row.get("chunk_id"),
        "score": candidate.score,
        "company_name": row.get("company_name"),
        "ticker": row.get("ticker"),
        "cik": row.get("cik"),
        "requested_year": row.get("requested_year"),
        "form": row.get("form"),
        "filed_date": row.get("filed_date"),
        "report_period": row.get("report_period"),
        "section_path": row.get("section_path"),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "source_path": row.get("source_path"),
        "context_text": row.get("context_text"),
        "text": text,
    }
