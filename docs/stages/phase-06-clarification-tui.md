# 阶段 6：用户澄清 Tool 与 TUI 完整交互

## 1. 阶段目标

实现请求用户澄清 tool，并在 TUI 中呈现交互。当 Agent 缺少公司、年份、表单或计算口径时，它不应该猜，而应该暂停 loop，向用户问一个短问题，收到答案后继续执行。

## 2. 做了什么

新增文件：

- `fin_report_agent/tools/clarify_tool.py`
- `fin_report_agent/tui/app.py`
- `fin_report_agent/tui/render.py`

更新：

- `fin_report_agent/agent/tool_registry.py` 增加 `UserClarificationRequest` 和 `ToolNeedsUserInput`。
- `fin_report_agent/agent/loop.py` 增加 `PendingClarification`、暂停和恢复逻辑。
- `tests/test_agent_loop.py` 增加澄清暂停和恢复测试。

新增 CLI：

- `python -m fin_report_agent.main`

## 3. 怎么实现

澄清 tool 的流程：

1. 模型调用 `ask_user_clarification`。
2. tool handler 不直接读取 stdin，而是抛出 `ToolNeedsUserInput`。
3. Agent Loop 捕获异常，返回 `AgentTurnResult(status="needs_clarification")`。
4. TUI 显示问题和可选选项。
5. 用户输入答案。
6. TUI 调用 `resume_after_clarification()`。
7. Loop 把用户答案写成 tool result message，再继续请求模型。

TUI 第一版行为：

- 使用 `prompt_toolkit.PromptSession.prompt_async()` 获取用户问题和澄清答案。
- `on_text_delta` 直接流式打印模型文本。
- `on_tool_start` 和 `on_tool_result` 打印简短工具状态。
- 用户输入 `exit` 或 `quit` 退出。

## 4. 关键决策

- 澄清作为 tool，而不是普通 assistant 文本。
- 澄清 tool 本身不读用户输入，只发出结构化暂停信号。
- TUI 使用 `prompt_toolkit` 管理输入历史，输出仍保持极简流式打印。
- 所有 tools 在 `build_registry(config)` 中集中注册。

## 5. 决策原因

- 澄清作为 tool 可以纳入统一 tool calling 协议，模型能在拿到用户答案后自然继续。
- tool 不读 stdin，保证同一个 Agent Loop 可被 TUI、测试和未来 eval runner 复用。
- 第一版 TUI 的核心是验证多轮、流式、工具状态和澄清恢复，因此只使用 `prompt_toolkit` 的输入能力，不做复杂布局。
- 集中注册 tools 让阶段 1-6 的能力边界清晰可查。

## 6. 验证方式

运行：

```bash
uv run pytest tests/test_agent_loop.py
```

覆盖：

- `ask_user_clarification` 能让 Loop 暂停。
- 用户答案写回 tool result 后，Loop 能继续完成回答。

已验证 CLI 和 registry：

```bash
uv run python - <<'PY'
from fin_report_agent.config import load_config
from fin_report_agent.tui.app import build_registry
config = load_config(require_llm=False)
registry = build_registry(config)
print([schema["function"]["name"] for schema in registry.schemas()])
PY
```

输出：

```text
['resolve_company', 'download_filing_markdown', 'index_filing_markdown', 'search_filings', 'calculate_decimal', 'ask_user_clarification']
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

- 后续可以把 TUI 升级为更完整的 `prompt_toolkit` 布局，但当前实现已经满足多轮、流式、tool 状态和澄清恢复。
- 阶段 7 eval runner 可以模拟澄清答案，不需要改 Agent Loop。
