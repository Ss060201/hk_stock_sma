"""Research-only helpers for Phase 6 TOR formula validation."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.time_aligned_tor_benchmark import (
    calculate_implied_volume,
    calculate_share_base_difference_pct,
    calculate_tor,
    calculate_volume_difference_pct,
    fetch_yahoo_daily_observation,
    load_time_aligned_reference,
    summarize_optional,
)

FORMULA_MATCH_RELATIVE_ERROR_PCT = 1.0
MINOR_FORMULA_RELATIVE_ERROR_PCT = 5.0
SHARE_BASE_MINOR_OUTLIER_PCT = 2.0
SHARE_BASE_MATERIAL_OUTLIER_PCT = 5.0
LEGACY_TIMESTAMP_MISMATCH_THRESHOLD_PCT = 25.0


def calculate_tor_difference(
    calculated_tor: Optional[float], observed_tor: Optional[float]
) -> Optional[float]:
    """Return absolute TOR difference in percentage points."""
    if calculated_tor is None or observed_tor is None:
        return None
    return calculated_tor - observed_tor


def calculate_tor_relative_error(
    calculated_tor: Optional[float], observed_tor: Optional[float]
) -> Optional[float]:
    """Return relative TOR error against the observed TOR."""
    if calculated_tor is None or observed_tor in (None, 0):
        return None
    return (calculated_tor - observed_tor) / observed_tor * 100.0


def classify_timestamp_status(
    *,
    aastocks_tor: Optional[float],
    benchmark_time: str,
    source_note: str,
) -> str:
    """Classify whether same-observation evidence is strong enough for formula testing."""
    if aastocks_tor is None or not benchmark_time:
        return "timestamp_uncertain"

    note = source_note.lower()
    if "same-session" in note and "not reliably extractable" not in note:
        return "timestamp_aligned"
    return "timestamp_uncertain"


def classify_formula_validation(
    *,
    observed_tor: Optional[float],
    calculated_tor: Optional[float],
    timestamp_status: str,
    formula_match_relative_error_pct: float = FORMULA_MATCH_RELATIVE_ERROR_PCT,
    minor_formula_relative_error_pct: float = MINOR_FORMULA_RELATIVE_ERROR_PCT,
) -> str:
    """Classify formula agreement using explicit thresholds defined before measurement."""
    if (
        observed_tor is None
        or calculated_tor is None
        or timestamp_status != "timestamp_aligned"
    ):
        return "insufficient_data"

    relative_error = abs(calculate_tor_relative_error(calculated_tor, observed_tor) or 0.0)
    if relative_error <= formula_match_relative_error_pct:
        return "formula_match"
    if relative_error <= minor_formula_relative_error_pct:
        return "minor_formula_difference"
    return "material_formula_difference"


def classify_share_base_outlier(
    share_base_difference_pct: Optional[float],
    *,
    minor_threshold_pct: float = SHARE_BASE_MINOR_OUTLIER_PCT,
    material_threshold_pct: float = SHARE_BASE_MATERIAL_OUTLIER_PCT,
) -> str:
    """Classify share-base discrepancy as aligned, minor, or material."""
    if share_base_difference_pct is None:
        return "insufficient_data"

    absolute_difference = abs(share_base_difference_pct)
    if absolute_difference > material_threshold_pct:
        return "material_share_base_outlier"
    if absolute_difference > minor_threshold_pct:
        return "minor_share_base_outlier"
    return "share_base_aligned"


def classify_legacy_benchmark_comparison(
    *,
    legacy_implied_volume_difference_pct: Optional[float],
    share_base_outlier_status: str,
    timestamp_threshold_pct: float = LEGACY_TIMESTAMP_MISMATCH_THRESHOLD_PCT,
) -> str:
    """Classify whether the legacy TOR is likely from a different observation window."""
    if legacy_implied_volume_difference_pct is None:
        return "insufficient_data"

    if (
        abs(legacy_implied_volume_difference_pct) > timestamp_threshold_pct
        and share_base_outlier_status != "material_share_base_outlier"
    ):
        return "timestamp_mismatch_suspected"

    if share_base_outlier_status == "material_share_base_outlier":
        return "share_base_outlier"

    return "legacy_close_to_current_session"


def load_share_base_outlier_research(csv_path: str | Path) -> dict[str, dict[str, str]]:
    """Load official share-base research notes keyed by ticker."""
    path = Path(csv_path)
    records: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            ticker = str(raw.get("ticker", "")).zfill(4)
            records[ticker] = {key: str(value or "").strip() for key, value in raw.items()}
    return records


def build_phase6_report_data(
    reference_path: str | Path,
    outlier_research_path: str | Path,
) -> dict[str, object]:
    """Build a reproducible Phase 6 report using only research artifacts."""
    rows = load_time_aligned_reference(reference_path)
    outlier_research = load_share_base_outlier_research(outlier_research_path)

    results: list[dict[str, object]] = []
    for row in rows:
        yahoo = fetch_yahoo_daily_observation(row.ticker, row.benchmark_date)
        yahoo_volume = yahoo["yahoo_volume"]
        yahoo_share_base = yahoo["yahoo_share_base"]

        calculated_tor = calculate_tor(row.aastocks_volume, row.aastocks_share_base)
        tor_difference = calculate_tor_difference(calculated_tor, row.aastocks_tor)
        tor_relative_error = calculate_tor_relative_error(calculated_tor, row.aastocks_tor)
        timestamp_status = classify_timestamp_status(
            aastocks_tor=row.aastocks_tor,
            benchmark_time=row.benchmark_time,
            source_note=row.source_note,
        )
        formula_validation = classify_formula_validation(
            observed_tor=row.aastocks_tor,
            calculated_tor=calculated_tor,
            timestamp_status=timestamp_status,
        )

        volume_difference_pct = calculate_volume_difference_pct(
            yahoo_volume, row.aastocks_volume
        )
        share_base_difference_pct = calculate_share_base_difference_pct(
            yahoo_share_base, row.aastocks_share_base
        )
        share_base_outlier_status = classify_share_base_outlier(share_base_difference_pct)

        legacy_implied_volume = calculate_implied_volume(
            row.legacy_aastocks_tor, row.aastocks_share_base
        )
        legacy_implied_volume_difference_pct = calculate_volume_difference_pct(
            legacy_implied_volume, row.aastocks_volume
        )
        legacy_comparison_status = classify_legacy_benchmark_comparison(
            legacy_implied_volume_difference_pct=legacy_implied_volume_difference_pct,
            share_base_outlier_status=share_base_outlier_status,
        )

        results.append(
            {
                "ticker": row.ticker,
                "benchmark_date": row.benchmark_date,
                "benchmark_time": row.benchmark_time,
                "aastocks_tor": row.aastocks_tor,
                "aastocks_volume": row.aastocks_volume,
                "aastocks_share_base": row.aastocks_share_base,
                "source": row.source,
                "source_note": row.source_note,
                "calculated_tor": calculated_tor,
                "tor_difference": tor_difference,
                "tor_relative_error": tor_relative_error,
                "timestamp_status": timestamp_status,
                "formula_validation": formula_validation,
                "yahoo_volume": yahoo_volume,
                "yahoo_volume_date": yahoo["yahoo_volume_date"],
                "yahoo_share_base": yahoo_share_base,
                "volume_difference_pct": volume_difference_pct,
                "share_base_difference_pct": share_base_difference_pct,
                "share_base_outlier_status": share_base_outlier_status,
                "legacy_aastocks_tor": row.legacy_aastocks_tor,
                "legacy_implied_volume": legacy_implied_volume,
                "legacy_implied_volume_difference_pct": legacy_implied_volume_difference_pct,
                "legacy_comparison_status": legacy_comparison_status,
                "outlier_research": outlier_research.get(row.ticker),
            }
        )

    summary = {
        "total_rows": len(results),
        "rows_with_observed_aastocks_tor": sum(
            1 for row in results if row["aastocks_tor"] is not None
        ),
        "formula_matches": sum(
            1 for row in results if row["formula_validation"] == "formula_match"
        ),
        "minor_formula_differences": sum(
            1 for row in results if row["formula_validation"] == "minor_formula_difference"
        ),
        "material_formula_differences": sum(
            1
            for row in results
            if row["formula_validation"] == "material_formula_difference"
        ),
        "insufficient_formula_rows": sum(
            1 for row in results if row["formula_validation"] == "insufficient_data"
        ),
        "timestamp_uncertain_rows": sum(
            1 for row in results if row["timestamp_status"] == "timestamp_uncertain"
        ),
        "legacy_timestamp_mismatch_suspected_rows": sum(
            1
            for row in results
            if row["legacy_comparison_status"] == "timestamp_mismatch_suspected"
        ),
        "share_base_aligned_rows": sum(
            1 for row in results if row["share_base_outlier_status"] == "share_base_aligned"
        ),
        "minor_share_base_outliers": sum(
            1
            for row in results
            if row["share_base_outlier_status"] == "minor_share_base_outlier"
        ),
        "material_share_base_outliers": sum(
            1
            for row in results
            if row["share_base_outlier_status"] == "material_share_base_outlier"
        ),
        "absolute_volume_difference_pct": summarize_optional(
            [
                abs(row["volume_difference_pct"])
                if row["volume_difference_pct"] is not None
                else None
                for row in results
            ]
        ),
        "absolute_share_base_difference_pct": summarize_optional(
            [
                abs(row["share_base_difference_pct"])
                if row["share_base_difference_pct"] is not None
                else None
                for row in results
            ]
        ),
    }
    return {"summary": summary, "rows": results}


def main() -> None:
    """Print the Phase 6 report data as JSON."""
    reference_path = ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
    outlier_research_path = (
        ROOT / "validation" / "benchmarks" / "share_base_outlier_research.csv"
    )
    print(
        json.dumps(
            build_phase6_report_data(reference_path, outlier_research_path),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
