# 阶段 4：检索 Tool + Reranker

## 1. 阶段目标

实现 Agentic RAG 的核心入口：把检索作为 tool 暴露给 Agent Loop。检索时先按 metadata filter 缩小范围，再用 bge-m3 向量召回，最后用 bge-reranker 重排。

## 2. 做了什么

新增文件：

- `fin_report_agent/retrieval/search.py`
- `fin_report_agent/retrieval/rerank.py`
- `fin_report_agent/tools/retrieval_tool.py`

新增 tool：

- `search_filings`

辅助能力：

- `RetrievalRuntime` 延迟加载 LanceDB、embedding 和 reranker。
- `NoopReranker` 作为测试和降级路径。
- `HashEmbeddingModel` 作为显式测试 embedding。

## 3. 怎么实现

`search_filings` 的参数：

- `query`：模型改写后的检索查询。
- `companies`：公司、ticker 或 CIK。
- `years`：年份。
- `forms`：10-K 或 10-Q。
- `top_k`：最终返回结果数。

执行流程：

1. `_build_filters()` 将 `companies`、`years`、`forms` 转为 metadata filters。
2. `embedding_model.embed_texts([query])` 得到查询向量。
3. `LanceDBChunkStore.search()` 在 where filter 下召回候选 chunks。
4. `Reranker.rerank()` 对候选 chunks 重新排序。
5. `_format_candidate()` 控制每个 chunk 输出长度，并保留来源字段。

tool description 明确要求模型：

- 调用前改写用户问题。
- 查询里加入英文财务术语、公司、年份、表单和可能的 SEC section。
- 已知 metadata 必须填 filters。
- 不要用检索 tool 做算术，计算交给 `calculate_decimal`。

## 4. 关键决策

- 检索 tool 不隐藏在回答流程前置步骤里，而是由模型主动调用。
- 先 metadata filter，再向量召回。
- 初召回数量为 `max(top_k * 5, 30)`，再 rerank 到 top_k。
- reranker 默认本地 `BAAI/bge-reranker-base`，可通过 `FIN_AGENT_RERANKER_MODEL` 覆盖。
- 检索无结果时返回建议，引导模型先下载并索引。

## 5. 决策原因

- 这正是 Agentic RAG 的 “Agentic” 部分：模型决定何时需要查证。
- 财报问答通常公司和年份明确，metadata filter 能显著减少误召回。
- reranker 可以把语义相似但不回答问题的 chunk 往后排。
- 模型名称通过环境变量覆盖，可以适配用户本机实际缓存。
- 无结果时给下一步建议，能让 Agent 自己修复“未索引”的状态。

## 6. 验证方式

已验证 registry 注册检索 tools：

```bash
uv run python - <<'PY'
from fin_report_agent.config import load_config
from fin_report_agent.tui.app import build_registry
config = load_config(require_llm=False)
registry = build_registry(config)
print([schema["function"]["name"] for schema in registry.schemas()])
PY
```

输出包含：

```text
index_filing_markdown
search_filings
```

完整测试：

```bash
uv run pytest
```

结果：

```text
13 passed
```

## 7. 后续事项

- 真实检索需要先安装 `uv sync --extra retrieval`。
- 如果本机 reranker 缓存名不是默认值，设置 `FIN_AGENT_RERANKER_MODEL`。
- 如果只想调试检索控制流，可以临时设置 `FIN_AGENT_ALLOW_HASH_EMBEDDINGS=1` 和 `FIN_AGENT_DISABLE_RERANKER=1`。

