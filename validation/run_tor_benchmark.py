"""Compare old float-based TOR with the new share-base TOR benchmark set."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import CompositeShareBaseProvider, CSVShareBaseProvider, YahooShareBaseProvider
from validation.share_base_validation import summarize_error_metrics


def _get_float_shares(info: dict) -> int | None:
    value = info.get("floatShares")
    if value in (None, "", 0):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number)


def main() -> None:
    benchmark_path = ROOT / "validation" / "benchmarks" / "tor_reference.csv"
    provider = CompositeShareBaseProvider(
        [
            CSVShareBaseProvider(ROOT / "metadata" / "share_base.csv"),
            YahooShareBaseProvider(),
        ]
    )

    rows = []
    with benchmark_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = row["ticker"].zfill(4)
            yahoo_ticker = f"{ticker}.HK"
            aastocks_tor = float(row["aastocks_tor_pct"])
            ticker_obj = yf.Ticker(yahoo_ticker)
            info = ticker_obj.info or {}
            history = ticker_obj.history(period="5d", auto_adjust=False)
            if history.empty:
                continue

            volume = float(history["Volume"].iloc[-1])
            float_shares = _get_float_shares(info)
            share_result = provider.get_share_base(ticker_obj)
            old_tor = (volume / float_shares * 100.0) if float_shares else None
            new_tor = (volume / share_result.share_base * 100.0) if share_result.share_base else None

            rows.append(
                {
                    "ticker": ticker,
                    "volume": volume,
                    "aastocks_tor_pct": aastocks_tor,
                    "old_tor_pct": old_tor,
                    "new_tor_pct": new_tor,
                    "share_base": share_result.share_base,
                    "method": share_result.method,
                    "source": share_result.source,
                    "confidence": share_result.confidence,
                    "warning": share_result.warning,
                }
            )

    summary = {
        "old": summarize_error_metrics(
            [row["old_tor_pct"] for row in rows],
            [row["aastocks_tor_pct"] for row in rows],
        ),
        "new": summarize_error_metrics(
            [row["new_tor_pct"] for row in rows],
            [row["aastocks_tor_pct"] for row in rows],
        ),
        "closer_to_aastocks": sum(
            1
            for row in rows
            if row["old_tor_pct"] is not None
            and row["new_tor_pct"] is not None
            and abs(row["new_tor_pct"] - row["aastocks_tor_pct"])
            < abs(row["old_tor_pct"] - row["aastocks_tor_pct"])
        ),
        "worse_than_before": sum(
            1
            for row in rows
            if row["old_tor_pct"] is not None
            and row["new_tor_pct"] is not None
            and abs(row["new_tor_pct"] - row["aastocks_tor_pct"])
            > abs(row["old_tor_pct"] - row["aastocks_tor_pct"])
        ),
    }

    print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
