from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fin_report_agent.agent.loop import AgentCallbacks, AgentLoop
from fin_report_agent.agent.prompts import SYSTEM_PROMPT
from fin_report_agent.agent.tool_registry import Tool, ToolRegistry
from fin_report_agent.config import AppConfig, load_config
from fin_report_agent.eval.dataset import JsonlCase, read_jsonl, write_json
from fin_report_agent.eval.memory import KeywordReranker, build_eval_store, noop_reranker
from fin_report_agent.eval.metrics import mean, mrr_at_k, ndcg_at_k, percent, recall_at_k
from fin_report_agent.llm import OpenAICompatibleLLM
from fin_report_agent.retrieval.search import FilingSearcher, _normalize_company
from fin_report_agent.tools.calculator_tool import build_calculator_tool
from fin_report_agent.tools.clarify_tool import build_clarify_tool


@dataclass
class RealToolTrace:
    """真实模型评测中的工具调用轨迹。"""

    starts: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)


def run_real_eval(config: AppConfig, eval_dir: Path, *, max_cases: int | None = None) -> dict[str, Any]:
    """用真实清洗财报和真实 LLM 运行检索层 + Agent 层评测。"""

    return asyncio.run(_run_real_eval_async(config, eval_dir, max_cases=max_cases))


async def _run_real_eval_async(config: AppConfig, eval_dir: Path, *, max_cases: int | None = None) -> dict[str, Any]:
    """共享同一个真实 LLM，避免评测层重复初始化。"""

    agent_cases = read_jsonl(eval_dir / "cases.jsonl")
    retrieval_cases = read_jsonl(eval_dir / "retrieval_cases.jsonl")
    if max_cases:
        agent_cases = agent_cases[:max_cases]
        retrieval_cases = retrieval_cases[:max_cases]

    filing_paths = sorted(config.filings_dir.glob("*.md"))
    if not filing_paths:
        raise RuntimeError(f"没有找到真实 MCP markdown：{config.filings_dir}")

    llm = OpenAICompatibleLLM(config.api_key, config.base_url, config.model)
    retrieval = await _run_real_retrieval_eval(retrieval_cases, filing_paths, llm)
    agent = await _run_real_agent_eval(agent_cases, filing_paths, llm, config)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "real_llm_real_filings",
        "model": config.model,
        "filing_count": len(filing_paths),
        "filings": [str(path) for path in filing_paths],
        "retrieval": retrieval,
        "agent": agent,
    }


async def _run_real_agent_eval(
    cases: list[JsonlCase],
    filing_paths: list[Path],
    llm: OpenAICompatibleLLM,
    config: AppConfig,
) -> dict[str, Any]:
    """运行第二层真实 Agent 任务评测。"""

    store, embedding_model = build_eval_store(filing_paths, use_context=True)
    searcher = FilingSearcher(store, embedding_model, KeywordReranker())
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[real-eval][agent] {index}/{len(cases)} {case.case_id}", flush=True)
        rows.append(await _run_real_case_with_retries(case, searcher, llm, config))
    calculation_scores = [row["calculation_close_match"] for row in rows if row["calculation_expected"]]
    summary = {
        "case_count": len(rows),
        "task_success_rate": mean([row["task_success"] for row in rows]),
        "required_tool_presence": mean([row["required_tool_presence"] for row in rows]),
        "metadata_filter_accuracy": mean([row["metadata_filter_accuracy"] for row in rows]),
        "answer_judge_success": mean([row["answer_judge_success"] for row in rows]),
        "answer_supported_by_evidence": mean([row["answer_supported_by_evidence"] for row in rows]),
        "answers_question": mean([row["answers_question"] for row in rows]),
        "calculation_close_match": mean(calculation_scores) if calculation_scores else None,
        "clarification_precision": mean([row["clarification_precision"] for row in rows]),
        "invalid_tool_call_rate": mean([row["invalid_tool_call_rate"] for row in rows]),
        "average_tool_calls": mean([float(row["tool_call_count"]) for row in rows]),
    }
    return {"summary": summary, "details": rows}


