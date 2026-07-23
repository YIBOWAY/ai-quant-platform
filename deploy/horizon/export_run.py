#!/usr/bin/env python3
"""Export Horizon upstream artifacts into the platform inbox contract.

Host-testable pure logic. Discovers the latest upstream run-store stages and/or
daily summaries under ``--horizon-data``, maps ContentItem-like dicts into the
Task-3 inbox schema, and writes:

    <inbox>/runs/<run_id>/{meta.json,items.json,summary-*.md,READY}

``READY`` is written last and only on full success. On any exception the run
directory may be partial but never contains ``READY``; process exits non-zero.

Empty-item policy: still emit ``items.json=[]``, ``meta.item_count=0``, and
``READY`` so ops can observe the attempt. Downstream ingest skips empty runs as
not fresh.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Prefer enriched > filtered > scored stage files (MCP run store).
_STAGE_FILES: tuple[str, ...] = (
    "enriched_items.json",
    "filtered_items.json",
    "scored_items.json",
)

_SUMMARY_TRUNCATE = 2000


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_run_id(now: datetime | None = None) -> str:
    """Return ``YYYYMMDDTHHMMSSZ-<short>`` UTC run id."""

    stamp = (now or utc_now()).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "+00:00")
    text = str(value).strip()
    return text or None


def _truncate(text: str, limit: int = _SUMMARY_TRUNCATE) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def map_content_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a ContentItem-like dict to an inbox item. Returns None if unusable."""

    title = str(raw.get("title") or "").strip()
    url_val = raw.get("url")
    url = str(url_val).strip() if url_val is not None else ""
    if not title or not url:
        return None

    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        item_id = secrets.token_hex(8)

    source_type = raw.get("source_type")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    source = (
        str(source_type).strip()
        if source_type is not None and str(source_type).strip()
        else str(metadata.get("source") or metadata.get("feed_name") or "unknown")
    )

    summary_raw = raw.get("ai_summary")
    if summary_raw is None or not str(summary_raw).strip():
        content = raw.get("content")
        summary_raw = content if content is not None else None
    summary = None if summary_raw is None else _truncate(str(summary_raw).strip())

    tags = raw.get("ai_tags") if isinstance(raw.get("ai_tags"), list) else []
    category: str | None = None
    if tags:
        first = tags[0]
        if first is not None and str(first).strip():
            category = str(first).strip()
    if category is None:
        meta_cat = metadata.get("category")
        if meta_cat is not None and str(meta_cat).strip():
            category = str(meta_cat).strip()
    if category is None:
        category = "industry"

    score_val = raw.get("ai_score")
    score: float | None
    if score_val is None:
        score = None
    else:
        try:
            score = float(score_val)
        except (TypeError, ValueError):
            score = None

    title_en = raw.get("title_en")
    if title_en is None:
        # Horizon stores localized titles under metadata; fall back to title.
        meta_en = metadata.get("title_en")
        title_en = meta_en if meta_en is not None else title

    return {
        "id": item_id,
        "title": title,
        "title_en": str(title_en) if title_en is not None else title,
        "url": url,
        "source": source,
        "published_at": _iso_or_none(raw.get("published_at")),
        "summary": summary,
        "category": category,
        "score": score,
    }


def discover_item_lists(horizon_data: Path) -> list[tuple[Path, list[dict[str, Any]]]]:
    """Return ``(source_path, items)`` candidates, newest-first where possible."""

    found: list[tuple[float, Path, list[dict[str, Any]]]] = []

    # MCP-style run store: data/mcp-runs/<run_id>/{enriched,filtered,scored}_items.json
    mcp_root = horizon_data / "mcp-runs"
    if mcp_root.is_dir():
        for run_dir in mcp_root.iterdir():
            if not run_dir.is_dir():
                continue
            for stage_name in _STAGE_FILES:
                stage_path = run_dir / stage_name
                if not stage_path.is_file():
                    continue
                try:
                    payload = _read_json(stage_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, list):
                    continue
                items = [x for x in payload if isinstance(x, dict)]
                mtime = stage_path.stat().st_mtime
                found.append((mtime, stage_path, items))
                break  # prefer first matching stage in priority order

    # Loose stage files directly under data/ (best-effort fallback)
    for stage_name in _STAGE_FILES:
        stage_path = horizon_data / stage_name
        if stage_path.is_file():
            try:
                payload = _read_json(stage_path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, list):
                items = [x for x in payload if isinstance(x, dict)]
                found.append((stage_path.stat().st_mtime, stage_path, items))
                break

    found.sort(key=lambda row: row[0], reverse=True)
    return [(path, items) for _, path, items in found]


