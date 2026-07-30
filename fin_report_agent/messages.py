from __future__ import annotations

from typing import Any

Message = dict[str, Any]


def system_message(content: str) -> Message:
    """创建 system 消息，让所有会话共享同一套 Agent 行为约束。"""

    return {"role": "system", "content": content}


def user_message(content: str) -> Message:
    """创建用户消息；保留原文能让多轮指代尽量交给模型理解。"""

    return {"role": "user", "content": content}


def tool_message(tool_call_id: str, name: str, content: str) -> Message:
    """创建 tool 结果消息，按 OpenAI tool calling 协议接回模型上下文。"""

    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
    }
