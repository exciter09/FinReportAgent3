from __future__ import annotations

from pathlib import Path
from typing import Any

from fin_report_agent.agent.tool_registry import Tool
from fin_report_agent.config import AppConfig
from fin_report_agent.retrieval.embeddings import EmbeddingModel, create_embedding_model
from fin_report_agent.retrieval.ingest import ingest_markdown
from fin_report_agent.retrieval.rerank import Reranker, create_reranker
from fin_report_agent.retrieval.search import FilingSearcher
from fin_report_agent.retrieval.store import LanceDBChunkStore


class RetrievalRuntime:
    """延迟创建检索依赖，避免 TUI 启动时立刻加载本地大模型。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        store: LanceDBChunkStore | None = None,
        embedding_model: EmbeddingModel | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.config = config
        self._store = store
        self._embedding_model = embedding_model
        self._reranker = reranker
        self._searcher: FilingSearcher | None = None

    def store(self) -> LanceDBChunkStore:
        """懒加载 LanceDB store，只有索引或检索时才初始化。"""

        if self._store is None:
            self._store = LanceDBChunkStore(self.config.lancedb_dir)
        return self._store

    def embedding_model(self) -> EmbeddingModel:
        """懒加载 embedding 模型，避免普通聊天阶段浪费启动时间。"""

        if self._embedding_model is None:
            self._embedding_model = create_embedding_model()
        return self._embedding_model

    def reranker(self) -> Reranker:
        """懒加载 reranker，只有 search_filings 真正执行时才加载。"""

        if self._reranker is None:
            self._reranker = create_reranker()
        return self._reranker

    def searcher(self) -> FilingSearcher:
        """组合 store、embedding 和 reranker 成完整检索服务。"""

        if self._searcher is None:
            self._searcher = FilingSearcher(self.store(), self.embedding_model(), self.reranker())
        return self._searcher


def build_retrieval_tools(config: AppConfig, runtime: RetrievalRuntime | None = None) -> list[Tool]:
    """创建索引和检索 tools，实现 Agentic RAG 的检索入口。"""

    retrieval = runtime or RetrievalRuntime(config)

    def index_filing_markdown(path: str) -> dict[str, Any]:
        """把指定 markdown 文件写入 LanceDB，供后续 search_filings 使用。"""

        markdown_path = Path(path).expanduser().resolve()
        if not markdown_path.exists():
            return {"success": False, "error": f"文件不存在：{markdown_path}"}
        result = ingest_markdown(markdown_path, retrieval.store(), retrieval.embedding_model())
        return {
            "success": result.success,
            "source_path": result.source_path,
            "chunk_count": result.chunk_count,
            "error": result.error,
        }

    def search_filings(
        query: str,
        companies: list[str] | None = None,
        years: list[int] | None = None,
        forms: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """按 metadata filter、向量召回和 rerank 检索财报 chunks。"""

        try:
            result = retrieval.searcher().search(
                query,
                companies=companies,
                years=years,
                forms=forms,
                top_k=top_k,
            )
            if not result["results"]:
                result["suggestion"] = "未找到已索引财报片段；如本地没有索引，请先调用 download_filing_markdown 和 index_filing_markdown。"
            result["success"] = True
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    return [
        Tool(
            name="index_filing_markdown",
            description=(
                "把 download_filing_markdown 返回的本地 markdown path 建成结构感知向量索引。"
                "当财报刚下载完成或 search_filings 提示没有索引时调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "本地 markdown 文件绝对路径或相对路径"}
                },
                "required": ["path"],
            },
            handler=index_filing_markdown,
        ),
        Tool(
            name="search_filings",
            description=(
                "Search indexed 10-K/10-Q filing chunks. Before calling this tool, rewrite the user's question "
                "into a focused financial filing search query. Include normalized company, fiscal year, form type, "
                "financial metric names, and likely SEC section names when known. Use metadata filters whenever "
                "the company, ticker, year, or form is known. Do not use this tool for arithmetic; use "
                "calculate_decimal after retrieving numeric facts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "改写后的检索查询，尽量包含英文财务术语和相关 SEC section",
                    },
                    "companies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "公司名、ticker 或 CIK；明确时必须填写",
                    },
                    "years": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "请求年份；明确时必须填写",
                    },
                    "forms": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["10-K", "10-Q"]},
                        "description": "财报类型；明确时必须填写",
                    },
                    "top_k": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
            handler=search_filings,
        ),
    ]
