from __future__ import annotations

from fin_report_agent.tools.calculator_tool import DecimalCalculatorSession


def test_decimal_calculator_keeps_session_variables() -> None:
    calculator = DecimalCalculatorSession()

    first = calculator.run("revenue = 383285\ncost = 214137\nmargin = (revenue - cost) / revenue")
    second = calculator.run("round(margin * 100, 2)")

    assert first["success"] is True
    assert second["result"] == "44.13"
    assert first["variables"]["margin"].startswith("0.441")


def test_decimal_calculator_rejects_imports_and_unknown_names() -> None:
    calculator = DecimalCalculatorSession()

    import_result = calculator.run("import os")
    unknown_result = calculator.run("revenue + 1")

    assert import_result["success"] is False
    assert unknown_result["success"] is False
