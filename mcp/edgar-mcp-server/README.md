# Edgar 10-K/10-Q Markdown MCP Server

基于 [dgunning/edgartools](https://github.com/dgunning/edgartools) 的一个专用 MCP server。

它做一件事：输入中英文公司名和年份，找到对应 SEC 公司，下载该年份的 10-K/10-Q，使用 `edgartools` 转成 markdown，再做轻量清洗并保存为本地 `.md` 文件。

## Tools

### `resolve_company_name`

输入公司名、ticker 或 CIK，返回解析结果和候选公司。

示例参数：

```json
{"company_name": "苹果"}
```

### `download_10k_10q_markdown`

下载并清洗指定年份的 10-K/10-Q。

示例参数：

```json
{
  "company_name": "苹果",
  "year": 2023,
  "form_type": "both",
  "max_filings": 4
}
```

返回内容包含：

- resolved company: 公司名、CIK、ticker
- filings: 每个财报的 form、filed date、report period、accession number
- path: 清洗后的 markdown 文件路径
- bytes/chars: 文件大小和字符数
- filing_url/homepage_url: SEC 原始链接

默认不会把整篇 markdown 塞回 MCP 响应，只返回文件路径和预览。需要直接返回内容时，把 `include_content` 设为 `true`，并用 `max_content_chars` 控制长度。

## 安装

```bash
python -m venv .venv
.venv/bin/python -m pip install .
```

## SEC Identity

SEC 要求请求带身份标识。运行前请设置：

```bash
export EDGAR_IDENTITY="Your Name your.email@example.com"
```

可选输出目录：

```bash
export EDGAR_MCP_OUTPUT_DIR="/absolute/path/to/edgar_markdown"
```

如果不设置，默认写到当前工作目录下的 `edgar_filings/`。

## MCP 配置示例

本地开发安装后：

```json
{
  "mcpServers": {
    "edgar-report-mcp": {
      "command": "/absolute/path/to/edgar-mcp-server/.venv/bin/edgar-report-mcp",
      "env": {
        "EDGAR_IDENTITY": "Your Name your.email@example.com",
        "EDGAR_MCP_OUTPUT_DIR": "/absolute/path/to/edgar_markdown"
      }
    }
  }
}
```

## 中文公司名

SEC 和 `edgartools` 原生索引主要是英文公司名、ticker 和 CIK。这个 server 内置了一批常见中文别名，例如：

- 苹果 -> AAPL
- 微软 -> MSFT
- 英伟达/辉达 -> NVDA
- 特斯拉 -> TSLA
- 亚马逊 -> AMZN
- 谷歌/字母表 -> GOOGL
- 阿里巴巴 -> BABA

你可以通过环境变量扩展别名：

```bash
export EDGAR_COMPANY_ALIASES_JSON='{"小鹏汽车":"XPEV","蔚来":"NIO"}'
```

注意：很多中国公司在美国是 foreign private issuer，通常提交 `20-F`/`6-K`，不是 `10-K`/`10-Q`。如果指定年份没有 10-K/10-Q，工具会返回说明和建议。

## 本地验证

```bash
python -m unittest discover -s tests
```

列出 MCP tools：

```bash
python - <<'PY'
import anyio
from edgar_mcp_server.server import app

async def main():
    tools = await app.list_tools()
    print([tool.name for tool in tools])

anyio.run(main)
PY
```
