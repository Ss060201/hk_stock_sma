import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_ingest_stack import get_data_stack, _try_yfinance_download, _finalize_df_and_return
import pandas as pd
import numpy as np

if __name__ == "__main__":
    SYMS = ['0700.HK','0005.HK','2318.HK']
    print("="*70)
    print("D3-3a data_ingest_stack 測試 (System date 2026-09-04 HKT)")
    print("="*70)
    for s in SYMS:
        print(f"\n====== {s}  get_data_stack(s, end_date=None) ======")
        df, sb = get_data_stack(s)
        if df is None or len(df)==0:
            print(f"  ❌ FAIL df=None")
            continue
        ds = pd.to_datetime(df.index).sort_values()
        print(f"  rows={len(df)} last_5_dates={[d.strftime('%Y-%m-%d') for d in ds[-5:]]}")
        close_s = df.sort_index()['Close']
        for i in range(-5, 0):
            print(f"    {ds[i].strftime('%Y-%m-%d')}  Close={float(close_s.iloc[i]):.3f}  Open={float(df.sort_index()['Open'].iloc[i]):.3f}")
        # Direct _try_yfinance_download w/o end_date filter
        print(f"  --- direct _try_yfinance_download ---")
        try:
            df2, sb2 = _try_yfinance_download(s)
            if isinstance(df2.columns, pd.MultiIndex):
                df2.columns = df2.columns.get_level_values(0)
            ds2 = pd.to_datetime(df2.index).sort_values()
            print(f"    rows={len(df2)} last_5_dates={[d.strftime('%Y-%m-%d') for d in ds2[-5:]]}")
            for i in range(-5, 0):
                print(f"      {ds2[i].strftime('%Y-%m-%d')} C={float(df2.sort_index()['Close'].iloc[i]):.3f}")
            fin = _finalize_df_and_return(df2, s, s, None, "yf")
            if fin is not None:
                dff, sbf = fin
                dsf = pd.to_datetime(dff.index).sort_values()
                print(f"    finalize last_5={[d.strftime('%Y-%m-%d') for d in dsf[-5:]]}")
        except Exception as e:
            print(f"    direct ERR: {type(e).__name__}: {e}")
