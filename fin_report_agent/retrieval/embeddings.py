from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass


class EmbeddingModel:
    """embedding 模型协议；检索代码只依赖 embed_texts 这一件事。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把文本列表转成向量列表。"""

        raise NotImplementedError


@dataclass
class LocalBGEEmbeddingModel(EmbeddingModel):
    """本地 bge-m3 embedding 封装，默认只从 Hugging Face 缓存加载。"""

    model_name: str = "BAAI/bge-m3"

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(f"无法导入 sentence-transformers，请先安装依赖：{exc}") from exc

        try:
            self.model = SentenceTransformer(self.model_name, local_files_only=True)
        except Exception as exc:
            raise RuntimeError(f"无法从本机 Hugging Face 缓存加载 embedding 模型 {self.model_name}：{exc}") from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """使用 bge-m3 生成归一化向量。"""

        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, vector)) for vector in vectors]


@dataclass
class HashEmbeddingModel(EmbeddingModel):
    """测试用确定性 embedding；只有显式允许时才用于本地调试。"""

    dimensions: int = 64

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """用哈希构造稳定向量，让测试不依赖大模型。"""

        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [((digest[index % len(digest)] / 255.0) * 2 - 1) for index in range(self.dimensions)]
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors


def create_embedding_model() -> EmbeddingModel:
    """创建默认 embedding 模型；测试可通过环境变量启用哈希模型。"""

    if os.environ.get("FIN_AGENT_ALLOW_HASH_EMBEDDINGS") == "1":
        return HashEmbeddingModel()
    return LocalBGEEmbeddingModel(os.environ.get("FIN_AGENT_EMBEDDING_MODEL", "BAAI/bge-m3"))
