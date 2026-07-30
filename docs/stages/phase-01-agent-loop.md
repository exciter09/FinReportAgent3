# 阶段 1：极简 Agent Loop + LLM + Tool Registry

## 1. 阶段目标

实现一个不依赖大型 Agent 框架的最小 Agent Loop，让系统支持多轮对话、OpenAI compatible chat completions、流式输出和 tool calling。这是后续 MCP、检索、计算和澄清能力的共同底座。

## 2. 做了什么

新增文件：

- `pyproject.toml`：定义主项目、CLI、依赖和测试配置。
- `fin_report_agent/config.py`：读取 `.env` 和环境变量。
- `fin_report_agent/llm.py`：OpenAI compatible Chat Completions 客户端。
- `fin_report_agent/messages.py`：最小消息构造函数。
- `fin_report_agent/agent/tool_registry.py`：tool dataclass、schema 转换和调用分发。
- `fin_report_agent/agent/prompts.py`：详细 system prompt。
- `fin_report_agent/agent/loop.py`：核心 Agent Loop。
- `tests/test_agent_loop.py`：fake LLM 流式 tool calling 测试。

## 3. 怎么实现

Agent Loop 的核心流程：

1. 初始化时写入一条 system message。
2. 每轮用户输入追加为 user message。
3. 调用 `llm.chat_stream(messages, tools)`。
4. 一边把 `delta.content` 通过 callback 流式交给 TUI，一边收集 `delta.tool_calls`。
5. 如果 assistant message 没有 tool calls，本轮完成。
6. 如果有 tool calls，按 name 从 `ToolRegistry` 找到工具并执行。
7. 工具结果写成 `role=tool` 消息，再继续请求模型。
8. 超过 `max_tool_rounds` 时返回中文上限提示。

Tool Registry 保持极简：

- `Tool` 只包含 `name`、`description`、`parameters`、`handler`。
- `Tool.schema()` 负责转成 OpenAI tool calling schema。
- `Tool.call()` 同时支持同步和异步 handler。
- `ToolRegistry.call()` 只按名称分发，不做业务判断。

LLM 客户端保持极简：

- 使用 `httpx.AsyncClient`。
- 非流式方法 `chat()` 返回完整 assistant message。
- 流式方法 `chat_stream()` 解析 SSE 中的 `data:` 行，并逐个产出 delta。
- API 错误转成中文 RuntimeError。

## 4. 关键决策

- 不使用 LangChain、LlamaIndex 或工作流框架。
- 消息结构保持 OpenAI API 原始 dict 形态。
- Agent Loop 用 callback 把 UI 渲染和控制流解耦。
- tool call arguments 必须完整收集后再 JSON parse。
- system prompt 明确要求：财报事实先检索、缺信息先澄清、计算必须调用 Decimal tool。

## 5. 决策原因

- 教学项目需要让读者看见 Agent Loop 的真实控制流。
- 原始 dict 消息减少结构转换，便于和 API 文档对照。
- callback 让 TUI、测试和后续评测 runner 可以复用同一个 Loop。
- 增量 tool call 直接 JSON parse 容易失败，必须等 arguments 拼完整。
- system prompt 是 Agent 行为的第一道约束，尤其要防止模型凭记忆编财报数字。

## 6. 验证方式

运行：

```bash
uv run pytest tests/test_agent_loop.py
```

覆盖：

- 模型流式返回 tool call 时，Agent Loop 能执行工具并继续生成最终回答。
- `ask_user_clarification` 触发暂停后，Loop 能接收用户答案并恢复。

完整测试：

```bash
uv run pytest
```

结果：

```text
13 passed
```

## 7. 后续事项

- 阶段 7 的 eval runner 可以直接复用 `AgentLoop`，把 TUI callback 换成 trace recorder。
- 如果不同 LLM provider 的流式格式有差异，只需要扩展 `llm.py` 的 delta 解析。

