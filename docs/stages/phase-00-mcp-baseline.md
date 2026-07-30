# 阶段 0：理解并固定 MCP 数据入口

## 1. 阶段目标

本阶段的目标是确认初始提供的 `edgar-report-mcp` server 是主项目的数据入口，并固定它和主 Agent 之间的边界：MCP server 只负责解析公司、下载 SEC 10-K/10-Q、清洗 markdown 和返回本地路径；主项目负责 Agent Loop、检索索引、计算、澄清和 TUI。

## 2. 做了什么

- 阅读 `mcp/edgar-mcp-server/README.md`，确认已有 tools 和本地验证方式。
- 阅读 `mcp/edgar-mcp-server/src/edgar_mcp_server/server.py`，确认 markdown header、文件输出、中文别名和错误返回格式。
- 保留 MCP server 的原有职责，不把主 Agent 逻辑写进 `mcp/edgar-mcp-server`。
- 在主项目中新增 `fin_report_agent/mcp_client/edgar.py`，后续只通过 MCP stdio 协议调用该 server。

## 3. 怎么实现

主项目通过 `EdgarMCPClient` 调用 MCP：

1. 默认用 `uv run --project mcp/edgar-mcp-server edgar-report-mcp` 启动 server。
2. 把 `EDGAR_IDENTITY` 和 `EDGAR_MCP_OUTPUT_DIR` 传给 MCP subprocess。
3. 使用 `ClientSession.call_tool` 调用 `resolve_company_name` 或 `download_10k_10q_markdown`。
4. 把 MCP SDK 返回的 structured content 或 text content 统一解析为 `dict`。

这样主项目只依赖 MCP 协议和 tool 名称，不依赖 server 内部 helper 函数。

## 4. 关键决策

- 不直接 import `edgar_mcp_server.server`。
- 默认通过 `uv --project` 启动 MCP 子项目。
- MCP 下载结果在 Agent tool 包装层被压缩，去掉大段 `preview` 和 `content`。
- 下载后的 markdown 不自动进入检索库，索引由 `index_filing_markdown` 明确完成。

## 5. 决策原因

- MCP server 是外部数据获取层，主 Agent 应该把它当作协议服务而不是内部模块。
- `uv --project` 能让子项目按自己的 `pyproject.toml` 管理依赖，避免主项目强行绑定 `edgartools`。
- 压缩 MCP 响应可以减少模型上下文浪费，保留关键路径、表单、披露日期和 SEC 链接即可。
- 下载和索引分开，能让教学时清楚看到“数据获取”和“检索构建”是两件事。

## 6. 验证方式

已验证：

```bash
uv run python - <<'PY'
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
print("mcp-client-import-ok")
PY
```

结果：

```text
mcp-client-import-ok
```

同时完整测试通过：

```bash
uv run pytest
```

结果：

```text
13 passed
```

## 7. 后续事项

- 真正下载财报前必须设置 `EDGAR_IDENTITY`。
- 若用户希望使用固定 MCP 可执行文件，可以设置 `EDGAR_MCP_COMMAND` 覆盖默认启动命令。

