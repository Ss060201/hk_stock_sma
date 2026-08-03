"""Tests for the CSV float metadata provider."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from providers.csv_float_provider import CSVFloatProvider


def _write_csv(contents: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "float.csv"
    path.write_text(contents, encoding="utf-8")
    return path


class CSVFloatProviderTests(unittest.TestCase):
    def test_prefers_float_shares_when_available(self) -> None:
        csv_path = _write_csv(
            "ticker,company,outstanding,float_ratio,float_shares,last_update,source,confidence\n"
            "3317,Test Co,500000000,0.55,275000000,2026-08-03,manual,high\n"
        )
        provider = CSVFloatProvider(csv_path)

        result = provider.get_float_shares("3317.HK")

        self.assertEqual(result.ticker, "3317")
        self.assertEqual(result.share_base, 275000000)
        self.assertEqual(result.method, "float")
        self.assertIsNone(result.warning)
        self.assertEqual(result.source, "manual")
        self.assertEqual(result.confidence, "high")

    def test_falls_back_to_outstanding_when_float_missing(self) -> None:
        csv_path = _write_csv(
            "ticker,company,outstanding,float_ratio,float_shares,last_update,source,confidence\n"
            "1672,Test Co,900000000,,,2026-08-03,hkex,medium\n"
        )
        provider = CSVFloatProvider(csv_path)

        result = provider.get_float_shares("1672")

        self.assertEqual(result.share_base, 900000000)
        self.assertEqual(result.method, "outstanding")
        self.assertIsNotNone(result.warning)

    def test_returns_warning_when_no_share_base_is_available(self) -> None:
        csv_path = _write_csv(
            "ticker,company,outstanding,float_ratio,float_shares,last_update,source,confidence\n"
            "2432,Test Co,,,,2026-08-03,csv,low\n"
        )
        provider = CSVFloatProvider(csv_path)

        result = provider.get_float_shares("2432")

        self.assertIsNone(result.share_base)
        self.assertIsNone(result.method)
        self.assertIn("Neither float_shares nor outstanding", result.warning or "")

    def test_validates_required_schema(self) -> None:
        csv_path = _write_csv("ticker,company,float_shares\n3317,Test Co,100\n")

        with self.assertRaises(ValueError):
            CSVFloatProvider(csv_path)


if __name__ == "__main__":
    unittest.main()
