# 阶段开发文档

本目录用于存放每个开发阶段结束后的独立文档。`docs/DEVELOPMENT.md` 只保留总体设计和阶段索引，具体阶段的实现细节、技术决策和验证结果都写在这里。

## 命名规则

```text
phase-00-mcp-baseline.md
phase-01-agent-loop.md
phase-02-mcp-integration.md
phase-03-contextual-retrieval.md
phase-04-retrieval-tool.md
phase-05-decimal-calculator.md
phase-06-clarification-tui.md
phase-07-evaluation.md
```

## 文档模板

```markdown
# 阶段 X：阶段名称

## 1. 阶段目标

说明本阶段要解决的问题、交付的能力，以及它在整体 Agent 架构中的位置。

## 2. 做了什么

列出新增模块、文件、功能、命令和用户可见行为。

## 3. 怎么实现

解释核心数据流、函数边界、关键接口、重要伪代码和模块之间的调用关系。

## 4. 关键决策

记录本阶段做出的技术取舍。

## 5. 决策原因

说明为什么这样设计，尤其要覆盖极简性、教学性、可维护性和可验证性。

## 6. 验证方式

记录运行过的命令、测试结果、手动验证步骤和已知限制。

## 7. 后续事项

列出遗留问题、下一阶段依赖和可以改进的地方。
```