async def _run_real_retrieval_eval(
    cases: list[JsonlCase],
    filing_paths: list[Path],
    llm: OpenAICompatibleLLM,
) -> dict[str, Any]:
    """运行第一层真实财报检索评测，用 LLM judge 判断 top-k 是否含答案证据。"""

    variants = {
        "vector_only": {"use_context": False, "use_filters": False, "reranker": noop_reranker()},
        "metadata_filter": {"use_context": False, "use_filters": True, "reranker": noop_reranker()},
        "full_context_rerank": {"use_context": True, "use_filters": True, "reranker": KeywordReranker()},
    }
    summary: dict[str, Any] = {}
    details: dict[str, list[dict[str, Any]]] = {}

    for name, settings in variants.items():
        print(f"[real-eval][retrieval] variant={name}", flush=True)
        store, embedding_model = build_eval_store(filing_paths, use_context=bool(settings["use_context"]))
        searcher = FilingSearcher(store, embedding_model, settings["reranker"])
        rows: list[dict[str, Any]] = []
        for index, case in enumerate(cases, start=1):
            print(f"[real-eval][retrieval] {name} {index}/{len(cases)} {case.case_id}", flush=True)
            payload = case.payload
            result = searcher.search(
                payload["query"],
                companies=payload.get("companies") if settings["use_filters"] else None,
                years=payload.get("years") if settings["use_filters"] else None,
                forms=payload.get("forms") if settings["use_filters"] else None,
                top_k=10,
            )
            relevance = await _judge_retrieval_results(llm, payload, result["results"])
            is_relevant = lambda item: bool(relevance.get(str(item.get("chunk_id")), 0))
            rows.append(
                {
                    "id": case.case_id,
                    "recall_at_5": recall_at_k(result["results"], is_relevant, 5),
                    "mrr_at_10": mrr_at_k(result["results"], is_relevant, 10),
                    "ndcg_at_10": ndcg_at_k(result["results"], is_relevant, 10),
                    "metadata_match_at_5": _real_metadata_match_at_k(result["results"], payload, 5),
                    "top_chunk": result["results"][0]["chunk_id"] if result["results"] else None,
                    "applied_filters": result["filters"],
                    "relevance_labels": relevance,
                }
            )
        details[name] = rows
        summary[name] = {
            "case_count": len(rows),
            "recall_at_5": mean([row["recall_at_5"] for row in rows]),
            "mrr_at_10": mean([row["mrr_at_10"] for row in rows]),
            "ndcg_at_10": mean([row["ndcg_at_10"] for row in rows]),
            "metadata_match_at_5": mean([row["metadata_match_at_5"] for row in rows]),
        }

    return {"summary": summary, "details": details}


async def _judge_retrieval_results(
    llm: OpenAICompatibleLLM,
    payload: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, int]:
    """判断每个检索结果是否足以支持回答查询；返回 chunk_id -> 0/1。"""

    candidates = []
    for rank, item in enumerate(results[:10], start=1):
        candidates.append(
            {
                "rank": rank,
                "chunk_id": item.get("chunk_id"),
                "company": item.get("ticker"),
                "year": item.get("requested_year"),
                "report_period": item.get("report_period"),
                "form": item.get("form"),
                "section": item.get("section_path"),
                "text": f"{item.get('context_text', '')}\n{item.get('text', '')}"[:1600],
            }
        )

    prompt = {
        "role": "user",
        "content": (
            "你是财报检索评测员。请只输出 JSON，不要输出额外文字。\n"
            "判断每个候选片段是否与查询相关：相关=片段本身足以提供回答查询所需的关键事实、表格数字或风险披露；"
            "不要求措辞与标注短语完全一致，但公司、年份/报告期、表单和主题必须匹配。\n"
            "输出格式：{\"labels\":[{\"chunk_id\":\"...\",\"relevant\":0或1,\"reason\":\"极短原因\"}]}\n\n"
            f"查询：{payload['query']}\n"
            f"期望过滤：companies={payload.get('companies')}, years={payload.get('years')}, forms={payload.get('forms')}\n\n"
            f"候选片段：{json.dumps(candidates, ensure_ascii=False)}"
        ),
    }
    try:
        result = await llm.chat([prompt])
        content = str(result.get("content") or "{}").strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end >= start:
            parsed = json.loads(content[start : end + 1])
            labels = parsed.get("labels", [])
            return {
                str(item.get("chunk_id")): int(bool(item.get("relevant")))
                for item in labels
                if item.get("chunk_id") is not None
            }
    except Exception:
        pass
    return {str(item.get("chunk_id")): 0 for item in results[:10] if item.get("chunk_id") is not None}


