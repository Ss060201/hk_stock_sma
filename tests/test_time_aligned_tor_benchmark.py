"""Tests for Phase 5 time-aligned TOR benchmark helpers."""

from __future__ import annotations

import unittest

from validation.time_aligned_tor_benchmark import (
    calculate_implied_volume,
    calculate_share_base_difference_pct,
    calculate_tor,
    calculate_tor_difference_pct,
    calculate_volume_difference_pct,
    classify_benchmark_row,
)


class TimeAlignedTorBenchmarkTests(unittest.TestCase):
    def test_calculate_implied_volume(self) -> None:
        self.assertEqual(calculate_implied_volume(0.5, 1_000_000), 5_000.0)

    def test_calculate_volume_difference_pct(self) -> None:
        self.assertAlmostEqual(
            calculate_volume_difference_pct(1_010_000, 1_000_000),
            1.0,
        )

    def test_calculate_share_base_difference_pct(self) -> None:
        self.assertAlmostEqual(
            calculate_share_base_difference_pct(1_050_000, 1_000_000),
            5.0,
        )

    def test_calculate_tor_and_difference_pct(self) -> None:
        tor = calculate_tor(5_000, 1_000_000)
        self.assertAlmostEqual(tor, 0.5)
        self.assertAlmostEqual(calculate_tor_difference_pct(0.5, 0.4), 25.0)

    def test_classify_formula_matches(self) -> None:
        self.assertEqual(
            classify_benchmark_row(
                aastocks_tor=0.5,
                calculated_tor=0.49,
                share_base_difference_pct=0.1,
                legacy_implied_volume_difference_pct=None,
            ),
            "formula_matches",
        )

    def test_classify_share_base_mismatch(self) -> None:
        self.assertEqual(
            classify_benchmark_row(
                aastocks_tor=None,
                calculated_tor=None,
                share_base_difference_pct=12.0,
                legacy_implied_volume_difference_pct=5.0,
            ),
            "share_base_mismatch",
        )

    def test_classify_date_mismatch(self) -> None:
        self.assertEqual(
            classify_benchmark_row(
                aastocks_tor=None,
                calculated_tor=None,
                share_base_difference_pct=0.2,
                legacy_implied_volume_difference_pct=80.0,
            ),
            "date_mismatch_suspected",
        )

    def test_classify_insufficient_data(self) -> None:
        self.assertEqual(
            classify_benchmark_row(
                aastocks_tor=None,
                calculated_tor=None,
                share_base_difference_pct=0.2,
                legacy_implied_volume_difference_pct=5.0,
            ),
            "insufficient_data",
        )


if __name__ == "__main__":
    unittest.main()
