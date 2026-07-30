from __future__ import annotations

from fin_report_agent.retrieval.chunker import DocumentChunk


def _content_type(text: str) -> str:
    """根据简单规则描述 chunk 内容类型，帮助 embedding 理解文本形态。"""

    has_table = any(line.strip().startswith("|") and line.strip().endswith("|") for line in text.splitlines())
    has_narrative = any(line.strip() and not line.strip().startswith("|") for line in text.splitlines())
    if has_table and has_narrative:
        return "table and narrative text"
    if has_table:
        return "table"
    return "narrative text"


def build_context_text(chunk: DocumentChunk) -> str:
    """为 chunk 生成规则化上下文描述，实现极简 Contextual Retrieval。"""

    metadata = chunk.metadata
    company = metadata.company_name or metadata.ticker or metadata.cik or "Unknown company"
    filing = f"{metadata.requested_year or ''} {metadata.form or 'filing'}".strip()
    dates = []
    if metadata.filed_date:
        dates.append(f"filed {metadata.filed_date}")
    if metadata.report_period:
        dates.append(f"report period {metadata.report_period}")
    section = " > ".join(chunk.section_path) if chunk.section_path else "Unknown section"

    return "\n".join(
        [
            "[Chunk context]",
            f"Company: {company} ({metadata.ticker or metadata.cik or 'unknown identifier'})",
            f"Filing: {filing}" + (f", {', '.join(dates)}" if dates else ""),
            f"Section: {section}",
            f"Content type: {_content_type(chunk.text)}",
            "This chunk is from an SEC 10-K/10-Q filing and should be used as source-grounded evidence.",
        ]
    )


def attach_context(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """把上下文描述写回 chunk，并生成真正用于 embedding 的 indexed_text。"""

    for chunk in chunks:
        chunk.context_text = build_context_text(chunk)
        chunk.indexed_text = f"{chunk.context_text}\n\n{chunk.text}"
    return chunks
