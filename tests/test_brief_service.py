from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from quant_system.brief.models import (
    BriefArchivePayload,
    BriefIssue,
    BriefIssueEnvelope,
    BriefSnapshot,
    BriefSourceWatermark,
)
from quant_system.brief.service import BriefService, BriefSnapshotMismatch


def _payload() -> BriefArchivePayload:
    return BriefArchivePayload.model_validate(
        {
            "schema_version": "brief_snapshot_v1",
            "title": "每日晨报",
            "issue_date": "2026-07-14",
            "locale": "zh",
            "generated_at": "2026-07-14T08:30:00+08:00",
            "lede": "模拟账户与市场事实的当日摘要。",
            "account": {
                "account_id": "default",
                "base_currency": "USD",
                "equity": 101234.5,
                "cash": 61234.5,
                "pnl_abs": 1234.5,
                "pnl_pct": 0.01234,
                "invested_pct": 0.4,
                "price_source": {"kind": "futu", "as_of": "2026-07-14T08:29:00+08:00"},
                "positions": [
                    {
                        "symbol": "AAPL",
                        "quantity": 10,
                        "avg_cost": 200,
                        "last_price": 210,
                        "market_value": 2100,
                        "weight": 0.0207,
                        "unrealized_pnl": 100,
                        "price_kind": "realtime",
                        "price_as_of": "2026-07-14T08:29:00+08:00",
                    }
                ],
            },
            "paper_equity": [
                {
                    "timestamp": "2026-07-14T08:29:00+08:00",
                    "equity": 101234.5,
                    "cash": 61234.5,
                    "market_value": 40000,
                    "source": "current_quote",
                }
            ],
            "markets": [
                {
                    "symbol": "SPY",
                    "last": 620.2,
                    "change_pct": 0.004,
                    "source": "futu",
                    "as_of": "2026-07-14T00:00:00Z",
                }
            ],
            "market_note": "SPY 小幅上涨。",
            "ai_news": [
                {
                    "id": "news-1",
                    "title": "A new model was released",
                    "url": "https://example.com/news-1",
                    "source": "example",
                    "published_at": "2026-07-14T01:00:00Z",
                    "summary": "A factual summary.",
                    "category": "models",
                    "score": 9.1,
                }
            ],
            "hermes_log": [
                {
                    "timestamp": "2026-07-14T02:00:00Z",
                    "status": "ok",
                    "text": "Hermes completed backtest",
                    "href": "/hermes/results/run-1",
                    "summary": "run-1",
                }
            ],
            "warnings": ["AI HOT response came from local cache."],
        }
    )


def _watermark() -> BriefSourceWatermark:
    return BriefSourceWatermark.model_validate(
        {
            "captured_at": "2026-07-14T08:30:00+08:00",
            "sources": [
                {
                    "name": "paper_account",
                    "status": "available",
                    "as_of": "2026-07-14T08:29:00+08:00",
                    "detail": "futu",
                },
                {
                    "name": "ai_news",
                    "status": "stale",
                    "as_of": "2026-07-14T08:00:00+08:00",
                    "detail": "local cache",
                },
            ],
        }
    )


class _RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_snapshot(self, **kwargs: Any) -> BriefIssueEnvelope:
        self.calls.append(kwargs)
        return BriefIssueEnvelope(
            issue=BriefIssue(
                issue_id="issue-1",
                public_id=kwargs["public_id"],
                issue_date=kwargs["issue_date"],
                locale=kwargs["locale"],
                status="published",
            ),
            snapshot=BriefSnapshot(
                snapshot_id="snapshot-1",
                version=1,
                payload=kwargs["payload"],
                source_watermark=kwargs["source_watermark"],
            ),
        )


def test_generate_issue_persists_the_exact_validated_snapshot() -> None:
    repository = _RecordingRepository()
    payload = _payload()
    watermark = _watermark()

    result = BriefService(repository).generate_issue(
        issue_date=date(2026, 7, 14),
        locale="zh",
        payload=payload,
        source_watermark=watermark,
    )

    assert result.snapshot.payload == payload.model_dump(mode="json")
    assert result.snapshot.source_watermark == watermark.model_dump(mode="json")
    assert repository.calls == [
        {
            "issue_date": date(2026, 7, 14),
            "locale": "zh",
            "public_id": result.issue.public_id,
            "payload": payload.model_dump(mode="json"),
            "source_watermark": watermark.model_dump(mode="json"),
        }
    ]


@pytest.mark.parametrize(
    ("issue_date", "locale"),
    [
        (date(2026, 7, 13), "zh"),
        (date(2026, 7, 14), "en"),
    ],
)
def test_generate_issue_rejects_request_and_payload_identity_mismatch(
    issue_date: date,
    locale: str,
) -> None:
    repository = _RecordingRepository()

    with pytest.raises(BriefSnapshotMismatch):
        BriefService(repository).generate_issue(
            issue_date=issue_date,
            locale=locale,
            payload=_payload(),
            source_watermark=_watermark(),
        )

    assert repository.calls == []
