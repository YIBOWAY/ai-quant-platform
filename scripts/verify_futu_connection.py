from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

DEFAULT_TICKERS = ["US.AAPL", "US.NVDA", "US.MSFT", "US.SPY"]


@dataclass
class VerificationFailure(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify read-only Futu OpenD quote connectivity for US stock and options data."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="OpenD host")
    parser.add_argument("--port", type=int, default=11111, help="OpenD port")
    parser.add_argument("--start", default="2024-01-02", help="History query start date")
    parser.add_argument("--end", default="2024-01-12", help="History query end date")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="US symbols in Futu format, for example US.AAPL",
    )
    parser.add_argument(
        "--option-underlying",
        default="US.AAPL",
        help="Underlying used for options checks",
    )
    return parser.parse_args()


def _assert_ret_ok(ret: int, payload: Any, context: str) -> None:
    if ret != 0:
        raise VerificationFailure(f"{context} failed: {payload}")


def _sanitize_row(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if hasattr(value, "item"):
            value = value.item()
        sanitized[key] = value
    return sanitized


def main() -> int:
    args = _parse_args()

    try:
        from futu import (
            KLType,
            OpenQuoteContext,
            OptionType,
            Session,
        )
    except Exception as exc:  # pragma: no cover - manual environment verification
        print(f"FAIL sdk_import: {exc}")
        return 1

    print("verify_futu_connection")
    print(f"host={args.host} port={args.port}")
    print(f"tickers={','.join(args.tickers)}")

    quote_ctx = OpenQuoteContext(host=args.host, port=args.port)
    try:
        ret, state = quote_ctx.get_global_state()
        _assert_ret_ok(ret, state, "get_global_state")
        print(
            "global_state="
            f"qot_logined={state.get('qot_logined')} "
            f"qot_connect_status={state.get('qot_connect_status')}"
        )

        print("history_kline_checks")
        for ticker in args.tickers:
            ret, data, _page_req_key = quote_ctx.request_history_kline(
                ticker,
                start=args.start,
                end=args.end,
                ktype=KLType.K_DAY,
                extended_time=False,
                session=Session.ALL,
            )
            _assert_ret_ok(ret, data, f"request_history_kline({ticker})")
            if data.empty:
                raise VerificationFailure(f"request_history_kline({ticker}) returned no data")
            first_row = _sanitize_row(
                data.iloc[0].to_dict(),
                ["code", "time_key", "open", "high", "low", "close", "volume"],
            )
            print(f"  {ticker}: rows={len(data)} first={first_row}")

        print("options_checks")
        ret, expiries = quote_ctx.get_option_expiration_date(args.option_underlying)
        _assert_ret_ok(ret, expiries, "get_option_expiration_date")
        if expiries.empty:
            raise VerificationFailure(
                f"get_option_expiration_date({args.option_underlying}) returned no rows"
            )
        non_expired = expiries.loc[expiries["option_expiry_date_distance"] >= 0]
        selected = non_expired.iloc[0] if not non_expired.empty else expiries.iloc[-1]
        expiry = str(selected["strike_time"])
        print(
            "  expiries="
            f"rows={len(expiries)} selected_expiry={expiry} "
            f"distance={selected['option_expiry_date_distance']}"
        )

        ret, chain = quote_ctx.get_option_chain(
            args.option_underlying,
            start=expiry,
            end=expiry,
            option_type=OptionType.ALL,
        )
        _assert_ret_ok(ret, chain, "get_option_chain")
        if chain.empty:
            raise VerificationFailure(
                f"get_option_chain({args.option_underlying}, {expiry}) returned no rows"
            )
        chain_first = _sanitize_row(
            chain.iloc[0].to_dict(),
            [
                "code",
                "name",
                "option_type",
                "strike_price",
                "strike_time",
                "stock_owner",
            ],
        )
        print(f"  chain_rows={len(chain)} first={chain_first}")

        option_code = str(chain.iloc[0]["code"])
        ret, snapshot = quote_ctx.get_market_snapshot([option_code])
        _assert_ret_ok(ret, snapshot, f"get_market_snapshot({option_code})")
        if snapshot.empty:
            raise VerificationFailure(
                f"get_market_snapshot({option_code}) returned no rows"
            )
        snapshot_first = _sanitize_row(
            snapshot.iloc[0].to_dict(),
            [
                "code",
                "update_time",
                "last_price",
                "bid_price",
                "ask_price",
                "volume",
                "option_open_interest",
                "option_implied_volatility",
                "option_delta",
                "option_gamma",
                "option_theta",
                "option_vega",
            ],
        )
        print(f"  option_snapshot={snapshot_first}")
        print("PASS read_only_quote_connectivity")
        return 0
    except VerificationFailure as exc:
        print(f"FAIL {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - manual environment verification
        print(f"FAIL unexpected_error: {exc}")
        return 1
    finally:
        quote_ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
