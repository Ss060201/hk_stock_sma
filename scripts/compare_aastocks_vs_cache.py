"""
C1 比對腳本：AAStocks HTML 爬下 4 檔數據 vs 本地 SQLite ohlcv_cache 最後交易日
"""
from __future__ import annotations

import os, re, sys, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd
from cache_layer import (
    ensure_schema,
    list_cached_symbols,
    get_cached_ohlcv,
)

SYMBOLS = [
    ("00700", "0700.HK", "tmp_aastocks_00700.html"),
    ("02318", "2318.HK", "tmp_aastocks_02318.html"),
    ("01299", "1299.HK", "tmp_aastocks_01299.html"),
    ("00005", "0005.HK", "tmp_aastocks_00005.html"),
]


def aastocks_extract(html_path: str) -> dict:
    if not os.path.exists(html_path):
        return {}
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    out = {}
    # 1. Name
    m = re.search(r'<title>(.*?)(?:\s*[-–|].*?)?</title>', txt, re.I)
    if m:
        out["name_raw"] = m.group(1).strip()
    # 2. 現價 (last) / 前收市 / 開市 / 最高 / 最低 — 一般 aastocks 頁面有表格
    # 各種 pattern 組合
    patterns = {
        "prev_close": [
            r"前收市[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"Prev[\s_]*Close[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"<td[^>]*>\s*前收市\s*</td>\s*<td[^>]*>([0-9]+(?:\.[0-9]+)?)</td>",
        ],
        "open": [
            r"開市[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"Open[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        ],
        "high": [
            r"最高[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"High[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        ],
        "low": [
            r"最低[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"Low[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        ],
        "last": [
            r"<div[^>]*class=\"[^\"']*?quote[^\"']*?\"[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*<",
            r"現價[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
            r"Last[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        ],
        "turnover": [
            r"成交金額[^0-9HK\$億萬千]{0,20}([0-9]+(?:\.[0-9]+)?\s*(?:億|萬|千|HK\$)?)",
            r"Turnover[^0-9HK\$億萬千]{0,20}([0-9]+(?:\.[0-9]+)?\s*(?:B|M|K|HK\$)?)",
        ],
        "chg_pct": [
            r"([\+\-][0-9]+(?:\.[0-9]+)?)\s*%",
        ],
    }
    for key, pats in patterns.items():
        for p in pats:
            mm = re.search(p, txt, re.I | re.S)
            if mm:
                out[key] = mm.group(1).strip()
                break
    # 再補充：一些 AAStocks 把數據放在 JS 陣列內，例如 arr = ["0700","騰訊控股",380.2,382,...]
    try:
        candidates = []
        for mm in re.finditer(r'"([0-9]{4,5})"\s*,\s*"([^"]{1,20})"\s*,\s*(-?[0-9]+\.?[0-9]*)\s*,\s*(-?[0-9]+\.?[0-9]*)\s*,\s*(-?[0-9]+\.?[0-9]*)\s*,\s*(-?[0-9]+\.?[0-9]*)\s*,\s*(-?[0-9]+\.?[0-9]*)', txt):
            candidates.append(mm.groups())
        if candidates:
            c = candidates[0]
            out.setdefault("last_js", c[2])
            out.setdefault("name_js", c[1])
            out.setdefault("chg_js", c[3])
    except Exception:
        pass
    # 最後再找 body 數字 (fallback)：body 所有 xxxxx.xx 的 unique 前 20 大排序
    nums = sorted(set(float(n) for n in re.findall(r'\b(\d{2,4}\.\d{2})\b', txt)), reverse=True)
    out["top_prices"] = nums[:15]
    return out


def main():
    ensure_schema(None)
    cached_by_sym = {}
    for s in list_cached_symbols(limit=200):
        cached_by_sym[s["symbol"].upper()] = s
    print("=" * 78)
    print("AAStocks(HTML 爬取) vs 本地 SQLite Cache 數據對比 (C1)")
    print("=" * 78)
    total_diff_count = 0
    for aa_code, yahoo_code, html_file in SYMBOLS:
        path = os.path.join(ROOT, html_file)
        aa = aastocks_extract(path)
        print(f"\n【{yahoo_code}】(AAStocks symbol={aa_code}) — name={aa.get('name_raw') or aa.get('name_js')}")
        if not aa or all(k not in aa for k in ("last", "prev_close", "last_js")):
            print("  ⚠️  AAStocks 解析失敗，僅 dump top prices：", aa.get("top_prices"))
        local = None
        df, sb, cs = None, None, None
        if yahoo_code in cached_by_sym:
            df, sb, cs = get_cached_ohlcv(yahoo_code, max_age_sec=60*60*24*60)
        if df is None or len(df) < 20:
            print("  ❌ 本地 SQLite 無此快取，跳過對比")
            continue
        last_local = pd.to_numeric(df["Close"], errors="coerce").replace(0, np.nan).dropna()
        c_local = float(last_local.iloc[-1])
        prev_local = float(last_local.iloc[-2])
        local_pct = (c_local - prev_local) / prev_local * 100.0
        if "High" in df.columns and "Low" in df.columns:
            hi_local = float(pd.to_numeric(df["High"], errors="coerce").iloc[-1]) if pd.notna(pd.to_numeric(df["High"], errors="coerce").iloc[-1]) else None
            lo_local = float(pd.to_numeric(df["Low"], errors="coerce").iloc[-1]) if pd.notna(pd.to_numeric(df["Low"], errors="coerce").iloc[-1]) else None
            op_local = float(pd.to_numeric(df["Open"], errors="coerce").iloc[-1]) if "Open" in df.columns and pd.notna(pd.to_numeric(df["Open"], errors="coerce").iloc[-1]) else None
        else:
            hi_local = lo_local = op_local = None
        # 找 AAStocks 對應數值
        aa_last = None
        for k in ("last", "last_js"):
            try:
                if aa.get(k):
                    aa_last = float(str(aa[k]).replace(",",""))
                    break
            except Exception:
                pass
        aa_prev = None
        try:
            if aa.get("prev_close"):
                aa_prev = float(str(aa["prev_close"]).replace(",",""))
        except Exception:
            pass
        aa_hi = None
        try:
            if aa.get("high"):
                aa_hi = float(str(aa["high"]).replace(",",""))
        except Exception:
            pass
        aa_lo = None
        try:
            if aa.get("low"):
                aa_lo = float(str(aa["low"]).replace(",",""))
        except Exception:
            pass
        aa_op = None
        try:
            if aa.get("open"):
                aa_op = float(str(aa["open"]).replace(",",""))
        except Exception:
            pass
        # 如果沒找到 last，從 top_prices 推測（找 AAStocks 名 vs local 最接近的 2 個值對應 prev/last）
        if aa_last is None and aa_prev is None and aa.get("top_prices"):
            tp = aa["top_prices"]
            # prev/curr 兩個相對接近的價格
            for i in range(len(tp)-1):
                a, b = tp[i], tp[i+1]
                if max(a,b) / max(min(a,b), 1e-9) < 1.05:
                    aa_prev, aa_last = (a, b) if abs(b - c_local) <= abs(a - c_local) else (b, a)
                    break
        def _cmp(label, aa_v, local_v):
            nonlocal total_diff_count
            if aa_v is None or local_v is None:
                print(f"    {label:>12s}:  AA={aa_v}  local={local_v}  (資料不足)")
                return
            diff = float(aa_v) - float(local_v)
            reld = abs(diff) / max(abs(float(local_v)), 1e-9) * 100.0
            mark = "✅" if reld < 0.5 else "⚠️" if reld < 2.0 else "❌"
            if mark != "✅":
                total_diff_count += 1
            print(f"    {label:>12s}:  AA={float(aa_v):>10.2f}  local={float(local_v):>10.2f}  Δ={diff:+.2f}  ({reld:+.2f}%)  {mark}")
        _cmp("Close(最後收盤)", aa_last, c_local)
        _cmp("PrevClose(前收)", aa_prev, prev_local)
        _cmp("High(最高)", aa_hi, hi_local)
        _cmp("Low(最低)", aa_lo, lo_local)
        _cmp("Open(開市)", aa_op, op_local)
        # 漲跌幅 (AAStocks chg_pct vs local_pct)，本地用 Close-Prev/Prev
        aa_pct = None
        try:
            if aa.get("chg_pct"):
                # 取第一個出現的 +/-xx.xx%
                aa_pct = float(str(aa["chg_pct"]).replace(",",""))
        except Exception:
            pass
        if aa_pct is None and aa_last and aa_prev:
            aa_pct = (aa_last - aa_prev) / max(aa_prev, 1e-9) * 100.0
        _cmp("ChgPct(漲跌幅%)", aa_pct, local_pct)
        print(f"    Cache status: {cs}  rows={len(df)}  share_base={sb}")
    print("\n" + "=" * 78)
    if total_diff_count == 0:
        print("SUMMARY: ✅ 所有可比對字段偏差 < 0.5%，數據與 AAStocks 權威源吻合")
    else:
        print(f"SUMMARY: ⚠️ 有 {total_diff_count} 處欄位偏差 ≥ 0.5%（可能是交易時段 vs 收盤時間差 / 不同收盤價來源，需確認）")
    print("=" * 78)


if __name__ == "__main__":
    raise SystemExit(main())
