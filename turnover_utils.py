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
TURNOVER_STATUS_SCALED = "SHARE_BASE_SCALED"

TUR_UPPER_BOUND_PCT = 10.0
TUR_LOWER_BOUND_PCT = 0.005
_AUTO_SCALE_FACTORS = (
    2.0, 2.5, 4.0, 5.0, 8.0, 10.0, 20.0, 25.0, 50.0, 100.0,
    0.5, 0.4, 0.25, 0.2, 0.125, 0.1, 0.05, 0.04, 0.02, 0.01,
)


def _auto_scale_share_base(vol_series: object, share_base: float) -> Tuple[float, Optional[float]]:
    if share_base <= 0:
        return share_base, None
    vols = pd.to_numeric(pd.Series(vol_series), errors="coerce").dropna()
    if vols.empty:
        return share_base, None
    p50 = float(np.nanpercentile(vols.values, 50))
    p75 = float(np.nanpercentile(vols.values, 75))
    vmax = float(np.nanmax(vols.values))
    if p75 <= 0 or vmax <= 0:
        return share_base, None

    def _tur_stats(base: float):
        return (
            p50 / base * 100.0,
            p75 / base * 100.0,
            vmax / base * 100.0,
        )

    med_o, p75_o, max_o = _tur_stats(share_base)
    lb = TUR_LOWER_BOUND_PCT
    ub = TUR_UPPER_BOUND_PCT
    if lb <= med_o <= ub and lb <= p75_o <= ub and lb <= max_o <= ub * 1.2:
        return share_base, None

    candidates = []
    for factor in _AUTO_SCALE_FACTORS:
        med, p75, mx = _tur_stats(share_base * factor)
        strong_ok = lb <= med <= ub and lb <= p75 <= ub and lb <= mx <= ub
        soft_ok = (lb * 0.4) <= med <= (ub * 1.5) and (lb * 0.4) <= p75 <= (ub * 1.5) and (lb * 0.4) <= mx <= (ub * 2.0)
        if strong_ok or soft_ok:
            candidates.append((0 if strong_ok else 1, abs(np.log(factor)), factor))
    if not candidates:
        return share_base, None
    candidates.sort()
    _, _, best_factor = candidates[0]
    return share_base * best_factor, float(best_factor)


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

    safe_high = high.values.copy() if isinstance(high, pd.Series) else np.asarray(high, dtype=float)
    safe_low = low.values.copy() if isinstance(low, pd.Series) else np.asarray(low, dtype=float)
    safe_high = np.asarray(safe_high, dtype=float)
    safe_low = np.asarray(safe_low, dtype=float)
    opn_v = np.asarray(opn, dtype=float)
    cls_v = np.asarray(close, dtype=float)

    def _bad_arr(arr: np.ndarray) -> np.ndarray:
        return (~np.isfinite(arr)) | (arr <= 0)

    h_bad_arr = _bad_arr(safe_high) if isinstance(safe_high, np.ndarray) else _bad(pd.Series(safe_high)).values
    l_bad_arr = _bad_arr(safe_low) if isinstance(safe_low, np.ndarray) else _bad(pd.Series(safe_low)).values

    need_ohlc_fallback = h_bad_arr | l_bad_arr
    safe_high = np.where(need_ohlc_fallback, np.fmax(opn_v, cls_v), safe_high)
    safe_low = np.where(need_ohlc_fallback, np.fmin(opn_v, cls_v), safe_low)

    valid_range = (~_bad_arr(safe_high)) & (~_bad_arr(safe_low))
    equal_high_low = valid_range & np.isfinite(safe_high) & np.isfinite(safe_low) & (np.abs(safe_high - safe_low) < 1e-9)
    swapped = valid_range & np.isfinite(safe_high) & np.isfinite(safe_low) & (safe_high < safe_low - 1e-9)

    span = np.nanmax(np.vstack([
        np.abs(cls_v - opn_v),
        safe_low * 0.0,
    ]), axis=0)
    min_span = np.fmax(span, np.fmax(safe_low * 0.001, 0.0005))

    safe_high = np.where(swapped, safe_low + min_span, safe_high)
    safe_low = np.where(swapped, safe_low, safe_low)

    need_final_fallback = (~np.isfinite(safe_high)) | (~np.isfinite(safe_low))
    safe_high = np.where(need_final_fallback, safe_low + min_span, safe_high)
    safe_low = np.where(need_final_fallback, safe_low, safe_low)

    prev_close = np.concatenate([[np.nan], cls_v[:-1]])
    prev_close = np.where((~np.isfinite(prev_close)) | (prev_close <= 0), np.nan, prev_close)

    amp_raw = (safe_high - safe_low) / prev_close * 100.0
    amp_raw = np.where(equal_high_low, 0.0, amp_raw)
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
    """Attach a Turnover_Rate column and return calculation status.

    Splits/mergers (e.g. 10合1) frequently leave Yahoo share-base metadata
    10x / 100x stale for weeks.  We auto-scale the denominator whenever the
    historical P75 TUR falls outside ``[TUR_LOWER_BOUND_PCT,
    TUR_UPPER_BOUND_PCT]`` and some ×10^k factor brings it back into the
    plausible AASTOCKS band.
    """
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

    sb_value = float(share_base)
    scaled_sb, factor = _auto_scale_share_base(result_df[volume_column], sb_value)
    if factor is not None:
        status = TURNOVER_STATUS_SCALED
        reason = (
            f"Yahoo share base auto-scaled ×{factor:g} to align TUR with the "
            f"AASTOCKS plausible band [{TUR_LOWER_BOUND_PCT}%, {TUR_UPPER_BOUND_PCT}%] "
            f"(HK 2/2.5/5/20/25合併拆股 Yahoo metadata 常延遲)."
        )
    else:
        scaled_sb = sb_value

    result_df["Turnover_Rate"] = (
        result_df[volume_column].astype(float) / scaled_sb * 100
    )
    return result_df, status, reason