def discover_summaries(horizon_data: Path) -> dict[str, Path]:
    """Find zh/en summary markdown paths. Prefer mcp-runs, then data/summaries."""

    result: dict[str, Path] = {}

    mcp_root = horizon_data / "mcp-runs"
    if mcp_root.is_dir():
        run_dirs = sorted(
            (p for p in mcp_root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for run_dir in run_dirs:
            for lang in ("zh", "en"):
                if lang in result:
                    continue
                candidate = run_dir / f"summary-{lang}.md"
                if candidate.is_file():
                    result[lang] = candidate
            if "zh" in result and "en" in result:
                return result

    summaries_dir = horizon_data / "summaries"
    if summaries_dir.is_dir():
        # Filenames: horizon-{date}-{language}.md — pick latest per language.
        by_lang: dict[str, list[Path]] = {"zh": [], "en": []}
        for path in summaries_dir.iterdir():
            if not path.is_file() or path.suffix != ".md":
                continue
            name = path.name
            if name.endswith("-zh.md"):
                by_lang["zh"].append(path)
            elif name.endswith("-en.md"):
                by_lang["en"].append(path)
        for lang, paths in by_lang.items():
            if lang in result or not paths:
                continue
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            result[lang] = paths[0]

    return result


def build_inbox_payload(
    horizon_data: Path,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the inbox run payload from upstream artifacts (no filesystem writes)."""

    when = now or utc_now()
    rid = run_id or make_run_id(when)
    generated_at = when.isoformat().replace("+00:00", "+00:00")
    # Normalize to +00:00 style even if platform uses Z
    if generated_at.endswith("+00:00"):
        pass
    elif generated_at.endswith("Z"):
        generated_at = generated_at[:-1] + "+00:00"

    candidates = discover_item_lists(horizon_data)
    source_path: str | None = None
    raw_items: list[dict[str, Any]] = []
    if candidates:
        source_file, raw_items = candidates[0]
        source_path = str(source_file)

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        mapped = map_content_item(raw)
        if mapped is not None:
            items.append(mapped)

    summaries = discover_summaries(horizon_data)
    summary_texts: dict[str, str] = {}
    for lang, path in summaries.items():
        try:
            summary_texts[lang] = path.read_text(encoding="utf-8")
        except OSError:
            continue

    meta = {
        "run_id": rid,
        "generated_at": generated_at,
        "item_count": len(items),
        "status": "ok",
        "source": "horizon",
        "upstream_items_path": source_path,
        "daily_date": when.date().isoformat(),
    }

    return {
        "run_id": rid,
        "meta": meta,
        "items": items,
        "summaries": summary_texts,
    }


def write_inbox_run(inbox: Path, payload: dict[str, Any]) -> Path:
    """Atomically-ish write run artifacts; READY last. Raises on failure."""

    run_id = str(payload["run_id"])
    run_dir = inbox / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta_path = run_dir / "meta.json"
    items_path = run_dir / "items.json"
    ready_path = run_dir / "READY"

    # Never leave a stale READY from a previous partial attempt.
    if ready_path.exists():
        ready_path.unlink()

    meta_path.write_text(
        json.dumps(payload["meta"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    items_path.write_text(
        json.dumps(payload["items"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summaries = payload.get("summaries") or {}
    for lang, text in summaries.items():
        if lang not in ("zh", "en"):
            continue
        (run_dir / f"summary-{lang}.md").write_text(str(text), encoding="utf-8")

    # READY last — only after all other files succeeded.
    ready_path.write_text("", encoding="utf-8")
    return run_dir


def export_run(
    horizon_data: str | Path,
    inbox: str | Path,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> Path:
    """Discover upstream artifacts and write one inbox run. Returns run dir."""

    horizon_path = Path(horizon_data)
    inbox_path = Path(inbox)
    if not horizon_path.is_dir():
        raise FileNotFoundError(f"horizon data dir not found: {horizon_path}")

    payload = build_inbox_payload(horizon_path, now=now, run_id=run_id)
    return write_inbox_run(inbox_path, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export Horizon upstream data into the platform inbox contract."
    )
    parser.add_argument(
        "--horizon-data",
        required=True,
        help="Upstream Horizon data directory (contains summaries/ and/or mcp-runs/).",
    )
    parser.add_argument(
        "--inbox",
        required=True,
        help="Platform inbox root (will write runs/<run_id>/).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional fixed run_id (default: UTC timestamp + short suffix).",
    )
    args = parser.parse_args(argv)

    try:
        run_dir = export_run(args.horizon_data, args.inbox, run_id=args.run_id)
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        print(f"export_run failed: {exc}", file=sys.stderr)
        return 1

    print(f"exported {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
