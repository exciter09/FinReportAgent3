from __future__ import annotations

import sys
from types import ModuleType

from fin_report_agent.retrieval.embeddings import LocalBGEEmbeddingModel
from fin_report_agent.retrieval.rerank import LocalBGEReranker
from fin_report_agent.retrieval.store import SearchCandidate


def test_embedding_model_loads_from_local_cache(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_module = ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        """假模型只记录初始化参数，不触发真实模型加载。"""

        def __init__(self, model_name: str, local_files_only: bool) -> None:
            captured["model_name"] = model_name
            captured["local_files_only"] = local_files_only

        def encode(self, texts, normalize_embeddings: bool, show_progress_bar: bool):
            captured["normalize_embeddings"] = normalize_embeddings
            return [[1.0, 0.0] for _ in texts]

    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    model = LocalBGEEmbeddingModel("fake-bge-m3")
    vectors = model.embed_texts(["hello"])

    assert captured["model_name"] == "fake-bge-m3"
    assert captured["local_files_only"] is True
    assert captured["normalize_embeddings"] is True
    assert vectors == [[1.0, 0.0]]


def test_reranker_loads_from_local_cache(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_module = ModuleType("sentence_transformers")

    class FakeCrossEncoder:
        """假 reranker 只记录初始化参数，不触发真实模型加载。"""

        def __init__(self, model_name: str, local_files_only: bool) -> None:
            captured["model_name"] = model_name
            captured["local_files_only"] = local_files_only

        def predict(self, pairs):
            captured["pairs"] = pairs
            return [0.9]

    fake_module.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    reranker = LocalBGEReranker("fake-bge-reranker")
    results = reranker.rerank(
        "revenue",
        [SearchCandidate(record={"indexed_text": "net sales revenue"}, score=1.0)],
        top_k=1,
    )

    assert captured["model_name"] == "fake-bge-reranker"
    assert captured["local_files_only"] is True
    assert captured["pairs"] == [("revenue", "net sales revenue")]
    assert results[0].score == 0.9
