"""US-listed security discovery from a pinned FinanceDatabase CSV snapshot.

This directory is metadata only. It never supplies prices, valuation multiples,
historical universe membership or permission to trade a security.
"""

from __future__ import annotations

import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx

CATALOG_VERSION = "5865ce3b26e6f393dc0600cad1ae02339bd7d52d"
CATALOG_BASE = f"https://raw.githubusercontent.com/JerBouma/FinanceDatabase/{CATALOG_VERSION}"
CATALOG_SOURCES = [
    (kind, exchange, f"{CATALOG_BASE}/database/{folder}/{exchange}.csv")
    for kind, folder, exchanges in (
        ("equity", "equities", ("NMS", "NYQ", "NCM", "NGM", "ASE", "PCX")),
        ("etf", "etfs", ("PCX", "NMS", "NGM", "BTS", "NYQ", "ASE")),
    )
    for exchange in exchanges
]


def catalog_path(settings) -> Path:
    return Path(settings.data.data_dir) / "security_catalog.json"


def parse_catalog_csv(text: str, *, asset_type: str, exchange: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not {"symbol", "name", "currency", "exchange", "isin"}.issubset(reader.fieldnames or []):
        raise ValueError("security_catalog_columns_missing")
    result = []
    for row in reader:
        symbol = row["symbol"].strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", symbol):
            continue
        if row.get("delisted", "").strip().lower() == "true":
            continue
        result.append(
            {
                "symbol": symbol,
                "name": row["name"].strip(),
                "asset_type": asset_type,
                "exchange": row["exchange"].strip() or exchange,
                "currency": row["currency"].strip(),
                "sector": row.get("sector", "").strip() or None,
                "industry": row.get("industry", "").strip() or None,
                "isin": row["isin"].strip() or None,
            }
        )
    return result


def refresh_catalog(settings) -> dict:
    def download(source):
        kind, exchange, url = source
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
        return parse_catalog_csv(response.text, asset_type=kind, exchange=exchange)

    with ThreadPoolExecutor(max_workers=4) as executor:
        batches = list(executor.map(download, CATALOG_SOURCES))
    records = {}
    for batch in batches:
        for item in batch:
            records[(item["symbol"], item["asset_type"], item["exchange"])] = item
    if not records:
        raise ValueError("security_catalog_empty")
    license_response = httpx.get(f"{CATALOG_BASE}/LICENSE", timeout=15)
    license_response.raise_for_status()
    document = {
        "source": "FinanceDatabase",
        "version": CATALOG_VERSION,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "scope": "US-listed equities and ETFs",
        "sources": [row[2] for row in CATALOG_SOURCES],
        "license": f"{CATALOG_BASE}/LICENSE",
        "license_notice": license_response.text,
        "items": sorted(records.values(), key=lambda row: (row["symbol"], row["exchange"])),
    }
    path = catalog_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return {
        key: value for key, value in document.items() if key not in {"items", "license_notice"}
    } | {"count": len(records)}


@lru_cache(maxsize=1)
def _read_catalog(path: str, modified_ns: int) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("version") != CATALOG_VERSION or not document.get("items"):
        raise ValueError("security_catalog_version_or_content_invalid")
    return document


def search_catalog(settings, query: str, *, limit: int = 8) -> dict:
    path = catalog_path(settings)
    document = _read_catalog(str(path), path.stat().st_mtime_ns)
    query = query.strip().casefold()
    tokens = query.split()
    matches = []
    for row in document["items"]:
        symbol, name = row["symbol"].casefold(), row["name"].casefold()
        if not tokens or not all(token in f"{symbol} {name}" for token in tokens):
            continue
        rank = (
            0
            if symbol == query
            else 1
            if name == query
            else 2
            if symbol.startswith(query)
            else 3
            if name.startswith(query)
            else 4
        )
        matches.append((rank, row))
    matches.sort(key=lambda item: (item[0], len(item[1]["symbol"]), item[1]["symbol"]))
    return {
        "items": [item[1] for item in matches[:limit]],
        "source": document["source"],
        "version": document["version"],
        "retrieved_at": document["retrieved_at"],
        "total": len(document["items"]),
        "scope": document["scope"],
    }
