from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from urllib.request import Request, urlopen

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
SP500_RAW_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "refs/heads/main/data/constituents.csv"
)
NASDAQ100_RAW_CSV_URL = (
    "https://raw.githubusercontent.com/Gary-Strauss/NASDAQ100_Constituents/"
    "master/data/nasdaq100_constituents.csv"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the committed options universe CSV. This is a manual one-shot "
            "utility; the trading platform never fetches universe data at runtime."
        )
    )
    parser.add_argument(
        "--output",
        default="data/options_universe/sp500_nasdaq100.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--bootstrap-wikipedia",
        action="store_true",
        help="Fetch current S&P 500 / Nasdaq 100 tables from Wikipedia once.",
    )
    parser.add_argument(
        "--bootstrap-github",
        action="store_true",
        help="Fetch maintained public CSV snapshots from GitHub once.",
    )
    args = parser.parse_args()

    if not args.bootstrap_wikipedia and not args.bootstrap_github:
        print(
            "No source selected. Pass --bootstrap-github, --bootstrap-wikipedia, "
            "or edit the CSV manually.",
            file=sys.stderr,
        )
        return 2

    rows = (
        build_universe_from_github_csv()
        if args.bootstrap_github
        else build_universe_from_wikipedia()
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "name", "sector", "exchange", "source"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {output}")
    return 0


def build_universe_from_wikipedia() -> list[dict[str, str]]:
    sp500 = _read_wikipedia_table(
        SP500_URL,
        symbol_header="Symbol",
        name_header="Security",
        sector_header="GICS Sector",
        source="sp500",
    )
    nasdaq100 = _read_wikipedia_table(
        NASDAQ100_URL,
        symbol_header="Ticker",
        name_header="Company",
        sector_header="GICS Sector",
        source="nasdaq100",
    )
    merged: dict[str, dict[str, str]] = {}
    for row in sp500 + nasdaq100:
        ticker = row["ticker"]
        if ticker in merged:
            merged[ticker]["source"] = "both"
            if merged[ticker]["sector"] == "Unknown" and row["sector"] != "Unknown":
                merged[ticker]["sector"] = row["sector"]
            continue
        merged[ticker] = row

    def priority(item: dict[str, str]) -> tuple[int, str]:
        source_rank = {"both": 0, "nasdaq100": 1, "sp500": 2}[item["source"]]
        return source_rank, item["ticker"]

    return sorted(merged.values(), key=priority)


def build_universe_from_github_csv() -> list[dict[str, str]]:
    sp500 = _read_remote_csv(
        SP500_RAW_CSV_URL,
        symbol_header="Symbol",
        name_header="Security",
        sector_header="GICS Sector",
        source="sp500",
    )
    nasdaq100 = _read_remote_csv(
        NASDAQ100_RAW_CSV_URL,
        symbol_header="Ticker",
        name_header="Company",
        sector_header="GICS_Sector",
        source="nasdaq100",
    )
    merged: dict[str, dict[str, str]] = {}
    for row in sp500 + nasdaq100:
        ticker = row["ticker"]
        if ticker in merged:
            merged[ticker]["source"] = "both"
            continue
        merged[ticker] = row

    def priority(item: dict[str, str]) -> tuple[int, str]:
        source_rank = {"both": 0, "nasdaq100": 1, "sp500": 2}[item["source"]]
        return source_rank, item["ticker"]

    return sorted(merged.values(), key=priority)


def _read_remote_csv(
    url: str,
    *,
    symbol_header: str,
    name_header: str,
    sector_header: str,
    source: str,
) -> list[dict[str, str]]:
    request = Request(url, headers={"User-Agent": "ai-quant-platform/manual-universe-refresh"})
    with urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig")
    rows: list[dict[str, str]] = []
    reader = csv.DictReader(text.splitlines())
    for raw in reader:
        ticker = str(raw.get(symbol_header, "")).strip().replace(".", "-").upper()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": str(raw.get(name_header, "")).strip(),
                "sector": str(raw.get(sector_header, "")).strip() or "Unknown",
                "exchange": "US",
                "source": source,
            }
        )
    return rows


def _read_wikipedia_table(
    url: str,
    *,
    symbol_header: str,
    name_header: str,
    sector_header: str,
    source: str,
) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for this manual refresh script") from exc

    request = Request(url, headers={"User-Agent": "ai-quant-platform/manual-universe-refresh"})
    with urlopen(request, timeout=20) as response:
        soup = BeautifulSoup(response.read(), "html.parser")

    for table in soup.find_all("table"):
        headers = [cell.get_text(" ", strip=True) for cell in table.find_all("th")]
        if symbol_header not in headers or name_header not in headers:
            continue
        header_cells = table.find_all("tr")[0].find_all("th")
        header_names = [cell.get_text(" ", strip=True) for cell in header_cells]
        symbol_index = header_names.index(symbol_header)
        name_index = header_names.index(name_header)
        sector_index = (
            header_names.index(sector_header)
            if sector_header in header_names
            else None
        )
        rows: list[dict[str, str]] = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(symbol_index, name_index):
                continue
            ticker = cells[symbol_index].get_text(" ", strip=True).replace(".", "-").upper()
            if not ticker:
                continue
            sector = (
                cells[sector_index].get_text(" ", strip=True)
                if sector_index is not None and len(cells) > sector_index
                else "Unknown"
            )
            rows.append(
                {
                    "ticker": ticker,
                    "name": cells[name_index].get_text(" ", strip=True),
                    "sector": sector or "Unknown",
                    "exchange": "US",
                    "source": source,
                }
            )
        if rows:
            return rows
    raise RuntimeError(f"unable to find expected table at {url}")


if __name__ == "__main__":
    raise SystemExit(main())
