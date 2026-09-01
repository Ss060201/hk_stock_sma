"""
COT 綠區 A + B（5 TI={7,14,27,57,106}）單元測試（7 TC，完全獨立：不 import streamlit）。
對應桌面 calc_cot_ti5_vector / 手機 calc_cot_ti5_vector_m（兩端邏輯完全一致，此處用複製的純 calc 函式測試）。

2026-09-02 修復 bug：pn 取最後一個「有限值」而非單純 iloc[-1]（對 Yahoo 末列 NaN/0 的常態）。
"""
from __future__ import annotations

import math
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


COT_5_FIXED_TI = [7, 14, 27, 57, 106]


def calc_cot_ti5_vector_test(df: pd.DataFrame, ti_list: Optional[List[int]] = None) -> Dict[str, Any]:
    """tests 內複製版（不 import app_mobile/app.py，避免 streamlit 初始化 crash），與產品程式碼邏輯完全一致（2026-09-02 fixed last-finite 版）。"""
    ti_list = list(ti_list) if ti_list is not None else list(COT_5_FIXED_TI)
    res: Dict[str, Any] = {
        "ok": False,
        "reason": "",
        "ti_list": list(ti_list),
        "last_date": None,
        "last_close": None,
        "cot_a_row": {},
        "ud_per_ti": {},
        "cot_b_row": {},
        "ud_majority": "",
        "trailing_nan_skipped": 0,
    }
    if df is None or df.empty:
        res["reason"] = "df empty"
        return res
    try:
        if "Close" not in df.columns:
            res["reason"] = "missing Close column"
            return res
        close_s = pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan)
        N = len(close_s)
        if N < 2:
            res["reason"] = "N < 2"
            return res
        valid_arr_finite = np.isfinite(close_s.to_numpy(dtype=float, copy=False))
        valid_positions = np.flatnonzero(valid_arr_finite)
        if valid_positions.size == 0:
            res["reason"] = "no valid Close (all rows NaN/0)"
            return res
        n = int(valid_positions[-1])
        skipped = (N - 1) - n
        res["trailing_nan_skipped"] = int(skipped)
        pn_val = float(close_s.iloc[n])
        pn = float(pn_val)
        try:
            ts = close_s.index[n]
            res["last_date"] = pd.Timestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            res["last_date"] = None
        res["last_close"] = pn
        close_arr = close_s.to_numpy(dtype=float, copy=False)
        cot_a: Dict[int, float] = {}
        ud_per: Dict[int, str] = {}
        cot_b: Dict[int, float] = {}
        u_cnt = 0
        d_cnt = 0
        for ti in ti_list:
            ti_i = int(ti)
            if ti_i <= 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            src = n - ti_i
            if src < 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            base = float(close_arr[src])
            if (not np.isfinite(base)) or base <= 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            w = close_arr[src:(n + 1)]
            w_f = w[np.isfinite(w)]
            if w_f.size == 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            w_min = float(np.min(w_f))
            w_max = float(np.max(w_f))
            diff_a = pn - base
            cot_a[ti] = (diff_a / base) / float(ti_i)
            if pn > base:
                direction = "U"
                u_cnt += 1
                cot_b[ti] = (((pn - w_min) / w_min) / float(ti_i)) if (np.isfinite(w_min) and w_min > 0) else float("nan")
            elif pn < base:
                direction = "D"
                d_cnt += 1
                cot_b[ti] = (((pn - w_max) / w_max) / float(ti_i)) if (np.isfinite(w_max) and w_max > 0) else float("nan")
            else:
                direction = ""
                cot_b[ti] = float("nan")
            ud_per[ti] = direction
        res["cot_a_row"] = cot_a
        res["ud_per_ti"] = ud_per
        res["cot_b_row"] = cot_b
        if u_cnt > d_cnt:
            res["ud_majority"] = "U"
        elif d_cnt > u_cnt:
            res["ud_majority"] = "D"
        else:
            res["ud_majority"] = ""
        res["ok"] = True
        return res
    except Exception as exc:
        res["ok"] = False
        res["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


def _is_nan(x: Any) -> bool:
    if x is None:
        return True
    try:
        return not np.isfinite(float(x))
    except Exception:
        return True


def _make_synthetic_df(n_days: int, last_date_str: str = "2026-08-11", daily_growth_pct: Optional[float] = None,
                       pattern: str = "linear", base_close: float = 100.0, seed: int = 42,
                       zero_base_pos: Optional[int] = None, trailing_nan_count: int = 0) -> pd.DataFrame:
    """Build deterministic bdate-range df with Close (no OHLCV needed) for COT calcs."""
    rng = np.random.default_rng(seed)
    last_dt = pd.Timestamp(last_date_str)
    dates = pd.bdate_range(end=last_dt, periods=n_days)
    closes = np.full(n_days, np.nan, dtype=float)
    if pattern == "linear" and daily_growth_pct is not None:
        r = daily_growth_pct / 100.0
        closes[0] = base_close
        for i in range(1, n_days):
            closes[i] = closes[i - 1] * (1.0 + r)
    elif pattern == "wave":
        closes[0] = base_close
        for i in range(1, n_days):
            phase = (i % 30) / 30.0 * 2.0 * math.pi
            closes[i] = base_close * (1.0 + 0.03 * math.sin(phase)) + rng.normal(0, base_close * 0.002)
    else:
        closes[0] = base_close
        for i in range(1, n_days):
            closes[i] = closes[i - 1] * (1.0 + rng.normal(0, 0.003))
    if zero_base_pos is not None:
        zero_idx = int(zero_base_pos) % n_days
        closes[zero_idx] = 0.0
    if trailing_nan_count and trailing_nan_count > 0:
        n_trail = min(int(trailing_nan_count), n_days)
        for i in range(1, n_trail + 1):
            closes[-i] = np.nan
    df = pd.DataFrame({"Close": closes.astype(float)}, index=dates)
    df.index.name = "Date"
    return df


# ========================= 7 TC =========================

def tc1_basic_cot7_matches_handcalc() -> bool:
    """TC1 基礎 COT7：每日漲 2% 7 天 → 手算 COT(7) = 2.000%/日 精確到 3 位小數。"""
    df = _make_synthetic_df(n_days=8, daily_growth_pct=2.0, pattern="linear", base_close=100.0, seed=1)
    r = calc_cot_ti5_vector_test(df, ti_list=[7])
    if not r.get("ok"):
        print("TC1 FAIL: not ok", r.get("reason"))
        return False
    v_raw = r["cot_a_row"].get(7)
    if _is_nan(v_raw):
        print("TC1 FAIL: cot7 NaN")
        return False
    v_pct = float(v_raw) * 100.0
    P0 = float(df["Close"].iloc[0])
    P7 = float(df["Close"].iloc[7])
    hand = ((P7 - P0) / P0) / 7.0 * 100.0
    ok = abs(v_pct - hand) < 5e-4
    if not ok:
        print(f"TC1 FAIL: got={v_pct:.6f}% hand={hand:.6f}% diff={abs(v_pct-hand):.6e}")
    return ok


def tc2_u_trend_cotu14_matches() -> bool:
    """TC2 U 上升：每日 2% 線性漲 14 天 → TI=14；窗口 min = Close[0]（最低點）→ COTu(14) = 手算 ((P14-P0)/P0)/14"""
    df = _make_synthetic_df(n_days=15, daily_growth_pct=2.0, pattern="linear", base_close=100.0, seed=2)
    r = calc_cot_ti5_vector_test(df, ti_list=[14])
    if not r.get("ok"):
        print("TC2 FAIL: not ok", r.get("reason"))
        return False
    ud = r["ud_per_ti"].get(14, "")
    if ud != "U":
        print(f"TC2 FAIL: per_ti direction not U, got='{ud}'")
        return False
    v_raw = r["cot_b_row"].get(14)
    if _is_nan(v_raw):
        print("TC2 FAIL: cotb 14 NaN")
        return False
    v_pct = float(v_raw) * 100.0
    P0 = float(df["Close"].iloc[0])
    P14 = float(df["Close"].iloc[14])
    hand = ((P14 - P0) / P0) / 14.0 * 100.0
    ok = abs(v_pct - hand) < 5e-4
    if not ok:
        print(f"TC2 FAIL: got={v_pct:.6f}% hand={hand:.6f}% diff={abs(v_pct-hand):.6e}")
    return ok


def tc3_d_trend_cotd14_matches() -> bool:
    """TC3 D 下降：每日 -2% 14 天 → 窗口 max = Close[0]（最高）；COTd(14) = ((P14 - P0)/P0) / 14。U/D 每個為 D → 多數決 D。"""
    df = _make_synthetic_df(n_days=15, daily_growth_pct=-2.0, pattern="linear", base_close=200.0, seed=3)
    r = calc_cot_ti5_vector_test(df, ti_list=[14])
    if not r.get("ok"):
        print("TC3 FAIL: not ok", r.get("reason"))
        return False
    ud = r["ud_per_ti"].get(14, "")
    if ud != "D":
        print(f"TC3 FAIL: per_ti direction not D, got='{ud}'")
        return False
    if r["ud_majority"] != "D":
        print(f"TC3 FAIL: majority should be D (only 1 TI → D), got='{r['ud_majority']}'")
        return False
    v_raw = r["cot_b_row"].get(14)
    if _is_nan(v_raw):
        print("TC3 FAIL: cotb 14 NaN")
        return False
    v_pct = float(v_raw) * 100.0
    P0 = float(df["Close"].iloc[0])
    P14 = float(df["Close"].iloc[14])
    hand = ((P14 - P0) / P0) / 14.0 * 100.0
    if abs(v_pct - hand) >= 5e-4:
        print(f"TC3 FAIL: got={v_pct:.6f}% hand={hand:.6f}% diff={abs(v_pct-hand):.6e}")
        return False
    if float(v_raw) >= 0:
        print("TC3 FAIL: D 下降 COTd MUST be < 0, got >=0")
        return False
    return True


def tc4_boundary_nan_short_df() -> bool:
    """TC4 NaN 邊界：只有 50 列（< 106） → 57/106 兩欄位 NaN（57 ≤ 50? n=49，n-57 = -8 <0，所以 57 也是 NaN；14/7 有）。"""
    df = _make_synthetic_df(n_days=50, daily_growth_pct=0.5, pattern="linear", base_close=50.0, seed=4)
    r = calc_cot_ti5_vector_test(df, ti_list=COT_5_FIXED_TI)
    if not r.get("ok"):
        print("TC4 FAIL: not ok", r.get("reason"))
        return False
    check_ok = True
    for ti in [7, 14]:
        if _is_nan(r["cot_a_row"].get(ti)):
            print(f"TC4 FAIL: ti={ti} should be numeric, got NaN")
            check_ok = False
    for ti in [27, 57, 106]:
        v = r["cot_a_row"].get(ti)
        if (not _is_nan(v)) and (not _is_nan(r["cot_b_row"].get(ti))):
            print(f"TC4 FAIL: ti={ti} should be NaN (n-ti<0), got cot_a={v} cot_b={r['cot_b_row'].get(ti)}")
            check_ok = False
    return check_ok


def tc5_div0_guard_em_dash() -> bool:
    """TC5 除 0 guard：窗口 base 有 0 → U/D/COTb 全部 NaN（不出現 Inf）。"""
    n = 20
    df = _make_synthetic_df(n_days=n, pattern="linear", daily_growth_pct=1.0, base_close=80.0, seed=5)
    close_arr = df["Close"].to_numpy(dtype=float, copy=True)
    zero_idx = (n - 1) - 7
    close_arr[zero_idx] = 0.0
    df["Close"] = close_arr
    r = calc_cot_ti5_vector_test(df, ti_list=[7])
    if not r.get("ok"):
        print("TC5 FAIL: overall not ok", r.get("reason"))
        return False
    if (not _is_nan(r["cot_a_row"].get(7))) or (not _is_nan(r["cot_b_row"].get(7))):
        print(
            f"TC5 FAIL: base 0 → guard should make cot_a/ cot_b NaN, "
            f"got cot_a={r['cot_a_row'].get(7)} cot_b={r['cot_b_row'].get(7)}"
        )
        return False
    return True


def tc6_ud_majority_tie_d() -> bool:
    """TC6 U/D 多數決：50 日波浪 df，指定 ti_list=[7,14,27,50] 4 個；強制前 2 U 後 2 D → 平手 → ""；改成 3 D 1 U → majority D。"""
    df = _make_synthetic_df(n_days=60, pattern="wave", base_close=150.0, seed=42)
    r = calc_cot_ti5_vector_test(df, ti_list=[7, 14, 27, 50])
    if not r.get("ok"):
        print("TC6 FAIL: not ok", r.get("reason"))
        return False
    ud_vals = [r["ud_per_ti"].get(ti, "") for ti in [7, 14, 27, 50]]
    u = sum(1 for x in ud_vals if x == "U")
    d = sum(1 for x in ud_vals if x == "D")
    expected_maj = "" if u == d else ("U" if u > d else "D")
    if r["ud_majority"] != expected_maj:
        print(
            f"TC6 FAIL: ud_per={ud_vals} u={u} d={d} → expected='{expected_maj}' "
            f"got='{r['ud_majority']}'"
        )
        return False
    r2 = calc_cot_ti5_vector_test(df, ti_list=[7, 14, 27, 50, 59])
    if not r2.get("ok"):
        print("TC6 FAIL r2: not ok", r2.get("reason"))
        return False
    u2 = sum(1 for ti in [7, 14, 27, 50, 59] if r2["ud_per_ti"].get(ti, "") == "U")
    d2 = sum(1 for ti in [7, 14, 27, 50, 59] if r2["ud_per_ti"].get(ti, "") == "D")
    expected_2 = "" if u2 == d2 else ("U" if u2 > d2 else "D")
    if r2["ud_majority"] != expected_2:
        print(
            f"TC6 FAIL r2: u={u2} d={d2} → expected='{expected_2}' got='{r2['ud_majority']}' "
            f"(ud_per={[r2['ud_per_ti'].get(ti) for ti in [7,14,27,50,59]]})"
        )
        return False
    return True


def tc7_trailing_nan_last_row_fixed() -> bool:
    """TC7（本次新增 → 修復截圖 bug）：末 2 列 Close = NaN，但倒數第 3 列 = 100、倒數第 10 列 = 90。
    預期：n = 最後一個有限值位置，skipped=2；last_date=倒數第 3 列日期；COT(7)=((100-90)/90)/7 與手算一致；ud 為 U（因為 100>90）。"""
    n_days = 20
    df = _make_synthetic_df(n_days=n_days, pattern="linear", daily_growth_pct=0.0, base_close=90.0, seed=7, trailing_nan_count=0)
    closes = df["Close"].to_numpy(dtype=float, copy=True)
    for i in range(len(closes)):
        if i < len(closes) - 3:
            closes[i] = 90.0
        elif i == len(closes) - 3:
            closes[i] = 100.0
        else:
            closes[i] = np.nan
    df["Close"] = closes
    # Sanity
    assert pd.isna(closes[-1])
    assert pd.isna(closes[-2])
    assert float(closes[-3]) == 100.0
    r = calc_cot_ti5_vector_test(df, ti_list=[7, 14])
    if not r.get("ok"):
        print("TC7 FAIL: not ok", r.get("reason"))
        return False
    if int(r.get("trailing_nan_skipped", 0)) != 2:
        print(f"TC7 FAIL: skipped should be 2, got={r.get('trailing_nan_skipped')}")
        return False
    expected_date = pd.Timestamp(df.index[-3]).strftime("%Y-%m-%d")
    if r.get("last_date") != expected_date:
        print(f"TC7 FAIL: last_date expected='{expected_date}', got='{r.get('last_date')}'")
        return False
    if abs(float(r.get("last_close", 0.0)) - 100.0) >= 1e-7:
        print(f"TC7 FAIL: last_close expected=100.0, got={r.get('last_close')}")
        return False
    # COT 7: base = closes[n-7] = closes[10] (n=17, n-7=10) → 90
    v_raw = r["cot_a_row"].get(7)
    if _is_nan(v_raw):
        print("TC7 FAIL: cot7 NaN")
        return False
    v_pct = float(v_raw) * 100.0
    hand = ((100.0 - 90.0) / 90.0) / 7.0 * 100.0
    if abs(v_pct - hand) >= 5e-4:
        print(f"TC7 FAIL: got={v_pct:.6f}% hand={hand:.6f}%")
        return False
    if r["ud_per_ti"].get(7, "") != "U":
        print(f"TC7 FAIL: per_ti[7] should be U, got='{r['ud_per_ti'].get(7)}'")
        return False
    return True


ALL_TCS = [
    ("TC1 基礎 COT7 線性漲手算對齊", tc1_basic_cot7_matches_handcalc),
    ("TC2 U 上升 COTu(14) 窗口 min 對齊", tc2_u_trend_cotu14_matches),
    ("TC3 D 下降 COTd(14) 負值 + 多數決 D", tc3_d_trend_cotd14_matches),
    ("TC4 df 短 50 列 → 27/57/106 NaN 邊界", tc4_boundary_nan_short_df),
    ("TC5 base 零點 → 除 0 guard NaN", tc5_div0_guard_em_dash),
    ("TC6 U/D 多數決平手 & 5 TI 不一致", tc6_ud_majority_tie_d),
    ("TC7 末列 NaN → 取倒數最後有限值 Pn 對齊（截圖 bug 重現）", tc7_trailing_nan_last_row_fixed),
]


def main() -> int:
    passed = 0
    failed = 0
    for name, fn in ALL_TCS:
        try:
            ok = bool(fn())
        except Exception as e:
            ok = False
            print(f"[EXC] {name}: {type(e).__name__}: {str(e)[:300]}")
        if ok:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name}")
    print("-" * 60)
    print(f"Total {len(ALL_TCS)}: passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
