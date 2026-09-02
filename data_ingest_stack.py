from __future__ import annotations

import logging
import random
import re
import threading
import time
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf


LOGGER = logging.getLogger("data_ingest_stack")


# ---------------------------------------------------------------------------
# Session manager (mirrors app.py _YFSessionManager, pure Python no st)
# ---------------------------------------------------------------------------
class _YFSessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions = []
        self._last_refresh_ts = 0.0
        self._error_until: Dict[str, float] = {}
        self._error_count: Dict[str, int] = {}

    def _acquire(self):
        self._lock.acquire()

    def _release(self):
        try:
            self._lock.release()
        except Exception:
            pass

    def _maybe_refresh_sessions(self, max_age_sec: int = 900):
        now = time.time()
        if self._sessions and (now - self._last_refresh_ts) < max_age_sec:
            return
        try:
            new_sessions = []
            for _ in range(3):
                s = requests.Session()
                s.headers.update({
                    "User-Agent": random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
                        "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
                    ]),
                    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-TW,zh-Hant;q=0.9,zh;q=0.8,en-US;q=0.7,en;q=0.6",
                })
                new_sessions.append(s)
            self._sessions = new_sessions
            self._last_refresh_ts = now
        except Exception:
            pass

    def should_skip(self, ticker: str):
        self._acquire()
        try:
            until = self._error_until.get(ticker, 0.0)
            if until and time.time() < until:
                return True
            return False
        finally:
            self._release()

    def get_session(self):
        self._acquire()
        try:
            self._maybe_refresh_sessions()
            if self._sessions:
                return self._sessions[random.randint(0, len(self._sessions) - 1)]
            return None
        finally:
            self._release()

    def record_success(self, ticker: str):
        self._acquire()
        try:
            self._error_count[ticker] = 0
            self._error_until.pop(ticker, None)
        finally:
            self._release()

    def record_failure(self, ticker: str, cooldown_sec: int = 180):
        self._acquire()
        try:
            c = (self._error_count.get(ticker, 0) or 0) + 1
            self._error_count[ticker] = c
            if c >= 2:
                self._error_until[ticker] = time.time() + cooldown_sec
        finally:
            self._release()


_YF_SESS_MGR = _YFSessionManager()


# ---------------------------------------------------------------------------
# In-memory logs (mirror app.py global log rings, pure Python)
# ---------------------------------------------------------------------------
_YF_LAST_ERROR: Dict[str, Any] = {}
_NATIVE_DOWNLOAD_STATS: Dict[str, Any] = {
    "native_attempts": 0, "native_success": 0,
    "yf_attempts": 0, "yf_success": 0,
    "stooq_attempts": 0, "stooq_success": 0,
    "sina_attempts": 0, "sina_success": 0,
}
_YF_PERSIST_ERR_LOG: list = []
_YF_NATIVE_STEP_LOG: list = []
_YF_LOG_LOCK = threading.RLock()


def _yf_append_log(log_list: list, payload, limit: int = 20):
    try:
        with _YF_LOG_LOCK:
            log_list.append(payload)
            while len(log_list) > limit:
                log_list.pop(0)
    except Exception:
        pass


def _yf_log_step(symbol: str, stage: str, message: str):
    _yf_append_log(_YF_NATIVE_STEP_LOG,
                   (time.strftime("%H:%M:%S"), symbol, stage, (message or "")[:220]), limit=12)


def _persist_last_error(symbol: str, route: str, detail: str):
    try:
        _YF_LAST_ERROR[symbol] = {
            "time": time.strftime("%H:%M:%S"),
            "route": route,
            "detail": (detail or "")[:240],
        }
    except Exception:
        pass
    _yf_append_log(_YF_PERSIST_ERR_LOG,
                   (time.strftime("%H:%M:%S"), symbol, route, (detail or "")[:240]), limit=80)


# ---------------------------------------------------------------------------
# Ticker helpers (mirror app.py)
# ---------------------------------------------------------------------------
def clean_ticker_input(symbol):
    return str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")


def get_yahoo_ticker(symbol):
    s = str(symbol or "").strip()
    if s.isdigit():
        return f"{s.zfill(4)}.HK"
    return s


