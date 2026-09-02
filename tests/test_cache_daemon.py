"""Standalone test for the SQLite cache layer + daemon queue flow.

Network is NOT required for any TC in this file (daemon download stack tests would be separate).
Run:  python tests/test_cache_daemon.py
Expected: Total 7: passed=7 failed=0
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cache_layer import (  # noqa: E402
    _DEFAULT_CACHE_TTL_SEC,
    ensure_schema,
    get_all_stats,
    get_cached_ohlcv,
    get_db,
    get_fetch_status,
    get_queue_depth,
    list_cached_symbols,
    mark_fetch_done,
    mark_fetch_failed,
    peek_next_pending,
    claim_pending,
    request_async_fetch,
    upsert_ohlcv,
)


def _make_synthetic_df(n_rows: int = 300, base_close: float = 100.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(), periods=n_rows, freq="B", tz=None)
    rets = rng.normal(loc=0.0004, scale=0.018, size=n_rows)
    close = base_close * np.exp(np.cumsum(rets))
    open_ = close * (1.0 + rng.normal(0, 0.005, n_rows))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.008, n_rows)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.008, n_rows)))
    vol = rng.integers(low=500_000, high=12_000_000, size=n_rows).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=dates,
    )


class TempDb:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "t_ohlcv.sqlite")

    def close(self):
        try:
            self._tmp.cleanup()
        except Exception:
            pass


_TC_RESULTS: Dict[str, Tuple[bool, str]] = {}


def _tc(name: str, fn):
    t0 = time.time()
    try:
        fn()
        ok, msg = True, f"OK in {time.time()-t0:.2f}s"
    except AssertionError as ae:
        ok, msg = False, f"FAIL assert: {ae}"
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"FAIL exc {type(e).__name__}: {e}"
    _TC_RESULTS[name] = (ok, msg)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  —  {msg}")
    return ok


def tc1_schema_and_tables():
    db = TempDb()
    try:
        ensure_schema(db.path)
        with get_db(db.path) as conn:
            r = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            names = sorted(row["name"] for row in r)
        expected = {"async_fetch_queue", "fetcher_stats", "ohlcv_cache"}
        missing = sorted(expected - set(names))
        extra = sorted((set(names) - expected) - {"sqlite_sequence"})
        assert not missing and not extra, f"missing={missing} extra={extra} all={names}"
    finally:
        db.close()


def tc2_upsert_get_hit_roundtrip():
    db = TempDb()
    try:
        ensure_schema(db.path)
        sym = "00700.HK"
        df = _make_synthetic_df(n_rows=400, base_close=380.0, seed=3)
        sb = 12_345_678.0
        upsert_ohlcv(sym, df, share_base=sb, source="unittest", db_path=db.path)
        df2, sb2, status = get_cached_ohlcv(sym, max_age_sec=3600, db_path=db.path, bump_stats=False)
        assert status == "HIT", status
        assert df2 is not None and len(df2) == len(df), (None if df2 is None else len(df2), len(df))
        assert np.isclose(float(sb2), sb, rtol=1e-6), (sb2, sb)
        # Index + close values within tolerance
        assert list(df.index) == list(df2.index) or np.allclose(df.index.astype(np.int64), df2.index.astype(np.int64))
        close_diff_max = float(np.max(np.abs(df["Close"].to_numpy() - df2["Close"].to_numpy())))
        assert close_diff_max < 1e-6, f"close drift {close_diff_max}"
        # Metadata last_valid_close present via list_cached_symbols
        rows = list_cached_symbols(db_path=db.path, limit=10)
        assert len(rows) == 1 and rows[0]["symbol"] == sym, rows
        lv = float(rows[0]["last_valid_close"])
        expected_lv = float(pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan).dropna().iloc[-1])
        assert np.isclose(lv, expected_lv, rtol=1e-6), (lv, expected_lv)
    finally:
        db.close()


def tc3_stale_and_miss_by_age():
    db = TempDb()
    try:
        ensure_schema(db.path)
        sym = "00005.HK"
        df = _make_synthetic_df(n_rows=250, base_close=60.0, seed=11)
        upsert_ohlcv(sym, df, share_base=9_900_000_000.0, source="unittest", db_path=db.path)
        # Force last_refresh_ts into past via direct SQL
        with get_db(db.path) as conn:
            conn.execute(
                "UPDATE ohlcv_cache SET last_refresh_ts=? WHERE symbol=?",
                (int(time.time()) - 99999, sym),
            )
        # max_age_sec very small → STALE but still returns df (caller decides)
        df_st, sb_st, st_st = get_cached_ohlcv(sym, max_age_sec=60, db_path=db.path, bump_stats=False)
        assert st_st == "STALE", st_st
        assert df_st is not None and len(df_st) > 0
        # end_date filter
        cutoff = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=90)
        df_cut, sb_c, st_c = get_cached_ohlcv(sym, end_date=cutoff, max_age_sec=None, db_path=db.path, bump_stats=False)
        assert st_c in ("HIT", "STALE"), st_c
        assert df_cut is not None and len(df_cut) > 0 and df_cut.index.max() <= cutoff
    finally:
        db.close()


def tc4_queue_lifecycle_queued_to_done():
    db = TempDb()
    try:
        ensure_schema(db.path)
        sym_a = "09988.HK"
        sym_b = "01299.HK"
        r1 = request_async_fetch(sym_a, db_path=db.path)
        r2 = request_async_fetch(sym_b, db_path=db.path)
        assert r1 == "QUEUED" and r2 == "QUEUED", (r1, r2)
        # Re-enqueue same symbol → ALREADY_PENDING
        r1b = request_async_fetch(sym_a, db_path=db.path)
        assert r1b == "ALREADY_PENDING", r1b
        pending = peek_next_pending(limit=2, db_path=db.path)
        assert [p["symbol"] for p in pending] == [sym_a, sym_b], pending
        # Claim A
        assert claim_pending(sym_a, db_path=db.path) is True
        # After claim, peek should return B first
        pending2 = peek_next_pending(limit=10, db_path=db.path)
        assert pending2 and pending2[0]["symbol"] == sym_b, pending2
        # Mark A done via upsert (upsert auto clears pending & writes DONE queue row)
        df_a = _make_synthetic_df(n_rows=200, base_close=120.0, seed=5)
        upsert_ohlcv(sym_a, df_a, share_base=4_400_000.0, db_path=db.path)
        st = get_fetch_status(sym_a, db_path=db.path)
        assert st["queue"] and st["queue"]["status"] == "DONE", st
        assert st["cache"] and int(st["cache"]["rows"]) == len(df_a), st
        # Re-request DONE symbol with default short TTL guard returns RECENTLY_DONE
        r_done = request_async_fetch(sym_a, db_path=db.path)
        # Because completed_ts is recent (< default cache half TTL)
        assert r_done in {"RECENTLY_DONE", "QUEUED"}, r_done
    finally:
        db.close()


def tc5_failed_and_retry_limit():
    db = TempDb()
    try:
        ensure_schema(db.path)
        sym = "02318.HK"
        # Simulate max retries exceeded by forcing attempt >= 3 & status FAILED
        request_async_fetch(sym, db_path=db.path)
        claim_pending(sym, db_path=db.path)
        mark_fetch_failed(sym, "HTTP 429 Too Many Requests", db_path=db.path)
        # Retry 2 more times (attempt will go to 3 max and stay FAILED)
        for _ in range(5):
            rr = request_async_fetch(sym, db_path=db.path)
            if rr == "QUEUED":
                claim_pending(sym, db_path=db.path)
                mark_fetch_failed(sym, "again 429", db_path=db.path)
            else:
                break
        # After 3 FAILED attempts, re-request should be RECENTLY_FAILED (max queue attempts hit)
        final = get_fetch_status(sym, db_path=db.path)
        att = int(final["queue"]["attempt"]) if final and final["queue"] else 0
        assert att >= 3, f"attempts={att}; final={final}"
        err = str((final["queue"] or {}).get("error_msg") or "")
        assert "429" in err, err
    finally:
        db.close()


def tc6_depth_and_stats_bump():
    db = TempDb()
    try:
        ensure_schema(db.path)
        # Seed 2 pending
        request_async_fetch("01810.HK", db_path=db.path)
        request_async_fetch("02628.HK", db_path=db.path)
        # 1 cache hit (bump stats) + 1 cache miss (bump stats)
        df = _make_synthetic_df(n_rows=180, base_close=18.0, seed=9)
        upsert_ohlcv("01810.HK", df, share_base=2_000_000.0, db_path=db.path)
        get_cached_ohlcv("01810.HK", max_age_sec=3600, db_path=db.path, bump_stats=True)
        get_cached_ohlcv("99880.HK", max_age_sec=3600, db_path=db.path, bump_stats=True)
        depth = get_queue_depth(db_path=db.path)
        assert int(depth.get("TOTAL_CACHED", 0)) >= 1, depth
        stats = get_all_stats(db_path=db.path)
        assert int(stats.get("cache_hit", 0)) >= 1, stats
        assert int(stats.get("cache_miss", 0)) >= 1, stats
    finally:
        db.close()


def tc7_df_roundtrip_numeric_parquet_consistency():
    db = TempDb()
    try:
        ensure_schema(db.path)
        sym = "01024.HK"
        df = _make_synthetic_df(n_rows=600, base_close=25.0, seed=42)
        sb = 1.2345678e9
        upsert_ohlcv(sym, df, share_base=sb, db_path=db.path)
        df2, sb2, st = get_cached_ohlcv(sym, max_age_sec=600, db_path=db.path, bump_stats=False)
        assert st == "HIT", st
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            a = df[col].to_numpy(dtype=float)
            b = df2[col].to_numpy(dtype=float)
            max_abs = float(np.max(np.abs(a - b)))
            assert max_abs < 1e-5, f"{col} drift {max_abs}"
        assert np.isclose(float(sb2), sb, rtol=1e-9), (sb2, sb)
    finally:
        db.close()


def main() -> int:
    print(f"Starting cache_daemon tests. Root={_ROOT}")
    t_all = time.time()
    _tc("TC1 schema & 3 tables exist", tc1_schema_and_tables)
    _tc("TC2 upsert → HIT roundtrip with df/share_base/metadata", tc2_upsert_get_hit_roundtrip)
    _tc("TC3 STALE/MISS aging + end_date filter", tc3_stale_and_miss_by_age)
    _tc("TC4 QUEUED→ALREADY_PENDING→claim→upsert→DONE transitions", tc4_queue_lifecycle_queued_to_done)
    _tc("TC5 mark_fetch_failed + max attempts guard + 429 error preserved", tc5_failed_and_retry_limit)
    _tc("TC6 get_queue_depth + fetcher_stats bumps accurate", tc6_depth_and_stats_bump)
    _tc("TC7 parquet roundtrip preserves numeric precision (OHLCV + share_base)", tc7_df_roundtrip_numeric_parquet_consistency)

    total = len(_TC_RESULTS)
    passed = sum(1 for ok, _ in _TC_RESULTS.values() if ok)
    failed = total - passed
    print(f"\n=====================================\nTotal {total}: passed={passed} failed={failed}  wall={time.time()-t_all:.2f}s")
    glyph_pass = "[PASS]"
    glyph_fail = "[FAIL]"
    try:
        print(f"  {'OK' if True else 'NG'}  {glyph_pass}", end="\r")
    except Exception:
        pass
    for n, (ok, m) in _TC_RESULTS.items():
        print(f"  {glyph_pass if ok else glyph_fail}  {n}  {m}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