async def _run_real_case(case: JsonlCase, searcher: FilingSearcher, llm: OpenAICompatibleLLM, config: AppConfig) -> dict[str, Any]:
    """执行单条真实模型样本，并用同一 LLM 做证据支持性 judge。"""

    trace = RealToolTrace()
    loop = AgentLoop(
        llm,
        _build_real_registry(searcher),
        _real_eval_system_prompt(),
        max_tool_rounds=config.max_tool_rounds,
        callbacks=AgentCallbacks(
            on_text_delta=lambda text: trace.text_parts.append(text),
            on_tool_start=lambda name, arguments: trace.starts.append({"name": name, "arguments": arguments}),
            on_tool_result=lambda name, payload: trace.results.append({"name": name, "payload": payload}),
        ),
    )

    final_content = ""
    for turn in case.payload["turns"]:
        result = await loop.run_turn(turn["user"])
        while result.status == "needs_clarification" and result.pending_clarification:
            answer = case.payload.get("clarification_answer") or "请基于当前问题中最合理的公司、年份和表单继续。"
            result = await loop.resume_after_clarification(result.pending_clarification, answer)
        if result.message and result.message.get("content"):
            final_content = str(result.message["content"])

    evidence = _collect_evidence(trace)
    judge = await _judge_answer(llm, case, final_content, evidence)
    return _score_real_case(case, trace, final_content, evidence, judge)


async def _run_real_case_with_retries(
    case: JsonlCase,
    searcher: FilingSearcher,
    llm: OpenAICompatibleLLM,
    config: AppConfig,
    *,
    retries: int = 1,
) -> dict[str, Any]:
    """真实 API 偶发断连时重试单条样本，避免整轮指标被网络抖动主导。"""

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await _run_real_case(case, searcher, llm, config)
        except Exception as exc:
            last_exc = exc
            print(
                f"[real-eval][agent] {case.case_id} attempt {attempt + 1} failed: {_error_message(exc)}",
                flush=True,
            )
    return _failed_agent_case(case, last_exc or RuntimeError("unknown failure"))


def _build_real_registry(searcher: FilingSearcher) -> ToolRegistry:
    """真实评测 registry：检索真实 markdown，计算和澄清复用正式工具。"""

    registry = ToolRegistry()

    def search_filings(
        query: str,
        companies: list[str] | None = None,
        years: list[int] | None = None,
        forms: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """检索真实 MCP markdown chunks。"""

        result = searcher.search(query, companies=companies, years=years, forms=forms, top_k=top_k)
        result["success"] = True
        if not result["results"]:
            result["suggestion"] = "没有在真实 MCP markdown 索引中找到匹配片段；请放宽公司、年份或表单过滤。"
        return result

    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Search indexed real 10-K/10-Q filing chunks downloaded by the EDGAR MCP tool. "
                "Before calling, rewrite the user question into a focused SEC filing search query. "
                "Use metadata filters whenever company, ticker, year, or form is known. "
                "For fiscal-year questions, use the fiscal/report year from the user."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "companies": {"type": "array", "items": {"type": "string"}},
                    "years": {"type": "array", "items": {"type": "integer"}},
                    "forms": {"type": "array", "items": {"type": "string", "enum": ["10-K", "10-Q"]}},
                    "top_k": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
            handler=search_filings,
        )
    )
    registry.register(build_calculator_tool())
    registry.register(build_clarify_tool())
    return registry


def _real_eval_system_prompt() -> str:
    """真实评测只使用已通过 MCP 下载并索引的 markdown，不在评测中现场下载。"""

    return (
        SYSTEM_PROMPT
        + "\n真实评测约束：本轮只允许使用已下载并索引的 MCP Markdown 财报。"
        "如果本地索引没有对应公司、年份或表单，请说明缺少证据，不要调用下载工具。"
    )