# ---------------------------------------------------------------------------
# Ticker alias pool (for providers with mismatched conventions)
#   Examples for 0011.HK -> [0011.HK, 0011.hk, 11.HK, 00011.HK]
#   Route4 Sina additionally requires hk prefix separately.
# ---------------------------------------------------------------------------
def _build_ticker_aliases(symbol: str) -> list[str]:
    raw = str(symbol or "").strip()
    if not raw:
        return []
    digits = re.sub(r"\D", "", raw)
    suffix = ".HK"
    # extract any explicit suffix if present
    for sf in (".HK", ".hk"):
        if raw.endswith(sf):
            suffix = sf
            break
    seen: set[str] = set()
    out: list[str] = []
    # Primary: keep original as-is first
    for cand in (raw, raw.upper() if not raw.isupper() else raw, raw.lower() if not raw.islower() else raw):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    # 4-digit canonical (e.g. 0011.HK)
    if digits:
        d4 = digits.zfill(4)
        for c in (f"{d4}.HK", f"{d4}.hk"):
            if c not in seen:
                seen.add(c); out.append(c)
        # non-padded numeric (e.g. 11.HK for short codes like Hang Seng Bank)
        d_strip = digits.lstrip("0") or digits
        for c in (f"{d_strip}.HK", f"{d_strip}.hk"):
            if c not in seen:
                seen.add(c); out.append(c)
        # 5-digit canonical (Stooq sometimes uses 00011.HK)
        if len(digits) <= 5:
            d5 = digits.zfill(5)
            for c in (f"{d5}.HK", f"{d5}.hk"):
                if c not in seen:
                    seen.add(c); out.append(c)
        # ---- G6b extras for HK short codes that often get mis-formatted by providers:
        # hk + digits (no dot) — Route3 stooq / Route4 sina compatible raw forms
        hk_prefix_upper = f"HK{d4}"
        hk_prefix_lower = f"hk{d4}"
        if len(digits) <= 5:
            d5_raw = digits.zfill(5)
            hk_prefix_upper5 = f"HK{d5_raw}"
            hk_prefix_lower5 = f"hk{d5_raw}"
        else:
            hk_prefix_upper5 = f"HK{digits}"
            hk_prefix_lower5 = f"hk{digits}"
        for c in (hk_prefix_upper, hk_prefix_lower, hk_prefix_upper5, hk_prefix_lower5):
            if c not in seen:
                seen.add(c); out.append(c)
        # digits only with no suffix for providers that infer market from context
        for c in (d4, d5_raw if len(digits) <= 5 else digits, d_strip):
            if c and c not in seen:
                seen.add(c); out.append(c)
    # De-dup and trim
    trimmed: list[str] = []
    for c in out:
        if c and c not in trimmed:
            trimmed.append(c)
    return trimmed[:20]


# ---------------------------------------------------------------------------
# Share-base post resolver (mirror app.py _resolve_share_base_post)
# ---------------------------------------------------------------------------
def _resolve_share_base_post(df: pd.DataFrame, symbol: str,
                             fallback_avg_tor_pct: float = 0.35,
                             fallback_window: int = 120):
    approx_note = None
    share_base = None
    try:
        t_obj = yf.Ticker(symbol)
        try:
            from providers.share_base_provider import get_share_base_provider  # type: ignore
            provider = get_share_base_provider()
            ticker_raw = clean_ticker_input(getattr(t_obj, "ticker", symbol))
            from providers.base_share_provider import Ticker as _BTicker  # type: ignore
            lookup_obj = _BTicker(ticker=ticker_raw, yahoo_symbol=symbol, market="HK")
            res = provider.get_share_base(lookup_obj)
            val = getattr(res, "share_base", None)
            if val is not None and pd.notna(val) and float(val) > 0:
                return float(val), None
        except Exception:
            pass
    except Exception:
        share_base = None

    if share_base is not None and pd.notna(share_base) and float(share_base) > 0:
        return float(share_base), approx_note

    if df is None or df.empty or "Volume" not in df.columns:
        return None, "NO_VOLUME"

    try:
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        use_n = min(int(fallback_window), len(vol))
        if use_n < 10:
            return None, "NO_VOLUME"
        tail = vol.tail(use_n).replace(0, np.nan).dropna()
        if len(tail) < 10:
            return None, "NO_VOLUME"
        avg_vol = float(tail.mean())
        if avg_vol <= 0:
            return None, "NO_VOLUME"
        denom = max(0.0005, float(fallback_avg_tor_pct) / 100.0)
        share_base_approx = avg_vol / denom
        if not np.isfinite(share_base_approx) or share_base_approx <= 0:
            return None, "NO_VOLUME"
        approx_note = f"APPROX_{fallback_avg_tor_pct:g}pct_window{fallback_window}"
        return float(share_base_approx), approx_note
    except Exception:
        return None, "NO_VOLUME"


