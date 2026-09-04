import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from cache_layer import get_cached_ohlcv

if __name__ == "__main__":
    # Import get_data_v7 directly from app.py (skip streamlit runtime by early execute the module with streamlit import)
    # Workaround: manually mock streamlit to load app.py module without errors
    import importlib.util, types

    # Step 0: print BEFORE state
    print("="*70)
    print("D3-6 BEFORE: get_cached_ohlcv last dates (end_date=2026-09-04, max_age=None)")
    print("="*70)
    for s in ['0700.HK','0005.HK','2318.HK','1299.HK','0700.HK']:
        df, sb, st = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
        if df is None:
            print(f"  {s}: MISS"); continue
        ds = pd.to_datetime(df.index).sort_values()
        close_s = df.sort_index()["Close"]
        print(f"  {s}: last date={ds[-1].strftime('%Y-%m-%d')} rows={len(df)} close_last={float(close_s.iloc[-1]):.3f}")

    print("\n" + "="*70)
    print("D3-6 Step1: Manually call data_ingest_stack.get_data_stack directly for 4 symbols")
    print("="*70)
    from data_ingest_stack import get_data_stack
    from cache_layer import upsert_ohlcv

    TARGETS = ['0700.HK','0005.HK','2318.HK','1299.HK']
    END_DATE = pd.Timestamp("2026-09-04 23:59:59")
    for s in TARGETS:
        print(f"\n--- {s} live download via data_ingest_stack.get_data_stack (end={END_DATE.date()}) ---")
        try:
            df, sb = get_data_stack(s, end_date=END_DATE)
            if df is None or len(df)==0:
                print(f"  ❌ FAIL: None/empty")
                continue
            ds = pd.to_datetime(df.index).sort_values()
            close_s = df.sort_index()["Close"]
            open_s  = df.sort_index()["Open"]
            high_s  = df.sort_index()["High"]
            low_s   = df.sort_index()["Low"]
            print(f"  ✅ SUCCESS: rows={len(df)} sb={sb}")
            for i in range(-3, 0):
                print(f"    {ds[i].strftime('%Y-%m-%d')}  O={float(open_s.iloc[i]):.3f}  H={float(high_s.iloc[i]):.3f}  L={float(low_s.iloc[i]):.3f}  C={float(close_s.iloc[i]):.3f}")
            # upsert to SQLite
            print(f"  → upsert_ohlcv() ...")
            upsert_ohlcv(s, df, share_base=sb, source="manual_d3_fix")
            print(f"  ✅ UPSERT OK")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ EXCEPTION: {type(e).__name__}: {e}")

    print("\n" + "="*70)
    print("D3-6 AFTER: re-check local SQLite last dates")
    print("="*70)
    for s in TARGETS:
        df, sb, st = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
        if df is None:
            print(f"  {s}: MISS"); continue
        ds = pd.to_datetime(df.index).sort_values()
        close_s = df.sort_index()["Close"]
        print(f"  {s}: last date={ds[-1].strftime('%Y-%m-%d')} rows={len(df)} close_last={float(close_s.iloc[-1]):.3f} ({st})")
    print("\n✅ D3-6 done")
