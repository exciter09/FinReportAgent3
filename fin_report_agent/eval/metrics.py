from __future__ import annotations

import math
from typing import Any, Callable


def mean(values: list[float]) -> float:
    """计算均值；空列表返回 0，避免报告生成时报错。"""

    return sum(values) / len(values) if values else 0.0


def recall_at_k(results: list[dict[str, Any]], is_relevant: Callable[[dict[str, Any]], bool], k: int) -> float:
    """二值 Recall@k：top k 中出现任意相关结果即为 1。"""

    return 1.0 if any(is_relevant(result) for result in results[:k]) else 0.0


def mrr_at_k(results: list[dict[str, Any]], is_relevant: Callable[[dict[str, Any]], bool], k: int) -> float:
    """计算 MRR@k，相关结果越靠前分数越高。"""

    for index, result in enumerate(results[:k], start=1):
        if is_relevant(result):
            return 1.0 / index
    return 0.0


def ndcg_at_k(results: list[dict[str, Any]], is_relevant: Callable[[dict[str, Any]], bool], k: int) -> float:
    """用二值相关性计算 nDCG@k。"""

    dcg = 0.0
    relevance = [1.0 if is_relevant(result) else 0.0 for result in results[:k]]
    ideal_relevance = sorted(relevance, reverse=True)
    for index, result in enumerate(results[:k], start=1):
        if is_relevant(result):
            dcg += 1.0 / math.log2(index + 1)
    ideal = sum(value / math.log2(index + 1) for index, value in enumerate(ideal_relevance, start=1))
    return dcg / ideal if ideal else 0.0


def percent(value: float) -> str:
    """把 0-1 分数格式化成百分比字符串。"""

    return f"{value * 100:.1f}%"
