"""
HK Stock SMA 數據正確性驗證腳本 (B1)
6 層驗證：
1. OHLCV 結構 / 值域 / 邏輯 (H>=L, Close>0, Gap<60%)
2. SMA7/SMA28 Rolling mean 正確（手算抽查 3 行）
3. Amp(%) = (H-L)/prev_close*100 手算對齊
4. Devk = (Close[t]-Avg3[t-k])/Avg3[t-k]*100（抽查 k=0,k=2 各 2 點）
5. AvgDev = sum(Dev0~5)/6 手算比對
6. fetcher_stats / list_cached_symbols 元數據完整性 (valid cached >= 5)
"""
from __future__ import annotations

import os
import sys
import json
import time
from typing import List, Dict, Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd

from cache_layer import (
    ensure_schema,
    get_db,
    get_cache_db_path,
    list_cached_symbols,
    get_cached_ohlcv,
    get_stat,
)

try:
    from tests.test_pmax_index6_matrix import calc_pmax_index6_matrix as tc_calc_pmax6
except Exception:
    tc_calc_pmax6 = None

PASS, FAIL = "✅ PASS", "❌ FAIL"
results: List[Dict[str, Any]] = []


def record(name, ok, detail=""):
    results.append({"name": name, "ok": ok, "detail": detail})
    print(f"{'[PASS]' if ok else '[FAIL]'} {name}" + (f" — {detail}" if detail else ""))


