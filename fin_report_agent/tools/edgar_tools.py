from __future__ import annotations

from typing import Any

from fin_report_agent.agent.tool_registry import Tool
from fin_report_agent.config import AppConfig
from fin_report_agent.mcp_client.edgar import EdgarMCPClient


def build_edgar_tools(config: AppConfig) -> list[Tool]:
    """创建 EDGAR MCP 相关 tools，让 Agent 能解析公司并下载财报。"""

    client = EdgarMCPClient(config)

    async def resolve_company(company_name: str, limit: int = 10) -> dict[str, Any]:
        """调用 MCP server 解析公司，返回候选项供模型判断或澄清。"""

        return await client.call_tool(
            "resolve_company_name",
            {"company_name": company_name, "limit": limit},
        )

    async def download_filing_markdown(
        company_name: str,
        year: int,
        form_type: str = "both",
        max_filings: int | None = None,
    ) -> dict[str, Any]:
        """下载指定年份的 10-K/10-Q markdown，并返回本地路径。"""

        result = await client.call_tool(
            "download_10k_10q_markdown",
            {
                "company_name": company_name,
                "year": year,
                "form_type": form_type,
                "output_dir": str(config.filings_dir),
                "max_filings": max_filings,
                "include_content": False,
            },
        )
        return _compact_download_result(result)

    return [
        Tool(
            name="resolve_company",
            description=(
                "解析美股公司名称、ticker 或 CIK。用户给中文公司名、英文简称或可能歧义的公司名时调用。"
                "如果返回多个候选且无法确定，应继续调用 ask_user_clarification。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "用户输入的公司名、ticker 或 CIK"},
                    "limit": {"type": "integer", "description": "最多返回候选数量", "default": 10},
                },
                "required": ["company_name"],
            },
            handler=resolve_company,
        ),
        Tool(
            name="download_filing_markdown",
            description=(
                "下载指定公司、年份和 10-K/10-Q 类型的 SEC 财报 markdown。"
                "仅在本地缺少该财报或 search_filings 提示未索引时调用。下载后通常要调用 index_filing_markdown 建立索引。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名、ticker 或 CIK"},
                    "year": {"type": "integer", "description": "SEC filing year，例如 2023"},
                    "form_type": {"type": "string", "enum": ["10-K", "10-Q", "both"], "default": "both"},
                    "max_filings": {"type": "integer", "description": "最多下载几份 filings，可空"},
                },
                "required": ["company_name", "year", "form_type"],
            },
            handler=download_filing_markdown,
        ),
    ]


def _compact_download_result(result: dict[str, Any]) -> dict[str, Any]:
    """压缩 MCP 下载响应，避免预览正文占用模型上下文。"""

    compact = {key: value for key, value in result.items() if key not in {"preview", "content"}}
    filings = compact.get("filings")
    if isinstance(filings, list):
        compact["filings"] = [
            {
                "status": item.get("status"),
                "form": item.get("form"),
                "filed_date": item.get("filed_date"),
                "report_period": item.get("report_period"),
                "accession_number": item.get("accession_number"),
                "path": item.get("path"),
                "filing_url": item.get("filing_url"),
                "homepage_url": item.get("homepage_url"),
            }
            for item in filings
            if isinstance(item, dict)
        ]
    if compact.get("success"):
        compact["next_step"] = "请调用 index_filing_markdown 为返回的 path 建立索引，然后再调用 search_filings 检索原文。"
    return compact
