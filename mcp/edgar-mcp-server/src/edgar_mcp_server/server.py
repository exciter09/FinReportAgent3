from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer

logger = logging.getLogger("edgar-report-mcp")

SERVER_INSTRUCTIONS = """
This MCP server downloads cleaned SEC 10-K/10-Q markdown reports by company name and year.
It accepts English names, tickers, CIKs, and common Chinese company names. Set EDGAR_IDENTITY
to comply with SEC access rules.
"""

app = MCPServer(
    name="edgar-report-mcp",
    title="EDGAR 10-K/10-Q Markdown",
    version="0.1.0",
    instructions=SERVER_INSTRUCTIONS.strip(),
)

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
SPACE_RE = re.compile(r"[ \t]+")
NON_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
PAGE_BREAK_RE = re.compile(r"^\{(\d+)\}-+$")


@contextmanager
def _third_party_stdout_to_stderr():
    """Keep MCP stdio stdout clean even if edgartools emits progress/log text."""
    with redirect_stdout(sys.stderr):
        yield


@dataclass
class ResolvedCompany:
    requested: str
    resolved_identifier: str
    source: str
    company: Any
    candidates: list[dict[str, Any]]

    @property
    def ticker(self) -> str | None:
        tickers = getattr(self.company, "tickers", None)
        if tickers:
            return str(tickers[0])
        ticker = getattr(self.company, "ticker", None)
        return str(ticker) if ticker else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "resolved_identifier": self.resolved_identifier,
            "source": self.source,
            "name": getattr(self.company, "name", None),
            "cik": str(getattr(self.company, "cik", "")),
            "ticker": self.ticker,
            "candidates": self.candidates,
        }


