from __future__ import annotations

import asyncio

from fin_report_agent.config import load_config
from fin_report_agent.tui.app import run_tui


def main() -> None:
    """命令行入口；保持极简，只负责加载配置并启动 TUI。"""

    asyncio.run(run_tui(load_config()))


if __name__ == "__main__":
    main()
