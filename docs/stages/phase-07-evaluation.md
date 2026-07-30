# 阶段 7：评测集和指标报告

## 1. 阶段目标

本阶段实现两层评测：

1. 检索层评测：用人工标注 gold terms 的查询集评估 `Recall@5`、`MRR@10`、`nDCG@10` 和 `Metadata Match@5`，并比较 `vector_only`、`metadata_filter`、`full_context_rerank` 三种方案。
2. 端到端 Agent 评测：用 30 条模拟用户交互覆盖单轮事实、多轮上下文、多公司比较、Decimal 计算、澄清和边界场景，评估工具调用、过滤参数、计算、澄清、来源和任务成功率。

评测默认使用本地 fixture 财报，避免依赖 SEC 实时下载、远程 LLM 波动和本机 bge 模型缓存。阶段收尾时额外实现真实评测模式：只通过 EDGAR MCP 下载清洗后的真实 markdown，并用真实 OpenAI-compatible 模型运行同一批检索和 Agent 任务。

## 2. 做了什么

新增代码：

- `fin_report_agent/eval/dataset.py`
- `fin_report_agent/eval/fixtures.py`
- `fin_report_agent/eval/memory.py`
- `fin_report_agent/eval/metrics.py`
- `fin_report_agent/eval/retrieval_eval.py`
- `fin_report_agent/eval/agent_eval.py`
- `fin_report_agent/eval/runner.py`
- `fin_report_agent/eval/real_eval.py`

新增数据：

- `data/eval/retrieval_cases.jsonl`：12 条检索 gold cases。
- `data/eval/cases.jsonl`：30 条端到端模拟交互 cases。

真实 MCP 财报样本：

- `data/filings/AAPL_2023_10-K_2023-11-03_0000320193-23-000106.md`
- `data/filings/AAPL_2024_10-Q_2024-08-02_0000320193-24-000081.md`
- `data/filings/AMZN_2024_10-K_2024-02-02_0001018724-24-000008.md`
- `data/filings/MSFT_2023_10-K_2023-07-27_0000950170-23-035122.md`
- `data/filings/MSFT_2024_10-Q_2024-10-30_0000950170-24-118967.md`
- `data/filings/NVDA_2024_10-K_2024-02-21_0001045810-24-000029.md`
- `data/filings/TSLA_2024_10-K_2024-01-29_0001628280-24-002390.md`

新增测试：

- `tests/test_eval_runner.py`

新增 CLI：

- `python -m fin_report_agent.eval.runner`
- `python -m fin_report_agent.eval.real_eval`

## 3. 怎么实现

### 检索层

`run_retrieval_eval()` 执行以下流程：

1. `write_fixture_filings()` 生成迷你 10-K/10-Q markdown。
2. 复用正式的 `parse_metadata_file()`、`chunk_markdown()` 和 `attach_context()` 构建 chunks。
3. 用 `InMemoryChunkStore` 替代 LanceDB，让评测不依赖重依赖。
4. 用 `KeywordEmbeddingModel` 替代 bge-m3，让结果稳定可复现。
5. 跑三种 variant：无过滤 baseline、metadata filter、metadata filter + context + rerank。
6. 对每条 retrieval case 计算 `Recall@5`、`MRR@10`、`nDCG@10` 和 `Metadata Match@5`。

### 端到端 Agent 层

`run_agent_eval()` 执行以下流程：

1. 读取 30 条 JSONL 模拟用户交互。
2. 构建 fixture 检索索引。
3. 用正式 `AgentLoop` 跑每条样本。
4. 用 `ScriptedEvalLLM` 稳定地产生 tool calls 和最终回答。
5. 检索 tool 使用 fixture searcher。
6. 计算 tool 复用正式 `DecimalCalculatorSession`。
7. 澄清 tool 复用正式 `ask_user_clarification` 暂停机制。
8. 从 tool trace 和最终答案中计算端到端指标。

### 真实 MCP + 真实模型评测

`run_real_eval()` 执行以下流程：

1. 从 `data/filings/*.md` 读取 EDGAR MCP 已清洗的真实 markdown，不直接请求 SEC 页面。
2. 用正式 metadata parser、chunker、context 生成逻辑构建内存索引。
3. 检索层仍比较 `vector_only`、`metadata_filter`、`full_context_rerank` 三个变体。
4. 因真实 SEC 原文不会包含 fixture gold phrase，检索相关性由配置的真实模型 judge top-10 候选片段。
5. Agent 层使用正式 `AgentLoop`、真实模型、真实 `search_filings`、正式 Decimal 计算工具和澄清工具。
6. 最终答案由真实模型 judge：是否回答问题、是否由证据支持、是否提到来源、计算是否与证据一致。
7. 每个 Agent case 最多重试 1 次，避免临时 `ConnectError` 或流式断连直接拖垮整轮评测。
8. 流式 LLM 调用设置超时，防止真实模型长时间不返回导致评测挂死。

