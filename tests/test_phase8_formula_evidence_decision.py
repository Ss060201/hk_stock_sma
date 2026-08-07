"""Tests for Phase 8 formula evidence decision helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from validation.phase8_formula_evidence_decision import (
    build_phase8_report_data,
    calculate_absolute_difference,
    calculate_relative_difference,
    classify_matrix_row,
    classify_tor_evidence,
    decide_formula_decision,
)


ROOT = Path(__file__).resolve().parents[1]


class Phase8FormulaEvidenceDecisionTests(unittest.TestCase):
    def test_empty_observed_sample_is_insufficient(self) -> None:
        self.assertEqual(
            decide_formula_decision(
                observed_rows=0,
                same_observation_rows=0,
                formula_confirming_rows=0,
                formula_rejecting_rows=0,
                supporting_definition_available=False,
                derived_rows=0,
                contradictory_evidence=False,
                explainable_remaining_discrepancies=False,
            ),
            "INSUFFICIENT_EVIDENCE",
        )

    def test_derived_tor_never_counts_as_observed(self) -> None:
        self.assertEqual(classify_tor_evidence(None, 1.23), "DERIVED")
        self.assertEqual(classify_tor_evidence(None, None), "UNKNOWN")

    def test_five_reliable_observed_matching_rows_confirms_formula(self) -> None:
        self.assertEqual(
            decide_formula_decision(
                observed_rows=5,
                same_observation_rows=5,
                formula_confirming_rows=5,
                formula_rejecting_rows=0,
                supporting_definition_available=True,
                derived_rows=5,
                contradictory_evidence=False,
                explainable_remaining_discrepancies=True,
            ),
            "FORMULA_CONFIRMED",
        )

    def test_five_observed_mismatch_rows_reject_formula(self) -> None:
        self.assertEqual(
            decide_formula_decision(
                observed_rows=5,
                same_observation_rows=5,
                formula_confirming_rows=0,
                formula_rejecting_rows=5,
                supporting_definition_available=True,
                derived_rows=0,
                contradictory_evidence=True,
                explainable_remaining_discrepancies=False,
            ),
            "FORMULA_NOT_SUPPORTED",
        )

    def test_supported_but_not_confirmed_requires_supporting_evidence(self) -> None:
        self.assertEqual(
            decide_formula_decision(
                observed_rows=0,
                same_observation_rows=0,
                formula_confirming_rows=0,
                formula_rejecting_rows=0,
                supporting_definition_available=True,
                derived_rows=11,
                contradictory_evidence=False,
                explainable_remaining_discrepancies=True,
            ),
            "FORMULA_SUPPORTED_BUT_NOT_CONFIRMED",
        )

    def test_share_base_sensitivity_calculation(self) -> None:
        self.assertAlmostEqual(calculate_absolute_difference(1.5, 1.2), 0.3)
        self.assertAlmostEqual(calculate_relative_difference(1.5, 1.2), 25.0)

    def test_missing_denominator_handling(self) -> None:
        self.assertIsNone(calculate_absolute_difference(None, 1.2))
        self.assertIsNone(calculate_relative_difference(1.2, None))
        self.assertIsNone(calculate_relative_difference(1.2, 0))

    def test_timestamp_uncertainty_leads_to_partial_support_not_direct_test(self) -> None:
        self.assertEqual(
            classify_matrix_row(
                formula_testable=False,
                outlier_classification="TIMESTAMP_MISMATCH",
                volume_evidence="OBSERVED",
                share_base_evidence="OBSERVED",
            ),
            "PARTIALLY_SUPPORTED",
        )

    def test_2577_remains_research_only(self) -> None:
        data = build_phase8_report_data(
            ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv",
            ROOT / "validation" / "benchmarks" / "share_base_outlier_research.csv",
        )
        row = next(item for item in data["row_analysis"] if item["ticker"] == "2577")
        matrix = next(item for item in data["matrix_rows"] if item["ticker"] == "2577")
        self.assertEqual(row["outlier_classification"], "SHARE_BASE_OUTLIER")
        self.assertFalse(row["formula_testable"])
        self.assertEqual(matrix["classification"], "OUTLIER")

    def test_9678_remains_research_only(self) -> None:
        data = build_phase8_report_data(
            ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv",
            ROOT / "validation" / "benchmarks" / "share_base_outlier_research.csv",
        )
        row = next(item for item in data["row_analysis"] if item["ticker"] == "9678")
        self.assertEqual(row["outlier_classification"], "SHARE_BASE_OUTLIER")
        self.assertFalse(row["formula_testable"])
        self.assertIsNotNone(row["official_share_base"])

    def test_evidence_matrix_classification(self) -> None:
        self.assertEqual(
            classify_matrix_row(
                formula_testable=True,
                outlier_classification="NO_MATERIAL_OUTLIER",
                volume_evidence="OBSERVED",
                share_base_evidence="OBSERVED",
            ),
            "DIRECTLY_TESTABLE",
        )
        self.assertEqual(
            classify_matrix_row(
                formula_testable=False,
                outlier_classification="SHARE_BASE_OUTLIER",
                volume_evidence="OBSERVED",
                share_base_evidence="OBSERVED",
            ),
            "OUTLIER",
        )


if __name__ == "__main__":
    unittest.main()
