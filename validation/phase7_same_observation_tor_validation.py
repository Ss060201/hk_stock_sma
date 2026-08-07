"""Research-only helpers for Phase 7 same-observation TOR validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.phase6_tor_formula_validation import load_share_base_outlier_research
from validation.time_aligned_tor_benchmark import (
    TimeAlignedBenchmarkRow,
    calculate_tor,
    fetch_yahoo_daily_observation,
    load_time_aligned_reference,
    summarize_optional,
)

FORMULA_MATCH_RELATIVE_ERROR_PCT = 1.0
MINOR_FORMULA_RELATIVE_ERROR_PCT = 5.0
MINIMUM_SUPPORTED_SAMPLE_SIZE = 5


def calculate_absolute_error(
    calculated_tor: Optional[float], observed_tor: Optional[float]
) -> Optional[float]:
    """Return absolute TOR error in percentage points."""
    if calculated_tor is None or observed_tor is None:
        return None
    return abs(calculated_tor - observed_tor)


def calculate_relative_error_pct(
    calculated_tor: Optional[float], observed_tor: Optional[float]
) -> Optional[float]:
    """Return absolute relative error against observed TOR."""
    if calculated_tor is None or observed_tor in (None, 0):
        return None
    return abs(calculated_tor - observed_tor) / abs(observed_tor) * 100.0


def has_complete_same_observation_data(row: TimeAlignedBenchmarkRow) -> bool:
    """Return True only when TOR, volume, share base, and timestamp are all present."""
    return bool(
        row.benchmark_date
        and row.benchmark_time
        and row.aastocks_tor is not None
        and row.aastocks_volume is not None
        and row.aastocks_share_base is not None
    )


def classify_timestamp_consistency(row: TimeAlignedBenchmarkRow) -> str:
    """Classify whether a row has complete same-observation timing evidence."""
    if has_complete_same_observation_data(row):
        return "timestamp_consistent"
    if row.benchmark_date and row.benchmark_time:
        return "timestamp_partial"
    return "timestamp_unknown"


def classify_formula_result(
    *,
    calculated_tor: Optional[float],
    observed_tor: Optional[float],
    timestamp_status: str,
    formula_match_relative_error_pct: float = FORMULA_MATCH_RELATIVE_ERROR_PCT,
    minor_formula_relative_error_pct: float = MINOR_FORMULA_RELATIVE_ERROR_PCT,
) -> str:
    """Classify formula agreement using conservative predeclared thresholds."""
    if (
        calculated_tor is None
        or observed_tor is None
        or timestamp_status != "timestamp_consistent"
    ):
        return "insufficient_data"

    relative_error_pct = calculate_relative_error_pct(calculated_tor, observed_tor)
    if relative_error_pct is None:
        return "insufficient_data"
    if relative_error_pct <= formula_match_relative_error_pct:
        return "formula_match"
    if relative_error_pct <= minor_formula_relative_error_pct:
        return "minor_difference"
    return "material_difference"


def classify_evidence_quality(row: TimeAlignedBenchmarkRow) -> str:
    """Classify TOR evidence quality for a row."""
    if row.aastocks_tor is not None and has_complete_same_observation_data(row):
        return "observed"
    if row.aastocks_volume is not None and row.aastocks_share_base is not None and row.benchmark_time:
        return "derived"
    if row.source or row.source_note:
        return "supporting"
    return "unknown"


def determine_formula_validation_status(
    row_results: list[dict[str, object]],
    *,
    minimum_supported_sample_size: int = MINIMUM_SUPPORTED_SAMPLE_SIZE,
) -> str:
    """Determine the Phase 7 validation outcome from complete same-observation samples."""
    complete_rows = [
        row for row in row_results if row["formula_classification"] != "insufficient_data"
    ]
    if len(complete_rows) < minimum_supported_sample_size:
        return "INSUFFICIENT_SAMPLE"

    material_differences = [
        row for row in complete_rows if row["formula_classification"] == "material_difference"
    ]
    if material_differences:
        return "REJECTED_OR_UNRESOLVED"

    formula_matches = [
        row for row in complete_rows if row["formula_classification"] == "formula_match"
    ]
    if len(formula_matches) >= max(minimum_supported_sample_size, len(complete_rows) - 1):
        return "SUPPORTED"
    return "REJECTED_OR_UNRESOLVED"


def build_phase7_report_data(
    reference_path: str | Path,
    outlier_research_path: str | Path,
) -> dict[str, object]:
    """Build the Phase 7 report from reproducible research artifacts."""
    rows = load_time_aligned_reference(reference_path)
    outlier_research = load_share_base_outlier_research(outlier_research_path)

    results: list[dict[str, object]] = []
    for row in rows:
        calculated_tor = calculate_tor(row.aastocks_volume, row.aastocks_share_base)
        absolute_error = calculate_absolute_error(calculated_tor, row.aastocks_tor)
        relative_error_pct = calculate_relative_error_pct(calculated_tor, row.aastocks_tor)
        timestamp_status = classify_timestamp_consistency(row)
        formula_classification = classify_formula_result(
            calculated_tor=calculated_tor,
            observed_tor=row.aastocks_tor,
            timestamp_status=timestamp_status,
        )
        yahoo = fetch_yahoo_daily_observation(row.ticker, row.benchmark_date)

        results.append(
            {
                "ticker": row.ticker,
                "observation_date": row.benchmark_date,
                "observation_time": row.benchmark_time,
                "aastocks_volume": row.aastocks_volume,
                "aastocks_share_issued": row.aastocks_share_base,
                "aastocks_displayed_tor": row.aastocks_tor,
                "source": row.source,
                "source_url": row.source_url,
                "capture_method": row.capture_method,
                "tor_capture_status": row.tor_capture_status,
                "tor_source": row.tor_source,
                "tor_confidence": row.tor_confidence,
                "calculated_tor": calculated_tor,
                "absolute_error": absolute_error,
                "relative_error_pct": relative_error_pct,
                "formula_classification": formula_classification,
                "timestamp_status": timestamp_status,
                "evidence_quality": classify_evidence_quality(row),
                "yahoo_volume": yahoo["yahoo_volume"],
                "yahoo_volume_date": yahoo["yahoo_volume_date"],
                "notes": row.source_note,
                "outlier_research": outlier_research.get(row.ticker),
            }
        )

    summary = {
        "total_benchmark_rows": len(results),
        "rows_with_observed_tor": sum(
            1 for row in results if row["aastocks_displayed_tor"] is not None
        ),
        "rows_with_complete_same_observation_data": sum(
            1 for row in results if row["timestamp_status"] == "timestamp_consistent"
        ),
        "formula_matches": sum(
            1 for row in results if row["formula_classification"] == "formula_match"
        ),
        "minor_differences": sum(
            1 for row in results if row["formula_classification"] == "minor_difference"
        ),
        "material_differences": sum(
            1 for row in results if row["formula_classification"] == "material_difference"
        ),
        "insufficient_rows": sum(
            1 for row in results if row["formula_classification"] == "insufficient_data"
        ),
        "observed_rows": sum(1 for row in results if row["evidence_quality"] == "observed"),
        "derived_rows": sum(1 for row in results if row["evidence_quality"] == "derived"),
        "supporting_rows": sum(1 for row in results if row["evidence_quality"] == "supporting"),
        "unknown_rows": sum(1 for row in results if row["evidence_quality"] == "unknown"),
        "absolute_error_summary": summarize_optional(
            [row["absolute_error"] for row in results]
        ),
        "relative_error_summary_pct": summarize_optional(
            [row["relative_error_pct"] for row in results]
        ),
    }
    summary["formula_validation_status"] = determine_formula_validation_status(results)

    return {"summary": summary, "rows": results}


def main() -> None:
    """Print the Phase 7 report data as JSON."""
    reference_path = ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
    outlier_research_path = (
        ROOT / "validation" / "benchmarks" / "share_base_outlier_research.csv"
    )
    print(
        json.dumps(
            build_phase7_report_data(reference_path, outlier_research_path),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
