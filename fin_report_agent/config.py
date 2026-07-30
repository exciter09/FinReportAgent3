from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    """保存应用启动所需配置，避免业务代码到处读取环境变量。"""

    api_key: str
    base_url: str
    model: str
    data_dir: Path
    filings_dir: Path
    lancedb_dir: Path
    max_tool_rounds: int
    edgar_identity: str | None
    edgar_output_dir: Path
    mcp_project_dir: Path


def _read_env_file(path: Path) -> dict[str, str]:
    """读取简单的 KEY=VALUE 文件；项目只需要极简 .env 解析能力。"""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _get_value(env_file_values: dict[str, str], key: str, default: str | None = None) -> str | None:
    """按“真实环境变量优先”的规则读取配置值。"""

    return os.environ.get(key) or env_file_values.get(key) or default


def _require_value(env_file_values: dict[str, str], key: str) -> str:
    """读取必填配置；缺失时给出中文错误，方便教学和本地排查。"""

    value = _get_value(env_file_values, key)
    if not value:
        raise RuntimeError(f"缺少必要配置 {key}，请在 .env 或环境变量中设置。")
    return value


def load_config(root: Path | None = None, *, require_llm: bool = True) -> AppConfig:
    """从项目根目录加载配置，并创建本地数据目录。"""

    project_root = (root or Path.cwd()).resolve()
    env_file_values = _read_env_file(project_root / ".env")

    if require_llm:
        api_key = _require_value(env_file_values, "API_KEY")
        base_url = _require_value(env_file_values, "BASE_URL")
        model = _require_value(env_file_values, "MODEL")
    else:
        api_key = _get_value(env_file_values, "API_KEY", "") or ""
        base_url = _get_value(env_file_values, "BASE_URL", "http://localhost") or "http://localhost"
        model = _get_value(env_file_values, "MODEL", "fake-model") or "fake-model"

    data_dir = Path(_get_value(env_file_values, "FIN_AGENT_DATA_DIR", str(project_root / "data")) or "data").expanduser().resolve()
    filings_dir = Path(
        _get_value(env_file_values, "EDGAR_MCP_OUTPUT_DIR", str(data_dir / "filings")) or str(data_dir / "filings")
    ).expanduser().resolve()
    lancedb_dir = Path(
        _get_value(env_file_values, "FIN_AGENT_LANCEDB_DIR", str(data_dir / "lancedb")) or str(data_dir / "lancedb")
    ).expanduser().resolve()
    max_tool_rounds = int(_get_value(env_file_values, "FIN_AGENT_MAX_TOOL_ROUNDS", "8") or "8")

    data_dir.mkdir(parents=True, exist_ok=True)
    filings_dir.mkdir(parents=True, exist_ok=True)
    lancedb_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        data_dir=data_dir,
        filings_dir=filings_dir,
        lancedb_dir=lancedb_dir,
        max_tool_rounds=max_tool_rounds,
        edgar_identity=_get_value(env_file_values, "EDGAR_IDENTITY"),
        edgar_output_dir=filings_dir,
        mcp_project_dir=project_root / "mcp" / "edgar-mcp-server",
    )
