import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cache_layer import get_cached_ohlcv
import pandas as pd

SYMBOLS = ['0001.HK','0005.HK','0027.HK','0388.HK','0700.HK','0823.HK','1299.HK','2318.HK']

if __name__ == "__main__":
    print("="*70)
    print("D3-1 本地 ohlcv_cache 最後交易日檢查 (System date: 2026-09-04)")
    print("="*70)
    for s in SYMBOLS:
        df, sb, st = get_cached_ohlcv(s, max_age_sec=None, bump_stats=False)
        if df is None or len(df)==0:
            print(f"  {s:>10s}: ❌ MISS status={st}")
            continue
        idx = pd.to_datetime(df.index) if not isinstance(df.index, pd.DatetimeIndex) else df.index
        ds = idx.sort_values()
        last_5 = ds[-5:] if len(ds)>=5 else ds
        last_str = [d.strftime("%Y-%m-%d") for d in last_5]
        pct_chg = None
        close_series = df.sort_index()["Close"]
        if len(close_series) >= 2:
            c_n = float(close_series.iloc[-1])
            c_p = float(close_series.iloc[-2])
            if abs(c_p)>1e-9:
                pct_chg = (c_n-c_p)/c_p*100
        print(f"  {s:>10s}: last[{len(ds)}d]={', '.join(last_str)}  status={st:5s} sb={sb} last_close={close_series.iloc[-1]:.3f} prev={close_series.iloc[-2] if len(close_series)>=2 else None} {'(today=2026-09-04 ⚠️ MISSING 09-03!)' if ds[-1].strftime('%Y-%m-%d') < '2026-09-03' else '(has 09-03 ✅)'}")
    print()
