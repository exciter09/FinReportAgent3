from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FixtureSection:
    """fixture 财报中的一个 SEC section。"""

    title: str
    body: str


@dataclass
class FixtureFiling:
    """用于可复现评测的迷你 10-K/10-Q markdown。"""

    company_name: str
    ticker: str
    cik: str
    year: int
    form: str
    filed_date: str
    report_period: str
    accession_number: str
    sections: list[FixtureSection]

    def path_name(self) -> str:
        """生成稳定文件名，便于报告引用。"""

        return f"{self.ticker}_{self.year}_{self.form}.md"

    def markdown(self) -> str:
        """生成与 EDGAR MCP 输出兼容的 markdown header 和正文。"""

        rows = [
            ("Resolved company", self.company_name),
            ("Ticker", self.ticker),
            ("CIK", self.cik),
            ("Requested year", self.year),
            ("Form", self.form),
            ("Filed date", self.filed_date),
            ("Report period", self.report_period),
            ("Accession number", self.accession_number),
        ]
        header = [
            f"# {self.company_name} {self.form} Markdown",
            "",
            "| Field | Value |",
            "| --- | --- |",
        ]
        header.extend(f"| {key} | {value} |" for key, value in rows)
        header.extend(["", "---", ""])
        body: list[str] = []
        for section in self.sections:
            body.extend([f"## {section.title}", "", section.body.strip(), ""])
        return "\n".join(header + body).strip() + "\n"


FIXTURE_FILINGS = [
    FixtureFiling(
        "Apple Inc.",
        "AAPL",
        "320193",
        2023,
        "10-K",
        "2023-11-03",
        "2023-09-30",
        "0000320193-23-000106",
        [
            FixtureSection(
                "Item 7. Management's Discussion and Analysis",
                """
Apple fiscal 2023 net sales were $383.3 billion. Products net sales were $298.1 billion.
Services net sales were $85.2 billion. Apple gross profit was $169.1 billion.
Foreign exchange and supply constraints were discussed as operating risks.
""",
            ),
            FixtureSection(
                "Item 8. Financial Statements",
                """
Apple cash, cash equivalents and marketable securities were $61.6 billion at September 30, 2023.
The company reported diluted earnings per share of $6.13.
""",
            ),
        ],
    ),
    FixtureFiling(
        "Apple Inc.",
        "AAPL",
        "320193",
        2024,
        "10-Q",
        "2024-05-03",
        "2024-03-30",
        "0000320193-24-000069",
        [
            FixtureSection(
                "Item 2. Management's Discussion and Analysis",
                """
Apple second quarter 2024 net sales were $90.8 billion. Services net sales were $23.9 billion.
Products net sales were $66.9 billion. Cash and marketable securities were $67.2 billion.
""",
            )
        ],
    ),
    FixtureFiling(
        "Microsoft Corporation",
        "MSFT",
        "789019",
        2023,
        "10-K",
        "2023-07-27",
        "2023-06-30",
        "0000950170-23-035122",
        [
            FixtureSection(
                "Item 7. Management's Discussion and Analysis",
                """
Microsoft fiscal 2023 revenue was $211.9 billion. Gross profit was $146.1 billion.
Microsoft Cloud revenue was $111.6 billion. Operating income was $88.5 billion.
""",
            ),
            FixtureSection(
                "Item 1A. Risk Factors",
                """
Microsoft described risks from competition, cybersecurity incidents, and cloud service availability.
""",
            ),
        ],
    ),
    FixtureFiling(
        "Microsoft Corporation",
        "MSFT",
        "789019",
        2024,
        "10-Q",
        "2024-04-25",
        "2024-03-31",
        "0000950170-24-048288",
        [
            FixtureSection(
                "Item 2. Management's Discussion and Analysis",
                """
Microsoft third quarter 2024 revenue was $61.9 billion. Microsoft Cloud revenue was $35.1 billion.
Gross profit was $43.4 billion and operating income was $27.6 billion.
""",
            )
        ],
    ),
    FixtureFiling(
        "NVIDIA Corporation",
        "NVDA",
        "1045810",
        2024,
        "10-K",
        "2024-02-21",
        "2024-01-28",
        "0001045810-24-000029",
        [
            FixtureSection(
                "Item 7. Management's Discussion and Analysis",
                """
NVIDIA fiscal 2024 revenue was $60.9 billion. Data Center revenue was $47.5 billion.
Gross profit was $44.3 billion. Inventory was $5.3 billion, compared with $4.6 billion in the prior year.
""",
            ),
            FixtureSection(
                "Item 1A. Risk Factors",
                """
NVIDIA discussed risks from export controls, supply constraints, and customer concentration.
""",
            ),
        ],
    ),
    FixtureFiling(
        "Tesla, Inc.",
        "TSLA",
        "1318605",
        2023,
        "10-K",
        "2024-01-29",
        "2023-12-31",
        "0001628280-24-002390",
        [
            FixtureSection(
                "Item 7. Management's Discussion and Analysis",
                """
Tesla 2023 total revenues were $96.8 billion. Automotive revenues were $82.4 billion.
Gross profit was $17.7 billion and operating income was $8.9 billion.
""",
            )
        ],
    ),
    FixtureFiling(
        "Amazon.com, Inc.",
        "AMZN",
        "1018724",
        2023,
        "10-K",
        "2024-02-02",
        "2023-12-31",
        "0001018724-24-000008",
        [
            FixtureSection(
                "Item 7. Management's Discussion and Analysis",
                """
Amazon 2023 net sales were $574.8 billion. AWS net sales were $90.8 billion.
Operating income was $36.9 billion. Capital expenditures were $52.7 billion.
""",
            ),
            FixtureSection(
                "Item 1A. Risk Factors",
                """
Amazon described risks from competition, fulfillment capacity, and cloud infrastructure demand.
""",
            ),
        ],
    ),
]


def write_fixture_filings(base_dir: Path) -> list[Path]:
    """把 fixture 财报写到 data/eval/fixtures/filings，供 ingest 流程读取。"""

    filings_dir = base_dir / "fixtures" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filing in FIXTURE_FILINGS:
        path = filings_dir / filing.path_name()
        path.write_text(filing.markdown(), encoding="utf-8")
        paths.append(path)
    return paths
