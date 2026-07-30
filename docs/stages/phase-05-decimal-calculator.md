# 阶段 5：Decimal 计算 Tool

## 1. 阶段目标

实现会话级金融计算环境，让模型在比较毛利率、同比增速、占比、差额和单位换算时使用 `Decimal`，避免 float 误差和任意 Python 执行风险。

## 2. 做了什么

新增文件：

- `fin_report_agent/tools/calculator_tool.py`
- `tests/test_calculator_tool.py`

新增 tool：

- `calculate_decimal`

## 3. 怎么实现

`DecimalCalculatorSession` 保存当前会话变量：

```python
variables: dict[str, Decimal]
```

执行流程：

1. `ast.parse(code, mode="exec")` 解析模型提交的代码。
2. 只允许两类 statement：表达式和单变量赋值。
3. 表达式解释器只允许：
   - 数字常量
   - 已定义变量
   - `+`、`-`、`*`、`/`、`**`
   - 一元正负号
   - `abs`、`min`、`max`、`round`
4. 所有数字通过 `Decimal(str(value))` 进入计算。
5. 返回最后一个表达式结果和当前变量表。

## 4. 关键决策

- 使用 AST 白名单解释器，不使用 `eval`。
- 每个 TUI 会话复用同一个 `DecimalCalculatorSession`。
- JSON 返回中所有 Decimal 都转成字符串。
- system prompt 和 tool description 都要求模型先检索数字来源，再计算。

## 5. 决策原因

- `eval` 会执行任意 Python，不适合让模型直接驱动。
- 多轮复用变量能支持“刚才那个毛利率再乘以 100”一类追问。
- JSON float 会丢精度，字符串能保留 Decimal 结果。
- 计算只保证算术正确，数字事实仍必须来自财报检索。

## 6. 验证方式

运行：

```bash
uv run pytest tests/test_calculator_tool.py
```

覆盖：

- 会话变量可复用。
- 毛利率百分比可用 Decimal 得到稳定结果。
- `import` 和未知变量会被拒绝。

完整测试：

```bash
uv run pytest
```

结果：

```text
13 passed
```

## 7. 后续事项

- 后续可增加格式化 helper，例如把 `0.4413` 输出成 `44.13%`，但第一版交给模型根据上下文表达。

