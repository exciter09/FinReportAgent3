# 阶段 2：接入 MCP 并实现财报下载流程

## 1. 阶段目标

把初始提供的 EDGAR MCP server 接入主 Agent，让模型可以通过 tools 解析公司和下载 10-K/10-Q markdown。

## 2. 做了什么

新增文件：

- `fin_report_agent/mcp_client/edgar.py`：MCP stdio client。
- `fin_report_agent/tools/edgar_tools.py`：Agent 可见的 `resolve_company` 和 `download_filing_markdown`。

更新：

- `fin_report_agent/tui/app.py` 在 registry 中注册 EDGAR tools。
- `README.md` 增加 MCP server 安装说明。

## 3. 怎么实现

`EdgarMCPClient` 负责协议调用：

1. 准备 MCP server 启动命令。
2. 准备环境变量。
3. 通过 `stdio_client` 建立连接。
4. 初始化 MCP `ClientSession`。
5. 调用指定 tool。
6. 将不同 MCP SDK 版本的返回格式标准化为 dict。

两个 Agent tools：

- `resolve_company` 调用 MCP 的 `resolve_company_name`。
- `download_filing_markdown` 调用 MCP 的 `download_10k_10q_markdown`，并显式设置输出目录为 `data/filings/` 或 `EDGAR_MCP_OUTPUT_DIR`。

下载 tool 会压缩 MCP 响应：

- 保留 `company`、`requested`、`output_dir`、`filings`、`errors`。
- 删除大段 `preview` 和 `content`。
- 成功时添加 `next_step`，提示模型继续调用 `index_filing_markdown`。

## 4. 关键决策

- MCP client 默认用 `uv run --project mcp/edgar-mcp-server edgar-report-mcp` 启动。
- 提供 `EDGAR_MCP_COMMAND` 作为高级覆盖入口。
- Agent tool 名称使用更面向 Agent 行为的名字：`resolve_company`、`download_filing_markdown`。
- 下载 tool 不直接索引，索引由检索阶段 tool 负责。

## 5. 决策原因

- 默认命令不要求用户手动找 MCP 可执行文件路径。
- 覆盖命令保留部署弹性。
- Agent tool 名称应该表达“模型为什么调用它”，而不是完全复制 MCP 内部命名。
- 下载和索引分离，能让用户和文档清楚看到数据生命周期。

## 6. 验证方式

已验证 MCP client 依赖可导入：

```bash
uv run python - <<'PY'
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
print("mcp-client-import-ok")
PY
```

已验证 registry 注册了 EDGAR tools：

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
resolve_company
download_filing_markdown
```

## 7. 后续事项

- 真实下载需要设置 `EDGAR_IDENTITY`。
- 如果下载到 foreign private issuer 且没有 10-K/10-Q，MCP server 会返回 20-F/6-K 相关建议，Agent 应向用户解释。

