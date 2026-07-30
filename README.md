# FinReportAgent

这是一个教学性质的美股财报分析问答 Agent。项目以 SEC 10-K/10-Q 财报 markdown 为数据源，使用 Agentic RAG，让检索、计算、澄清和财报下载都作为 tool 被极简 Agent Loop 调用。

详细开发计划见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。每个阶段结束后的独立开发文档放在 [docs/stages/](docs/stages/)。

## 快速开始

```bash
uv venv
source .venv/bin/activate
uv sync
uv pip install -e mcp/edgar-mcp-server
```

如果要启用 LanceDB、bge-m3 embedding 和 bge-reranker 检索链路，安装 retrieval extra：

```bash
uv sync --extra retrieval
```

`.env` 需要提供 OpenAI compatible chat completions 配置：

```bash
API_KEY=...
BASE_URL=...
MODEL=...
```

下载 SEC 财报前还需要设置：

```bash
export EDGAR_IDENTITY="Your Name your.email@example.com"
```

启动 TUI：

```bash
uv run python -m fin_report_agent.main
```

运行测试：

```bash
uv run pytest
```

运行阶段 7 评测：

```bash
uv run python -m fin_report_agent.eval.runner --eval-dir data/eval --output-dir data/eval/runs/latest
```

评测会生成：

- `data/eval/runs/latest/report.json`
- `data/eval/runs/latest/report.md`

运行真实 MCP 财报 + 真实模型评测：

```bash
uv pip install -e mcp/edgar-mcp-server
uv run python -m fin_report_agent.eval.real_eval --eval-dir data/eval --output-dir data/eval/runs/real_latest
```

真实评测会读取 `data/filings/*.md` 中由 EDGAR MCP 下载并清洗好的财报，生成：

- `data/eval/runs/real_latest/real_report.json`
- `data/eval/runs/real_latest/real_report.md`

## 当前阶段

当前代码已按阶段 1-7 的计划实现：

- 极简 Agent Loop：支持多轮对话、流式输出和 tool calling。
- EDGAR MCP tools：公司解析和 10-K/10-Q markdown 下载。
- 检索链路：metadata filter、结构感知切块、规则 Contextual Retrieval、LanceDB、bge-m3、bge-reranker。
- Agentic RAG tools：`index_filing_markdown` 和 `search_filings`。
- Decimal 计算 tool：会话级安全 REPL，使用 `Decimal` 而不是 float。
- 用户澄清 tool：Agent Loop 可暂停，TUI 收集用户回答后恢复。
- TUI：模块入口 `python -m fin_report_agent.main`。
- Evaluation：第一层检索消融评测、第二层 30 条端到端 Agent 评测，以及真实 MCP 财报 + 真实模型复评。

当前真实 MCP 财报 + 真实模型评测结果：

- 真实财报：7 份 EDGAR MCP 清洗后的 10-K/10-Q markdown。
- Retrieval full_context_rerank：Recall@5 50.0%，MRR@10 0.341，nDCG@10 0.433，Metadata Match@5 100.0%。
- Agent 30-case strict task success：70.0%。
- Agent answer judge success：83.3%，answers question：93.3%，calculation correctness：100.0%。
