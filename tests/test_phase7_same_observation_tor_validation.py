"""Tests for Phase 7 same-observation TOR validation helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from validation.phase7_same_observation_tor_validation import (
    calculate_absolute_error,
    calculate_relative_error_pct,
    classify_evidence_quality,
    classify_formula_result,
    classify_timestamp_consistency,
    determine_formula_validation_status,
    has_complete_same_observation_data,
)
from validation.time_aligned_tor_benchmark import load_time_aligned_reference


ROOT = Path(__file__).resolve().parents[1]


class Phase7SameObservationTorValidationTests(unittest.TestCase):
    def test_observed_tor_parsing_and_schema_compatibility(self) -> None:
        rows = load_time_aligned_reference(
            ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
        )
        self.assertEqual(len(rows), 11)
        first = rows[0]
        self.assertEqual(first.ticker, "0005")
        self.assertEqual(first.aastocks_tor, None)
        self.assertTrue(first.source_url.startswith("https://www.aastocks.com/"))
        self.assertEqual(first.capture_method, "quick_quote_dom_and_frontend_object")
        self.assertEqual(first.tor_capture_status, "not_available_turnoverrate_na")

    def test_calculated_tor_errors(self) -> None:
        self.assertAlmostEqual(calculate_absolute_error(1.4715, 1.4700), 0.0015)
        self.assertAlmostEqual(
            calculate_relative_error_pct(1.4715, 1.4700),
            abs(1.4715 - 1.4700) / 1.4700 * 100.0,
        )

    def test_formula_classification(self) -> None:
        self.assertEqual(
            classify_formula_result(
                calculated_tor=1.0,
                observed_tor=1.009,
                timestamp_status="timestamp_consistent",
            ),
            "formula_match",
        )
        self.assertEqual(
            classify_formula_result(
                calculated_tor=1.0,
                observed_tor=1.03,
                timestamp_status="timestamp_consistent",
            ),
            "minor_difference",
        )
        self.assertEqual(
            classify_formula_result(
                calculated_tor=1.0,
                observed_tor=1.10,
                timestamp_status="timestamp_consistent",
            ),
            "material_difference",
        )

    def test_missing_observed_tor_is_insufficient(self) -> None:
        self.assertEqual(
            classify_formula_result(
                calculated_tor=1.0,
                observed_tor=None,
                timestamp_status="timestamp_partial",
            ),
            "insufficient_data",
        )

    def test_timestamp_consistency(self) -> None:
        rows = load_time_aligned_reference(
            ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
        )
        row = rows[0]
        self.assertFalse(has_complete_same_observation_data(row))
        self.assertEqual(classify_timestamp_consistency(row), "timestamp_partial")

    def test_evidence_quality(self) -> None:
        rows = load_time_aligned_reference(
            ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
        )
        self.assertEqual(classify_evidence_quality(rows[0]), "derived")

    def test_formula_validation_status_requires_minimum_sample(self) -> None:
        results = [
            {"formula_classification": "formula_match"},
            {"formula_classification": "formula_match"},
            {"formula_classification": "formula_match"},
            {"formula_classification": "formula_match"},
        ]
        self.assertEqual(
            determine_formula_validation_status(results),
            "INSUFFICIENT_SAMPLE",
        )


if __name__ == "__main__":
    unittest.main()
