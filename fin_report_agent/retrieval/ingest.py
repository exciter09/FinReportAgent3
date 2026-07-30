from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fin_report_agent.retrieval.chunker import DocumentChunk, chunk_markdown
from fin_report_agent.retrieval.contextual import attach_context
from fin_report_agent.retrieval.embeddings import EmbeddingModel
from fin_report_agent.retrieval.metadata import parse_metadata_file
from fin_report_agent.retrieval.store import LanceDBChunkStore


@dataclass
class IngestResult:
    """一次 markdown 索引构建的结果摘要。"""

    success: bool
    source_path: str
    chunk_count: int
    error: str | None = None


def chunk_to_record(chunk: DocumentChunk, vector: list[float]) -> dict[str, Any]:
    """把 DocumentChunk 转成 LanceDB 行记录。"""

    metadata = chunk.metadata.to_dict()
    return {
        "chunk_id": chunk.chunk_id,
        "text": chunk.text,
        "context_text": chunk.context_text,
        "indexed_text": chunk.indexed_text,
        "vector": vector,
        "section_path": chunk.section_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "token_count": chunk.token_count,
        **metadata,
    }


def ingest_markdown(path: Path, store: LanceDBChunkStore, embedding_model: EmbeddingModel) -> IngestResult:
    """读取一份 MCP markdown，结构切块、加上下文、生成向量并写入 LanceDB。"""

    try:
        metadata, markdown = parse_metadata_file(path)
        chunks = attach_context(chunk_markdown(markdown, metadata))
        vectors = embedding_model.embed_texts([chunk.indexed_text for chunk in chunks])
        records = [chunk_to_record(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=False)]
        count = store.add_records(records, source_path=str(path.resolve()))
        return IngestResult(success=True, source_path=str(path.resolve()), chunk_count=count)
    except Exception as exc:
        return IngestResult(success=False, source_path=str(path), chunk_count=0, error=str(exc))
