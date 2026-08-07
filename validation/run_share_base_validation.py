"""Validate Yahoo share-base values against local research benchmarks."""

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
from validation.share_base_validation import (
    build_threshold_flags,
    calculate_absolute_difference,
    calculate_percentage_difference,
)


def main() -> None:
    benchmark_path = ROOT / "validation" / "benchmarks" / "share_base_reference.csv"
    override_path = ROOT / "metadata" / "share_base.csv"
    provider = CompositeShareBaseProvider(
        [CSVShareBaseProvider(override_path), YahooShareBaseProvider()]
    )

    rows = []
    with benchmark_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = row["ticker"].zfill(4)
            yahoo_ticker = f"{ticker}.HK"
            ticker_obj = yf.Ticker(yahoo_ticker)
            result = provider.get_share_base(ticker_obj)
            expected = int(float(row["expected_share_base"]))
            pct_difference = calculate_percentage_difference(result.share_base, expected)
            rows.append(
                {
                    "ticker": ticker,
                    "expected_share_base": expected,
                    "resolved_share_base": result.share_base,
                    "method": result.method,
                    "source": result.source,
                    "confidence": result.confidence,
                    "warning": result.warning,
                    "absolute_difference": calculate_absolute_difference(result.share_base, expected),
                    "percentage_difference": pct_difference,
                    **build_threshold_flags(pct_difference, (1, 2, 5)),
                }
            )

    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
