from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class UserClarificationRequest:
    """表示 tool 需要暂停 Agent Loop，等待用户补充信息。"""

    question: str
    options: list[str]
    reason: str | None = None


class ToolNeedsUserInput(Exception):
    """澄清 tool 用这个异常把“需要用户输入”传回 Agent Loop。"""

    def __init__(self, request: UserClarificationRequest) -> None:
        super().__init__(request.question)
        self.request = request


@dataclass
class Tool:
    """Agent 可调用工具的最小描述。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        """转成 OpenAI tool calling 需要的 function schema。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def call(self, arguments: dict[str, Any]) -> Any:
        """执行同步或异步 handler，让工具作者不必关心调用细节。"""

        result = self.handler(**arguments)
        if inspect.isawaitable(result):
            return await result
        return result


class ToolRegistry:
    """保存 tool name 到 Tool 的映射，并负责统一分发调用。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个 tool；重名通常代表配置错误，因此直接拒绝。"""

        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool

    def extend(self, tools: list[Tool]) -> None:
        """批量注册 tools，减少 main.py 中的样板代码。"""

        for tool in tools:
            self.register(tool)

    def schemas(self) -> list[dict[str, Any]]:
        """返回所有 tool schema，供 LLM 请求体使用。"""

        return [tool.schema() for tool in self._tools.values()]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """按名称调用 tool，并给未知 tool 一个中文错误。"""

        tool = self._tools.get(name)
        if tool is None:
            return {"success": False, "error": f"未知工具：{name}"}
        return await tool.call(arguments)
