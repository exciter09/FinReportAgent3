from __future__ import annotations

from pathlib import Path

from fin_report_agent.eval.runner import run_all


def test_phase7_eval_runner_produces_expected_metrics(tmp_path: Path) -> None:
    """阶段 7 评测应能在本地 fixture 上稳定跑出核心指标。"""

    source_dir = Path("data/eval")
    (tmp_path / "cases.jsonl").write_text((source_dir / "cases.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "retrieval_cases.jsonl").write_text(
        (source_dir / "retrieval_cases.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report = run_all(tmp_path)

    retrieval = report["retrieval"]["summary"]
    agent = report["agent"]["summary"]
    assert retrieval["vector_only"]["metadata_match_at_5"] < retrieval["metadata_filter"]["metadata_match_at_5"]
    assert retrieval["metadata_filter"]["mrr_at_10"] >= retrieval["vector_only"]["mrr_at_10"]
    assert agent["case_count"] == 30
    assert agent["task_success_rate"] == 1.0
    assert agent["calculation_exact_match"] == 1.0