# ---------------------------------------------------------------------------
# Route 1: native Yahoo chart (mirror app.py L3019)
# ---------------------------------------------------------------------------
def _native_yahoo_chart_download(symbol, range_: str = "5y", interval: str = "1d", timeout: int = 25):
    from urllib.parse import urlencode as _urlenc
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    ]
    ua = random.choice(uas)
    _yf_log_step(symbol, "native.init", f"ua={ua[:40]}... range={range_}")
    common_headers = {
        "User-Agent": ua,
        "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh-Hant;q=0.9,zh;q=0.8,en-US;q=0.7,en;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": f"https://finance.yahoo.com/quote/{symbol}",
    }
    with requests.Session() as s:
        s.headers.update(common_headers)
        last_err = None
        try:
            time.sleep(random.uniform(0.6, 1.4))
            _yf_log_step(symbol, "native.warmup1", "GET finance.yahoo.com/")
            r = s.get("https://finance.yahoo.com/", timeout=min(timeout, 15), allow_redirects=True)
            _yf_log_step(symbol, "native.warmup1", f"status={r.status_code} len={len(r.content or b'')}")
        except Exception as e:
            _yf_log_step(symbol, "native.warmup1", f"EXCEPTION {type(e).__name__}: {str(e)[:120]}")
            last_err = RuntimeError(f"warmup finance.yahoo.com failed: {type(e).__name__}")
        try:
            _yf_log_step(symbol, "native.warmup2", "GET consent.yahoo.com ...")
            s.get("https://consent.yahoo.com/v2/collectConsent?sessionId=3_cc-session_" + str(int(time.time()*1000)),
                  timeout=min(timeout, 10), allow_redirects=True)
        except Exception as e_w:
            _yf_log_step(symbol, "native.warmup2", f"EXCEPTION {type(e_w).__name__}")

        time.sleep(random.uniform(0.8, 1.6))

        p_basic = {"range": range_, "interval": interval,
                   "includeAdjustedClose": "false", "includePrePost": "false"}
        p_ev = {**p_basic, "events": "div%2Csplits%2CcapitalGains"}
        def make_urls(host):
            return [
                f"https://{host}/v8/finance/chart/{symbol}?{_urlenc(p_ev)}",
                f"https://{host}/v8/finance/chart/{symbol}?{_urlenc(p_basic)}",
            ]
        base_urls = (make_urls("query1.finance.yahoo.com") +
                     make_urls("query2.finance.yahoo.com"))
        _yf_log_step(symbol, "native.urls", f"count={len(base_urls)} first={base_urls[0].split('?')[0]}")
        for idx, url in enumerate(base_urls):
            try:
                time.sleep(random.uniform(1.2, 2.8))
                _yf_log_step(symbol, f"native.req[{idx}]", f"GET {url.split('//')[1].split('?')[0]}")
                r = s.get(url, timeout=timeout, allow_redirects=True)
                body_len = len(r.content or b"")
                body_snip = ""
                try:
                    body_snip = (r.text or "")[:160]
                except Exception:
                    pass
                _yf_log_step(symbol, f"native.req[{idx}]", f"status={r.status_code} len={body_len} snip={body_snip}")
                if r.status_code != 200:
                    last_err = RuntimeError(f"HTTP {r.status_code} @ {url.split('//')[1].split('?')[0][:36]} | {body_snip}")
                    _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                    continue
                try:
                    data = r.json()
                except Exception as je:
                    last_err = RuntimeError(f"chart JSON parse failed: {je} | head={body_snip}")
                    _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                    continue
                result_l = data.get("chart", {}).get("result") or []
                if not result_l:
                    err = (data.get("chart", {}).get("error") or {})
                    last_err = RuntimeError(f"chart empty result: code={err.get('code')} desc={str(err.get('description',''))[:100]}")
                    _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                    continue
                result = result_l[0]
                meta = result.get("meta") or {}
                _yf_log_step(symbol, f"native.req[{idx}]",
                             f"meta symbol={meta.get('symbol')} currency={meta.get('currency')} ts_len={len(result.get('timestamp') or [])}")
                ts = result.get("timestamp") or []
                q = (result.get("indicators") or {}).get("quote") or []
                if not ts or not q:
                    last_err = RuntimeError("chart missing timestamp/quote")
                    _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                    continue
                quote = q[0]
                index = pd.to_datetime(ts, unit="s", utc=True).tz_convert(None)
                o = quote.get("open") or []
                h = quote.get("high") or []
                lo = quote.get("low") or []
                c = quote.get("close") or []
                v = quote.get("volume") or []
                n = min(len(index), len(o), len(h), len(lo), len(c), len(v))
                if n < 10:
                    last_err = RuntimeError(f"chart rows too few ({n})")
                    _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                    continue
                df = pd.DataFrame({
                    "Open": o[:n], "High": h[:n], "Low": lo[:n],
                    "Close": c[:n], "Volume": v[:n],
                }, index=index[:n])
                _yf_log_step(symbol, f"native.req[{idx}]", f"SUCCESS rows={len(df)} close_last={df['Close'].iloc[-1] if len(df) else '?'}")
                return df, None
            except Exception as e:
                last_err = RuntimeError(f"{type(e).__name__}: {str(e)[:180]}")
                _persist_last_error(symbol, f"native[{idx}]", str(last_err))
                _yf_log_step(symbol, f"native.req[{idx}]", f"EXCEPTION {type(e).__name__}: {str(e)[:140]}")
                continue
    raise RuntimeError(f"native yahoo chart failed: {last_err}")


