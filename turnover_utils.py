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


def _clean_series_for_num(s: object) -> pd.Series:
    if isinstance(s, pd.Series):
        return pd.to_numeric(s, errors="coerce").astype(float)
    arr = np.asarray(s, dtype=float)
    return pd.Series(np.where(np.isfinite(arr), arr, np.nan))


def compute_safe_amplitude(
    df: pd.DataFrame,
    *,
    open_col: str = "Open",
    high_col: str = "High",
    low_col: str = "Low",
    close_col: str = "Close",
) -> pd.Series:
    """Compute daily Amplitude (%) using defensive High/Low bounds.

    AASTOCKS defines 振幅 = (最高價 - 最低價) / 前收盤價 * 100.

    Data feeds often return corrupt High/Low for intraday rows:
      * High/Low = 0  (padding from incomplete OHLCV)
      * High/Low = NaN
      * High == Low  (single-tick snapshot)
      * High < Low   (swapped values / sort order errors)

    This helper applies progressive fallbacks so the output always matches
    the economically meaningful range of the day:
      1. raw  H/L from the input
      2. if H is bad, replace H = max(Open, Close)
      3. if L is bad, replace L = min(Open, Close)
      4. if H <= L after steps 2-3 (e.g. flat day): H_new = L + |Close - Open|
         or last-resort H = L * 1.001 to avoid 0 amplitude
    """
    index = df.index if isinstance(df, pd.DataFrame) else None
    close = pd.to_numeric(df[close_col], errors="coerce").astype(float)
    has_open = open_col in df.columns
    opn = pd.to_numeric(df[open_col], errors="coerce").astype(float) if has_open else close.copy()
    high = pd.to_numeric(df[high_col], errors="coerce").astype(float) if high_col in df.columns else pd.Series(np.nan, index=close.index)
    low = pd.to_numeric(df[low_col], errors="coerce").astype(float) if low_col in df.columns else pd.Series(np.nan, index=close.index)

    def _bad(series: pd.Series) -> pd.Series:
        return (~np.isfinite(series.values)) | (series.values <= 0)

    h_bad = _bad(high)
    l_bad = _bad(low)

    safe_high = high.values.copy()
    safe_low = low.values.copy()
    opn_v = opn.values
    cls_v = close.values
    safe_high = np.where(h_bad, np.fmax(opn_v, cls_v), safe_high)
    safe_low = np.where(l_bad, np.fmin(opn_v, cls_v), safe_low)

    span = np.nanmax(np.vstack([
        np.abs(cls_v - opn_v),
        (safe_high - safe_low) * 0.0,
    ]), axis=0)
    min_span = np.fmax(span, np.fmax(safe_low * 0.001, 0.0005))
    need_fix = (~np.isfinite(safe_high)) | (~np.isfinite(safe_low)) | (safe_high <= safe_low)
    safe_high = np.where(need_fix, safe_low + min_span, safe_high)
    safe_low = np.where(need_fix, safe_low, safe_low)

    prev_close = np.concatenate([[np.nan], cls_v[:-1]])
    prev_close = np.where((~np.isfinite(prev_close)) | (prev_close <= 0), np.nan, prev_close)

    amp_raw = (safe_high - safe_low) / prev_close * 100.0
    amp_raw = np.where(np.isfinite(amp_raw), amp_raw, np.nan)
    out_index = index if index is not None else close.index
    result = pd.Series(amp_raw, index=out_index)
    return result


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
