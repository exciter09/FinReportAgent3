from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fin_report_agent.agent.loop import AgentCallbacks, AgentLoop
from fin_report_agent.agent.prompts import SYSTEM_PROMPT
from fin_report_agent.agent.tool_registry import Tool, ToolRegistry
from fin_report_agent.eval.dataset import JsonlCase, read_jsonl
from fin_report_agent.eval.fixtures import write_fixture_filings
from fin_report_agent.eval.memory import KeywordReranker, build_eval_store
from fin_report_agent.eval.metrics import mean
from fin_report_agent.retrieval.search import FilingSearcher
from fin_report_agent.tools.calculator_tool import build_calculator_tool
from fin_report_agent.tools.clarify_tool import build_clarify_tool


@dataclass
class ToolTrace:
    """记录 AgentLoop 执行过程中的工具调用。"""

    starts: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)


class ScriptedEvalLLM:
    """按评测样本生成 tool calls，用同一个 AgentLoop 测端到端链路。"""

    def __init__(self, case: JsonlCase) -> None:
        self.case = case
        self.phase = 0

    async def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        """根据当前消息历史决定下一步：澄清、工具调用或最终回答。"""

        expected = self.case.payload["expected"]
        if expected.get("should_clarify") and not _has_tool_message(messages, "ask_user_clarification"):
            yield _tool_delta(
                "clarify_1",
                "ask_user_clarification",
                {
                    "question": expected.get("clarification_question", "请补充缺失信息。"),
                    "options": expected.get("clarification_options", []),
                    "reason": "评测样本要求先澄清。",
                },
            )
            return

        tool_sequence = expected.get("tools_sequence", [])
        completed_tools = [message.get("name") for message in messages if message.get("role") == "tool"]
        for tool_name in tool_sequence:
            if tool_name not in completed_tools:
                yield _tool_delta(f"{tool_name}_{len(completed_tools) + 1}", tool_name, _arguments_for(tool_name, expected))
                return

        for part in _final_answer(expected):
            yield {"content": part}


def run_agent_eval(eval_dir: Path) -> dict[str, Any]:
    """运行第二层端到端 Agent 评测，共 30 条模拟用户交互。"""

    cases = read_jsonl(eval_dir / "cases.jsonl")
    filing_paths = write_fixture_filings(eval_dir)
    store, embedding_model = build_eval_store(filing_paths, use_context=True)
    searcher = FilingSearcher(store, embedding_model, KeywordReranker())

    rows = [asyncio.run(_run_case(case, searcher)) for case in cases]
    summary = {
        "case_count": len(rows),
        "task_success_rate": mean([row["task_success"] for row in rows]),
        "tool_call_accuracy": mean([row["tool_call_accuracy"] for row in rows]),
        "metadata_filter_accuracy": mean([row["metadata_filter_accuracy"] for row in rows]),
        "answer_faithfulness": mean([row["answer_faithfulness"] for row in rows]),
        "calculation_exact_match": mean([row["calculation_exact_match"] for row in rows if row["calculation_expected"]]),
        "clarification_precision": mean([row["clarification_precision"] for row in rows]),
        "source_coverage": mean([row["source_coverage"] for row in rows if row["source_required"]]),
        "retrieval_support": mean([row["retrieval_support"] for row in rows if row["retrieval_expected"]]),
        "average_tool_calls": mean([float(row["tool_call_count"]) for row in rows]),
    }
    return {"summary": summary, "details": rows}


async def _run_case(case: JsonlCase, searcher: FilingSearcher) -> dict[str, Any]:
    """执行单条样本，自动回答澄清问题并收集最终指标。"""

    trace = ToolTrace()
    registry = _build_eval_registry(searcher)
    loop = AgentLoop(
        ScriptedEvalLLM(case),
        registry,
        SYSTEM_PROMPT,
        callbacks=AgentCallbacks(
            on_tool_start=lambda name, arguments: trace.starts.append({"name": name, "arguments": arguments}),
            on_tool_result=lambda name, payload: trace.results.append({"name": name, "payload": payload}),
        ),
    )

    final_content = ""
    for turn in case.payload["turns"]:
        result = await loop.run_turn(turn["user"])
        while result.status == "needs_clarification" and result.pending_clarification:
            answer = case.payload.get("clarification_answer", "")
            result = await loop.resume_after_clarification(result.pending_clarification, answer)
        if result.message and result.message.get("content"):
            final_content = str(result.message["content"])

    return _score_case(case, trace, final_content)


