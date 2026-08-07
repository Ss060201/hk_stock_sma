"""Tests for Phase 6 TOR formula validation helpers."""

from __future__ import annotations

import unittest

from validation.phase6_tor_formula_validation import (
    calculate_tor_difference,
    calculate_tor_relative_error,
    classify_formula_validation,
    classify_legacy_benchmark_comparison,
    classify_share_base_outlier,
    classify_timestamp_status,
)


class Phase6TorFormulaValidationTests(unittest.TestCase):
    def test_calculate_tor_difference(self) -> None:
        self.assertAlmostEqual(calculate_tor_difference(1.5, 1.4), 0.1)

    def test_calculate_tor_relative_error(self) -> None:
        self.assertAlmostEqual(calculate_tor_relative_error(1.5, 1.2), 25.0)

    def test_classify_timestamp_uncertain_when_observed_tor_missing(self) -> None:
        self.assertEqual(
            classify_timestamp_status(
                aastocks_tor=None,
                benchmark_time="16:08:20",
                source_note="AASTOCKS same-session public quote sample captured during research; displayed TOR field was not reliably extractable via non-invasive public tools.",
            ),
            "timestamp_uncertain",
        )

    def test_classify_timestamp_aligned_when_same_observation_is_proven(self) -> None:
        self.assertEqual(
            classify_timestamp_status(
                aastocks_tor=1.47,
                benchmark_time="16:08:20",
                source_note="AASTOCKS same-session public quote sample with directly observed TOR captured from the same observation window.",
            ),
            "timestamp_aligned",
        )

    def test_classify_formula_validation_formula_match(self) -> None:
        self.assertEqual(
            classify_formula_validation(
                observed_tor=1.0,
                calculated_tor=1.009,
                timestamp_status="timestamp_aligned",
            ),
            "formula_match",
        )

    def test_classify_formula_validation_minor_difference(self) -> None:
        self.assertEqual(
            classify_formula_validation(
                observed_tor=1.0,
                calculated_tor=1.03,
                timestamp_status="timestamp_aligned",
            ),
            "minor_formula_difference",
        )

    def test_classify_formula_validation_material_difference(self) -> None:
        self.assertEqual(
            classify_formula_validation(
                observed_tor=1.0,
                calculated_tor=1.10,
                timestamp_status="timestamp_aligned",
            ),
            "material_formula_difference",
        )

    def test_classify_formula_validation_requires_same_observation_data(self) -> None:
        self.assertEqual(
            classify_formula_validation(
                observed_tor=None,
                calculated_tor=1.10,
                timestamp_status="timestamp_uncertain",
            ),
            "insufficient_data",
        )

    def test_classify_legacy_benchmark_comparison_timestamp_mismatch(self) -> None:
        self.assertEqual(
            classify_legacy_benchmark_comparison(
                legacy_implied_volume_difference_pct=80.0,
                share_base_outlier_status="share_base_aligned",
            ),
            "timestamp_mismatch_suspected",
        )

    def test_classify_legacy_benchmark_comparison_share_base_outlier(self) -> None:
        self.assertEqual(
            classify_legacy_benchmark_comparison(
                legacy_implied_volume_difference_pct=80.0,
                share_base_outlier_status="material_share_base_outlier",
            ),
            "share_base_outlier",
        )

    def test_classify_share_base_outlier(self) -> None:
        self.assertEqual(classify_share_base_outlier(1.0), "share_base_aligned")
        self.assertEqual(classify_share_base_outlier(3.0), "minor_share_base_outlier")
        self.assertEqual(
            classify_share_base_outlier(12.0),
            "material_share_base_outlier",
        )


if __name__ == "__main__":
    unittest.main()
