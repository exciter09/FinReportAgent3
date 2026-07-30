from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from typing import Any

from fin_report_agent.config import AppConfig


@dataclass
class EdgarMCPClient:
    """通过 stdio MCP 协议调用已有的 EDGAR 财报下载 server。"""

    config: AppConfig

    def _command_and_args(self) -> tuple[str, list[str]]:
        """得到 MCP server 启动命令；默认用当前 Python 直接运行 MCP 模块。"""

        override = os.environ.get("EDGAR_MCP_COMMAND")
        if override:
            parts = shlex.split(override)
            return parts[0], parts[1:]
        server_src = self.config.mcp_project_dir / "src"
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(server_src)!r}); "
            "from edgar_mcp_server.server import main; "
            "main()"
        )
        return sys.executable, ["-c", code]

    def _env(self) -> dict[str, str]:
        """给 MCP subprocess 准备环境变量，尤其是 SEC identity 和输出目录。"""

        env = os.environ.copy()
        env["EDGAR_IDENTITY"] = (
            self.config.edgar_identity
            or os.environ.get("EDGAR_IDENTITY")
            or "FinReportAgent educational evaluation contact@example.com"
        )
        env["EDGAR_MCP_OUTPUT_DIR"] = str(self.config.edgar_output_dir)
        return env

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """启动 MCP server、调用一个 tool，并把结果标准化为 dict。"""

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            return {"success": False, "error": f"无法导入 mcp client，请先安装依赖：{exc}"}

        command, args = self._command_and_args()
        params = StdioServerParameters(command=command, args=args, env=self._env())

        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    return self._normalize_result(result)
        except Exception as exc:
            return {"success": False, "error": f"MCP 工具调用失败：{exc}"}

    def _normalize_result(self, result: Any) -> dict[str, Any]:
        """兼容不同 MCP SDK 版本的 tool result 表示。"""

        for attr in ("structured_content", "structuredContent"):
            value = getattr(result, attr, None)
            if isinstance(value, dict):
                return value

        content = getattr(result, "content", None) or []
        texts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                texts.append(text)

        joined = "\n".join(texts).strip()
        if not joined:
            return {"success": True, "content": ""}

        try:
            parsed = json.loads(joined)
            if isinstance(parsed, dict):
                return parsed
            return {"success": True, "content": parsed}
        except json.JSONDecodeError:
            return {"success": True, "content": joined}
