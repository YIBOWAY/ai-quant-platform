from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from quant_system.data.schema import REQUIRED_OHLCV_COLUMNS


class DataQualityIssue(BaseModel):
    check: str
    severity: str = "error"
    message: str
    row_count: int = 0


class DataQualityReport(BaseModel):
    passed: bool
    row_count: int
    symbol_count: int
    start_ts: str | None = None
    end_ts: str | None = None
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_markdown(self) -> str:
        lines = [
            "# Data Quality Report",
            "",
            f"- passed: {str(self.passed).lower()}",
            f"- row_count: {self.row_count}",
            f"- symbol_count: {self.symbol_count}",
            f"- start_ts: {self.start_ts}",
            f"- end_ts: {self.end_ts}",
            f"- issue_count: {self.issue_count}",
            "",
            "## Issues",
        ]
        if not self.issues:
            lines.append("")
            lines.append("No issues found.")
        else:
            for issue in self.issues:
                lines.append("")
                lines.append(
                    f"- `{issue.check}` [{issue.severity}] rows={issue.row_count}: "
                    f"{issue.message}"
                )
        lines.append("")
        return "\n".join(lines)


def validate_ohlcv(frame: pd.DataFrame) -> DataQualityReport:
    issues: list[DataQualityIssue] = []

    missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        issues.append(
            DataQualityIssue(
                check="required_columns",
                message=f"missing columns: {', '.join(missing)}",
                row_count=len(frame),
            )
        )

    if frame.empty:
        issues.append(
            DataQualityIssue(
                check="non_empty",
                message="OHLCV data frame is empty",
                row_count=0,
            )
        )

    if not missing and not frame.empty:
        duplicate_mask = frame.duplicated(subset=["symbol", "timestamp"], keep=False)
        if duplicate_mask.any():
            issues.append(
                DataQualityIssue(
                    check="duplicate_symbol_timestamp",
                    message="duplicate rows for the same symbol and timestamp",
                    row_count=int(duplicate_mask.sum()),
                )
            )

        price_mask = (
            (frame["high"] < frame["low"])
            | (frame["open"] > frame["high"])
            | (frame["open"] < frame["low"])
            | (frame["close"] > frame["high"])
            | (frame["close"] < frame["low"])
        )
        if price_mask.any():
            issues.append(
                DataQualityIssue(
                    check="ohlc_price_bounds",
                    message="OHLC prices violate high/low bounds",
                    row_count=int(price_mask.sum()),
                )
            )

        negative_volume_mask = frame["volume"] < 0
        if negative_volume_mask.any():
            issues.append(
                DataQualityIssue(
                    check="non_negative_volume",
                    message="volume must be greater than or equal to zero",
                    row_count=int(negative_volume_mask.sum()),
                )
            )

        null_mask = frame.loc[:, list(REQUIRED_OHLCV_COLUMNS)].isna().any(axis=1)
        if null_mask.any():
            issues.append(
                DataQualityIssue(
                    check="missing_values",
                    message="required fields contain missing values",
                    row_count=int(null_mask.sum()),
                )
            )

    timestamps = pd.to_datetime(frame["timestamp"], utc=True) if "timestamp" in frame else None
    start_ts = timestamps.min().isoformat() if timestamps is not None and len(timestamps) else None
    end_ts = timestamps.max().isoformat() if timestamps is not None and len(timestamps) else None
    symbol_count = int(frame["symbol"].nunique()) if "symbol" in frame and not frame.empty else 0

    return DataQualityReport(
        passed=not issues,
        row_count=len(frame),
        symbol_count=symbol_count,
        start_ts=start_ts,
        end_ts=end_ts,
        issues=issues,
    )