# ---------------------------------------------------------------------------
# Route 3: Stooq CSV (mirror app.py L3137)
# ---------------------------------------------------------------------------
def _native_stooq_download(symbol: str, period_years: int = 5, timeout: int = 25):
    _yf_log_step(symbol, "stooq.init", f"period={period_years}y symbol={symbol}")
    try:
        stooq_sym = symbol
        to_d = datetime.now()
        from_d = to_d - timedelta(days=int(period_years * 365.25) + 20)
        d1, m1, y1 = str(from_d.day).zfill(2), str(from_d.month).zfill(2), str(from_d.year)
        d2, m2, y2 = str(to_d.day).zfill(2), str(to_d.month).zfill(2), str(to_d.year)
        uas_stooq = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
        ]
        hdrs = {
            "User-Agent": random.choice(uas_stooq),
            "Accept": "text/csv,text/html,*/*;q=0.6",
            "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.7",
        }
        urls = [
            f"https://stooq.com/q/d/l/?s={stooq_sym}&d1={y1}{m1}{d1}&d2={y2}{m2}{d2}&i=d",
            f"https://stooq.pl/q/d/l/?s={stooq_sym}&d1={y1}{m1}{d1}&d2={y2}{m2}{d2}&i=d",
        ]
        _yf_log_step(symbol, "stooq.urls", f"count={len(urls)} first_s={stooq_sym}")
        last_err = None
        for idx, url in enumerate(urls):
            try:
                time.sleep(random.uniform(0.3, 0.8))
                _yf_log_step(symbol, f"stooq.req[{idx}]", f"GET {url.split('//')[1].split('&')[0]}")
                r = requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
                body = r.text or ""
                _yf_log_step(symbol, f"stooq.req[{idx}]", f"status={r.status_code} len={len(body)} snip={body[:120]}")
                if r.status_code != 200 or "Date,Open,High,Low,Close,Volume" not in body:
                    last_err = RuntimeError(f"Stooq[{idx}] invalid resp status={r.status_code} | head={body[:100]}")
                    _persist_last_error(symbol, f"stooq[{idx}]", str(last_err))
                    continue
                try:
                    df = pd.read_csv(StringIO(body), parse_dates=["Date"])
                except Exception as pe:
                    last_err = RuntimeError(f"Stooq[{idx}] csv parse failed: {pe}")
                    _persist_last_error(symbol, f"stooq[{idx}]", str(last_err))
                    continue
                if len(df) < 20 or "Close" not in df.columns:
                    last_err = RuntimeError(f"Stooq[{idx}] rows too few ({len(df)}) or no Close")
                    _persist_last_error(symbol, f"stooq[{idx}]", str(last_err))
                    continue
                df = df.rename(columns={"Date": "Date"}).set_index("Date").sort_index()
                df.index = pd.to_datetime(df.index)
                df.columns = [c if c in ("Open","High","Low","Close","Volume") else c.capitalize() for c in df.columns]
                for col in ("Open","High","Low","Close","Volume"):
                    if col not in df.columns:
                        df[col] = np.nan
                df = df[["Open","High","Low","Close","Volume"]]
                df = df.dropna(subset=["Close"])
                if len(df) < 20:
                    last_err = RuntimeError(f"Stooq[{idx}] after dropna rows too few ({len(df)})")
                    _persist_last_error(symbol, f"stooq[{idx}]", str(last_err))
                    continue
                _yf_log_step(symbol, f"stooq.req[{idx}]", f"SUCCESS rows={len(df)} close_last={float(df['Close'].iloc[-1])}")
                return df, None
            except Exception as e:
                last_err = RuntimeError(f"Stooq[{idx}] {type(e).__name__}: {str(e)[:160]}")
                _persist_last_error(symbol, f"stooq[{idx}]", str(last_err))
                _yf_log_step(symbol, f"stooq.req[{idx}]", f"EXCEPTION {type(e).__name__}: {str(e)[:120]}")
                continue
        raise RuntimeError(f"Stooq all failed: {last_err}")
    except Exception as e_out:
        raise RuntimeError(f"Stooq outer: {type(e_out).__name__}: {str(e_out)[:160]}") from e_out