def _normalize_alias(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[\s\u3000()（）,，.。·-]+", "", value)
    return value


def _contains_cjk(value: str) -> bool:
    return bool(CJK_RE.search(value))


def _load_aliases() -> dict[str, str]:
    with resources.files("edgar_mcp_server").joinpath("company_aliases_zh.json").open(
        "r", encoding="utf-8"
    ) as fh:
        aliases = json.load(fh)

    extra = os.environ.get("EDGAR_COMPANY_ALIASES_JSON")
    if extra:
        try:
            aliases.update(json.loads(extra))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse EDGAR_COMPANY_ALIASES_JSON: %s", exc)

    return {_normalize_alias(k): str(v).strip() for k, v in aliases.items() if str(v).strip()}


def _setup_identity(sec_identity: str | None = None, *, required: bool = False) -> str | None:
    identity = (
        sec_identity
        or os.environ.get("EDGAR_IDENTITY")
        or os.environ.get("SEC_IDENTITY")
        or os.environ.get("SEC_USER_AGENT")
    )
    if not identity:
        if required:
            raise RuntimeError(
                "SEC identity is required. Set EDGAR_IDENTITY to "
                "'Your Name your.email@example.com' in the MCP server environment."
            )
        return None

    from edgar import set_identity

    set_identity(identity)
    return identity


def _company_from_identifier(identifier: str):
    from edgar import Company

    attempts: list[Any] = [identifier.strip()]
    if identifier.strip().isdigit():
        attempts.append(int(identifier.strip().lstrip("0") or "0"))
    attempts.append(identifier.strip().upper())

    seen: set[str] = set()
    for attempt in attempts:
        key = str(attempt)
        if key in seen:
            continue
        seen.add(key)
        try:
            return Company(attempt)
        except Exception:
            continue
    return None


def _search_company_candidates(query: str, limit: int = 10) -> list[dict[str, Any]]:
    from edgar import find_company

    matches = find_company(query, top_n=max(1, min(limit, 25)))
    if matches is None or len(matches) == 0:
        return []

    candidates: list[dict[str, Any]] = []
    for _, row in matches.results.iterrows():
        ticker = getattr(row, "ticker", None)
        score = getattr(row, "score", None)
        candidates.append(
            {
                "cik": str(getattr(row, "cik", "")),
                "ticker": None if ticker is None or str(ticker) == "nan" else str(ticker),
                "name": str(getattr(row, "company", "")),
                "score": None if score is None else float(score),
            }
        )
    return candidates


def _resolve_company(company_name: str, *, limit: int = 10, sec_identity: str | None = None) -> ResolvedCompany:
    if not company_name or not company_name.strip():
        raise ValueError("company_name cannot be empty.")

    _setup_identity(sec_identity, required=False)

    requested = company_name.strip()
    aliases = _load_aliases()
    alias_identifier = aliases.get(_normalize_alias(requested))
    if alias_identifier:
        company = _company_from_identifier(alias_identifier)
        if company is not None:
            return ResolvedCompany(
                requested=requested,
                resolved_identifier=alias_identifier,
                source="chinese_alias",
                company=company,
                candidates=[
                    {
                        "cik": str(getattr(company, "cik", "")),
                        "ticker": getattr(company, "ticker", None) or alias_identifier,
                        "name": getattr(company, "name", None),
                        "score": 100.0,
                    }
                ],
            )

    company = _company_from_identifier(requested)
    if company is not None:
        return ResolvedCompany(
            requested=requested,
            resolved_identifier=requested,
            source="direct",
            company=company,
            candidates=[
                {
                    "cik": str(getattr(company, "cik", "")),
                    "ticker": getattr(company, "ticker", None),
                    "name": getattr(company, "name", None),
                    "score": 100.0,
                }
            ],
        )

    candidates = [] if _contains_cjk(requested) else _search_company_candidates(requested, limit=limit)
    if candidates:
        best = candidates[0]
        identifier = best.get("ticker") or best.get("cik") or best.get("name")
        company = _company_from_identifier(str(identifier))
        if company is not None:
            return ResolvedCompany(
                requested=requested,
                resolved_identifier=str(identifier),
                source="company_search",
                company=company,
                candidates=candidates,
            )

    hint = " Add EDGAR_COMPANY_ALIASES_JSON for custom Chinese aliases." if _contains_cjk(requested) else ""
    raise ValueError(
        f"Could not resolve company '{requested}' to an SEC company. "
        f"Try a ticker, CIK, exact English company name, or configured Chinese alias.{hint}"
    )


def _select_forms(form_type: Literal["10-K", "10-Q", "both"]) -> list[str]:
    normalized = form_type.upper()
    if normalized == "BOTH":
        return ["10-K", "10-Q"]
    if normalized in {"10-K", "10-Q"}:
        return [normalized]
    raise ValueError("form_type must be '10-K', '10-Q', or 'both'.")


def _output_dir(output_dir: str | None) -> Path:
    base = output_dir or os.environ.get("EDGAR_MCP_OUTPUT_DIR") or "edgar_filings"
    path = Path(base).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(*parts: Any) -> str:
    joined = "_".join(str(part) for part in parts if part not in (None, ""))
    joined = NON_FILENAME_RE.sub("_", joined)
    joined = re.sub(r"_+", "_", joined).strip("._-")
    return joined[:180] or "filing"


def _date_to_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _escape_md_table(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _clean_markdown(markdown: str) -> str:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = CONTROL_CHARS_RE.sub("", markdown)
    markdown = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"<br\s*/?>", "\n", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"</(?:div|p|center|section|article|header|footer)>", "\n", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"<[^>\n]+>", "", markdown)
    markdown = unescape(markdown)

    cleaned_lines: list[str] = []
    blank_count = 0
    in_code_fence = False

    for original_line in markdown.split("\n"):
        line = original_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            cleaned_lines.append(stripped)
            blank_count = 0
            continue

        if not in_code_fence:
            page_match = PAGE_BREAK_RE.match(stripped)
            if page_match:
                line = f"<!-- page {page_match.group(1)} -->"
                stripped = line
            elif stripped.startswith("|") and stripped.endswith("|"):
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                line = "| " + " | ".join(cells) + " |"
                stripped = line
            else:
                line = SPACE_RE.sub(" ", line).strip()
                stripped = line

        if not stripped:
            if blank_count == 0 and cleaned_lines:
                cleaned_lines.append("")
            blank_count += 1
            continue

        cleaned_lines.append(line)
        blank_count = 0

    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned + "\n" if cleaned else ""


def _metadata_header(resolution: ResolvedCompany, filing: Any, requested_year: int) -> str:
    company = resolution.company
    fields = [
        ("Requested company", resolution.requested),
        ("Resolved company", getattr(company, "name", None)),
        ("Ticker", resolution.ticker),
        ("CIK", getattr(company, "cik", None)),
        ("Requested year", requested_year),
        ("Form", getattr(filing, "form", None)),
        ("Filed date", _date_to_string(getattr(filing, "filing_date", None))),
        ("Report period", _date_to_string(getattr(filing, "period_of_report", None))),
        ("Accession number", getattr(filing, "accession_number", None) or getattr(filing, "accession_no", None)),
        ("Filing URL", getattr(filing, "filing_url", None)),
        ("SEC homepage", getattr(filing, "homepage_url", None)),
    ]

    title_company = getattr(company, "name", None) or resolution.requested
    title = f"# {title_company} {getattr(filing, 'form', 'Filing')} Markdown"
    table = ["| Field | Value |", "| --- | --- |"]
    table.extend(f"| {_escape_md_table(k)} | {_escape_md_table(v)} |" for k, v in fields if v not in (None, ""))
    return title + "\n\n" + "\n".join(table) + "\n\n---\n\n"


def _filing_filename(resolution: ResolvedCompany, filing: Any, requested_year: int) -> str:
    company = resolution.company
    accession = getattr(filing, "accession_number", None) or getattr(filing, "accession_no", None)
    stem = _safe_filename(
        resolution.ticker or getattr(company, "cik", None),
        requested_year,
        getattr(filing, "form", None),
        _date_to_string(getattr(filing, "filing_date", None)),
        accession,
    )
    return f"{stem}.md"


def _filing_metadata(filing: Any, path: Path, status: str, markdown_chars: int | None = None) -> dict[str, Any]:
    stat = path.stat() if path.exists() else None
    return {
        "status": status,
        "form": getattr(filing, "form", None),
        "filed_date": _date_to_string(getattr(filing, "filing_date", None)),
        "report_period": _date_to_string(getattr(filing, "period_of_report", None)),
        "accession_number": getattr(filing, "accession_number", None) or getattr(filing, "accession_no", None),
        "path": str(path),
        "bytes": stat.st_size if stat else None,
        "characters": markdown_chars,
        "filing_url": getattr(filing, "filing_url", None),
        "homepage_url": getattr(filing, "homepage_url", None),
    }


def _preview_file(path: Path, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n... (truncated)"


@app.tool(
    name="resolve_company_name",
    title="Resolve Company Name",
    description=(
        "Resolve an English or Chinese company name, ticker, or CIK to an SEC company. "
        "中文公司名会先走内置别名和 EDGAR_COMPANY_ALIASES_JSON。"
    ),
)
def resolve_company_name(
    company_name: str,
    limit: int = 10,
    sec_identity: str | None = None,
) -> dict[str, Any]:
    try:
        with _third_party_stdout_to_stderr():
            resolution = _resolve_company(company_name, limit=limit, sec_identity=sec_identity)
        return {"success": True, "company": resolution.to_dict()}
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "suggestions": [
                "Try a ticker like AAPL or MSFT.",
                "Try the exact English company name.",
                "For Chinese names, set EDGAR_COMPANY_ALIASES_JSON to a JSON alias map.",
            ],
        }


@app.tool(
    name="download_10k_10q_markdown",
    title="Download 10-K/10-Q Markdown",
    description=(
        "Input company_name and year, then download SEC 10-K/10-Q filings as cleaned markdown files. "
        "Supports English names, tickers, CIKs, and common Chinese company aliases."
    ),
)
def download_10k_10q_markdown(
    company_name: str,
    year: int,
    form_type: Literal["10-K", "10-Q", "both"] = "both",
    output_dir: str | None = None,
    max_filings: int | None = None,
    include_amendments: bool = False,
    overwrite: bool = False,
    include_content: bool = False,
    max_content_chars: int = 20000,
    sec_identity: str | None = None,
) -> dict[str, Any]:
    try:
        forms = _select_forms(form_type)
        destination = _output_dir(output_dir)

        with _third_party_stdout_to_stderr():
            _setup_identity(sec_identity, required=True)
            resolution = _resolve_company(company_name, sec_identity=sec_identity)
            filings = resolution.company.get_filings(
                year=year,
                form=forms,
                amendments=include_amendments,
            )

        filing_list = list(filings) if filings else []
        if max_filings is not None and max_filings > 0:
            filing_list = filing_list[:max_filings]

        if not filing_list:
            return {
                "success": False,
                "company": resolution.to_dict(),
                "requested": {
                    "year": year,
                    "forms": forms,
                    "include_amendments": include_amendments,
                },
                "error": f"No {', '.join(forms)} filings found for {resolution.company.name} in {year}.",
                "suggestions": [
                    "Check whether the year should be the filing year rather than the fiscal period year.",
                    "Foreign private issuers often file 20-F/6-K instead of 10-K/10-Q.",
                    "Set include_amendments=true if you need amended filings.",
                ],
            }

        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for filing in filing_list:
            path = destination / _filing_filename(resolution, filing, year)
            try:
                if path.exists() and not overwrite:
                    results.append(_filing_metadata(filing, path, status="exists"))
                    continue

                with _third_party_stdout_to_stderr():
                    raw_markdown = filing.markdown() or ""
                clean_body = _clean_markdown(raw_markdown)
                if not clean_body:
                    raise RuntimeError("Filing markdown is empty after conversion.")

                final_markdown = _metadata_header(resolution, filing, year) + clean_body
                path.write_text(final_markdown, encoding="utf-8")
                results.append(
                    _filing_metadata(
                        filing,
                        path,
                        status="downloaded",
                        markdown_chars=len(final_markdown),
                    )
                )
            except Exception as exc:
                errors.append(
                    {
                        "form": getattr(filing, "form", None),
                        "filed_date": _date_to_string(getattr(filing, "filing_date", None)),
                        "accession_number": getattr(filing, "accession_number", None)
                        or getattr(filing, "accession_no", None),
                        "error": str(exc),
                    }
                )

        response: dict[str, Any] = {
            "success": bool(results) and not errors,
            "company": resolution.to_dict(),
            "requested": {
                "year": year,
                "forms": forms,
                "include_amendments": include_amendments,
                "max_filings": max_filings,
            },
            "output_dir": str(destination),
            "filings": results,
            "errors": errors,
        }

        if include_content and results:
            response["content"] = [
                {
                    "path": item["path"],
                    "markdown": _preview_file(Path(item["path"]), max(1000, max_content_chars)),
                }
                for item in results
                if item.get("path")
            ]
        elif results:
            first_path = Path(results[0]["path"])
            response["preview"] = _preview_file(first_path, min(4000, max(1000, max_content_chars)))

        return response
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "suggestions": [
                "Set EDGAR_IDENTITY in the MCP server environment.",
                "Use resolve_company_name first if the company name is ambiguous.",
                "Try form_type='10-K' or form_type='10-Q' to narrow the request.",
            ],
        }


def main() -> None:
    logging.basicConfig(level=os.environ.get("EDGAR_MCP_LOG_LEVEL", "INFO"))
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