## 4. 关键决策

- 默认评测不调用真实 LLM，保证回归结果可重复；真实评测作为独立命令运行。
- fixture 评测复用正式 chunker/context/AgentLoop/calculator/clarify 代码。
- 真实评测只使用 EDGAR MCP 生成的清洗 markdown，不在评测 runner 里绕过 MCP 直接下载。
- 检索评测保留消融实验，而不是只报最终 pipeline 分数。
- 端到端评测把自然语言优美度放在后面，优先验证行为链路和可追溯性。
- `data/eval/runs/` 和生成的 fixture markdown 不提交，评测报告本地生成。

## 5. 决策原因

- 真实 LLM 评测容易受模型版本、API 延迟和采样波动影响；阶段 7 先保证工程链路可重复。
- 真实财报文本和 fixture 文案不同，真实评测必须使用 judge 判断证据相关性和计算正确性，不能用 fixture 字符串硬匹配。
- 严格任务成功率同时约束工具策略、metadata filter、答案证据和澄清行为；答案质量另看 `Answer judge success`，便于区分“答案对但工具参数不理想”的样本。
- 复用正式核心模块能防止评测变成另一套玩具实现。
- 消融实验能解释 metadata filter 和 context/rerank 的价值，适合简历项目呈现。
- 财报 Agent 的可靠性首先来自工具调用、检索过滤、计算精度和来源覆盖。

## 6. 验证方式

运行真实 MCP + 真实模型评测：

```bash
uv pip install -e mcp/edgar-mcp-server
uv run python -m fin_report_agent.eval.real_eval --eval-dir data/eval --output-dir data/eval/runs/real_latest
```

生成：

```text
data/eval/runs/real_latest/real_report.json
data/eval/runs/real_latest/real_report.md
```

本次真实评测配置：

- Model: `deepseek-v4-flash`
- Filing count: 7
- SEC identity: 使用项目默认教学评测 UA 或 `.env`/环境变量中的 `EDGAR_IDENTITY`
- 下载方式：仅通过 `edgar-report-mcp` 的 `download_10k_10q_markdown`

本次真实评测结果：

| 层级 | 指标 | 结果 |
| --- | --- | ---: |
| Retrieval vector_only | Recall@5 | 33.3% |
| Retrieval vector_only | MRR@10 | 0.165 |
| Retrieval vector_only | nDCG@10 | 0.240 |
| Retrieval vector_only | Metadata Match@5 | 26.7% |
| Retrieval metadata_filter | Recall@5 | 41.7% |
| Retrieval metadata_filter | MRR@10 | 0.298 |
| Retrieval metadata_filter | nDCG@10 | 0.385 |
| Retrieval metadata_filter | Metadata Match@5 | 100.0% |
| Retrieval full_context_rerank | Recall@5 | 50.0% |
| Retrieval full_context_rerank | MRR@10 | 0.341 |
| Retrieval full_context_rerank | nDCG@10 | 0.433 |
| Retrieval full_context_rerank | Metadata Match@5 | 100.0% |
| Agent | Case count | 30 |
| Agent | Strict task success rate | 70.0% |
| Agent | Required tool presence | 100.0% |
| Agent | Metadata filter accuracy | 90.0% |
| Agent | Answer judge success | 83.3% |
| Agent | Supported by evidence | 83.3% |
| Agent | Answers question | 93.3% |
| Agent | Calculation correctness | 100.0% |
| Agent | Clarification precision | 96.7% |
| Agent | Invalid tool call rate | 3.9% |
| Agent | Average tool calls | 2.70 |

## 7. 后续事项

- 将真实检索评测从关键词内存索引升级到 LanceDB、bge-m3 和 bge-reranker。
- 针对真实失败样本优化 query rewrite 和证据覆盖，尤其是风险披露、季度口径、多轮追问。
- 将 fixture 回归里的 answer faithfulness 从规则 gold terms 扩展为可选 LLM judge 或人工复核。
- 在简历中使用指标时，应区分 deterministic fixture benchmark 和 real LLM + real filings benchmark。
