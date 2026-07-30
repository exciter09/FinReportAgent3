from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fin_report_agent.agent.tool_registry import ToolNeedsUserInput, ToolRegistry, UserClarificationRequest
from fin_report_agent.messages import Message, system_message, tool_message, user_message


TextCallback = Callable[[str], None | Awaitable[None]]
ToolCallback = Callable[[str, dict[str, Any]], None | Awaitable[None]]


@dataclass
class PendingClarification:
    """保存一次暂停中的澄清请求，TUI 拿到后向用户提问。"""

    tool_call_id: str
    tool_name: str
    question: str
    options: list[str]
    reason: str | None


@dataclass
class AgentTurnResult:
    """描述一轮 Agent 执行的结果，方便 TUI 判断是否需要继续。"""

    status: str
    message: Message | None = None
    pending_clarification: PendingClarification | None = None


@dataclass
class AgentCallbacks:
    """把流式文本和工具状态交给前端渲染，Agent Loop 本身不关心 UI。"""

    on_text_delta: TextCallback | None = None
    on_tool_start: ToolCallback | None = None
    on_tool_result: ToolCallback | None = None


class AgentLoop:
    """支持多轮对话、流式输出和 tool calling 的极简 Agent Loop。"""

    def __init__(
        self,
        llm: Any,
        tools: ToolRegistry,
        system_prompt: str,
        *,
        max_tool_rounds: int = 8,
        callbacks: AgentCallbacks | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_tool_rounds = max_tool_rounds
        self.callbacks = callbacks or AgentCallbacks()
        self.messages: list[Message] = [system_message(system_prompt)]

    async def run_turn(self, text: str) -> AgentTurnResult:
        """追加用户输入并运行到最终回答、澄清请求或工具轮数上限。"""

        self.messages.append(user_message(text))
        return await self._run_until_stop()

    async def resume_after_clarification(self, pending: PendingClarification, answer: str) -> AgentTurnResult:
        """把用户澄清答案作为 tool result 接回上下文，然后继续 Agent Loop。"""

        content = json.dumps({"success": True, "answer": answer}, ensure_ascii=False)
        self.messages.append(tool_message(pending.tool_call_id, pending.tool_name, content))
        return await self._run_until_stop()

    async def _run_until_stop(self) -> AgentTurnResult:
        """循环调用模型和工具，直到模型给出自然语言最终回答。"""

        for _ in range(self.max_tool_rounds):
            assistant = await self._collect_assistant_message()
            self.messages.append(assistant)

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return AgentTurnResult(status="completed", message=assistant)

            for tool_call in tool_calls:
                pending = await self._execute_tool_call(tool_call)
                if pending is not None:
                    return AgentTurnResult(status="needs_clarification", pending_clarification=pending)

        limit_message = {
            "role": "assistant",
            "content": "工具调用轮数已达到上限，请缩小问题范围后重试。",
        }
        self.messages.append(limit_message)
        await self._emit_text(limit_message["content"])
        return AgentTurnResult(status="tool_round_limit", message=limit_message)

    async def _collect_assistant_message(self) -> Message:
        """收集流式 delta，拼成 OpenAI tool calling 格式的 assistant 消息。"""

        content_parts: list[str] = []
        tool_buffers: dict[int, dict[str, Any]] = {}

        async for delta in self.llm.chat_stream(self.messages, self.tools.schemas()):
            text = delta.get("content")
            if text:
                content_parts.append(text)
                await self._emit_text(text)

            for tool_delta in delta.get("tool_calls") or []:
                index = int(tool_delta.get("index", 0))
                buffer = tool_buffers.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if tool_delta.get("id") and not buffer["id"]:
                    buffer["id"] = tool_delta["id"]
                function_delta = tool_delta.get("function") or {}
                if function_delta.get("name") and not buffer["function"]["name"]:
                    buffer["function"]["name"] = function_delta["name"]
                if function_delta.get("arguments"):
                    buffer["function"]["arguments"] += function_delta["arguments"]

        message: Message = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
        }
        if tool_buffers:
            message["tool_calls"] = [tool_buffers[index] for index in sorted(tool_buffers)]
        return message

    async def _execute_tool_call(self, tool_call: dict[str, Any]) -> PendingClarification | None:
        """执行单个 tool call，并把结果写回消息历史。"""

        function = tool_call.get("function") or {}
        name = function.get("name") or ""
        raw_arguments = function.get("arguments") or "{}"
        tool_call_id = tool_call.get("id") or f"tool_{len(self.messages)}"

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            result = {"success": False, "error": f"工具参数不是合法 JSON：{exc}"}
            self.messages.append(tool_message(tool_call_id, name, json.dumps(result, ensure_ascii=False)))
            return None

        await self._emit_tool_start(name, arguments)
        try:
            result = await self.tools.call(name, arguments)
        except ToolNeedsUserInput as exc:
            request: UserClarificationRequest = exc.request
            return PendingClarification(
                tool_call_id=tool_call_id,
                tool_name=name,
                question=request.question,
                options=request.options,
                reason=request.reason,
            )
        except Exception as exc:
            result = {"success": False, "error": f"工具执行失败：{exc}"}

        await self._emit_tool_result(name, result)
        self.messages.append(tool_message(tool_call_id, name, json.dumps(result, ensure_ascii=False)))
        return None

    async def _emit_text(self, text: str) -> None:
        """把模型文本增量交给前端；测试中可以不提供回调。"""

        if self.callbacks.on_text_delta:
            result = self.callbacks.on_text_delta(text)
            if hasattr(result, "__await__"):
                await result

    async def _emit_tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        """通知前端工具开始执行，用于 TUI 显示状态行。"""

        if self.callbacks.on_tool_start:
            result = self.callbacks.on_tool_start(name, arguments)
            if hasattr(result, "__await__"):
                await result

    async def _emit_tool_result(self, name: str, result_value: Any) -> None:
        """通知前端工具执行结束，避免用户面对无响应的等待。"""

        if self.callbacks.on_tool_result:
            result = self.callbacks.on_tool_result(name, {"result": result_value})
            if hasattr(result, "__await__"):
                await result
