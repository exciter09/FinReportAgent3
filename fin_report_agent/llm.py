from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx


@dataclass
class OpenAICompatibleLLM:
    """OpenAI compatible Chat Completions 的极简异步客户端。"""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 120.0

    @property
    def chat_url(self) -> str:
        """拼出 chat completions 地址，兼容 base_url 是否带 /v1。"""

        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        """构造鉴权请求头；密钥只进入请求，不进入日志或返回值。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, stream: bool) -> dict[str, Any]:
        """构造最小请求体，让 Agent Loop 保持对模型行为的直接控制。"""

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """非流式调用，主要给评测或调试使用。"""

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.chat_url,
                headers=self._headers(),
                json=self._payload(messages, tools, stream=False),
            )
        if response.status_code >= 400:
            raise RuntimeError(f"LLM 请求失败：HTTP {response.status_code}，{response.text[:500]}")
        data = response.json()
        return data["choices"][0]["message"]

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式调用并逐条产出 delta；Agent Loop 负责把 delta 拼成完整消息。"""

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream(
                "POST",
                self.chat_url,
                headers=self._headers(),
                json=self._payload(messages, tools, stream=True),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise RuntimeError(f"LLM 流式请求失败：HTTP {response.status_code}，{body[:500]!r}")

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    raw_data = line.removeprefix("data:").strip()
                    if raw_data == "[DONE]":
                        break
                    try:
                        event = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if choices:
                        yield choices[0].get("delta") or {}
