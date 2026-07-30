from __future__ import annotations

from pathlib import Path

from fin_report_agent.retrieval.chunker import chunk_markdown
from fin_report_agent.retrieval.contextual import attach_context
from fin_report_agent.retrieval.metadata import parse_metadata_table


SAMPLE_MARKDOWN = """# Apple Inc. 10-K Markdown

| Field | Value |
| --- | --- |
| Resolved company | Apple Inc. |
| Ticker | AAPL |
| CIK | 320193 |
| Requested year | 2023 |
| Form | 10-K |
| Filed date | 2023-11-03 |
| Report period | 2023-09-30 |
| Accession number | 0000320193-23-000106 |

---

## Item 7. Management's Discussion and Analysis

Net sales were $383.3 billion in 2023.

| Segment | Net sales |
| --- | --- |
| Services | $85.2 billion |

<!-- page 12 -->

## Item 8. Financial Statements

Consolidated statements are included here.
"""


def test_metadata_parser_reads_mcp_header() -> None:
    metadata = parse_metadata_table(SAMPLE_MARKDOWN, "/tmp/aapl.md")

    assert metadata.company_name == "Apple Inc."
    assert metadata.ticker == "AAPL"
    assert metadata.requested_year == 2023
    assert metadata.form == "10-K"


def test_chunker_attaches_context_and_preserves_source_fields() -> None:
    metadata = parse_metadata_table(SAMPLE_MARKDOWN, str(Path("/tmp/aapl.md")))
    chunks = attach_context(chunk_markdown(SAMPLE_MARKDOWN, metadata, target_chars=300))

    assert chunks
    assert any("Item 7" in " > ".join(chunk.section_path) for chunk in chunks)
    assert all(chunk.context_text.startswith("[Chunk context]") for chunk in chunks)
    assert any("Apple Inc." in chunk.indexed_text for chunk in chunks)
