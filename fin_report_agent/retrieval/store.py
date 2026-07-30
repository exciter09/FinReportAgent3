from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SearchCandidate:
    """向量库返回的候选 chunk。"""

    record: dict[str, Any]
    score: float


class LanceDBChunkStore:
    """LanceDB 本地向量库封装，只暴露写入和过滤检索两个动作。"""

    def __init__(self, db_dir: Path, table_name: str = "filing_chunks") -> None:
        try:
            import lancedb
        except Exception as exc:
            raise RuntimeError(f"无法导入 LanceDB，请先安装依赖：{exc}") from exc

        self.db_dir = db_dir
        self.table_name = table_name
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_dir))

    def add_records(self, records: list[dict[str, Any]], *, source_path: str | None = None) -> int:
        """写入 chunk records；同一 source_path 重建时先删除旧记录。"""

        if not records:
            return 0

        if self.table_name in self.db.table_names():
            table = self.db.open_table(self.table_name)
            if source_path:
                table.delete(f"source_path = '{_escape_sql(source_path)}'")
            table.add(records)
        else:
            self.db.create_table(self.table_name, data=records)
        return len(records)

    def search(
        self,
        query_vector: list[float],
        *,
        filters: dict[str, list[Any]] | None = None,
        limit: int = 30,
    ) -> list[SearchCandidate]:
        """先应用 metadata filter，再做向量召回。"""

        if self.table_name not in self.db.table_names():
            return []

        table = self.db.open_table(self.table_name)
        query = table.search(query_vector).limit(limit)
        where = _filter_sql(filters or {})
        if where:
            query = query.where(where)
        rows = query.to_list()
        candidates: list[SearchCandidate] = []
        for row in rows:
            score = float(row.get("_distance", row.get("_score", 0.0)))
            candidates.append(SearchCandidate(record=row, score=score))
        return candidates


def _escape_sql(value: Any) -> str:
    """转义单引号，避免 metadata filter 字符串破坏 LanceDB where 语句。"""

    return str(value).replace("'", "''")


def _filter_sql(filters: dict[str, list[Any]]) -> str:
    """把简单的字段列表过滤转成 LanceDB SQL where。"""

    clauses: list[str] = []
    for key, values in filters.items():
        clean_values = [value for value in values if value not in (None, "")]
        if not clean_values:
            continue
        if all(isinstance(value, int) for value in clean_values):
            joined = ", ".join(str(value) for value in clean_values)
        else:
            joined = ", ".join(f"'{_escape_sql(value)}'" for value in clean_values)
        clauses.append(f"{key} IN ({joined})")
    return " AND ".join(clauses)
