from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_system.news.models import AiHotDaily, AiHotItem, utc_now_iso

_MAX_ITEMS = 500


@dataclass(frozen=True)
class HorizonInboxRun:
    run_id: str
    path: Path
    meta: dict
    items: list[AiHotItem]
    daily: AiHotDaily | None
    content_digest: str


def iter_ready_runs(inbox_dir: str | Path) -> list[HorizonInboxRun]:
    root = Path(inbox_dir) / "runs"
    if not root.is_dir():
        return []
    found: list[HorizonInboxRun] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "READY").is_file():
            found.append(load_run(child))
    return found


def load_run(run_dir: Path) -> HorizonInboxRun:
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    items_path = run_dir / "items.json"
    if not meta_path.is_file() or not items_path.is_file():
        raise ValueError(f"run requires meta.json and items.json: {run_dir}")

    meta_raw = meta_path.read_bytes()
    items_raw = items_path.read_bytes()
    meta_payload = json.loads(meta_raw.decode("utf-8"))
    raw_items = json.loads(items_raw.decode("utf-8"))
    if not isinstance(raw_items, list):
        raise ValueError("items.json must be a list")
    if len(raw_items) > _MAX_ITEMS:
        raise ValueError(f"items.json exceeds max of {_MAX_ITEMS} items")

    items = [_parse_item(obj) for obj in raw_items if isinstance(obj, dict)]
    meta = meta_payload if isinstance(meta_payload, dict) else {}
    daily = _load_daily(run_dir, meta, items)
    digest = hashlib.sha256(meta_raw + b"\n" + items_raw).hexdigest()
    run_id = str(meta.get("run_id") or run_dir.name)
    return HorizonInboxRun(
        run_id=run_id,
        path=run_dir,
        meta=meta,
        items=items,
        daily=daily,
        content_digest=digest,
    )


def _parse_item(obj: dict[str, Any]) -> AiHotItem:
    title = str(obj.get("title") or "").strip()
    url = str(obj.get("url") or "").strip()
    if not title:
        raise ValueError("item title must be non-empty")
    if not url:
        raise ValueError("item url must be non-empty")

    item_id = str(obj.get("id") or "").strip() or hashlib.sha256(url.encode()).hexdigest()[:16]
    score = obj.get("score")
    score_f: float | None
    if score is None:
        score_f = None
    else:
        try:
            score_f = float(score)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"item score is not a number: {score!r}") from exc

    selected: bool | None
    if score_f is not None:
        selected = True
    else:
        raw_selected = obj.get("selected")
        selected = None if raw_selected is None else bool(raw_selected)

    title_en = obj.get("title_en")
    published_at = obj.get("published_at")
    summary = obj.get("summary")
    category = obj.get("category")

    return AiHotItem(
        id=item_id,
        title=title,
        title_en=None if title_en is None else str(title_en),
        url=url,
        source=str(obj.get("source") or "unknown"),
        published_at=None if published_at is None else str(published_at),
        summary=None if summary is None else str(summary),
        category=None if category is None else str(category),
        score=score_f,
        selected=selected,
        raw=dict(obj),
    )


def _load_daily(
    run_dir: Path,
    meta: dict[str, Any],
    items: list[AiHotItem],
) -> AiHotDaily | None:
    daily_path = run_dir / "daily.json"
    if daily_path.is_file():
        return _daily_from_json(daily_path, meta)

    zh = run_dir / "summary-zh.md"
    en = run_dir / "summary-en.md"
    if not zh.is_file() and not en.is_file():
        return None

    generated = str(meta.get("generated_at") or utc_now_iso())
    date = str(meta.get("daily_date") or generated[:10])
    sections: list[dict[str, Any]] = []
    if zh.is_file():
        sections.append({"label": "summary-zh", "markdown": zh.read_text(encoding="utf-8")})
    if en.is_file():
        sections.append({"label": "summary-en", "markdown": en.read_text(encoding="utf-8")})
    lead_title = items[0].title if items else date
    return AiHotDaily(
        date=date,
        generated_at=generated,
        window_start=_optional_str(meta.get("window_start")),
        window_end=_optional_str(meta.get("window_end")),
        lead={"title": lead_title},
        sections=sections,
        flashes=[],
        warnings=[],
        raw={"source": "horizon_inbox", "run_id": meta.get("run_id")},
    )


def _daily_from_json(daily_path: Path, meta: dict[str, Any]) -> AiHotDaily:
    payload = json.loads(daily_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("daily.json must be an object")

    lead = payload.get("lead")
    sections = payload.get("sections", [])
    flashes = payload.get("flashes", [])
    generated = _optional_str(payload.get("generated_at") or payload.get("generatedAt")) or str(
        meta.get("generated_at") or utc_now_iso()
    )
    date = str(payload.get("date") or meta.get("daily_date") or generated[:10])
    return AiHotDaily(
        date=date,
        generated_at=generated,
        window_start=_optional_str(payload.get("window_start") or payload.get("windowStart")),
        window_end=_optional_str(payload.get("window_end") or payload.get("windowEnd")),
        lead=lead if isinstance(lead, dict) else None,
        sections=[item for item in sections if isinstance(item, dict)]
        if isinstance(sections, list)
        else [],
        flashes=[item for item in flashes if isinstance(item, dict)]
        if isinstance(flashes, list)
        else [],
        warnings=[str(w) for w in payload.get("warnings", []) if w is not None]
        if isinstance(payload.get("warnings"), list)
        else [],
        raw=dict(payload),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
