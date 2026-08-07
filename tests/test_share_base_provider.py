"""Tests for turnover share-base providers and validation helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from providers import CSVShareBaseProvider, CompositeShareBaseProvider, YahooShareBaseProvider
from validation.share_base_validation import (
    build_threshold_flags,
    calculate_absolute_difference,
    calculate_percentage_difference,
)


def _write_share_base_csv(contents: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "share_base.csv"
    path.write_text(contents, encoding="utf-8")
    return path


class ShareBaseProviderTests(unittest.TestCase):
    def test_yahoo_shares_outstanding_is_used_by_default(self) -> None:
        ticker_obj = SimpleNamespace(
            ticker="1810.HK",
            info={"sharesOutstanding": 25842130000, "floatShares": 17231368152},
        )

        result = YahooShareBaseProvider().get_share_base(ticker_obj)

        self.assertEqual(result.ticker, "1810")
        self.assertEqual(result.share_base, 25842130000)
        self.assertEqual(result.method, "shares_outstanding")
        self.assertEqual(result.source, "yfinance")

    def test_float_shares_is_never_silently_used_for_tor(self) -> None:
        ticker_obj = SimpleNamespace(
            ticker="2577.HK",
            info={"floatShares": 445272169},
        )

        result = YahooShareBaseProvider().get_share_base(ticker_obj)

        self.assertIsNone(result.share_base)
        self.assertIsNone(result.method)
        self.assertIn("sharesOutstanding", result.warning or "")

    def test_local_override_takes_priority(self) -> None:
        csv_path = _write_share_base_csv(
            "ticker,issued_shares,source,source_url,last_verified,confidence,notes\n"
            "1810,25842130000,manual,https://example.com,2026-08-07,high,outlier override\n"
        )
        provider = CompositeShareBaseProvider(
            [
                CSVShareBaseProvider(csv_path),
                YahooShareBaseProvider(),
            ]
        )
        ticker_obj = SimpleNamespace(
            ticker="1810.HK",
            info={"sharesOutstanding": 21302133634},
        )

        result = provider.get_share_base(ticker_obj)

        self.assertEqual(result.share_base, 25842130000)
        self.assertEqual(result.method, "override")
        self.assertEqual(result.source, "manual")

    def test_missing_share_base_produces_explicit_warning(self) -> None:
        provider = CompositeShareBaseProvider([YahooShareBaseProvider()])
        ticker_obj = SimpleNamespace(ticker="9678.HK", info={})

        result = provider.get_share_base(ticker_obj)

        self.assertIsNone(result.share_base)
        self.assertIsNone(result.method)
        self.assertIn("sharesOutstanding", result.warning or "")

    def test_ticker_normalization_handles_five_digit_and_suffix_input(self) -> None:
        csv_path = _write_share_base_csv(
            "ticker,issued_shares,source,source_url,last_verified,confidence,notes\n"
            "1810,25842130000,manual,https://example.com,2026-08-07,high,outlier override\n"
        )
        provider = CSVShareBaseProvider(csv_path)

        result = provider.get_share_base("01810.HK")

        self.assertEqual(result.ticker, "1810")
        self.assertEqual(result.share_base, 25842130000)

    def test_validation_helpers_flag_expected_thresholds(self) -> None:
        pct_diff = calculate_percentage_difference(102, 100)

        self.assertEqual(calculate_absolute_difference(102, 100), 2)
        self.assertEqual(pct_diff, 2.0)
        self.assertEqual(
            build_threshold_flags(pct_diff, (1, 2, 5)),
            {"above_1pct": True, "above_2pct": False, "above_5pct": False},
        )


if __name__ == "__main__":
    unittest.main()
