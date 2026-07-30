from __future__ import annotations

import os
from dataclasses import dataclass

from fin_report_agent.retrieval.store import SearchCandidate


class Reranker:
    """reranker 协议；检索流程只需要 rerank 一个动作。"""

    def rerank(self, query: str, candidates: list[SearchCandidate], *, top_k: int) -> list[SearchCandidate]:
        """把候选 chunk 重新排序。"""

        raise NotImplementedError


class NoopReranker(Reranker):
    """测试或降级用 reranker，保持向量召回顺序。"""

    def rerank(self, query: str, candidates: list[SearchCandidate], *, top_k: int) -> list[SearchCandidate]:
        """不改变排序，只截断 top_k。"""

        return candidates[:top_k]


@dataclass
class LocalBGEReranker(Reranker):
    """本地 bge-reranker 封装，默认只从 Hugging Face 缓存加载。"""

    model_name: str = "BAAI/bge-reranker-base"

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:
            raise RuntimeError(f"无法导入 sentence-transformers，请先安装依赖：{exc}") from exc

        try:
            self.model = CrossEncoder(self.model_name, local_files_only=True)
        except Exception as exc:
            raise RuntimeError(f"无法从本机 Hugging Face 缓存加载 reranker 模型 {self.model_name}：{exc}") from exc

    def rerank(self, query: str, candidates: list[SearchCandidate], *, top_k: int) -> list[SearchCandidate]:
        """用 query 和 indexed_text 的相关性分数重排候选 chunk。"""

        if not candidates:
            return []
        pairs = [(query, candidate.record.get("indexed_text", "")) for candidate in candidates]
        scores = self.model.predict(pairs)
        rescored = [
            SearchCandidate(record=candidate.record, score=float(score))
            for candidate, score in zip(candidates, scores, strict=False)
        ]
        return sorted(rescored, key=lambda item: item.score, reverse=True)[:top_k]


def create_reranker() -> Reranker:
    """创建默认 reranker；测试可显式使用 no-op。"""

    if os.environ.get("FIN_AGENT_DISABLE_RERANKER") == "1":
        return NoopReranker()
    return LocalBGEReranker(os.environ.get("FIN_AGENT_RERANKER_MODEL", "BAAI/bge-reranker-base"))