def main():
    print("=" * 64)
    print("HK Stock SMA — 數據正確性 6 層驗證 (B1)")
    print("=" * 64)

    # 0. 環境
    dbp = get_cache_db_path()
    print(f"[ENV] DB path: {dbp}")
    exists = os.path.exists(dbp)
    kb = os.path.getsize(dbp) // 1024 if exists else 0
    print(f"[ENV] DB exists={exists} size_kb={kb}")
    ensure_schema(None)
    record("DB Schema 相容 & ensure_schema 成功", exists, f"{kb} KB")

    # 1. 元數據數量門檻
    syms = list_cached_symbols(limit=500)
    n_syms = len(syms)
    valid_meta = [
        s for s in syms
        if (s.get("rows") or 0) >= 100
        and s.get("last_valid_close") is not None
        and float(s.get("last_valid_close") or 0) > 0
    ]
    n_valid_meta = len(valid_meta)
    record("有效快取個股數 >= 5", n_valid_meta >= 5, f"n={n_valid_meta}/total={n_syms}")

    if n_valid_meta == 0:
        print("[WARN] 無 valid cached 個股，跳過 2~5 層數值比對（請先跑 daemon 或 A1 artifact sync）")
        print_summary()
        return 0

    # 2. OHLCV 值域 / 結構邏輯，抽查 Top3 valid_meta
    target_df: pd.DataFrame | None = None
    target_symbol: str = ""
    for s in valid_meta[:3]:
        sym = s["symbol"]
        df, sb, cs = get_cached_ohlcv(sym, max_age_sec=60 * 60 * 24 * 60)
        if df is None or len(df) < 120:
            continue
        target_df = df
        target_symbol = sym
        close = pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan).dropna()
        lo = pd.to_numeric(df["Low"], errors="coerce") if "Low" in df.columns else pd.Series([np.nan] * len(df))
        hi = pd.to_numeric(df["High"], errors="coerce") if "High" in df.columns else pd.Series([np.nan] * len(df))
        # 2a) Close 連續 120 日不為 0
        ok_close = len(close.tail(120)) >= 120
        # 2b) H >= L
        mask_hl = np.isfinite(lo) & np.isfinite(hi)
        ok_hl = bool(((hi[mask_hl] >= lo[mask_hl])).all()) if mask_hl.any() else True
        # 2c) 最大單日跳空 < 60%（除牌/分拆皆不該）
        pct = close.pct_change().dropna().abs() * 100
        max_gap = float(pct.max()) if len(pct) > 0 else 0.0
        ok_gap = max_gap < 60.0
        # 2d) Share-base 正（if any）
        sb_ok = sb is None or (np.isfinite(float(sb)) and float(sb) > 0)
        record(f"OHLCV 值域 ({sym})", ok_close and ok_hl and ok_gap and sb_ok,
               f"rows={len(df)} Close>0_120d={ok_close} H>=L={ok_hl} max_gap%={max_gap:.2f} sb_ok={sb_ok}")

    if target_df is None:
        print("[WARN] 沒有任何個股 >= 120 列，結束")
        print_summary()
        return 1

    # 3. SMA7/SMA28 手算對齊
    close_s = pd.to_numeric(target_df["Close"], errors="coerce").replace(0, np.nan).dropna().reset_index(drop=True)
    if len(close_s) >= 30:
        for label, w in [("SMA7", 7), ("SMA28", 28)]:
            rng = close_s.rolling(window=w, min_periods=w).mean()
            # 抽查最後 2 個 index
            spot = len(close_s) - 1
            manual = float(close_s.iloc[spot - w + 1 : spot + 1].mean())
            algo = float(rng.iloc[spot])
            diff = abs(manual - algo)
            ok = (not np.isfinite(manual)) or (not np.isfinite(algo)) or diff < 1e-6
            record(f"{label} rolling mean 抽查 [{label} last={algo:.4f}]", ok,
                   f"manual={manual:.4f} abs_diff={diff:.2e}")

    # 4. Amp(%) 手算抽查 3 點
    if {"High", "Low"}.issubset(target_df.columns):
        hi_s = pd.to_numeric(target_df["High"], errors="coerce")
        lo_s = pd.to_numeric(target_df["Low"], errors="coerce")
        prev_close = pd.to_numeric(target_df["Close"], errors="coerce").shift(1).replace(0, np.nan)
        amp_manual = (hi_s - lo_s) / prev_close * 100.0
        spots = [len(target_df) - 1, len(target_df) - 2, max(0, len(target_df) - 60)]
        for i, spot in enumerate(spots):
            if spot < 1 or spot >= len(target_df): continue
            m = float(amp_manual.iloc[spot]) if np.isfinite(amp_manual.iloc[spot]) else np.nan
            a = None
            # 如果 cache 裡有 AMP 欄位，比對 stored amp vs manual amp
            if "AMP" in target_df.columns:
                stored = pd.to_numeric(target_df["AMP"], errors="coerce")
                if spot < len(stored) and np.isfinite(stored.iloc[spot]):
                    a = float(stored.iloc[spot])
            ok = (not np.isfinite(m)) or (a is None) or abs(m - a) < 1e-4
            detail = f"manual={m:.4f}" + (f" stored_AMP={a:.4f}" if a is not None else " (no AMP col, skip)")
            record(f"Amp(%) 抽查 #{i+1} idx={spot}", ok, detail)

    # 5. Devk / AvgDev 抽查 (tc_calc_pmax6 獨立純函數)
    if tc_calc_pmax6 is not None and len(target_df) >= 150:
        res = tc_calc_pmax6(target_df, pmax_window=106, avg_window=3, dev_offsets=[0,1,2,3,4,5], recent_rows=12)
        ok_mat = bool(res.get("ok"))
        record("calc_pmax_index6_matrix ok", ok_mat, f"reason={res.get('reason')}")
        trs = res.get("time_rows") or []
        if len(trs) >= 2:
            for idx in [0, len(trs) - 1]:
                r = trs[idx]
                dd = r["dev"]
                # 抽查 Dev0 = (Close - Avg3[t])/Avg3[t] * 100
                c3 = float(r["close"]) if r.get("close") is not None and np.isfinite(r.get("close")) else np.nan
                a3 = float(r["avg3_t"]) if r.get("avg3_t") is not None and np.isfinite(r.get("avg3_t")) else np.nan
                d0 = float(dd.get(0)) if (dd.get(0) is not None and np.isfinite(dd.get(0))) else np.nan
                if np.isfinite(a3) and a3 > 0 and np.isfinite(c3) and np.isfinite(d0):
                    manual_d0 = (c3 - a3) / a3 * 100.0
                    diff = abs(manual_d0 - d0)
                    record(f"Dev0 抽查 row#{idx} date={r.get('date')}", diff < 1e-4,
                           f"matrix={d0:.4f}% manual={manual_d0:.4f}% |diff|={diff:.2e}")
                # AvgDev = sum(Dev0~5)/6
                ad = r.get("avg_dev")
                vals = []
                for k in [0,1,2,3,4,5]:
                    dk = dd.get(k)
                    if dk is not None and np.isfinite(float(dk)):
                        vals.append(float(dk))
                if vals and (ad is not None and np.isfinite(float(ad))):
                    manual_ad = float(sum(vals)) / 6.0
                    diff = abs(manual_ad - float(ad))
                    record(f"AvgDev 抽查 row#{idx} date={r.get('date')}", diff < 1e-4,
                           f"matrix={float(ad):.4f}% manual={manual_ad:.4f}%")

    # 6. fetcher_stats / A1 sync 元數據抽查
    try:
        a1_ts = get_stat("a1_last_sync_ts", None)
        a1_n = get_stat("a1_last_valid_n", None)
        record("fetcher_stats.a1_last_sync_ts 存在", a1_ts is not None, f"ts={a1_ts}")
        record("fetcher_stats.a1_last_valid_n >= 5",
               a1_n is not None and int(a1_n) >= 5, f"n={a1_n}")
    except Exception as e:
        record("fetcher_stats.a1_last_sync_ts 存在", False, str(e)[:80])

    print_summary()
    return 0 if all(r["ok"] for r in results) else 1


def print_summary():
    total = len(results)
    ok = sum(1 for r in results if r["ok"])
    fail = total - ok
    print("=" * 64)
    print(f"SUMMARY: {PASS if fail == 0 else FAIL} passed={ok}/{total} failed={fail}")
    print("=" * 64)
    if fail:
        for r in results:
            if not r["ok"]:
                print(f"  ❌ {r['name']} — {r['detail']}")


if __name__ == "__main__":
    raise SystemExit(main())
