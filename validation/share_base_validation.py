"""Helpers for validating turnover share-base assumptions against benchmarks."""

from __future__ import annotations

from statistics import mean, median
from typing import Iterable, Optional


def calculate_absolute_difference(actual: Optional[float], expected: Optional[float]) -> Optional[float]:
    """Return the absolute difference between two values."""
    if actual is None or expected is None:
        return None
    return abs(actual - expected)


def calculate_percentage_difference(actual: Optional[float], expected: Optional[float]) -> Optional[float]:
    """Return absolute percentage difference using the benchmark as denominator."""
    if actual is None or expected in (None, 0):
        return None
    return abs(actual - expected) / abs(expected) * 100.0


def build_threshold_flags(pct_difference: Optional[float], thresholds: Iterable[float]) -> dict[str, bool]:
    """Build threshold flags such as 1%, 2%, and 5%."""
    values = {}
    for threshold in thresholds:
        label = f"above_{str(threshold).replace('.', '_')}pct"
        values[label] = pct_difference is not None and pct_difference > threshold
    return values


def calculate_error(value: Optional[float], benchmark: Optional[float]) -> Optional[float]:
    """Return signed error relative to benchmark."""
    if value is None or benchmark is None:
        return None
    return value - benchmark


def calculate_absolute_percentage_error(
    value: Optional[float], benchmark: Optional[float]
) -> Optional[float]:
    """Return absolute percentage error relative to benchmark."""
    if value is None or benchmark in (None, 0):
        return None
    return abs(value - benchmark) / abs(benchmark) * 100.0


def summarize_error_metrics(values: Iterable[Optional[float]], benchmarks: Iterable[Optional[float]]) -> dict[str, Optional[float]]:
    """Summarize signed and percentage errors for a series."""
    errors = []
    apes = []
    for value, benchmark in zip(values, benchmarks):
        error = calculate_error(value, benchmark)
        ape = calculate_absolute_percentage_error(value, benchmark)
        if error is not None:
            errors.append(error)
        if ape is not None:
            apes.append(ape)

    return {
        "mean_error": mean(errors) if errors else None,
        "median_error": median(errors) if errors else None,
        "mape": mean(apes) if apes else None,
        "median_ape": median(apes) if apes else None,
    }
