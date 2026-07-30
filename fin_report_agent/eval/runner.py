from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from fin_report_agent.eval.agent_eval import run_agent_eval
from fin_report_agent.eval.dataset import write_json
from fin_report_agent.eval.metrics import percent
from fin_report_agent.eval.retrieval_eval import run_retrieval_eval


def run_all(eval_dir: Path) -> dict[str, Any]:
    """运行第一层检索评测和第二层端到端 Agent 评测。"""

    retrieval = run_retrieval_eval(eval_dir)
    agent = run_agent_eval(eval_dir)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "retrieval": retrieval,
        "agent": agent,
    }


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    """把核心指标写成简短 markdown，方便放进文档或简历复盘。"""

    lines = [
        "# Phase 7 Evaluation Report",
        "",
        f"Generated at: {report['generated_at']}",
        "",
        "## Retrieval Layer",
        "",
        "| Variant | Recall@5 | MRR@10 | nDCG@10 | Metadata Match@5 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in report["retrieval"]["summary"].items():
        lines.append(
            f"| {name} | {percent(metrics['recall_at_5'])} | {metrics['mrr_at_10']:.3f} | "
            f"{metrics['ndcg_at_10']:.3f} | {percent(metrics['metadata_match_at_5'])} |"
        )

    agent = report["agent"]["summary"]
    lines.extend(
        [
            "",
            "## Agent Layer",
            "",
            f"- Case count: {agent['case_count']}",
            f"- Task success rate: {percent(agent['task_success_rate'])}",
            f"- Tool call accuracy: {percent(agent['tool_call_accuracy'])}",
            f"- Metadata filter accuracy: {percent(agent['metadata_filter_accuracy'])}",
            f"- Answer faithfulness: {percent(agent['answer_faithfulness'])}",
            f"- Calculation exact match: {percent(agent['calculation_exact_match'])}",
            f"- Clarification precision: {percent(agent['clarification_precision'])}",
            f"- Source coverage: {percent(agent['source_coverage'])}",
            f"- Retrieval support: {percent(agent['retrieval_support'])}",
            f"- Average tool calls: {agent['average_tool_calls']:.2f}",
            "",
            "Note: This report uses deterministic local fixture filings so it can run without live SEC downloads or remote LLM variance.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """命令行入口：生成 JSON 和 markdown 两份评测报告。"""

    parser = argparse.ArgumentParser(description="Run FinReportAgent phase 7 evaluations.")
    parser.add_argument("--eval-dir", default="data/eval", help="评测数据目录")
    parser.add_argument("--output-dir", default="data/eval/runs/latest", help="报告输出目录")
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    report = run_all(eval_dir)
    write_json(output_dir / "report.json", report)
    write_markdown_report(output_dir / "report.md", report)
    print(f"Wrote {output_dir / 'report.json'}")
    print(f"Wrote {output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
