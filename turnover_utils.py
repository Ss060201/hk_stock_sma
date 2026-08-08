"""Shared turnover-rate helpers for app surfaces."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

TURNOVER_STATUS_CALCULATED = "CALCULATED"
TURNOVER_STATUS_MISSING_VOLUME = "MISSING_VOLUME"
TURNOVER_STATUS_MISSING_SHARE_BASE = "MISSING_SHARE_BASE"
TURNOVER_STATUS_INVALID_SHARE_BASE = "INVALID_SHARE_BASE"
TURNOVER_STATUS_CALCULATION_ERROR = "CALCULATION_ERROR"


def calculate_turnover_rate(
    volume: object,
    share_base: object,
) -> Optional[float]:
    """Calculate turnover rate from volume and share base."""
    try:
        if volume is None or pd.isna(volume):
            return None
        if share_base is None or pd.isna(share_base):
            return None
        share_base_value = float(share_base)
        if share_base_value <= 0:
            return None
        return float(volume) / share_base_value * 100.0
    except Exception:
        return None


def classify_turnover_status(
    volume: object,
    share_base: object,
) -> Tuple[str, Optional[str]]:
    """Classify why turnover is or is not available for a single observation."""
    if volume is None or pd.isna(volume):
        return TURNOVER_STATUS_MISSING_VOLUME, "No usable Volume is available."
    if share_base is None or pd.isna(share_base):
        return TURNOVER_STATUS_MISSING_SHARE_BASE, "No share base is available."
    try:
        share_base_value = float(share_base)
    except Exception:
        return TURNOVER_STATUS_INVALID_SHARE_BASE, "Share base is not numeric."
    if share_base_value <= 0:
        return TURNOVER_STATUS_INVALID_SHARE_BASE, "Share base must be greater than 0."
    return TURNOVER_STATUS_CALCULATED, None


def apply_turnover_rate(
    df: pd.DataFrame,
    share_base: object,
    *,
    volume_column: str = "Volume",
) -> Tuple[pd.DataFrame, str, Optional[str]]:
    """Attach a Turnover_Rate column and return calculation status."""
    result_df = df.copy()
    if volume_column not in result_df.columns:
        result_df["Turnover_Rate"] = np.nan
        return (
            result_df,
            TURNOVER_STATUS_MISSING_VOLUME,
            f"Column '{volume_column}' is not present.",
        )

    latest_volume = result_df[volume_column].iloc[-1] if len(result_df) else None
    status, reason = classify_turnover_status(latest_volume, share_base)
    if status != TURNOVER_STATUS_CALCULATED:
        result_df["Turnover_Rate"] = np.nan
        return result_df, status, reason

    result_df["Turnover_Rate"] = (
        result_df[volume_column].astype(float) / float(share_base) * 100
    )
    return result_df, TURNOVER_STATUS_CALCULATED, None
