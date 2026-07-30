from __future__ import annotations

from typing import Any


def print_tool_start(name: str, arguments: dict[str, Any]) -> None:
    """以一行状态提示展示工具开始执行，避免用户等待时没有反馈。"""

    print(f"\n[tool:start] {name} {arguments}")


def print_tool_result(name: str, payload: dict[str, Any]) -> None:
    """以紧凑状态提示展示工具结束，详细 JSON 留在 Agent 上下文里。"""

    result = payload.get("result")
    success = result.get("success") if isinstance(result, dict) else None
    suffix = f" success={success}" if success is not None else ""
    print(f"\n[tool:done] {name}{suffix}")


def print_text_delta(text: str) -> None:
    """直接打印模型流式文本，是第一版 TUI 的最小渲染方式。"""

    print(text, end="", flush=True)
