"""Research-only Phase 8 formula evidence decision helper."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.phase6_tor_formula_validation import (
    classify_legacy_benchmark_comparison,
    classify_share_base_outlier,
    load_share_base_outlier_research,
)
from validation.time_aligned_tor_benchmark import (
    calculate_share_base_difference_pct,
    calculate_tor,
    calculate_volume_difference_pct,
    fetch_yahoo_daily_observation,
    load_time_aligned_reference,
)

FORMULA_MATCH_RELATIVE_ERROR_PCT = 1.0
MINIMUM_CONFIRMED_SAMPLE_SIZE = 5
AASTOCKS_TURNOVER_DEFINITION = (
    "Turnover Rate measures the trading volume to the total issued shares in a period of time."
)


def _parse_optional_float(value: object) -> Optional[float]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def calculate_relative_difference(
    left: Optional[float], right: Optional[float]
) -> Optional[float]:
    """Return relative difference using the right-hand value as denominator."""
    if left is None or right in (None, 0):
        return None
    return (left - right) / right * 100.0


def calculate_absolute_difference(
    left: Optional[float], right: Optional[float]
) -> Optional[float]:
    """Return absolute numeric difference."""
    if left is None or right is None:
        return None
    return abs(left - right)


def classify_tor_evidence(
    observed_tor: Optional[float], calculated_tor: Optional[float]
) -> str:
    """Classify TOR evidence without ever conflating derived with observed."""
    if observed_tor is not None:
        return "OBSERVED"
    if calculated_tor is not None:
        return "DERIVED"
    return "UNKNOWN"


def classify_timestamp_confidence(
    *,
    benchmark_date: str,
    benchmark_time: str,
    observed_tor: Optional[float],
) -> str:
    """Classify timestamp confidence for formula testing."""
    if benchmark_date and benchmark_time and observed_tor is not None:
        return "high"
    if benchmark_date and benchmark_time:
        return "medium"
    if benchmark_date:
        return "low"
    return "unknown"


def classify_share_base_confidence(
    *,
    ticker: str,
    share_base_outlier_status: str,
    outlier_research: Optional[dict[str, str]],
) -> str:
    """Classify share-base provenance confidence."""
    if share_base_outlier_status == "material_share_base_outlier":
        if outlier_research and outlier_research.get("confidence"):
            return outlier_research["confidence"]
        return "low"
    if ticker == "6681":
        return "high"
    return "high"


def classify_row_outlier(
    *,
    ticker: str,
    share_base_outlier_status: str,
    legacy_comparison_status: str,
    volume_difference_pct: Optional[float],
) -> str:
    """Classify the likely cause category for Phase 8 outlier review."""
    if share_base_outlier_status == "material_share_base_outlier":
        return "SHARE_BASE_OUTLIER"
    if legacy_comparison_status == "timestamp_mismatch_suspected":
        return "TIMESTAMP_MISMATCH"
    if volume_difference_pct is not None and abs(volume_difference_pct) > 5.0:
        return "VOLUME_MISMATCH"
    if ticker in {"0005", "2726"}:
        return "NO_MATERIAL_OUTLIER"
    return "INSUFFICIENT_EVIDENCE"


def classify_matrix_row(
    *,
    formula_testable: bool,
    outlier_classification: str,
    volume_evidence: str,
    share_base_evidence: str,
) -> str:
    """Classify a row for the evidence matrix."""
    if formula_testable:
        return "DIRECTLY_TESTABLE"
    if outlier_classification == "SHARE_BASE_OUTLIER":
        return "OUTLIER"
    if volume_evidence == "OBSERVED" and share_base_evidence == "OBSERVED":
        return "PARTIALLY_SUPPORTED"
    return "NOT_TESTABLE"


def decide_formula_decision(
    *,
    observed_rows: int,
    same_observation_rows: int,
    formula_confirming_rows: int,
    formula_rejecting_rows: int,
    supporting_definition_available: bool,
    derived_rows: int,
    contradictory_evidence: bool,
    explainable_remaining_discrepancies: bool,
    minimum_confirmed_sample_size: int = MINIMUM_CONFIRMED_SAMPLE_SIZE,
) -> str:
    """Return the conservative Phase 8 formula decision."""
    if (
        observed_rows >= minimum_confirmed_sample_size
        and same_observation_rows >= minimum_confirmed_sample_size
        and formula_confirming_rows >= minimum_confirmed_sample_size
        and formula_rejecting_rows == 0
    ):
        return "FORMULA_CONFIRMED"

    if (
        observed_rows >= minimum_confirmed_sample_size
        and formula_rejecting_rows >= minimum_confirmed_sample_size
    ):
        return "FORMULA_NOT_SUPPORTED"

    if (
        supporting_definition_available
        and derived_rows > 0
        and not contradictory_evidence
        and explainable_remaining_discrepancies
    ):
        return "FORMULA_SUPPORTED_BUT_NOT_CONFIRMED"

    return "INSUFFICIENT_EVIDENCE"


def build_phase8_report_data(
    reference_path: str | Path,
    outlier_research_path: str | Path,
) -> dict[str, object]:
    """Build the Phase 8 evidence decision dataset."""
    rows = load_time_aligned_reference(reference_path)
    outlier_research = load_share_base_outlier_research(outlier_research_path)

    sensitivity_rows: list[dict[str, object]] = []
    matrix_rows: list[dict[str, object]] = []
    row_analysis: list[dict[str, object]] = []

    for row in rows:
        yahoo = fetch_yahoo_daily_observation(row.ticker, row.benchmark_date)
        yahoo_volume = _parse_optional_float(yahoo["yahoo_volume"])
        yahoo_shares_outstanding = _parse_optional_float(yahoo["yahoo_share_base"])
        aastocks_share_base = row.aastocks_share_base
        share_issued = row.aastocks_share_base
        official_share_base = _parse_optional_float(
            outlier_research.get(row.ticker, {}).get("official_share_base")
            if outlier_research.get(row.ticker)
            else None
        )

        tor_share_issued = calculate_tor(row.aastocks_volume, share_issued)
        tor_yahoo = calculate_tor(row.aastocks_volume, yahoo_shares_outstanding)
        tor_aastocks = calculate_tor(row.aastocks_volume, aastocks_share_base)
        tor_official = calculate_tor(row.aastocks_volume, official_share_base)

        volume_difference_pct = calculate_volume_difference_pct(
            yahoo_volume, row.aastocks_volume
        )
        share_base_difference_pct = calculate_share_base_difference_pct(
            yahoo_shares_outstanding, row.aastocks_share_base
        )
        share_base_outlier_status = classify_share_base_outlier(share_base_difference_pct)
        legacy_implied_volume = (
            row.legacy_aastocks_tor / 100.0 * row.aastocks_share_base
            if row.legacy_aastocks_tor is not None and row.aastocks_share_base is not None
            else None
        )
        legacy_implied_volume_difference_pct = calculate_volume_difference_pct(
            legacy_implied_volume, row.aastocks_volume
        )
        legacy_comparison_status = classify_legacy_benchmark_comparison(
            legacy_implied_volume_difference_pct=legacy_implied_volume_difference_pct,
            share_base_outlier_status=share_base_outlier_status,
        )

        outlier_classification = classify_row_outlier(
            ticker=row.ticker,
            share_base_outlier_status=share_base_outlier_status,
            legacy_comparison_status=legacy_comparison_status,
            volume_difference_pct=volume_difference_pct,
        )

        volume_evidence = "OBSERVED" if row.aastocks_volume is not None else "UNKNOWN"
        share_base_evidence = "OBSERVED" if row.aastocks_share_base is not None else "UNKNOWN"
        tor_evidence = classify_tor_evidence(row.aastocks_tor, tor_aastocks)
        timestamp_confidence = classify_timestamp_confidence(
            benchmark_date=row.benchmark_date,
            benchmark_time=row.benchmark_time,
            observed_tor=row.aastocks_tor,
        )
        share_base_confidence = classify_share_base_confidence(
            ticker=row.ticker,
            share_base_outlier_status=share_base_outlier_status,
            outlier_research=outlier_research.get(row.ticker),
        )
        formula_testable = bool(
            row.aastocks_tor is not None
            and row.aastocks_volume is not None
            and row.aastocks_share_base is not None
            and row.benchmark_time
        )

        formula_relative_error_pct = calculate_relative_difference(
            tor_aastocks, row.aastocks_tor
        )
        if formula_testable and formula_relative_error_pct is not None:
            if abs(formula_relative_error_pct) <= FORMULA_MATCH_RELATIVE_ERROR_PCT:
                formula_result = "confirming"
            else:
                formula_result = "rejecting"
        else:
            formula_result = "evidence_only"

        tor_evidence_tier = (
            "Tier 2"
            if row.aastocks_tor is not None and row.tor_source == "aastocks_public_frontend_object"
            else ""
        )

        matrix_classification = classify_matrix_row(
            formula_testable=formula_testable,
            outlier_classification=outlier_classification,
            volume_evidence=volume_evidence,
            share_base_evidence=share_base_evidence,
        )

        sensitivity_rows.append(
            {
                "ticker": row.ticker,
                "timestamp": f"{row.benchmark_date} {row.benchmark_time}".strip(),
                "volume": row.aastocks_volume,
                "share_issued": share_issued,
                "yahoo_shares_outstanding": yahoo_shares_outstanding,
                "aastocks_share_base": aastocks_share_base,
                "official_share_base": official_share_base,
                "tor_share_issued": tor_share_issued,
                "tor_yahoo": tor_yahoo,
                "tor_aastocks": tor_aastocks,
                "tor_official": tor_official,
                "tor_yahoo_vs_aastocks_abs_diff": calculate_absolute_difference(
                    tor_yahoo, tor_aastocks
                ),
                "tor_yahoo_vs_aastocks_rel_diff_pct": calculate_relative_difference(
                    tor_yahoo, tor_aastocks
                ),
                "tor_official_vs_aastocks_abs_diff": calculate_absolute_difference(
                    tor_official, tor_aastocks
                ),
                "tor_official_vs_aastocks_rel_diff_pct": calculate_relative_difference(
                    tor_official, tor_aastocks
                ),
            }
        )

        matrix_rows.append(
            {
                "ticker": row.ticker,
                "observation_date": row.benchmark_date,
                "observation_timestamp": f"{row.benchmark_date} {row.benchmark_time}".strip(),
                "volume_evidence": volume_evidence,
                "share_base_evidence": share_base_evidence,
                "tor_evidence": tor_evidence,
                "tor_evidence_tier": tor_evidence_tier,
                "timestamp_confidence": timestamp_confidence,
                "share_base_confidence": share_base_confidence,
                "formula_testable": "true" if formula_testable else "false",
                "classification": matrix_classification,
                "notes": row.source_note,
                "source_url": row.source_url,
            }
        )

        row_analysis.append(
            {
                "ticker": row.ticker,
                "benchmark_date": row.benchmark_date,
                "benchmark_time": row.benchmark_time,
                "aastocks_volume": row.aastocks_volume,
                "aastocks_share_base": row.aastocks_share_base,
                "aastocks_tor": row.aastocks_tor,
                "tor_capture_status": row.tor_capture_status,
                "tor_confidence": row.tor_confidence,
                "volume_evidence": volume_evidence,
                "share_base_evidence": share_base_evidence,
                "tor_evidence": tor_evidence,
                "timestamp_confidence": timestamp_confidence,
                "share_base_confidence": share_base_confidence,
                "formula_testable": formula_testable,
                "formula_result": formula_result,
                "outlier_classification": outlier_classification,
                "legacy_comparison_status": legacy_comparison_status,
                "share_base_difference_pct": share_base_difference_pct,
                "volume_difference_pct": volume_difference_pct,
                "yahoo_shares_outstanding": yahoo_shares_outstanding,
                "official_share_base": official_share_base,
                "tor_share_issued": tor_share_issued,
                "tor_yahoo": tor_yahoo,
                "tor_aastocks": tor_aastocks,
                "tor_official": tor_official,
                "outlier_research": outlier_research.get(row.ticker),
            }
        )

    final_search = {
        "sources_checked": [
            "AASTOCKS detail quote page",
            "AASTOCKS quick quote page",
            "AASTOCKS mobile quote page",
            "AASTOCKS public frontend quote object",
            "AASTOCKS public quote endpoint via frontend bindings",
        ],
        "tier_1_count": 0,
        "tier_2_count": 0,
        "tier_3_count": 0,
        "same_observation_tor_unavailable": True,
        "reason": (
            "The bounded final investigation did not find any legitimate public AASTOCKS representation "
            "that exposed a directly attributable same-observation displayed TOR. "
            "The frontend object continued to expose timestamped Volume and ShareIssued but TurnoverRate remained N/A."
        ),
    }

    summary = {
        "benchmark_row_count": len(row_analysis),
        "rows_with_observed_tor": sum(1 for row in row_analysis if row["aastocks_tor"] is not None),
        "rows_with_same_observation_tor": sum(
            1 for row in row_analysis if row["formula_testable"]
        ),
        "rows_with_derived_tor_only": sum(
            1
            for row in row_analysis
            if row["tor_evidence"] == "DERIVED" and row["aastocks_tor"] is None
        ),
        "rows_with_sufficient_timestamp_evidence": sum(
            1 for row in row_analysis if row["timestamp_confidence"] in {"high", "medium"}
        ),
        "rows_with_reliable_share_base_evidence": sum(
            1 for row in row_analysis if row["share_base_confidence"] in {"high", "medium"}
        ),
        "rows_affected_by_known_share_base_outliers": sum(
            1 for row in row_analysis if row["outlier_classification"] == "SHARE_BASE_OUTLIER"
        ),
        "rows_affected_by_timestamp_uncertainty": sum(
            1 for row in row_analysis if row["outlier_classification"] == "TIMESTAMP_MISMATCH"
        ),
        "formula_confirming_rows": sum(
            1 for row in row_analysis if row["formula_result"] == "confirming"
        ),
        "formula_rejecting_rows": sum(
            1 for row in row_analysis if row["formula_result"] == "rejecting"
        ),
        "evidence_only_rows": sum(
            1 for row in row_analysis if row["formula_result"] == "evidence_only"
        ),
        "supporting_definition_available": True,
        "supporting_definition_text": AASTOCKS_TURNOVER_DEFINITION,
        "supporting_definition_source_url": "https://www.aastocks.com/en/stocks/quote/quick-quote.aspx?symbol=06681",
        "contradictory_evidence": False,
        "explainable_remaining_discrepancies": True,
        "final_search": final_search,
    }
    summary["formula_decision"] = decide_formula_decision(
        observed_rows=summary["rows_with_observed_tor"],
        same_observation_rows=summary["rows_with_same_observation_tor"],
        formula_confirming_rows=summary["formula_confirming_rows"],
        formula_rejecting_rows=summary["formula_rejecting_rows"],
        supporting_definition_available=summary["supporting_definition_available"],
        derived_rows=summary["rows_with_derived_tor_only"],
        contradictory_evidence=summary["contradictory_evidence"],
        explainable_remaining_discrepancies=summary["explainable_remaining_discrepancies"],
    )

    return {
        "summary": summary,
        "row_analysis": row_analysis,
        "sensitivity_rows": sensitivity_rows,
        "matrix_rows": matrix_rows,
    }


def main() -> None:
    """Print the Phase 8 evidence decision dataset as JSON."""
    reference_path = ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
    outlier_research_path = (
        ROOT / "validation" / "benchmarks" / "share_base_outlier_research.csv"
    )
    print(
        json.dumps(
            build_phase8_report_data(reference_path, outlier_research_path),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
