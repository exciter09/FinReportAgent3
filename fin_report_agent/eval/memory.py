from __future__ import annotations

import math
import re
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from fin_report_agent.retrieval.chunker import chunk_markdown
from fin_report_agent.retrieval.contextual import attach_context
from fin_report_agent.retrieval.embeddings import EmbeddingModel
from fin_report_agent.retrieval.ingest import chunk_to_record
from fin_report_agent.retrieval.metadata import parse_metadata_file
from fin_report_agent.retrieval.rerank import NoopReranker, Reranker
from fin_report_agent.retrieval.store import SearchCandidate


TOKEN_RE = re.compile(r"[A-Za-z0-9.-]+")
ALIASES = {
    "sales": ["revenue", "revenues"],
    "sale": ["revenue", "revenues"],
    "revenue": ["sales", "revenues"],
    "revenues": ["sales", "revenue"],
    "service": ["services"],
    "services": ["service"],
    "cloud": ["aws"],
    "aws": ["cloud"],
    "capex": ["capital", "expenditures"],
    "profit": ["income"],
    "income": ["profit"],
    "cyber": ["cybersecurity"],
    "cybersecurity": ["cyber"],
}


def tokenize(text: str) -> list[str]:
    """把英文财务查询切成小写 token；fixture 评测用它保持完全可复现。"""

    tokens: list[str] = []
    for token in TOKEN_RE.findall(text):
        normalized = token.lower()
        tokens.append(normalized)
        tokens.extend(ALIASES.get(normalized, []))
    return tokens


class KeywordEmbeddingModel(EmbeddingModel):
    """轻量词袋 embedding，供离线评测替代本地大模型。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把 token hash 到固定维度，并做 L2 归一化。"""

        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * 256
            for token in tokenize(text):
                vector[_stable_hash(token) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class KeywordReranker(Reranker):
    """用 query 和 chunk 的 token overlap 做可解释 rerank。"""

    def rerank(self, query: str, candidates: list[SearchCandidate], *, top_k: int) -> list[SearchCandidate]:
        """按关键词重叠数重排，分数越高越相关。"""

        query_counts = Counter(tokenize(query))
        rescored: list[SearchCandidate] = []
        for candidate in candidates:
            text_counts = Counter(tokenize(str(candidate.record.get("text", ""))))
            overlap = sum(min(count, text_counts[token]) for token, count in query_counts.items())
            rescored.append(SearchCandidate(record=candidate.record, score=float(overlap) + candidate.score * 0.01))
        return sorted(rescored, key=lambda item: item.score, reverse=True)[:top_k]


class InMemoryChunkStore:
    """与 LanceDBChunkStore 同形的内存 store，专门用于评测和测试。"""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add_records(self, records: list[dict[str, Any]], *, source_path: str | None = None) -> int:
        """写入 records；source_path 相同则先删旧数据。"""

        if source_path:
            self.records = [record for record in self.records if record.get("source_path") != source_path]
        self.records.extend(records)
        return len(records)

    def search(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, list[Any]] | None = None,
        limit: int = 30,
    ) -> list[SearchCandidate]:
        """在内存里应用 metadata filter，再按 cosine similarity 排序。"""

        filtered = [record for record in self.records if _matches_filters(record, filters or {})]
        candidates = [
            SearchCandidate(record=record, score=_dot(query_vector, record.get("vector", [])))
            for record in filtered
        ]
        return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def build_eval_store(filing_paths: list[Path], *, use_context: bool) -> tuple[InMemoryChunkStore, KeywordEmbeddingModel]:
    """用真实 chunker/context 流程构建内存索引，避免评测依赖 LanceDB。"""

    store = InMemoryChunkStore()
    embedding_model = KeywordEmbeddingModel()
    for path in filing_paths:
        metadata, markdown = parse_metadata_file(path)
        chunks = attach_context(chunk_markdown(markdown, metadata, target_chars=900, overlap_chars=120))
        texts = [chunk.indexed_text if use_context else chunk.text for chunk in chunks]
        vectors = embedding_model.embed_texts(texts)
        records = []
        for chunk, vector, text_for_index in zip(chunks, vectors, texts, strict=False):
            record = chunk_to_record(chunk, vector)
            if not use_context:
                record["indexed_text"] = text_for_index
            records.append(record)
        store.add_records(records, source_path=str(path.resolve()))
    return store, embedding_model


def noop_reranker() -> NoopReranker:
    """给消融实验返回不重排的 reranker。"""

    return NoopReranker()


def _matches_filters(record: dict[str, Any], filters: dict[str, list[Any]]) -> bool:
    """判断一条记录是否满足简单 metadata filters。"""

    for key, values in filters.items():
        if key == "requested_year" and values:
            report_period = str(record.get("report_period") or "")
            report_year = int(report_period[:4]) if report_period[:4].isdigit() else None
            if record.get(key) not in values and report_year not in values:
                return False
            continue
        if values and record.get(key) not in values:
            return False
    return True


def _dot(left: list[float], right: list[float]) -> float:
    """计算两个归一化词袋向量的点积。"""

    return float(sum(a * b for a, b in zip(left, right, strict=False)))


def _stable_hash(token: str) -> int:
    """使用稳定哈希，避免 Python hash seed 导致评测指标抖动。"""

    return int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16)