# ---------------------------------------------------------------------------
# Route 2: yfinance download (mirror app.py L3211)
# ---------------------------------------------------------------------------
def _try_yfinance_download(symbol, period: str = "5y", timeout: int = 30):
    try:
        sess = _YF_SESS_MGR.get_session()
        if sess is not None:
            try:
                yf_sess_getter = getattr(yf, "_get_session", None)
                if callable(yf_sess_getter):
                    yf_cur = yf_sess_getter()
                    if yf_cur is not None:
                        for k, val in sess.headers.items():
                            try:
                                yf_cur.headers[k] = val
                            except Exception:
                                continue
            except Exception:
                pass
        try:
            _persist_last_error(symbol, "yfinance", f"Ticker.history period={period} repair=True")
            t = yf.Ticker(symbol)
            df = t.history(period=period, auto_adjust=False, actions=False,
                           repair=True, timeout=timeout)
        except Exception:
            _persist_last_error(symbol, "yfinance", f"Ticker.history failed -> fallback download()")
            df = yf.download(symbol, period=period, progress=False, auto_adjust=False, timeout=timeout, actions=False)
        if df is None or df.empty:
            raise RuntimeError("yfinance returned empty DataFrame")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        share_base = None
        try:
            t2 = yf.Ticker(symbol)
            share_base, _ = _resolve_share_base_post(df, symbol)
        except Exception:
            share_base = None
        return df, share_base
    except Exception as exc:
        msg = str(exc) or ""
        name = type(exc).__name__
        short = f"{name}: {msg[:180]}"
        _persist_last_error(symbol, "yfinance", short)
        raise RuntimeError(short) from exc