def _build_eval_registry(searcher: FilingSearcher) -> ToolRegistry:
    """构造评测用 tools：检索走 fixture 索引，计算和澄清复用正式 tool。"""

    registry = ToolRegistry()

    def search_filings(
        query: str,
        companies: list[str] | None = None,
        years: list[int] | None = None,
        forms: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """评测版检索 tool，返回 fixture chunks。"""

        result = searcher.search(query, companies=companies, years=years, forms=forms, top_k=top_k)
        result["success"] = True
        return result

    registry.register(
        Tool(
            name="search_filings",
            description="评测用财报检索 tool。",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=search_filings,
        )
    )
    registry.register(build_calculator_tool())
    registry.register(build_clarify_tool())
    return registry


def _score_case(case: JsonlCase, trace: ToolTrace, final_content: str) -> dict[str, Any]:
    """根据 tool trace、最终答案和 gold requirements 计算端到端指标。"""

    expected = case.payload["expected"]
    expected_tools = list(expected.get("tools_sequence", []))
    if expected.get("should_clarify"):
        expected_tools = ["ask_user_clarification"] + expected_tools
    actual_tools = [item["name"] for item in trace.starts]

    tool_call_accuracy = 1.0 if actual_tools == expected_tools else 0.0
    metadata_filter_accuracy = _metadata_filter_accuracy(trace, expected)
    answer_faithfulness = 1.0 if all(term in final_content for term in expected.get("answer_contains", [])) else 0.0
    calculation_exact_match = _calculation_exact_match(trace, expected)
    clarification_precision = 1.0 if (bool(expected.get("should_clarify")) == ("ask_user_clarification" in actual_tools)) else 0.0
    source_coverage = _source_coverage(final_content, expected)
    retrieval_support = _retrieval_support(trace, expected)

    required_scores = [tool_call_accuracy, metadata_filter_accuracy, answer_faithfulness, clarification_precision]
    if expected.get("source_required"):
        required_scores.append(source_coverage)
    if "calculate_decimal" in expected_tools:
        required_scores.append(calculation_exact_match)
    if "search_filings" in expected_tools:
        required_scores.append(retrieval_support)

    return {
        "id": case.case_id,
        "category": case.payload.get("category"),
        "task_success": 1.0 if all(score == 1.0 for score in required_scores) else 0.0,
        "tool_call_accuracy": tool_call_accuracy,
        "metadata_filter_accuracy": metadata_filter_accuracy,
        "answer_faithfulness": answer_faithfulness,
        "calculation_exact_match": calculation_exact_match,
        "calculation_expected": "calculate_decimal" in expected_tools,
        "clarification_precision": clarification_precision,
        "source_coverage": source_coverage,
        "source_required": bool(expected.get("source_required")),
        "retrieval_support": retrieval_support,
        "retrieval_expected": "search_filings" in expected_tools,
        "tool_call_count": len(actual_tools),
        "actual_tools": actual_tools,
        "final_answer": final_content,
    }


def _metadata_filter_accuracy(trace: ToolTrace, expected: dict[str, Any]) -> float:
    """检查 search_filings 的 company/year/form 参数是否符合预期。"""

    if "search_filings" not in expected.get("tools_sequence", []):
        return 1.0
    search_call = next((item for item in trace.starts if item["name"] == "search_filings"), None)
    if not search_call:
        return 0.0
    arguments = search_call["arguments"]
    search_args = expected.get("search_args", {})
    checks = [
        set(arguments.get("companies", [])) == set(search_args.get("companies", [])),
        set(arguments.get("years", [])) == set(search_args.get("years", [])),
        set(arguments.get("forms", [])) == set(search_args.get("forms", [])),
    ]
    return 1.0 if all(checks) else 0.0


def _calculation_exact_match(trace: ToolTrace, expected: dict[str, Any]) -> float:
    """检查 Decimal tool 的 result 是否等于标注结果。"""

    if "calculate_decimal" not in expected.get("tools_sequence", []):
        return 1.0
    result = _tool_result(trace, "calculate_decimal")
    expected_result = expected.get("calculation_result")
    if not isinstance(result, dict) or expected_result is None:
        return 0.0
    return 1.0 if str(result.get("result")) == str(expected_result) else 0.0


def _source_coverage(final_content: str, expected: dict[str, Any]) -> float:
    """检查最终答案是否包含来源所需的 ticker/year/form。"""

    if not expected.get("source_required"):
        return 1.0
    source_terms = expected.get("source_terms") or []
    return 1.0 if all(term in final_content for term in source_terms) else 0.0


def _retrieval_support(trace: ToolTrace, expected: dict[str, Any]) -> float:
    """检查检索 tool 返回结果是否包含 gold terms。"""

    if "search_filings" not in expected.get("tools_sequence", []):
        return 1.0
    result = _tool_result(trace, "search_filings")
    if not isinstance(result, dict):
        return 0.0
    haystack = "\n".join(item.get("text", "") for item in result.get("results", []))
    gold_terms = expected.get("gold_terms", [])
    return 1.0 if all(term in haystack for term in gold_terms) else 0.0


def _tool_result(trace: ToolTrace, name: str) -> Any:
    """从 trace 中取某个 tool 的结果 payload。"""

    item = next((row for row in trace.results if row["name"] == name), None)
    if not item:
        return None
    payload = item["payload"]
    return payload.get("result") if isinstance(payload, dict) else payload


def _has_tool_message(messages: list[dict[str, Any]], name: str) -> bool:
    """判断上下文里是否已有指定 tool result。"""

    return any(message.get("role") == "tool" and message.get("name") == name for message in messages)


def _arguments_for(tool_name: str, expected: dict[str, Any]) -> dict[str, Any]:
    """根据样本 expected 字段生成下一次 tool call 参数。"""

    if tool_name == "search_filings":
        return expected.get("search_args", {})
    if tool_name == "calculate_decimal":
        return {"code": expected.get("calculation_code", "0")}
    return {}


def _tool_delta(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """构造 AgentLoop 可消费的流式 tool delta。"""

    return {
        "tool_calls": [
            {
                "index": 0,
                "id": call_id,
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        ]
    }


def _final_answer(expected: dict[str, Any]) -> list[str]:
    """生成包含标注事实和来源的最终答案，用于端到端链路评测。"""

    pieces = ["结论：", "；".join(expected.get("answer_contains", []))]
    if expected.get("source_required"):
        pieces.append("。来源：")
        pieces.append(" ".join(expected.get("source_terms", [])))
    return pieces
