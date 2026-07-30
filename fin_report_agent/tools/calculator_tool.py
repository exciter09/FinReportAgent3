from __future__ import annotations

import ast
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Any

from fin_report_agent.agent.tool_registry import Tool

getcontext().prec = 28


@dataclass
class DecimalCalculatorSession:
    """会话级 Decimal REPL，保存模型在多轮计算中定义的变量。"""

    variables: dict[str, Decimal] = field(default_factory=dict)

    def run(self, code: str) -> dict[str, Any]:
        """执行一段受限表达式或赋值语句，并返回最后一个表达式结果。"""

        try:
            tree = ast.parse(code, mode="exec")
            last_result: Decimal | None = None
            for statement in tree.body:
                last_result = self._execute_statement(statement)
            return {
                "success": True,
                "result": None if last_result is None else str(last_result),
                "variables": {name: str(value) for name, value in sorted(self.variables.items())},
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "variables": {name: str(value) for name, value in self.variables.items()}}

    def _execute_statement(self, statement: ast.stmt) -> Decimal | None:
        """执行白名单语句；只允许表达式和单变量赋值。"""

        if isinstance(statement, ast.Expr):
            return self._eval_expr(statement.value)
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise ValueError("只支持单变量赋值，例如 revenue = 100。")
            value = self._eval_expr(statement.value)
            self.variables[statement.targets[0].id] = value
            return value
        raise ValueError("只支持表达式和单变量赋值，不支持 import、循环或函数定义。")

    def _eval_expr(self, node: ast.AST) -> Decimal:
        """递归解释表达式 AST，确保所有计算都使用 Decimal。"""

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str)):
                return Decimal(str(node.value))
            raise ValueError("只支持数字常量。")
        if isinstance(node, ast.Name):
            if node.id not in self.variables:
                raise ValueError(f"未知变量：{node.id}")
            return self.variables[node.id]
        if isinstance(node, ast.BinOp):
            return self._apply_binary(node.op, self._eval_expr(node.left), self._eval_expr(node.right))
        if isinstance(node, ast.UnaryOp):
            value = self._eval_expr(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.Call):
            return self._call_function(node)
        raise ValueError("表达式包含不支持的语法。")

    def _apply_binary(self, operator: ast.operator, left: Decimal, right: Decimal) -> Decimal:
        """执行基础二元运算，拒绝金融计算中不需要的复杂语法。"""

        if isinstance(operator, ast.Add):
            return left + right
        if isinstance(operator, ast.Sub):
            return left - right
        if isinstance(operator, ast.Mult):
            return left * right
        if isinstance(operator, ast.Div):
            return left / right
        if isinstance(operator, ast.Pow):
            return left ** right
        raise ValueError("只支持 +、-、*、/、** 运算符。")

    def _call_function(self, node: ast.Call) -> Decimal:
        """执行少量安全函数，避免模型借函数调用逃逸到 Python 环境。"""

        if not isinstance(node.func, ast.Name):
            raise ValueError("不支持属性调用或复杂函数调用。")
        args = [self._eval_expr(arg) for arg in node.args]
        if node.func.id == "abs" and len(args) == 1:
            return abs(args[0])
        if node.func.id == "min" and args:
            return min(args)
        if node.func.id == "max" and args:
            return max(args)
        if node.func.id == "round" and len(args) in {1, 2}:
            ndigits = int(args[1]) if len(args) == 2 else 0
            return round(args[0], ndigits)
        raise ValueError("只支持 abs、min、max、round 函数。")


def build_calculator_tool(session: DecimalCalculatorSession | None = None) -> Tool:
    """创建 Decimal 计算 tool；同一个 session 在多轮中复用变量。"""

    calculator = session or DecimalCalculatorSession()

    def calculate_decimal(code: str) -> dict[str, Any]:
        """执行模型提交的 Decimal 计算代码。"""

        return calculator.run(code)

    return Tool(
        name="calculate_decimal",
        description=(
            "在当前会话的 Decimal 金融计算环境中执行表达式。用于比例、同比、差额、占比和单位换算。"
            "必须先通过 search_filings 获取数字来源，再把数字写成表达式。只支持基础运算、变量赋值、abs/min/max/round。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "一行或多行 Decimal 表达式或变量赋值，例如 gross_margin = gross_profit / revenue",
                }
            },
            "required": ["code"],
        },
        handler=calculate_decimal,
    )
