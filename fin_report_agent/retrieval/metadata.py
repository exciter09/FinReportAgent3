from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class FilingMetadata:
    """一份 10-K/10-Q markdown 的标准化元数据。"""

    company_name: str
    ticker: str
    cik: str
    requested_year: int | None
    form: str
    filed_date: str
    report_period: str
    accession_number: str
    source_path: str

    def to_dict(self) -> dict[str, object]:
        """转成 LanceDB 可保存的普通 dict。"""

        return asdict(self)


FIELD_MAP = {
    "Resolved company": "company_name",
    "Ticker": "ticker",
    "CIK": "cik",
    "Requested year": "requested_year",
    "Form": "form",
    "Filed date": "filed_date",
    "Report period": "report_period",
    "Accession number": "accession_number",
}


def _clean_cell(value: str) -> str:
    """清洗 markdown 表格单元格，保留真正的字段内容。"""

    return value.strip().replace("\\|", "|")


def parse_metadata_table(markdown: str, source_path: str) -> FilingMetadata:
    """解析 MCP markdown 顶部表格，并标准化为 FilingMetadata。"""

    values: dict[str, str] = {}
    for line in markdown.splitlines():
        if line.strip() == "---" and values:
            break
        if not line.startswith("|") or "---" in line:
            continue
        cells = [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "Field":
            continue
        key, value = cells[0], cells[1]
        field_name = FIELD_MAP.get(key)
        if field_name:
            values[field_name] = value

    year_text = values.get("requested_year") or ""
    year = int(year_text) if re.fullmatch(r"\d{4}", year_text) else None

    return FilingMetadata(
        company_name=values.get("company_name", ""),
        ticker=values.get("ticker", "").upper(),
        cik=values.get("cik", ""),
        requested_year=year,
        form=values.get("form", "").upper(),
        filed_date=values.get("filed_date", ""),
        report_period=values.get("report_period", ""),
        accession_number=values.get("accession_number", ""),
        source_path=source_path,
    )


def parse_metadata_file(path: Path) -> tuple[FilingMetadata, str]:
    """读取 markdown 文件，同时返回标准 metadata 和原始全文。"""

    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_metadata_table(text, str(path.resolve())), text