async def _judge_answer(llm: OpenAICompatibleLLM, case: JsonlCase, answer: str, evidence: str) -> dict[str, Any]:
    """让真实 LLM 根据检索证据判断最终答案是否回答问题且有依据。"""

    prompt = {
        "role": "user",
        "content": (
            "你是财报问答评测员。请只输出 JSON，不要输出额外文字。\n"
            "根据用户问题、Agent 最终答案和检索证据，判断：\n"
            "1. answers_question: 答案是否回答了用户问题。\n"
            "2. supported_by_evidence: 答案中的关键财报事实是否能由证据支持。\n"
            "3. mentions_source: 答案是否提到公司/年份/表单或类似来源。\n"
            "4. calculation_correct: 如果答案包含财务计算，公式和结果是否与证据一致；如果本题不需要计算，输出 1。\n"
            "如果问题本身超出已索引财报范围、要求预测，或财报原文不能证明该问题，且答案明确拒绝或说明缺少证据，"
            "answers_question 和 supported_by_evidence 都可以判为 1。\n"
            "输出格式：{\"answers_question\":0或1,\"supported_by_evidence\":0或1,\"mentions_source\":0或1,"
            "\"calculation_correct\":0或1,\"notes\":\"简短原因\"}\n\n"
            f"用户多轮问题：{json.dumps(case.payload['turns'], ensure_ascii=False)}\n\n"
            f"Agent 最终答案：{answer}\n\n"
            f"检索证据：{evidence[:12000]}"
        ),
    }
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            result = await llm.chat([prompt])
            content = str(result.get("content") or "{}").strip()
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end >= start:
                return json.loads(content[start : end + 1])
        except Exception as exc:
            last_exc = exc
    if last_exc:
        return {
            "answers_question": 0,
            "supported_by_evidence": 0,
            "mentions_source": 0,
            "calculation_correct": 0,
            "notes": f"judge failed: {_error_message(last_exc)}",
        }
    return {"answers_question": 0, "supported_by_evidence": 0, "mentions_source": 0, "notes": "judge returned non-json"}


def _real_metadata_match_at_k(results: list[dict[str, Any]], payload: dict[str, Any], k: int) -> float:
    """真实清洗文件可能 requested_year 和 report_period 年份不同，因此两个字段都接受。"""

    top = results[:k]
    if not top:
        return 0.0
    companies = {_normalize_company(company) for company in payload.get("companies", [])}
    years = set(payload.get("years", []))
    forms = {form.upper() for form in payload.get("forms", [])}
    matches = 0
    for result in top:
        ticker = _normalize_company(str(result.get("ticker") or ""))
        report_period = str(result.get("report_period") or "")
        report_year = int(report_period[:4]) if report_period[:4].isdigit() else None
        if companies and ticker not in companies:
            continue
        if years and result.get("requested_year") not in years and report_year not in years:
            continue
        if forms and str(result.get("form") or "").upper() not in forms:
            continue
        matches += 1
    return matches / len(top)


def _score_real_case(
    case: JsonlCase,
    trace: RealToolTrace,
    final_content: str,
    evidence: str,
    judge: dict[str, Any],
) -> dict[str, Any]:
    """把真实模型 trace 和 judge 结果转成指标行。"""

    expected = case.payload["expected"]
    expected_tools = list(expected.get("tools_sequence", []))
    if expected.get("should_clarify"):
        expected_tools = ["ask_user_clarification"] + expected_tools
    actual_tools = [item["name"] for item in trace.starts]

    required_tool_presence = 1.0 if all(tool in actual_tools for tool in expected_tools) else 0.0
    metadata_filter_accuracy = _real_metadata_filter_accuracy(trace, expected)
    clarification_precision = 1.0 if (bool(expected.get("should_clarify")) == ("ask_user_clarification" in actual_tools)) else 0.0
    invalid_tool_call_rate = _invalid_tool_call_rate(trace)
    answers_question = float(int(judge.get("answers_question", 0) or 0))
    supported_by_evidence = float(int(judge.get("supported_by_evidence", 0) or 0))
    calculation_close_match = _real_calculation_score(trace, expected, judge)
    answer_judge_success = 1.0 if answers_question and supported_by_evidence else 0.0

    required_scores = [required_tool_presence, metadata_filter_accuracy, clarification_precision, answer_judge_success]
    if "calculate_decimal" in expected_tools:
        required_scores.append(calculation_close_match)

    return {
        "id": case.case_id,
        "category": case.payload.get("category"),
        "task_success": 1.0 if all(score == 1.0 for score in required_scores) else 0.0,
        "required_tool_presence": required_tool_presence,
        "metadata_filter_accuracy": metadata_filter_accuracy,
        "answer_judge_success": answer_judge_success,
        "answers_question": answers_question,
        "answer_supported_by_evidence": supported_by_evidence,
        "mentions_source": float(int(judge.get("mentions_source", 0) or 0)),
        "calculation_close_match": calculation_close_match,
        "calculation_expected": "calculate_decimal" in expected_tools,
        "clarification_precision": clarification_precision,
        "invalid_tool_call_rate": invalid_tool_call_rate,
        "tool_call_count": len(actual_tools),
        "actual_tools": actual_tools,
        "final_answer": final_content,
        "judge": judge,
        "evidence_preview": evidence[:2000],
    }


