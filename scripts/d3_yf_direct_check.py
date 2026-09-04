import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yfinance as yf
import pandas as pd
import datetime as dt

TEST_SYMBOLS = ['0700.HK','2318.HK','1299.HK','0005.HK','00068.HK']

if __name__ == "__main__":
    print("="*70)
    print(f"D3-2 Yahoo Finance 即時檢查: now={dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    for s in TEST_SYMBOLS:
        print(f"\n--- {s} ---")
        try:
            tkr = yf.Ticker(s)
            info = tkr.fast_info
            print(f"  fast_info last_price={getattr(info,'last_price',None)} last_volume={getattr(info,'last_volume',None)} currency={getattr(info,'currency',None)} timezone={getattr(info,'timezone',None)}")
        except Exception as e:
            print(f"  fast_info err: {type(e).__name__}: {e}")
        try:
            df = yf.download(s, start='2026-08-28', end='2026-09-05', progress=False, auto_adjust=False, threads=False)
            if df is None or len(df)==0:
                print(f"  yf.download: EMPTY / None")
            else:
                print(f"  yf.download rows={len(df)} cols={list(df.columns)}")
                for idx, row in df.iterrows():
                    try:
                        close_v = float(row.get('Close', row.get(('Close', s), None))) if 'Close' in df.columns else None
                        open_v  = float(row.get('Open',  row.get(('Open', s), None)))  if 'Open' in df.columns else None
                        high_v  = float(row.get('High',  row.get(('High', s), None)))  if 'High' in df.columns else None
                        low_v   = float(row.get('Low',   row.get(('Low', s), None)))   if 'Low' in df.columns else None
                        vol_v   = float(row.get('Volume',row.get(('Volume', s), None)))if 'Volume' in df.columns else None
                        d_str = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)
                        print(f"    {d_str}  O={open_v}  H={high_v}  L={low_v}  C={close_v}  V={vol_v}")
                    except Exception as e2:
                        print(f"    row={idx} parse err: {e2} raw={row.to_dict() if hasattr(row,'to_dict') else row}")
        except Exception as e:
            print(f"  yf.download err: {type(e).__name__}: {e}")
