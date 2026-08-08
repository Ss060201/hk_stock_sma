"""Regression tests for shared turnover helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from turnover_utils import (
    TURNOVER_STATUS_CALCULATED,
    TURNOVER_STATUS_INVALID_SHARE_BASE,
    TURNOVER_STATUS_MISSING_SHARE_BASE,
    TURNOVER_STATUS_MISSING_VOLUME,
    apply_turnover_rate,
    calculate_turnover_rate,
    classify_turnover_status,
)


class TurnoverUtilsTests(unittest.TestCase):
    def test_regression_sample_6681_like_values(self) -> None:
        tor = calculate_turnover_rate(19_989_000, 1_358_280_000)

        self.assertIsNotNone(tor)
        self.assertAlmostEqual(tor, 1.47164, places=4)

    def test_apply_turnover_rate_calculates_value(self) -> None:
        df = pd.DataFrame({"Volume": [19_989_000]})

        result_df, status, reason = apply_turnover_rate(df, 1_358_280_000)

        self.assertEqual(status, TURNOVER_STATUS_CALCULATED)
        self.assertIsNone(reason)
        self.assertAlmostEqual(result_df["Turnover_Rate"].iloc[0], 1.47164, places=4)

    def test_missing_share_base_stays_missing(self) -> None:
        df = pd.DataFrame({"Volume": [1000]})

        result_df, status, reason = apply_turnover_rate(df, None)

        self.assertEqual(status, TURNOVER_STATUS_MISSING_SHARE_BASE)
        self.assertTrue(pd.isna(result_df["Turnover_Rate"].iloc[0]))
        self.assertIn("share base", reason.lower())

    def test_invalid_share_base_stays_missing(self) -> None:
        df = pd.DataFrame({"Volume": [1000]})

        result_df, status, reason = apply_turnover_rate(df, 0)

        self.assertEqual(status, TURNOVER_STATUS_INVALID_SHARE_BASE)
        self.assertTrue(pd.isna(result_df["Turnover_Rate"].iloc[0]))
        self.assertIn("greater than 0", reason)

    def test_missing_volume_status(self) -> None:
        status, reason = classify_turnover_status(None, 1000)

        self.assertEqual(status, TURNOVER_STATUS_MISSING_VOLUME)
        self.assertIn("Volume", reason)


if __name__ == "__main__":
    unittest.main()
