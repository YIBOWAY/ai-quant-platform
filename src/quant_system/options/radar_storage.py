from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quant_system.options.models import OptionsScreenerCandidate
from quant_system.options.radar import (
    OptionsRadarCandidate,
    OptionsRadarReport,
)


class RadarSnapshotStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def write(self, report: OptionsRadarReport) -> tuple[Path, Path]:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        data_path = self.root_dir / f"{report.run_date}.jsonl"
        meta_path = self.root_dir / f"{report.run_date}_meta.json"
        existing: dict[tuple[str, str, str], dict] = {}
        if data_path.exists():
            for line in data_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                existing[_candidate_key(payload)] = payload
        for candidate in report.candidates:
            payload = _candidate_to_json(report.run_date, candidate)
            existing[_candidate_key(payload)] = payload
        with data_path.open("w", encoding="utf-8") as handle:
            for payload in sorted(existing.values(), key=lambda item: -item["global_score"]):
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        meta_path.write_text(
            json.dumps(
                {
                    "run_date": report.run_date,
                    "started_at": report.started_at,
                    "finished_at": report.finished_at,
                    "universe_size": report.universe_size,
                    "scanned_tickers": report.scanned_tickers,
                    "failed_tickers": report.failed_tickers,
                    "candidate_count": len(existing),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return data_path, meta_path

    def read(self, run_date: str) -> OptionsRadarReport:
        data_path = self.root_dir / f"{run_date}.jsonl"
        meta_path = self.root_dir / f"{run_date}_meta.json"
        if not data_path.exists() or not meta_path.exists():
            raise FileNotFoundError(f"no radar snapshot for {run_date}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        candidates = []
        for line in data_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            candidates.append(_candidate_from_json(json.loads(line)))
        return OptionsRadarReport(
            run_date=run_date,
            started_at=str(meta.get("started_at", "")),
            finished_at=str(meta.get("finished_at", "")),
            universe_size=int(meta.get("universe_size", 0)),
            scanned_tickers=int(meta.get("scanned_tickers", 0)),
            failed_tickers=[tuple(item) for item in meta.get("failed_tickers", [])],
            candidates=candidates,
        )

    def list_dates(self) -> list[str]:
        dates = []
        for path in self.root_dir.glob("*_meta.json"):
            dates.append(path.name.removesuffix("_meta.json"))
        return sorted(dates, reverse=True)

    def latest_date(self) -> str | None:
        dates = self.list_dates()
        return dates[0] if dates else None


def _candidate_to_json(run_date: str, candidate: OptionsRadarCandidate) -> dict:
    payload = asdict(candidate)
    payload["run_date"] = run_date
    payload["candidate"] = candidate.candidate.model_dump(mode="json")
    return payload


def _candidate_from_json(payload: dict) -> OptionsRadarCandidate:
    return OptionsRadarCandidate(
        ticker=str(payload["ticker"]),
        sector=payload.get("sector"),
        strategy=payload["strategy"],
        candidate=OptionsScreenerCandidate.model_validate(payload["candidate"]),
        iv_rank=payload.get("iv_rank"),
        earnings_in_window=bool(payload.get("earnings_in_window", False)),
        global_score=float(payload.get("global_score", 0.0)),
        market_regime=payload.get("market_regime"),
        market_regime_penalty=float(payload.get("market_regime_penalty", 0.0)),
    )


def _candidate_key(payload: dict) -> tuple[str, str, str]:
    contract_symbol = str(payload["candidate"]["symbol"])
    return str(payload["ticker"]), contract_symbol, str(payload["strategy"])