def _failed_agent_case(case: JsonlCase, exc: Exception) -> dict[str, Any]:
    """单条真实模型调用失败时保留失败行，让整轮评测继续产出报告。"""

    expected_tools = list(case.payload.get("expected", {}).get("tools_sequence", []))
    error = _error_message(exc)
    return {
        "id": case.case_id,
        "category": case.payload.get("category"),
        "task_success": 0.0,
        "required_tool_presence": 0.0 if expected_tools else 1.0,
        "metadata_filter_accuracy": 0.0 if expected_tools else 1.0,
        "answer_judge_success": 0.0,
        "answers_question": 0.0,
        "answer_supported_by_evidence": 0.0,
        "mentions_source": 0.0,
        "calculation_close_match": 0.0,
        "calculation_expected": "calculate_decimal" in expected_tools,
        "clarification_precision": 0.0,
        "invalid_tool_call_rate": 1.0,
        "tool_call_count": 0,
        "actual_tools": [],
        "final_answer": "",
        "judge": {"error": error},
        "evidence_preview": "",
    }


def _error_message(exc: Exception) -> str:
    """异常 str 为空时回退到类型名，避免报告里只剩空错误。"""

    return str(exc) or exc.__class__.__name__


def _real_metadata_filter_accuracy(trace: RealToolTrace, expected: dict[str, Any]) -> float:
    """真实模型可多次检索；只要有一次检索参数覆盖期望 metadata 即通过。"""

    if "search_filings" not in expected.get("tools_sequence", []):
        return 1.0
    search_args = expected.get("search_args", {})
    expected_companies = {_normalize_company(company) for company in search_args.get("companies", [])}
    expected_years = set(search_args.get("years", []))
    expected_forms = {form.upper() for form in search_args.get("forms", [])}

    for call in trace.starts:
        if call["name"] != "search_filings":
            continue
        args = call["arguments"]
        actual_companies = {_normalize_company(company) for company in args.get("companies", [])}
        actual_years = set(args.get("years", []))
        actual_forms = {form.upper() for form in args.get("forms", [])}
        company_ok = not expected_companies or bool(expected_companies & actual_companies)
        year_ok = not expected_years or bool(expected_years & actual_years)
        form_ok = not expected_forms or bool(expected_forms & actual_forms)
        if company_ok and year_ok and form_ok:
            return 1.0
    return 0.0


def _real_calculation_score(trace: RealToolTrace, expected: dict[str, Any], judge: dict[str, Any]) -> float:
    """真实财报评测优先用 evidence judge 判断计算是否正确。"""

    if "calculate_decimal" not in expected.get("tools_sequence", []):
        return 1.0
    if "calculation_correct" in judge:
        return float(int(judge.get("calculation_correct", 0) or 0))
    return _calculation_close_match(trace, expected)


def _calculation_close_match(trace: RealToolTrace, expected: dict[str, Any]) -> float:
    """真实模型可能保留更多小数；这里按 0.2 容差比较 Decimal 结果。"""

    if "calculate_decimal" not in expected.get("tools_sequence", []):
        return 1.0
    expected_result = expected.get("calculation_result")
    if expected_result is None:
        return 0.0
    for row in trace.results:
        if row["name"] != "calculate_decimal":
            continue
        result = row["payload"].get("result") if isinstance(row["payload"], dict) else None
        if not isinstance(result, dict) or not result.get("success"):
            continue
        try:
            actual = Decimal(str(result.get("result")))
            expected_decimal = Decimal(str(expected_result))
        except (InvalidOperation, TypeError):
            continue
        if abs(actual - expected_decimal) <= Decimal("0.2"):
            return 1.0
    return 0.0


def _invalid_tool_call_rate(trace: RealToolTrace) -> float:
    """统计工具失败比例，反映真实模型是否产生坏参数或触发工具错误。"""

    if not trace.results:
        return 0.0
    failures = 0
    for row in trace.results:
        payload = row.get("payload", {})
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict) and result.get("success") is False:
            failures += 1
    return failures / len(trace.results)


def _collect_evidence(trace: RealToolTrace) -> str:
    """从 search_filings tool result 中抽取 judge 需要的证据片段。"""

    parts: list[str] = []
    for row in trace.results:
        if row["name"] != "search_filings":
            continue
        payload = row.get("payload", {})
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            continue
        for item in result.get("results", [])[:5]:
            source = f"{item.get('ticker')} {item.get('requested_year')} {item.get('form')} {item.get('section_path')}"
            parts.append(f"[{source}]\n{item.get('text', '')[:1800]}")
    return "\n\n".join(parts)


