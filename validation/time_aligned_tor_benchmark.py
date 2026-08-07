"""Utilities for the Phase 5 time-aligned TOR benchmark."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Optional

import yfinance as yf


@dataclass(frozen=True)
class TimeAlignedBenchmarkRow:
    """Raw reference row for a time-aligned TOR benchmark observation."""

    ticker: str
    benchmark_date: str
    benchmark_time: str
    aastocks_tor: Optional[float]
    aastocks_volume: Optional[float]
    aastocks_share_base: Optional[float]
    legacy_aastocks_tor: Optional[float]
    source: str
    source_url: str
    capture_method: str
    tor_capture_status: str
    tor_source: str
    tor_confidence: str
    source_note: str
    legacy_source_note: str


def _parse_optional_float(value: object) -> Optional[float]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_time_aligned_reference(csv_path: str | Path) -> list[TimeAlignedBenchmarkRow]:
    """Load time-aligned benchmark rows from CSV."""
    path = Path(csv_path)
    rows: list[TimeAlignedBenchmarkRow] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                TimeAlignedBenchmarkRow(
                    ticker=str(raw.get("ticker", "")).zfill(4),
                    benchmark_date=str(raw.get("benchmark_date", "")).strip(),
                    benchmark_time=str(raw.get("benchmark_time", "")).strip(),
                    aastocks_tor=_parse_optional_float(raw.get("aastocks_tor")),
                    aastocks_volume=_parse_optional_float(raw.get("aastocks_volume")),
                    aastocks_share_base=_parse_optional_float(raw.get("aastocks_share_base")),
                    legacy_aastocks_tor=_parse_optional_float(raw.get("legacy_aastocks_tor")),
                    source=str(raw.get("source", "")).strip(),
                    source_url=str(raw.get("source_url", "")).strip(),
                    capture_method=str(raw.get("capture_method", "")).strip(),
                    tor_capture_status=str(raw.get("tor_capture_status", "")).strip(),
                    tor_source=str(raw.get("tor_source", "")).strip(),
                    tor_confidence=str(raw.get("tor_confidence", "")).strip(),
                    source_note=str(raw.get("source_note", "")).strip(),
                    legacy_source_note=str(raw.get("legacy_source_note", "")).strip(),
                )
            )
    return rows


def calculate_volume_difference_pct(
    yahoo_volume: Optional[float], aastocks_volume: Optional[float]
) -> Optional[float]:
    """Return percent difference using AASTOCKS volume as denominator."""
    if yahoo_volume is None or aastocks_volume in (None, 0):
        return None
    return (yahoo_volume - aastocks_volume) / aastocks_volume * 100.0


def calculate_share_base_difference_pct(
    yahoo_share_base: Optional[float], aastocks_share_base: Optional[float]
) -> Optional[float]:
    """Return percent difference using AASTOCKS share base as denominator."""
    if yahoo_share_base is None or aastocks_share_base in (None, 0):
        return None
    return (yahoo_share_base - aastocks_share_base) / aastocks_share_base * 100.0


def calculate_implied_volume(
    aastocks_tor: Optional[float], aastocks_share_base: Optional[float]
) -> Optional[float]:
    """Return implied volume from TOR and share base."""
    if aastocks_tor is None or aastocks_share_base is None:
        return None
    return aastocks_tor / 100.0 * aastocks_share_base


def calculate_tor(
    volume: Optional[float], share_base: Optional[float]
) -> Optional[float]:
    """Return turnover rate from volume and share base."""
    if volume is None or share_base in (None, 0):
        return None
    return volume / share_base * 100.0


def calculate_tor_difference_pct(
    calculated_tor: Optional[float], observed_tor: Optional[float]
) -> Optional[float]:
    """Return relative TOR difference against the observed TOR."""
    if calculated_tor is None or observed_tor in (None, 0):
        return None
    return (calculated_tor - observed_tor) / observed_tor * 100.0


def fetch_yahoo_daily_observation(
    ticker: str, benchmark_date: str
) -> dict[str, Optional[float | str]]:
    """Fetch Yahoo daily volume and close for the benchmark date."""
    ticker_obj = yf.Ticker(f"{ticker}.HK")
    info = {}
    try:
        info = ticker_obj.info or {}
    except Exception:
        info = {}

    start = date.fromisoformat(benchmark_date)
    end = start + timedelta(days=1)
    history = ticker_obj.history(
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=False,
    )

    if history.empty:
        return {
            "yahoo_volume": None,
            "yahoo_close": None,
            "yahoo_volume_date": None,
            "yahoo_share_base": _parse_optional_float(info.get("sharesOutstanding")),
        }

    row = history.iloc[-1]
    return {
        "yahoo_volume": float(row["Volume"]),
        "yahoo_close": float(row["Close"]),
        "yahoo_volume_date": str(history.index[-1].date()),
        "yahoo_share_base": _parse_optional_float(info.get("sharesOutstanding")),
    }


def classify_benchmark_row(
    *,
    aastocks_tor: Optional[float],
    calculated_tor: Optional[float],
    share_base_difference_pct: Optional[float],
    legacy_implied_volume_difference_pct: Optional[float],
    formula_relative_tolerance_pct: float = 5.0,
    share_base_threshold_pct: float = 5.0,
    legacy_date_mismatch_threshold_pct: float = 25.0,
) -> str:
    """Classify a benchmark row using measurable evidence only."""
    if aastocks_tor is not None and calculated_tor is not None:
        rel = abs(calculate_tor_difference_pct(calculated_tor, aastocks_tor) or 0.0)
        if rel <= formula_relative_tolerance_pct:
            return "formula_matches"
        return "volume_mismatch"

    if (
        share_base_difference_pct is not None
        and abs(share_base_difference_pct) > share_base_threshold_pct
    ):
        return "share_base_mismatch"

    if (
        legacy_implied_volume_difference_pct is not None
        and abs(legacy_implied_volume_difference_pct) > legacy_date_mismatch_threshold_pct
    ):
        return "date_mismatch_suspected"

    return "insufficient_data"


def summarize_optional(values: Iterable[Optional[float]]) -> dict[str, Optional[float]]:
    """Return mean and median for non-null values."""
    items = [value for value in values if value is not None]
    return {
        "mean": mean(items) if items else None,
        "median": median(items) if items else None,
    }
