from __future__ import annotations

from fin_report_agent.agent.loop import AgentCallbacks, AgentLoop
from fin_report_agent.agent.prompts import SYSTEM_PROMPT
from fin_report_agent.agent.tool_registry import ToolRegistry
from fin_report_agent.config import AppConfig
from fin_report_agent.llm import OpenAICompatibleLLM
from fin_report_agent.tools.calculator_tool import build_calculator_tool
from fin_report_agent.tools.clarify_tool import build_clarify_tool
from fin_report_agent.tools.edgar_tools import build_edgar_tools
from fin_report_agent.tools.retrieval_tool import build_retrieval_tools
from fin_report_agent.tui.render import print_text_delta, print_tool_result, print_tool_start
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory


def build_registry(config: AppConfig) -> ToolRegistry:
    """注册阶段 1-6 的所有 tools，供 Agent Loop 统一暴露给模型。"""

    registry = ToolRegistry()
    registry.extend(build_edgar_tools(config))
    registry.extend(build_retrieval_tools(config))
    registry.register(build_calculator_tool())
    registry.register(build_clarify_tool())
    return registry


async def run_tui(config: AppConfig) -> None:
    """运行极简聊天 TUI，支持流式输出和澄清恢复。"""

    session = PromptSession(history=InMemoryHistory())
    llm = OpenAICompatibleLLM(config.api_key, config.base_url, config.model)
    loop = AgentLoop(
        llm,
        build_registry(config),
        SYSTEM_PROMPT,
        max_tool_rounds=config.max_tool_rounds,
        callbacks=AgentCallbacks(
            on_text_delta=print_text_delta,
            on_tool_start=print_tool_start,
            on_tool_result=print_tool_result,
        ),
    )

    print("FinReportAgent TUI。输入 exit 或 quit 退出。")
    while True:
        user_text = (await session.prompt_async("\nFinReportAgent> ")).strip()
        if user_text.lower() in {"exit", "quit"}:
            print("再见。")
            return
        if not user_text:
            continue

        print("\nAgent> ", end="", flush=True)
        result = await loop.run_turn(user_text)
        while result.status == "needs_clarification" and result.pending_clarification:
            pending = result.pending_clarification
            print(f"\n\n需要澄清：{pending.question}")
            for index, option in enumerate(pending.options, start=1):
                print(f"  {index}. {option}")
            answer = (await session.prompt_async("你的回答> ")).strip()
            print("\nAgent> ", end="", flush=True)
            result = await loop.resume_after_clarification(pending, answer)
        print()
