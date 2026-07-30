from __future__ import annotations

from typing import Any

from fin_report_agent.agent.tool_registry import Tool, ToolNeedsUserInput, UserClarificationRequest


def build_clarify_tool() -> Tool:
    """创建请求用户澄清 tool，让 Agent Loop 能暂停并交给 TUI 提问。"""

    def ask_user_clarification(
        question: str,
        options: list[str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """抛出结构化澄清请求；真正读取用户输入的是 TUI。"""

        raise ToolNeedsUserInput(UserClarificationRequest(question=question, options=options or [], reason=reason))

    return Tool(
        name="ask_user_clarification",
        description=(
            "当回答财报问题缺少必要公司、年份、表单或计算口径时，向用户提出一个简短澄清问题。"
            "每次只问一个最关键的问题；如果有少量明确选项，可以放进 options。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要展示给用户的简短中文问题"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选答案列表，可为空",
                },
                "reason": {"type": "string", "description": "为什么需要澄清，供 TUI 或调试展示"},
            },
            "required": ["question"],
        },
        handler=ask_user_clarification,
    )
