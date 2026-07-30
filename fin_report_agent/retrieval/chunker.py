from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from fin_report_agent.retrieval.metadata import FilingMetadata


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
ITEM_RE = re.compile(r"^(?:\*\*)?\s*Item\s+\d+[A-Z]?(?:\.)?\s+.+", re.IGNORECASE)
PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)


@dataclass
class DocumentChunk:
    """一个可被 embedding 和检索返回的结构感知文本块。"""

    chunk_id: str
    text: str
    context_text: str
    indexed_text: str
    metadata: FilingMetadata
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int


@dataclass
class _Section:
    """chunker 内部使用的 section，表示一个标题路径下的连续文本。"""

    path: list[str]
    lines: list[str]


def _strip_metadata_header(markdown: str) -> str:
    """移除 MCP 写入的 metadata header，避免它污染正文检索。"""

    marker = "\n---\n\n"
    if marker in markdown:
        return markdown.split(marker, 1)[1]
    return markdown


def _estimate_tokens(text: str) -> int:
    """用字符数粗估 token 数；教学项目先避免引入额外 tokenizer。"""

    return max(1, len(text) // 4)


def _page_range(text: str) -> tuple[int | None, int | None]:
    """从 chunk 文本中提取页码范围，方便最终回答给来源定位。"""

    pages = [int(match.group(1)) for match in PAGE_RE.finditer(text)]
    if not pages:
        return None, None
    return min(pages), max(pages)


def _is_table_line(line: str) -> bool:
    """识别 markdown 表格行，切块时尽量保持表格完整。"""

    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _split_blocks(lines: list[str]) -> list[str]:
    """按段落和表格块切分 section，为后续长度控制做准备。"""

    blocks: list[str] = []
    current: list[str] = []
    in_table = False

    for line in lines:
        table_line = _is_table_line(line)
        if table_line:
            if current and not in_table:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line)
            in_table = True
            continue

        if in_table:
            blocks.append("\n".join(current).strip())
            current = []
            in_table = False

        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current).strip())
            current = []

    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _chunk_id(metadata: FilingMetadata, index: int, text: str) -> str:
    """生成稳定 chunk id，避免同一财报重复索引时难以追踪。"""

    company = metadata.ticker or metadata.cik or "filing"
    year = metadata.requested_year or "year"
    form = (metadata.form or "form").replace("-", "")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{company}-{year}-{form}-{index:04d}-{digest}"


def _section_title(line: str) -> str | None:
    """识别 markdown 标题或 SEC Item 标题，作为结构切块边界。"""

    heading = HEADING_RE.match(line)
    if heading:
        return heading.group(2).strip()
    if ITEM_RE.match(line.strip()):
        return line.strip().strip("*")
    return None


def _sections(markdown: str) -> list[_Section]:
    """把 markdown 正文按标题和 SEC Item 切成结构 section。"""

    lines = _strip_metadata_header(markdown).splitlines()
    sections: list[_Section] = []
    current_path: list[str] = ["Document"]
    current_lines: list[str] = []

    for line in lines:
        title = _section_title(line)
        if title:
            if current_lines:
                sections.append(_Section(path=current_path, lines=current_lines))
                current_lines = []
            current_path = [title]
            current_lines.append(line)
            continue
        current_lines.append(line)

    if current_lines:
        sections.append(_Section(path=current_path, lines=current_lines))
    return sections


def chunk_markdown(
    markdown: str,
    metadata: FilingMetadata,
    *,
    target_chars: int = 4200,
    overlap_chars: int = 500,
) -> list[DocumentChunk]:
    """进行结构感知切块；context 字段稍后由 contextual.py 填充。"""

    chunks: list[DocumentChunk] = []
    for section in _sections(markdown):
        blocks = _split_blocks(section.lines)
        current: list[str] = []
        current_len = 0

        for block in blocks:
            block_len = len(block)
            if current and current_len + block_len > target_chars:
                text = "\n\n".join(current).strip()
                page_start, page_end = _page_range(text)
                chunks.append(
                    DocumentChunk(
                        chunk_id=_chunk_id(metadata, len(chunks) + 1, text),
                        text=text,
                        context_text="",
                        indexed_text=text,
                        metadata=metadata,
                        section_path=section.path,
                        page_start=page_start,
                        page_end=page_end,
                        token_count=_estimate_tokens(text),
                    )
                )
                overlap = text[-overlap_chars:].strip()
                current = [overlap, block] if overlap else [block]
                current_len = sum(len(item) for item in current)
            else:
                current.append(block)
                current_len += block_len

        if current:
            text = "\n\n".join(current).strip()
            page_start, page_end = _page_range(text)
            chunks.append(
                DocumentChunk(
                    chunk_id=_chunk_id(metadata, len(chunks) + 1, text),
                    text=text,
                    context_text="",
                    indexed_text=text,
                    metadata=metadata,
                    section_path=section.path,
                    page_start=page_start,
                    page_end=page_end,
                    token_count=_estimate_tokens(text),
                )
            )
    return chunks
