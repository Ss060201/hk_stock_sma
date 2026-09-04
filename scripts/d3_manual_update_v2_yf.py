import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yfinance as yf
import pandas as pd
import numpy as np
from cache_layer import get_cached_ohlcv, upsert_ohlcv

TARGETS = ['0001.HK','0005.HK','0027.HK','0388.HK','0700.HK','0823.HK','1299.HK','2318.HK']

def _resolve_share_base_fallback(df, symbol):
    """Simple share_base estimator: avg(20d turnover) / avg(20d close) * 0.0035"""
    try:
        df2 = df.sort_index().copy()
        closes = pd.to_numeric(df2["Close"], errors="coerce").replace(0, np.nan)
        vols = pd.to_numeric(df2.get("Volume", pd.Series(index=df2.index, dtype=float)), errors="coerce").fillna(0)
        turnovers = closes * vols
        closes_drop = closes.dropna()
        if len(closes_drop) < 20 or turnovers.dropna().sum() < 10:
            return None, "dropna_too_short"
        avg_close = float(closes_drop.tail(250).mean()) if len(closes_drop) >= 250 else float(closes_drop.mean())
        avg_turnover = float(turnovers.dropna().tail(250).mean()) if len(turnovers.dropna()) >= 250 else float(turnovers.dropna().mean())
        if avg_close > 1e-9:
            sb = avg_turnover / avg_close * 0.0035
            if sb > 1e9:
                return sb, "tail250_method"
    except Exception as e:
        return None, f"err:{type(e).__name__}"
    return None, "sb_too_low"

if __name__ == "__main__":
    print("="*70)
    print("D3-6 v2: Quick yfinance.download → SQLite upsert")
    print("="*70)
    print("BEFORE last dates:")
    for s in TARGETS:
        df, sb, st = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
        if df is None:
            print(f"  {s}: MISS"); continue
        ds = pd.to_datetime(df.index).sort_values()
        print(f"  {s}: last={ds[-1].strftime('%Y-%m-%d')} close={float(df.sort_index()['Close'].iloc[-1]):.3f}")

    for s in TARGETS:
        print(f"\n--- {s} ---")
        try:
            df_old, sb_old, _ = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
            # Append only: download latest 5 days, merge with old
            df_new = yf.download(s, start="2026-08-28", end=pd.Timestamp.now(tz="Asia/Hong_Kong").date() + pd.Timedelta(days=1),
                                 progress=False, auto_adjust=False, actions=False, threads=False)
            if df_new is None or len(df_new)==0:
                print(f"  ❌ yf.download returned empty")
                continue
            if isinstance(df_new.columns, pd.MultiIndex):
                df_new.columns = df_new.columns.get_level_values(0)
            df_new.index = pd.to_datetime(df_new.index)
            keep_cols = [c for c in ("Open","High","Low","Close","Volume") if c in df_new.columns]
            df_new = df_new[keep_cols].sort_index()
            # Drop rows where Close is NaN (no price = invalid / not traded yet)
            if "Close" in df_new.columns:
                cc = pd.to_numeric(df_new["Close"], errors="coerce")
                df_new = df_new[cc.notna() & (cc > 0)]
            print(f"  yf.download rows={len(df_new)} last_date={df_new.index[-1].strftime('%Y-%m-%d')} close={float(df_new['Close'].iloc[-1]):.3f}")

            # Merge with old df if exists
            if df_old is not None and len(df_old) > 0:
                if isinstance(df_old.index, pd.DatetimeIndex):
                    df_old_idx = df_old
                else:
                    df_old_idx = df_old.copy()
                    df_old_idx.index = pd.to_datetime(df_old_idx.index)
                cols_align = [c for c in df_new.columns if c in df_old_idx.columns]
                combined = pd.concat([df_old_idx[cols_align].sort_index(), df_new[cols_align].sort_index()])
                # Keep last for each duplicated index (prefer newer download)
                combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                df_out = combined
            else:
                df_out = df_new
            print(f"  merged rows={len(df_out)} last={df_out.index[-1].strftime('%Y-%m-%d')}")

            # share_base: reuse old if > 1e9, else compute fallback
            final_sb = sb_old if (sb_old is not None and isinstance(sb_old, (int,float)) and float(sb_old) > 1e9) else None
            if final_sb is None:
                final_sb, sb_note = _resolve_share_base_fallback(df_out, s)
                print(f"  share_base: computed={final_sb} ({sb_note})")
            else:
                print(f"  share_base: reused old={final_sb}")

            # Only upsert if we got at least 200 rows (so we know history stayed intact)
            if len(df_out) >= 200:
                upsert_ohlcv(s, df_out, share_base=final_sb, source="d3_manual_yf_fast")
                print(f"  ✅ upsert_ohlcv OK  len={len(df_out)}")
            else:
                print(f"  ⚠️  skip upsert, rows={len(df_out)} < 200 (too few)")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ {type(e).__name__}: {e}")

    print("\n" + "="*70)
    print("AFTER last dates:")
    for s in TARGETS:
        df, sb, st = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
        if df is None:
            print(f"  {s}: MISS"); continue
        ds = pd.to_datetime(df.index).sort_values()
        ci = df.sort_index()["Close"]
        oi = df.sort_index()["Open"]
        print(f"  {s}: last={ds[-1].strftime('%Y-%m-%d')} O={float(oi.iloc[-1]):.3f} C={float(ci.iloc[-1]):.3f} rows={len(df)} status={st}")