# ---------------------------------------------------------------------------
# Route 4: Sina HK K-line (mirror app.py L3258)
# ---------------------------------------------------------------------------
def _native_sina_download(symbol: str, timeout: int = 25):
    import json as _json
    _yf_log_step(symbol, "sina.init", f"symbol={symbol}")
    try:
        digits = re.sub(r"\D", "", symbol)
        if not digits:
            raise RuntimeError(f"sina: symbol {symbol} no digits")
        hk_code = f"hk{digits.zfill(5)}" if len(digits) <= 5 else f"hk{digits}"
        hdrs = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
            ]),
            "Accept": "application/json,text/plain,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
            "Referer": "https://finance.sina.com.cn/",
        }
        urls = [
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={hk_code}&scale=240&ma=no&datalen=1500",
            f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={hk_code}&scale=240&ma=no&datalen=1500",
        ]
        _yf_log_step(symbol, "sina.urls", f"hk_code={hk_code} count={len(urls)}")
        last_err = None
        for idx, url in enumerate(urls):
            try:
                time.sleep(random.uniform(0.3, 0.9))
                _yf_log_step(symbol, f"sina.req[{idx}]", f"GET {url.split('//')[1].split('?')[0]}")
                r = requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
                raw = (r.text or "").strip()
                _yf_log_step(symbol, f"sina.req[{idx}]", f"status={r.status_code} len={len(raw)} snip={raw[:140]}")
                if r.status_code != 200 or not raw:
                    last_err = RuntimeError(f"sina[{idx}] empty/status={r.status_code} | head={raw[:100]}")
                    _persist_last_error(symbol, f"sina[{idx}]", str(last_err))
                    continue
                if raw.startswith("(") and raw.endswith(")"):
                    raw = raw[1:-1]
                try:
                    arr = _json.loads(raw)
                except Exception as je:
                    last_err = RuntimeError(f"sina[{idx}] JSON parse: {je} | head={raw[:120]}")
                    _persist_last_error(symbol, f"sina[{idx}]", str(last_err))
                    continue
                if not isinstance(arr, list) or len(arr) < 20:
                    last_err = RuntimeError(f"sina[{idx}] rows too few ({len(arr) if isinstance(arr, list) else type(arr)})")
                    _persist_last_error(symbol, f"sina[{idx}]", str(last_err))
                    continue
                dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
                ok = 0
                for item in arr:
                    if not isinstance(item, dict): continue
                    try:
                        d = item.get("day") or item.get("date") or item.get("time")
                        o = float(item.get("open") or 0)
                        h = float(item.get("high") or 0)
                        l = float(item.get("low") or 0)
                        c = float(item.get("close") or 0)
                        v = float(item.get("volume") or 0)
                        if not d or o <= 0 or c <= 0 or h <= 0 or l <= 0:
                            continue
                        dates.append(pd.to_datetime(d))
                        opens.append(o); highs.append(h); lows.append(l); closes.append(c); volumes.append(int(v))
                        ok += 1
                    except Exception:
                        continue
                if ok < 20:
                    last_err = RuntimeError(f"sina[{idx}] valid rows too few ({ok})")
                    _persist_last_error(symbol, f"sina[{idx}]", str(last_err))
                    continue
                df = pd.DataFrame({
                    "Open": opens, "High": highs, "Low": lows,
                    "Close": closes, "Volume": volumes,
                }, index=dates)
                df = df.sort_index()
                _yf_log_step(symbol, f"sina.req[{idx}]", f"SUCCESS rows={len(df)} close_last={float(df['Close'].iloc[-1])}")
                return df, None
            except Exception as e:
                last_err = RuntimeError(f"sina[{idx}] {type(e).__name__}: {str(e)[:160]}")
                _persist_last_error(symbol, f"sina[{idx}]", str(last_err))
                _yf_log_step(symbol, f"sina.req[{idx}]", f"EXCEPTION {type(e).__name__}: {str(e)[:120]}")
                continue
        raise RuntimeError(f"sina all failed: {last_err}")
    except Exception as e_out:
        raise RuntimeError(f"sina outer: {type(e_out).__name__}: {str(e_out)[:160]}") from e_out


# ---------------------------------------------------------------------------
# Master stack: 4-route get_data (mirror app.py get_data_v7, NO st.cache_data)
# ---------------------------------------------------------------------------
def _finalize_df_and_return(df: pd.DataFrame, sym_used: str, orig_symbol: str,
                            end_date, route_key: str) -> Optional[Tuple[Optional[pd.DataFrame], Any]]:
    """Shared finalize: apply end_date filter, resolve share_base (fallback Volume/0.35%), return."""
    if end_date is not None:
        df = df[df.index <= pd.to_datetime(end_date)]
    if df is None or len(df) <= 5:
        return None
    share_base = None
    try:
        share_base, _sb_note = _resolve_share_base_post(df, sym_used)
    except Exception:
        share_base = None
    # Belt-and-suspenders: if share_base still 0/None/NaN, re-derive from df Volume
    if share_base is None or not (pd.notna(share_base) and float(share_base) > 0):
        try:
            if df is not None and "Volume" in df.columns and len(df) >= 10:
                vol = pd.to_numeric(df["Volume"], errors="coerce")
                tail = vol.tail(120).replace(0, np.nan).dropna()
                if len(tail) >= 10:
                    avg_v = float(tail.mean())
                    if avg_v > 0:
                        approx_sb = avg_v / 0.0035  # 120d avg volume / 35 bps turnover
                        if np.isfinite(approx_sb) and approx_sb > 0:
                            share_base = float(approx_sb)
        except Exception:
            pass
    _YF_SESS_MGR.record_success(orig_symbol)
    _NATIVE_DOWNLOAD_STATS[f"{route_key}_success"] = _NATIVE_DOWNLOAD_STATS.get(f"{route_key}_success", 0) + 1
    _persist_last_error(orig_symbol, route_key, f"OK rows={len(df)} sym_used={sym_used}")
    return df, share_base