def write_real_markdown_report(path: Path, report: dict[str, Any]) -> None:
    """写出真实模型真实财报评测报告。"""

    retrieval_summary = report["retrieval"]["summary"]
    agent_summary = report["agent"]["summary"]
    lines = [
        "# Real LLM + Real Filing Evaluation Report",
        "",
        f"Generated at: {report['generated_at']}",
        f"Model: {report['model']}",
        f"Real filing count: {report['filing_count']}",
        "",
        "## Retrieval Layer",
        "",
        "| Variant | Recall@5 | MRR@10 | nDCG@10 | Metadata Match@5 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in retrieval_summary.items():
        lines.append(
            f"| {name} | {percent(metrics['recall_at_5'])} | {metrics['mrr_at_10']:.3f} | "
            f"{metrics['ndcg_at_10']:.3f} | {percent(metrics['metadata_match_at_5'])} |"
        )

    lines.extend(
        [
            "",
            "## Agent Layer",
            "",
            f"- Case count: {agent_summary['case_count']}",
            f"- Strict task success rate: {percent(agent_summary['task_success_rate'])}",
            f"- Required tool presence: {percent(agent_summary['required_tool_presence'])}",
            f"- Metadata filter accuracy: {percent(agent_summary['metadata_filter_accuracy'])}",
            f"- Answer judge success: {percent(agent_summary['answer_judge_success'])}",
            f"- Supported by evidence: {percent(agent_summary['answer_supported_by_evidence'])}",
            f"- Answers question: {percent(agent_summary['answers_question'])}",
            f"- Calculation correctness: {_format_optional_percent(agent_summary['calculation_close_match'])}",
            f"- Clarification precision: {percent(agent_summary['clarification_precision'])}",
            f"- Invalid tool call rate: {percent(agent_summary['invalid_tool_call_rate'])}",
            f"- Average tool calls: {agent_summary['average_tool_calls']:.2f}",
            "",
            "## Strict Failed Agent Cases",
            "",
        ]
    )
    failed = [row for row in report["agent"]["details"] if row["task_success"] < 1.0]
    if not failed:
        lines.append("No failed cases.")
    else:
        for row in failed:
            lines.append(
                f"- {row['id']} ({row['category']}): failed={_failed_dimensions(row)}, tools={row['actual_tools']}, "
                f"judge={row['judge']}, answer={row['final_answer'][:300]}"
            )
    lines.extend(
        [
            "",
            "Note: This report uses cleaned Markdown filings downloaded through the local EDGAR MCP server. "
            "Retrieval relevance and final-answer support are judged by the configured real model.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _format_optional_percent(value: float | None) -> str:
    """计算题为空时显式写 N/A，避免 0% 误导。"""

    return "N/A" if value is None else percent(value)


def _failed_dimensions(row: dict[str, Any]) -> str:
    """报告严格失败样本时列出具体短板，方便区分答案错和工具策略错。"""

    dimensions = []
    checks = {
        "required_tool_presence": row.get("required_tool_presence"),
        "metadata_filter_accuracy": row.get("metadata_filter_accuracy"),
        "answer_judge_success": row.get("answer_judge_success"),
        "calculation_correctness": row.get("calculation_close_match") if row.get("calculation_expected") else 1.0,
        "clarification_precision": row.get("clarification_precision"),
    }
    for name, value in checks.items():
        if float(value or 0.0) < 1.0:
            dimensions.append(name)
    return ",".join(dimensions) or "unknown"


def main() -> None:
    """命令行入口：用真实 LLM 和真实 MCP markdown 重跑 Agent 评测。"""

    import argparse

    parser = argparse.ArgumentParser(description="Run real LLM + real filing evaluation.")
    parser.add_argument("--eval-dir", default="data/eval")
    parser.add_argument("--output-dir", default="data/eval/runs/real_latest")
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()

    config = load_config(require_llm=True)
    report = run_real_eval(config, Path(args.eval_dir), max_cases=args.max_cases)
    output_dir = Path(args.output_dir)
    write_json(output_dir / "real_report.json", report)
    write_real_markdown_report(output_dir / "real_report.md", report)
    print(f"Wrote {output_dir / 'real_report.json'}")
    print(f"Wrote {output_dir / 'real_report.md'}")


if __name__ == "__main__":
    main()
