"""One-click TUR/Amp health scanner for all watchlist + SQLite cached tickers.

Detects:
  (A) AMP staleness: consecutive rows where Amp == 0.10 exactly (old bug signature)
  (B) TUR out-of-band for >2 days: daily TUR outside [TUR_LOWER_BOUND_PCT, TUR_UPPER_BOUND_PCT]
      -> guesses best correction factor from _AUTO_SCALE_FACTORS and recommends float.csv line.

Run:  python scripts/tur_amp_health_scan.py [--top N] [--min-days N] [--extra-symbols CSV]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from turnover_utils import (
    TUR_UPPER_BOUND_PCT,
    TUR_LOWER_BOUND_PCT,
    _AUTO_SCALE_FACTORS,
    apply_turnover_rate,
    compute_safe_amplitude,
)
from providers import build_default_share_base_provider

DB_PATH = ROOT / "data" / "ohlcv_cache.sqlite"
WATCHLIST_CSV = ROOT / "metadata" / "watchlist.csv"
FLOAT_CSV = ROOT / "metadata" / "float.csv"
REPORT_PATH = ROOT / "data" / "tur_amp_health_report.csv"
JSON_REPORT_PATH = ROOT / "data" / "tur_amp_health_summary.json"

MIN_OBS_DAYS_DEFAULT = 10
AMP_LEGACY_STALE = 0.10  # old bug: Amp was padded to exactly 0.10% when H==L

# Real HK index constituents (2026Q3 snapshot, deduped across HSI + HSCEI + HSTECH, ~130 total)
# Sources: hsi.com.hk official constituent lists. Coverage: top liquid HK names.
HK_COMMON_LIQUID_CODES = {
    # === HSI (恆生指數 82 隻，精簡核心) ===
    "0001","0002","0003","0005","0006","0011","0012","0016","0017","0019",
    "0027","0066","0083","0101","0104","0116","0127","0151","0168","0175",
    "0241","0267","0285","0288","0291","0293","0316","0322","0347","0358",
    "0368","0386","0388","0392","0398","0460","0480","0489","0522","0525",
    "0548","0669","0688","0691","0700","0753","0762","0788","0811","0813",
    "0823","0853","0857","0867","0868","0881","0883","0909","0914","0934",
    "0939","0941","0945","0960","0966","0968","0981","0984","0992","0995",
    "0998","1024","1038","1044","1066","1088","1093","1097","1109","1112",
    "1113","1127","1171","1177","1186","1193","1208","1211","1299","1310",
    "1313","1316","1336","1339","1347","1371","1382","1395","1398","1402",
    # === HSCEI (國企指數，補足 HSI 未涵蓋者) ===
    "1548","1772","1776","1787","1801","1806","1810","1813","1818","1876",
    "1883","1898","1919","1928","1929","1966","1994","1997","2007","2015",
    "2018","2020","2127","2128","2129","2138","2180","2196","2238","2269",
    "2313","2314","2318","2328","2331","2333","2338","2359","2368","2382",
    "2388","2399","2401","2413","2422","2423","2433","2456","2468","2488",
    # === HSTECH (科技指數，補足前兩者未涵蓋者) ===
    "2518","2520","2588","2601","2607","2611","2618","2628","2660","2666",
    "2688","2689","2696","2707","2722","2753","2768","2777","2778","2788",
    "2799","2800","2801","2808","2812","2822","2828","2848","2857","2858",
    "2866","2877","2878","2888","2899","2907","2924","2929","2934","2939",
    "2981","2984","2992","2993","3024","3035","3189","3309","3311","3319",
    "3323","3328","3331","3333","3347","3360","3368","3382","3388","3401",
    "3419","3427","3435","3442","3443","3475","3476","3544","3579","3585",
    "3590","3594","3606","3610","3631","3636","3662","3663","3668","3669",
    "3690","3692","3693","3694","3719","3734","3738","3772","3773","3788",
    "3799","3800","3808","3813","3818","3828","3836","3848","3866","3868",
    "3888","3898","3899","3900","3908","3918","3927","3933","3939","3948",
    "3968","3969","3983","3988","3993","3996","3997","3998","3999","4009",
}


@dataclass
class TickHealth:
    ticker: str
    rows: int
    p98_amp: float
    amp_stale_hits: int
    tur_days_out: int
    tur_worst: float
    tur_median: float
    tur_last: float
    share_base: Optional[int]
    sb_method: str
    suggested_factor: Optional[float]
    suggested_shares: Optional[int]
    status: str  # OK / WARN / FATAL
    notes: str

    @property
    def as_row(self) -> dict:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "rows": self.rows,
            "p98_amp": f"{self.p98_amp:.3f}",
            "amp_stale_0.10_hits": self.amp_stale_hits,
            "tur_days_out": self.tur_days_out,
            "tur_median_pct": f"{self.tur_median:.5f}",
            "tur_last_pct": f"{self.tur_last:.5f}",
            "share_base": self.share_base,
            "sb_method": self.sb_method,
            "suggested_factor": (f"x{self.suggested_factor:g}" if self.suggested_factor else ""),
            "suggested_shares_outstanding": (f"{self.suggested_shares:,.0f}" if self.suggested_shares else ""),
            "notes": self.notes[:200],
        }

    def to_summary_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "tur_days_out": self.tur_days_out,
            "amp_stale_hits": self.amp_stale_hits,
            "tur_last_pct": round(self.tur_last, 5) if np.isfinite(self.tur_last) else None,
            "suggested_factor": f"x{self.suggested_factor:g}" if self.suggested_factor else None,
            "sb_method": self.sb_method,
        }


def _normalize_ticker(raw: str) -> str:
    s = (raw or "").strip().replace(" ", "")
    if s.lower().endswith(".hk"):
        s = s[:-3]
    if s.isdigit():
        s = s.zfill(4)
    return f"{s}.HK".upper()


def fetch_tickers_union(extra_csv: Optional[str] = None) -> list[str]:
    """5-layer union of ticker sources, deduped, sorted.

    Layers (low -> high priority, all unioned, dedup by normalized ticker):
      1. metadata/watchlist.csv  (if exists)
      2. SQLite ohlcv_cache.symbol  (what user has viewed in App)
      3. SQLite watchlist.symbol  (what user added to watchlist via SQLite)
      4. HK_COMMON_LIQUID_CODES  (HSI + HSCEI + HSTECH core constituents)
      5. --extra-symbols CLI CSV  (passed via GHA workflow_dispatch.inputs.extra_symbols)
    """
    tickers: set[str] = set()

    # L1: metadata/watchlist.csv
    if WATCHLIST_CSV.exists():
        try:
            with WATCHLIST_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    t = (row.get("ticker") or row.get("code") or row.get("symbol") or "").strip()
                    if t:
                        tickers.add(_normalize_ticker(t))
        except Exception as exc:
            print(f"[warn] watchlist.csv parse error: {exc}")

    # L2 + L3: SQLite (ohlcv_cache + watchlist table)
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT DISTINCT symbol FROM ohlcv_cache WHERE symbol IS NOT NULL"
                )
                for row in cur.fetchall():
                    s = (row["symbol"] or "").strip()
                    if s:
                        tickers.add(_normalize_ticker(s))
                # L3: watchlist table (ignore if table missing)
                try:
                    cur_wl = conn.execute(
                        "SELECT DISTINCT symbol FROM watchlist WHERE symbol IS NOT NULL"
                    )
                    for row in cur_wl.fetchall():
                        s = (row["symbol"] or "").strip()
                        if s:
                            tickers.add(_normalize_ticker(s))
                except sqlite3.OperationalError:
                    pass
        except Exception as exc:
            print(f"[warn] sqlite read error: {exc}")

    # L4: index constituents (map codes -> ticker)
    for code in HK_COMMON_LIQUID_CODES:
        tickers.add(_normalize_ticker(code))

    # L5: CLI --extra-symbols CSV
    if extra_csv:
        for part in extra_csv.split(","):
            t = part.strip()
            if t:
                tickers.add(_normalize_ticker(t))

    return sorted(tickers)


def load_ohlcv(ticker: str, min_obs_days: int = MIN_OBS_DAYS_DEFAULT) -> Optional[pd.DataFrame]:
    if not DB_PATH.exists():
        return None
    import io as _io
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT df_parquet FROM ohlcv_cache WHERE symbol = ? LIMIT 1",
                (ticker,),
            ).fetchone()
            if row is None or row["df_parquet"] is None:
                return None
            blob = row["df_parquet"]
            df = pd.read_parquet(_io.BytesIO(bytes(blob)))
            if df.index.name and str(df.index.name).lower() != "date":
                if "Date" in df.columns:
                    df = df.set_index("Date")
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            col_map = {
                "Open": "Open", "open": "Open",
                "High": "High", "high": "High",
                "Low": "Low", "low": "Low",
                "Close": "Close", "close": "Close",
                "Volume": "Volume", "volume": "Volume",
            }
            rename = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename)
            required = {"Open", "High", "Low", "Close", "Volume"}
            if not required.issubset(set(df.columns)):
                return None
            df = df.dropna(subset=["Close"])
            return df if len(df) >= min_obs_days else None
    except Exception:
        return None


def pick_best_factor(vol: pd.Series, share_base: float) -> Optional[float]:
    lb = TUR_LOWER_BOUND_PCT
    ub = TUR_UPPER_BOUND_PCT
    p50 = float(vol.quantile(0.5)) / share_base * 100
    p75 = float(vol.quantile(0.75)) / share_base * 100
    vmax = float(vol.max()) / share_base * 100
    if lb <= p50 <= ub and lb <= p75 <= ub and lb <= vmax <= ub * 1.2:
        return None
    def score(factor: float) -> tuple:
        med = p50 / factor
        p75n = p75 / factor
        mxn = vmax / factor
        ok_med = lb <= med <= ub
        ok_p75 = lb <= p75n <= ub
        ok_max = lb <= mxn <= ub * 1.2
        strong = int(ok_med) + int(ok_p75) + int(ok_max)
        dist = abs(np.log(med / 1.0)) if (lb <= med <= ub) else 1e9
        return (-strong, dist, abs(np.log(factor)))
    best = min(_AUTO_SCALE_FACTORS, key=score)
    final_p50 = p50 / best
    if not (lb * 0.1 <= final_p50 <= ub * 2):
        return None
    return best


def scan_one(ticker: str, provider, min_obs_days: int = MIN_OBS_DAYS_DEFAULT) -> Optional[TickHealth]:
    df = load_ohlcv(ticker, min_obs_days=min_obs_days)
    if df is None:
        return None
    sb_res = provider.get_share_base(ticker)
    sb = int(sb_res.share_base) if sb_res.share_base else None
    amp = compute_safe_amplitude(df[["Open", "High", "Low", "Close"]])
    amp_stale_hits = int(np.nansum(np.where(np.abs(amp * 100 - AMP_LEGACY_STALE) < 1e-6, 1, 0)))
    p98_amp = float(np.nanpercentile(amp * 100, 98)) if np.isfinite(amp).any() else 0.0
    if sb is None:
        tur_days_out = 0
        tur_last = float("nan")
        tur_median = float("nan")
        tur_worst = float("nan")
        suggested_factor = None
        suggested_shares = None
    else:
        df2, _status, _reason = apply_turnover_rate(df, sb)
        tur = df2["Turnover_Rate"]
        tur_arr = tur.dropna()
        tur_last = float(tur.iloc[-1]) if len(tur) else float("nan")
        tur_median = float(tur_arr.median()) if len(tur_arr) else float("nan")
        out_mask = (tur_arr < TUR_LOWER_BOUND_PCT) | (tur_arr > TUR_UPPER_BOUND_PCT)
        tur_days_out = int(out_mask.sum())
        tur_worst = float(tur_arr.iloc[int(np.nanargmax(np.abs(tur_arr.values)))]) if len(tur_arr) else float("nan")
        suggested_factor = pick_best_factor(df["Volume"].astype(float), sb)
        suggested_shares = int(sb * suggested_factor) if suggested_factor else None
    notes_parts = []
    if amp_stale_hits >= 2:
        notes_parts.append(f"{amp_stale_hits}x Amp=0.10 legacy stale")
    if tur_days_out >= 2 and sb is not None:
        notes_parts.append(f"{tur_days_out}d TUR outside [{TUR_LOWER_BOUND_PCT}%, {TUR_UPPER_BOUND_PCT}%]; median={tur_median:.5f}% last={tur_last:.5f}%")
    if sb is None:
        notes_parts.append("share_base unresolved (Yahoo + CSV both missing)")
    if suggested_factor:
        notes_parts.append(f"suggested sb x{suggested_factor:g} -> {suggested_shares:,.0f}")
    status = "OK"
    if (tur_days_out >= 5 or amp_stale_hits >= 3) or sb is None:
        status = "WARN"
    if tur_days_out >= 10 or amp_stale_hits >= 8:
        status = "FATAL"
    return TickHealth(
        ticker=ticker,
        rows=len(df),
        p98_amp=p98_amp,
        amp_stale_hits=amp_stale_hits,
        tur_days_out=tur_days_out,
        tur_worst=tur_worst,
        tur_median=tur_median,
        tur_last=tur_last,
        share_base=sb,
        sb_method=(sb_res.method or "NA"),
        suggested_factor=suggested_factor,
        suggested_shares=suggested_shares,
        status=status,
        notes=" | ".join(notes_parts),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="TUR/Amp health scanner across 5-layer ticker union")
    parser.add_argument("--top", type=int, default=500, help="Max tickers to scan (default 500)")
    parser.add_argument("--min-days", type=int, default=MIN_OBS_DAYS_DEFAULT)
    parser.add_argument(
        "--extra-symbols",
        type=str,
        default=None,
        help="Comma-separated extra tickers (e.g. 0700,1371.HK,0005). Passed via GHA extra_symbols.",
    )
    parser.add_argument(
        "--report-csv",
        type=str,
        default=None,
        help="Override CSV output path. Defaults to repo/data/tur_amp_health_report.csv. "
             "Use absolute path for GHA artifact directory.",
    )
    parser.add_argument(
        "--summary-json",
        type=str,
        default=None,
        help="Override JSON summary output path. Defaults to repo/data/tur_amp_health_summary.json. "
             "Use absolute path for GHA artifact directory.",
    )
    args = parser.parse_args()
    min_obs = max(args.min_days, 5)

    report_csv_path = Path(args.report_csv) if args.report_csv else REPORT_PATH
    summary_json_path = Path(args.summary_json) if args.summary_json else JSON_REPORT_PATH
    for p in (report_csv_path, summary_json_path):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    tickers_pool = fetch_tickers_union(extra_csv=args.extra_symbols)
    tickers = tickers_pool[: args.top]
    print(f"[info] union pool = {len(tickers_pool)} tickers (5 layers); scanning top {len(tickers)} (min {min_obs} rows each)")
    print(f"[info] CSV report -> {report_csv_path}")
    print(f"[info] JSON summary -> {summary_json_path}")
    provider = build_default_share_base_provider()

    results: list[TickHealth] = []
    for i, ticker in enumerate(tickers, 1):
        if i % 50 == 0 or i == len(tickers):
            print(f"  ... {i}/{len(tickers)}")
        res = scan_one(ticker, provider, min_obs_days=min_obs)
        if res:
            results.append(res)
    if not results:
        print("[warn] no ticker had enough cached rows. Run data fetcher first.")
        return 1

    counts = Counter(r.status for r in results)
    scanned_total = len(results)
    print(f"[done] scanned {scanned_total} tickers with data. OK={counts['OK']} WARN={counts['WARN']} FATAL={counts['FATAL']}")

    rows = [r.as_row for r in results]
    rows.sort(key=lambda r: ({"FATAL": 0, "WARN": 1, "OK": 2}[r["status"]], -int(r["tur_days_out"]), -int(r["amp_stale_0.10_hits"])))
    pd.DataFrame(rows).to_csv(report_csv_path, index=False, encoding="utf-8-sig")
    print(f"[report] wrote {report_csv_path}")

    # === JSON summary (for GHA artifact quick glance) ===
    problems = [r for r in results if r.status in ("WARN", "FATAL")]
    problems_sorted = sorted(problems, key=lambda r: ({"FATAL": 0, "WARN": 1}[r.status], -r.tur_days_out, -r.amp_stale_hits))
    sug_rows: List[str] = []
    for r in [rr for rr in results if rr.suggested_factor]:
        code = (r.ticker or "").replace(".HK", "")
        shares = f"{r.suggested_shares:,.0f}".replace(",", "") if r.suggested_shares else "0"
        sug_rows.append(f"{code},<VERIFY_AASTOCKS>,{shares},1.0,{shares},2026-09-08,verify_required,medium")
    summary = {
        "scanned_tickers_count": scanned_total,
        "union_pool_count": len(tickers_pool),
        "counts": {
            "OK": counts.get("OK", 0),
            "WARN": counts.get("WARN", 0),
            "FATAL": counts.get("FATAL", 0),
        },
        "fatal_and_warn_top10": [r.to_summary_dict() for r in problems_sorted[:10]],
        "tickers_with_suggested_factor": [r.to_summary_dict() for r in results if r.suggested_factor],
        "suggested_factor_candidates": sug_rows,
    }
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] wrote JSON summary -> {summary_json_path}")

    print()
    print("Top 10 issues (FATAL/WARN):")
    for r in rows[:10]:
        if r["status"] == "OK":
            break
        print(f"  [{r['status']:5s}] {r['ticker']:9s} tur_out={r['tur_days_out']:>3}d amp_stale={r['amp_stale_0.10_hits']:>2} {r['suggested_factor'] or '':>5} sb={r['sb_method']:12s} notes={r['notes'][:120]}")
    suggestions = [r for r in rows if r["suggested_shares_outstanding"]]
    if suggestions:
        print("\nSuggested float.csv additions (VERIFY with AASTOCKS before pasting into metadata/float.csv):")
        print("ticker,company,outstanding,float_ratio,float_shares,last_update,source,confidence")
        for r in suggestions[:12]:
            code = r["ticker"].replace(".HK", "")
            shares = r["suggested_shares_outstanding"].replace(",", "")
            print(f"{code},<AUTO_VERIFY_WITH_AASTOCKS>,{shares},1.0,{shares},2026-09-08,aastocks_to_verify,medium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
