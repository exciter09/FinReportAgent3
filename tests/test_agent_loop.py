from __future__ import annotations

import asyncio
from typing import Any

from fin_report_agent.agent.loop import AgentLoop
from fin_report_agent.agent.tool_registry import Tool, ToolRegistry
from fin_report_agent.tools.clarify_tool import build_clarify_tool


class FakeStreamingLLM:
    """测试用 fake LLM，用预设 delta 验证 Agent Loop 控制流。"""

    def __init__(self, calls: list[list[dict[str, Any]]]) -> None:
        self.calls = calls
        self.index = 0

    async def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        """按调用次数产出流式 delta，不访问真实 LLM API。"""

        deltas = self.calls[self.index]
        self.index += 1
        for delta in deltas:
            yield delta


def test_agent_loop_executes_tool_and_continues() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="echo",
                description="echo test",
                parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                handler=lambda text: {"success": True, "text": text},
            )
        )
        llm = FakeStreamingLLM(
            [
                [
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo", "arguments": "{\"text\":\""},
                            }
                        ]
                    },
                    {"tool_calls": [{"index": 0, "function": {"arguments": "hello\"}"}}]},
                ],
                [{"content": "完成"}],
            ]
        )
        loop = AgentLoop(llm, registry, "system")

        result = await loop.run_turn("hi")

        assert result.status == "completed"
        assert result.message and result.message["content"] == "完成"
        assert any(message["role"] == "tool" and "hello" in message["content"] for message in loop.messages)

    asyncio.run(scenario())


def test_agent_loop_pauses_and_resumes_for_clarification() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(build_clarify_tool())
        llm = FakeStreamingLLM(
            [
                [
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "clarify_1",
                                "function": {
                                    "name": "ask_user_clarification",
                                    "arguments": "{\"question\":\"要哪一年？\",\"options\":[\"2023\",\"2024\"]}",
                                },
                            }
                        ]
                    }
                ],
                [{"content": "收到，继续分析。"}],
            ]
        )
        loop = AgentLoop(llm, registry, "system")

        result = await loop.run_turn("分析苹果")
        assert result.status == "needs_clarification"
        assert result.pending_clarification
        assert result.pending_clarification.question == "要哪一年？"

        resumed = await loop.resume_after_clarification(result.pending_clarification, "2023")
        assert resumed.status == "completed"
        assert resumed.message and "继续分析" in resumed.message["content"]

    asyncio.run(scenario())
