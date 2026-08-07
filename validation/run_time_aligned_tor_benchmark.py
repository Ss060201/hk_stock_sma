"""Run the Phase 5 time-aligned TOR benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.time_aligned_tor_benchmark import (
    calculate_implied_volume,
    calculate_share_base_difference_pct,
    calculate_tor,
    calculate_tor_difference_pct,
    calculate_volume_difference_pct,
    classify_benchmark_row,
    fetch_yahoo_daily_observation,
    load_time_aligned_reference,
    summarize_optional,
)


def main() -> None:
    reference_path = ROOT / "validation" / "benchmarks" / "tor_time_aligned_reference.csv"
    rows = load_time_aligned_reference(reference_path)

    results = []
    for row in rows:
        yahoo = fetch_yahoo_daily_observation(row.ticker, row.benchmark_date)
        yahoo_volume = yahoo["yahoo_volume"]
        yahoo_share_base = yahoo["yahoo_share_base"]

        implied_volume = calculate_implied_volume(row.aastocks_tor, row.aastocks_share_base)
        calculated_tor = calculate_tor(row.aastocks_volume, row.aastocks_share_base)
        tor_difference = (
            (calculated_tor - row.aastocks_tor)
            if calculated_tor is not None and row.aastocks_tor is not None
            else None
        )
        tor_difference_pct = calculate_tor_difference_pct(calculated_tor, row.aastocks_tor)

        legacy_implied_volume = calculate_implied_volume(
            row.legacy_aastocks_tor, row.aastocks_share_base
        )
        legacy_implied_volume_difference_pct = calculate_volume_difference_pct(
            legacy_implied_volume, row.aastocks_volume
        )

        volume_difference_pct = calculate_volume_difference_pct(
            yahoo_volume, row.aastocks_volume
        )
        share_base_difference_pct = calculate_share_base_difference_pct(
            yahoo_share_base, row.aastocks_share_base
        )

        classification = classify_benchmark_row(
            aastocks_tor=row.aastocks_tor,
            calculated_tor=calculated_tor,
            share_base_difference_pct=share_base_difference_pct,
            legacy_implied_volume_difference_pct=legacy_implied_volume_difference_pct,
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
                "yahoo_volume": yahoo_volume,
                "yahoo_volume_date": yahoo["yahoo_volume_date"],
                "yahoo_share_base": yahoo_share_base,
                "volume_difference_pct": volume_difference_pct,
                "share_base_difference_pct": share_base_difference_pct,
                "implied_volume": implied_volume,
                "calculated_tor": calculated_tor,
                "tor_difference": tor_difference,
                "tor_difference_pct": tor_difference_pct,
                "legacy_aastocks_tor": row.legacy_aastocks_tor,
                "legacy_implied_volume": legacy_implied_volume,
                "legacy_implied_volume_difference_pct": legacy_implied_volume_difference_pct,
                "classification": classification,
                "source_note": row.source_note,
                "legacy_source_note": row.legacy_source_note,
            }
        )

    summary = {
        "total_benchmark_rows": len(results),
        "rows_with_explicit_date": sum(1 for row in results if row["benchmark_date"]),
        "rows_with_explicit_time": sum(1 for row in results if row["benchmark_time"]),
        "rows_with_observed_aastocks_tor": sum(
            1 for row in results if row["aastocks_tor"] is not None
        ),
        "rows_where_formula_matches": sum(
            1 for row in results if row["classification"] == "formula_matches"
        ),
        "rows_with_suspected_date_mismatch": sum(
            1 for row in results if row["classification"] == "date_mismatch_suspected"
        ),
        "rows_with_share_base_mismatch": sum(
            1 for row in results if row["classification"] == "share_base_mismatch"
        ),
        "rows_with_volume_mismatch": sum(
            1 for row in results if row["classification"] == "volume_mismatch"
        ),
        "rows_with_insufficient_data": sum(
            1 for row in results if row["classification"] == "insufficient_data"
        ),
        "absolute_tor_error": summarize_optional(
            [
                abs(row["tor_difference"])
                if row["tor_difference"] is not None
                else None
                for row in results
            ]
        ),
        "volume_difference_pct": summarize_optional(
            [abs(row["volume_difference_pct"]) for row in results]
        ),
        "share_base_difference_pct": summarize_optional(
            [abs(row["share_base_difference_pct"]) for row in results]
        ),
        "legacy_implied_volume_difference_pct": summarize_optional(
            [
                abs(row["legacy_implied_volume_difference_pct"])
                if row["legacy_implied_volume_difference_pct"] is not None
                else None
                for row in results
            ]
        ),
    }

    print(json.dumps({"summary": summary, "rows": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