def get_data_stack(symbol, end_date=None) -> Tuple[Optional[pd.DataFrame], Any]:
    """Returns (df, share_base) on success, else (None, None).

    G3: For every route, first try a list of ticker aliases
    (e.g. 0011.HK / 0011.hk / 11.HK / 00011.HK) to handle provider-specific
    ticker naming conventions that otherwise produce rows=0.
    """
    last_err = None
    if _YF_SESS_MGR.should_skip(symbol):
        return None, None
    aliases = _build_ticker_aliases(symbol) or [str(symbol).strip()]
    # Cap aliases per route (first 4 is enough for most HK ticker oddities)
    yahoo_aliases = aliases[:4]
    stooq_aliases = aliases[:6]
    # Sina extracts digits internally; try the original+canonical aliases for its digit parser
    sina_aliases = aliases[:3] + [str(symbol).strip()]

    for attempt in range(3):
        # --- Route 1: native yahoo (try yahoo aliases) ---
        _NATIVE_DOWNLOAD_STATS["native_attempts"] = _NATIVE_DOWNLOAD_STATS.get("native_attempts", 0) + 1
        for alias in yahoo_aliases:
            try:
                df, _sb = _native_yahoo_chart_download(alias, range_="5y", interval="1d", timeout=25)
                if df is not None and len(df) > 5:
                    ret = _finalize_df_and_return(df, alias, symbol, end_date, "native")
                    if ret is not None:
                        return ret
            except Exception as exc_native:
                last_err = exc_native

        # --- Route 2: yfinance (try yahoo aliases) ---
        _NATIVE_DOWNLOAD_STATS["yf_attempts"] = _NATIVE_DOWNLOAD_STATS.get("yf_attempts", 0) + 1
        for alias in yahoo_aliases:
            try:
                df, _sb = _try_yfinance_download(alias, period="5y", timeout=30)
                if df is not None and len(df) > 5:
                    ret = _finalize_df_and_return(df, alias, symbol, end_date, "yf")
                    if ret is not None:
                        return ret
            except Exception as exc_yf:
                last_err = exc_yf

        # --- Route 3: Stooq (try stooq aliases including 5-digit 00011.HK) ---
        _NATIVE_DOWNLOAD_STATS["stooq_attempts"] = _NATIVE_DOWNLOAD_STATS.get("stooq_attempts", 0) + 1
        for alias in stooq_aliases:
            try:
                df, _sb = _native_stooq_download(alias, period_years=5, timeout=25)
                if df is not None and len(df) > 5:
                    ret = _finalize_df_and_return(df, alias, symbol, end_date, "stooq")
                    if ret is not None:
                        return ret
            except Exception as exc_stooq:
                last_err = exc_stooq

        # --- Route 4: Sina (try sina aliases; it builds hk_code internally from digits) ---
        _NATIVE_DOWNLOAD_STATS["sina_attempts"] = _NATIVE_DOWNLOAD_STATS.get("sina_attempts", 0) + 1
        for alias in sina_aliases:
            try:
                df, _sb = _native_sina_download(alias, timeout=25)
                if df is not None and len(df) > 5:
                    ret = _finalize_df_and_return(df, alias, symbol, end_date, "sina")
                    if ret is not None:
                        return ret
            except Exception as exc_sina:
                last_err = exc_sina

        msg = str(last_err) or ""
        name = type(last_err).__name__
        if attempt < 2 and ("Invalid Crumb" in msg or "Unauthorized" in msg or "RateLimit" in name
                            or "Too Many Requests" in msg or "HTTP 40" in msg or "HTTP 5" in msg
                            or "empty" in msg.lower()):
            backoff = (2 ** attempt) * (1.0 + random.random())
            time.sleep(backoff)
            continue
        LOGGER.warning("Failed to load data for %s (attempt %s): %s", symbol, attempt+1, last_err)
        break
    _YF_SESS_MGR.record_failure(symbol, cooldown_sec=180)
    _persist_last_error(symbol, "final", f"ALL 3 attempts failed | last={type(last_err).__name__}: {str(last_err)[:160]}")
    return None, None


def get_download_stats() -> Dict[str, Any]:
    return dict(_NATIVE_DOWNLOAD_STATS)
