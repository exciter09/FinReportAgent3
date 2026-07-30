from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class JsonlCase:
    """一条 JSONL 评测样本，保留原始 payload 方便不同 runner 使用。"""

    case_id: str
    payload: dict[str, Any]


def read_jsonl(path: Path) -> list[JsonlCase]:
    """读取 JSONL 评测集；空行会被跳过，格式错误直接暴露出来。"""

    cases: list[JsonlCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        case_id = str(payload.get("id") or f"{path.stem}_{line_number:03d}")
        cases.append(JsonlCase(case_id=case_id, payload=payload))
    return cases


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """写出 JSON 报告，统一使用中文友好的 ensure_ascii=False。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
