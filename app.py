import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import json
import logging
import os
import time
import random
import shutil
import tempfile
import zipfile
from pathlib import Path
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from tempfile import gettempdir
from streamlit.errors import StreamlitSecretNotFoundError
from providers import (
    CSVFloatProvider,
    CSVShareBaseProvider,
    CompositeShareBaseProvider,
    ShareBaseLookupResult,
    YahooShareBaseProvider,
)
from turnover_utils import (
    TURNOVER_STATUS_CALCULATED,
    apply_turnover_rate,
)
from watchlist_storage import (
    delete_watchlist_symbol,
    get_watchlist_from_firestore,
    save_watchlist_symbol,
)

# --- Optional async SQLite cache layer (graceful degrade if module missing) ---
_CACHE_LAYER_OK = False
_get_cached_ohlcv = None
_request_async_fetch = None
_upsert_ohlcv = None
_get_queue_depth = None
_get_all_cache_stats = None
_ensure_cache_schema = None
_get_cache_db_path = None
_list_cached_symbols = None
_get_stat = None
_set_stat = None

_ARTIFACT_SYNC_OK = False
_ARTIFACT_LAST_SYNC_TS = ""
_ARTIFACT_CACHED_N = 0
_ARTIFACT_LAST_ERROR = ""

_GH_OWNER = "Ss060201"
_GH_REPO = "hk_stock_sma"
_GH_ARTIFACT_NAME = "ohlcv-cache-artifact-v5"
_A1_SYNC_TTL_SEC = 9 * 60
_A1_MIN_VALID_CACHED = 5


def _a1_read_gh_token() -> Optional[str]:
    for k in ("GH_PAT", "GITHUB_TOKEN"):
        v = os.environ.get(k)
        if v and str(v).strip():
            return str(v).strip()
    try:
        for k in ("GH_PAT", "GITHUB_TOKEN"):
            try:
                v = st.secrets.get(k) if hasattr(st, "secrets") else None
            except StreamlitSecretNotFoundError:
                v = None
            if v and str(v).strip():
                return str(v).strip()
    except Exception:
        pass
    return None


def _a1_fetch_latest_artifact_impl(gh_token: str) -> Tuple[bool, str, int, str]:
    log = logging.getLogger(__name__)
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "hk-stock-sma-a1-sync/1.0",
    }
    tmp_dir = tempfile.mkdtemp(prefix="a1_artifact_")
    try:
        list_url = (
            f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/artifacts"
            f"?name={requests.utils.quote(_GH_ARTIFACT_NAME)}&per_page=1"
        )
        r1 = requests.get(list_url, headers=headers, timeout=30, allow_redirects=True)
        if r1.status_code != 200:
            return False, "", 0, f"artifact_list HTTP {r1.status_code}"
        try:
            j1 = r1.json()
        except Exception:
            return False, "", 0, "artifact_list json parse failed"
        arts = j1.get("artifacts") or []
        if not arts:
            return False, "", 0, f"no artifact named {_GH_ARTIFACT_NAME}"
        dl_url = arts[0].get("archive_download_url")
        if not dl_url:
            return False, "", 0, "missing archive_download_url"
        r2 = requests.get(dl_url, headers=headers, timeout=120, allow_redirects=True, stream=True)
        if r2.status_code != 200:
            return False, "", 0, f"artifact_download HTTP {r2.status_code}"
        zip_path = os.path.join(tmp_dir, "a1_artifact.zip")
        with open(zip_path, "wb") as fz:
            for chunk in r2.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fz.write(chunk)
        if os.path.getsize(zip_path) < 20 * 1024:
            return False, "", 0, "artifact zip too small (<20KB)"
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                target = None
                for n in names:
                    base = os.path.basename(n)
                    if base == "ohlcv_cache.sqlite" and not n.endswith("/"):
                        target = n
                        break
                if target is None:
                    return False, "", 0, "zip missing ohlcv_cache.sqlite"
                zf.extract(target, tmp_dir)
                tmp_db_path = os.path.join(tmp_dir, target)
        except zipfile.BadZipFile:
            return False, "", 0, "bad zip file"
        except Exception as e:
            return False, "", 0, f"zip extract error: {type(e).__name__}"
        if os.path.getsize(tmp_db_path) < 50 * 1024:
            return False, "", 0, "sqlite too small (<50KB)"
        try:
            if _ensure_cache_schema is not None:
                _ensure_cache_schema(tmp_db_path)
        except Exception as e:
            return False, "", 0, f"ensure_schema error: {type(e).__name__}"
        valid_n = 0
        try:
            if _list_cached_symbols is not None:
                rows = _list_cached_symbols(db_path=tmp_db_path, limit=500)
                for r in rows:
                    if (r.get("rows") or 0) >= 100 and r.get("last_valid_close") is not None and r.get("last_trade_date"):
                        valid_n += 1
        except Exception:
            valid_n = 0
        if valid_n < _A1_MIN_VALID_CACHED:
            return False, "", valid_n, f"valid cached below threshold ({valid_n} < {_A1_MIN_VALID_CACHED})"
        final_db_path = _get_cache_db_path() if _get_cache_db_path is not None else None
        if not final_db_path:
            return False, "", valid_n, "get_cache_db_path not available"
        try:
            os.makedirs(os.path.dirname(final_db_path), exist_ok=True)
        except Exception:
            pass
        try:
            if os.path.exists(final_db_path):
                try:
                    mt = os.path.getmtime(final_db_path)
                    if time.time() - mt < _A1_SYNC_TTL_SEC:
                        return True, datetime.now().strftime("%Y-%m-%d %H:%M"), valid_n, "existing_db_fresh"
                except Exception:
                    pass
        except Exception:
            pass
        try:
            os.replace(tmp_db_path, final_db_path)
        except Exception:
            try:
                shutil.copy2(tmp_db_path, final_db_path)
            except Exception as e2:
                return False, "", valid_n, f"db replace error: {type(e2).__name__}"
        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            if _set_stat is not None:
                _set_stat("a1_last_sync_ts", ts_now, db_path=final_db_path)
                _set_stat("a1_last_valid_n", valid_n, db_path=final_db_path)
        except Exception:
            pass
        return True, ts_now, valid_n, ""
    except Exception as e:
        return False, "", 0, f"unexpected: {type(e).__name__}"
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _a1_sync_artifact_v5() -> bool:
    global _ARTIFACT_SYNC_OK, _ARTIFACT_LAST_SYNC_TS, _ARTIFACT_CACHED_N, _ARTIFACT_LAST_ERROR
    log = logging.getLogger(__name__)
    token = _a1_read_gh_token()
    if not token:
        _ARTIFACT_LAST_ERROR = "GH_PAT/GITHUB_TOKEN not set"
        _ARTIFACT_SYNC_OK = False
        return False
    if _get_stat is not None:
        try:
            dbp = _get_cache_db_path() if _get_cache_db_path is not None else None
            cached_ts = None
            if dbp and os.path.exists(dbp):
                try:
                    cached_ts = _get_stat("a1_last_sync_ts", None, db_path=dbp)
                except Exception:
                    cached_ts = None
            if cached_ts:
                try:
                    dt = datetime.strptime(str(cached_ts), "%Y-%m-%d %H:%M")
                    age = (datetime.now() - dt).total_seconds()
                    if age < _A1_SYNC_TTL_SEC:
                        try:
                            valid_n = _get_stat("a1_last_valid_n", 0, db_path=dbp) or 0
                        except Exception:
                            valid_n = 0
                        if valid_n >= _A1_MIN_VALID_CACHED:
                            _ARTIFACT_SYNC_OK = True
                            _ARTIFACT_LAST_SYNC_TS = str(cached_ts)
                            _ARTIFACT_CACHED_N = int(valid_n)
                            _ARTIFACT_LAST_ERROR = ""
                            return True
                except Exception:
                    pass
        except Exception:
            pass
    try:
        ok, ts, vn, err = _a1_fetch_latest_artifact_cached(token)
    except Exception as e:
        ok, ts, vn, err = False, "", 0, f"cached_call: {type(e).__name__}"
    _ARTIFACT_SYNC_OK = bool(ok)
    if ok:
        _ARTIFACT_LAST_SYNC_TS = ts or datetime.now().strftime("%Y-%m-%d %H:%M")
        _ARTIFACT_CACHED_N = int(vn)
        _ARTIFACT_LAST_ERROR = ""
    else:
        _ARTIFACT_LAST_SYNC_TS = ts or ""
        _ARTIFACT_CACHED_N = int(vn)
        _ARTIFACT_LAST_ERROR = err or "unknown error"
        log.warning("A1 artifact sync failed: %s", _ARTIFACT_LAST_ERROR)
    return bool(ok)


@st.cache_resource(ttl=_A1_SYNC_TTL_SEC, show_spinner=False)
def _a1_fetch_latest_artifact_cached(gh_token: str):
    return _a1_fetch_latest_artifact_impl(gh_token)


try:
    from cache_layer import (
        ensure_schema as _ensure_cache_schema,
        get_all_stats as _get_all_cache_stats,
        get_cached_ohlcv as _get_cached_ohlcv,
        get_queue_depth as _get_queue_depth,
        request_async_fetch as _request_async_fetch,
        upsert_ohlcv as _upsert_ohlcv,
        get_cache_db_path as _get_cache_db_path,
        list_cached_symbols as _list_cached_symbols,
        get_stat as _get_stat,
        set_stat as _set_stat,
    )
    try:
        _a1_sync_artifact_v5()
    except Exception as _exc_a1:
        _ARTIFACT_SYNC_OK = False
        _ARTIFACT_LAST_ERROR = f"a1_sync_exception: {type(_exc_a1).__name__}"
    try:
        _ensure_cache_schema(None)
        _CACHE_LAYER_OK = True
    except Exception as _exc_cache_init:
        LOGGER.warning("SQLite cache layer init failed (will use live fetch only): %s", _exc_cache_init)
        _CACHE_LAYER_OK = False
except Exception as _exc_cache_import:
    LOGGER.info("cache_layer module not found (daemon may not be installed): %s", _exc_cache_import)
    _CACHE_LAYER_OK = False

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

LOGGER = logging.getLogger(__name__)

# yfinance crumb 穩定化：指定 TZ cache 到可寫 temp 目錄 + 升級 session UA
try:
    _yf_tz_dir = Path(gettempdir()) / "hk_stock_sma_yf_tzcache"
    _yf_tz_dir.mkdir(parents=True, exist_ok=True)
    try:
        yf.set_tz_cache_location(str(_yf_tz_dir))
    except Exception:
        pass
except Exception:
    pass
_YF_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

# yfinance session 共享管理器 + 錯誤黑名單 (連續失敗 N 次後 M 秒內不重試)
class _YFSessionManager:
    def __init__(self):
        self._sessions: List[Any] = []
        self._last_refresh = 0.0
        self._error_count: Dict[str, int] = {}     # ticker -> 連續失敗次數
        self._error_until: Dict[str, float] = {}   # ticker -> 時間戳(秒)，在此之前 skip
        self._lock = None
        try:
            import threading as _th
            self._lock = _th.RLock()
        except Exception:
            self._lock = None

    def _acquire(self):
        if self._lock is not None:
            self._lock.acquire()

    def _release(self):
        if self._lock is not None:
            self._lock.release()

    def _maybe_refresh_sessions(self) -> None:
        import time as _t
        now = _t.time()
        if self._sessions and (now - self._last_refresh) < 600:
            return
        new_sessions = []
        try:
            for ua in _YF_UAS:
                try:
                    sess = requests.Session()
                    sess.headers["User-Agent"] = ua
                    sess.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    sess.headers["Accept-Language"] = "en-US,en;q=0.9,zh-HK;q=0.8,zh;q=0.7"
                    new_sessions.append(sess)
                except Exception:
                    continue
            if new_sessions:
                self._sessions = new_sessions
                self._last_refresh = now
                # 嘗試把 session 掛到 yfinance 全域
                yf_sess_getter = getattr(yf, "_get_session", None)
                if callable(yf_sess_getter):
                    try:
                        cur = yf_sess_getter()
                        if cur is not None and new_sessions:
                            cur.headers["User-Agent"] = new_sessions[0].headers["User-Agent"]
                            cur.headers.update(new_sessions[0].headers)
                    except Exception:
                        pass
        except Exception:
            pass

    def should_skip(self, ticker: str):
        import time as _t
        self._acquire()
        try:
            until = self._error_until.get(ticker, 0.0)
            if until and _t.time() < until:
                return True
            return False
        finally:
            self._release()

    def get_session(self):
        import random as _r, time as _t
        self._acquire()
        try:
            self._maybe_refresh_sessions()
            if self._sessions:
                return self._sessions[_r.randint(0, len(self._sessions) - 1)]
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
        import time as _t
        self._acquire()
        try:
            c = (self._error_count.get(ticker, 0) or 0) + 1
            self._error_count[ticker] = c
            if c >= 2:
                self._error_until[ticker] = _t.time() + cooldown_sec
        finally:
            self._release()

_YF_SESS_MGR = _YFSessionManager()

_APP_BUILD = {
    "commit": "d2ab411+daemonCache2",
    "time": "2026-09-02 22:30",
    "tag": "新增 SQLite 永續快取 + 背景守護程序 (data_fetcher_daemon.py)；首頁/單股 get_data_v7 優先讀快取，miss 則後台補採集 + 前台同步回填；節流延遲節奏嚴格保留；Build 雙端鏡像；監控指標(hit/miss/429)",
}
try:
    _APP_BUILD["yf_version"] = getattr(yf, "__version__", "n/a")
except Exception:
    _APP_BUILD["yf_version"] = "n/a"

# yfinance 版本緊急守門員：如果偵測到 1.x，直接用原生 requests 做 download，避免 Invalid Crumb 401
try:
    _yfv_parts = [int(p) for p in (getattr(yf, "__version__", "0.0.0") or "0.0.0").split(".") if p.isdigit()]
    _YF_VER_MAJOR = _yfv_parts[0] if _yfv_parts else 0
except Exception:
    _YF_VER_MAJOR = 0
_YF_IS_BROKEN_V1 = _YF_VER_MAJOR >= 1
if _YF_IS_BROKEN_V1:
    try:
        import warnings as _w
        _w.filterwarnings("ignore", message=".*yfinance.*1\\..*")
    except Exception:
        pass

# --- 2. CSS 樣式 (合併 v9.4 與 v9.6) ---
st.markdown("""
<style>
    :root {
        --mobile-padding: 8px;
        --desktop-padding: 16px;
        --card-radius: 8px;
        --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
        --shadow-md: 0 4px 6px rgba(0,0,0,0.10);
    }
    * {
        box-sizing: border-box;
        -webkit-tap-highlight-color: transparent;
    }
    /* 全局表格樣式 */
    .big-font-table { 
        font-size: 14px !important; 
        width: 100%; 
        border-collapse: collapse; 
        text-align: center; 
        font-family: 'Arial', sans-serif;
        margin-bottom: 20px;
    }
    .big-font-table th { 
        background-color: #f8f9fa; 
        color: #212529; 
        padding: 10px; 
        border: 1px solid #dee2e6; 
        font-weight: bold; 
    }
    .big-font-table td { 
        padding: 8px; 
        border: 1px solid #dee2e6; 
        color: #31333F; 
    }
    /* 第一欄樣式 */
    .big-font-table td:first-child {
        font-weight: bold;
        text-align: left;
        background-color: #fff;
        width: 140px;
    }
    /* 數值顏色 */
    .pos-val { color: #d9534f; font-weight: bold; } /* 紅色 */
    .neg-val { color: #28a745; font-weight: bold; } /* 綠色 */
    
    /* v9.6 特有樣式 (Header/Data Rows) */
    .header-row td {
        background-color: #ffffff !important; 
        font-weight: bold;
        color: #000;
        border-bottom: 2px solid #dee2e6;
    }
    .data-row td {
        background-color: #d4edda !important; /* 淺綠背景 */
        color: #000;
        font-weight: normal;
    }
    .section-title {
        background-color: #FFFF00 !important; /* 黃色背景 */
        color: #000;
        font-weight: bold;
        text-align: left;
        padding: 10px;
        font-size: 16px;
        border: 1px solid #dee2e6;
    }
    
    /* 按鈕樣式 */
    .stButton>button { width: 100%; min-height: 44px; padding: 12px 16px !important; border-radius: 6px; font-size: 14px; box-shadow: var(--shadow-sm); }
    .stButton>button:active { transform: scale(0.98); box-shadow: var(--shadow-md); }
    input, textarea, select { min-height: 44px; font-size: 16px; }

    .compact-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin: 8px 0 12px 0;
    }
    .compact-card {
        background: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 10px;
        padding: 10px 12px;
        box-shadow: var(--shadow-sm);
    }
    .compact-card .label {
        font-size: 12px;
        color: #6c757d;
        margin-bottom: 4px;
        line-height: 1.2;
    }
    .compact-card .value {
        font-size: 18px;
        font-weight: 700;
        color: #31333F;
        line-height: 1.2;
    }
    .compact-card .sub {
        font-size: 12px;
        margin-top: 6px;
        line-height: 1.3;
    }
    .compact-card .sub.pos {
        color: #28a745;
        font-weight: 600;
    }
    .compact-card .sub.neg {
        color: #dc3545;
        font-weight: 600;
    }
    .signal-card {
        background: #ffffff;
        border: 1px solid #e9ecef;
        border-left: 4px solid #6c757d;
        border-radius: 10px;
        padding: 10px 12px;
        box-shadow: var(--shadow-sm);
    }
    .signal-card.trigger {
        border-left-color: #dc3545;
        background: #fff5f5;
    }
    .signal-card.idle {
        border-left-color: #adb5bd;
    }
    .signal-card .title {
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 6px;
        color: #31333F;
    }
    .signal-card .meta {
        font-size: 12px;
        color: #6c757d;
        line-height: 1.35;
    }
    .nav-card {
        background: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 10px 12px;
        margin: 0 0 8px 0;
        box-shadow: var(--shadow-sm);
    }
    .nav-card.active {
        border-color: #86b7fe;
        background: #f4f8ff;
    }
    .nav-card .nav-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
    }
    .nav-card .nav-title {
        font-size: 14px;
        font-weight: 700;
        color: #31333F;
        line-height: 1.2;
    }
    .nav-card .nav-badge {
        font-size: 10px;
        font-weight: 700;
        color: #0d6efd;
        background: #e7f1ff;
        border-radius: 999px;
        padding: 2px 8px;
        white-space: nowrap;
    }
    .nav-card .nav-desc {
        margin: 0;
        padding-left: 18px;
        color: #6c757d;
        font-size: 12px;
        line-height: 1.45;
    }
    .nav-card .nav-desc li {
        margin: 2px 0;
    }
    .compare-card {
        background: #ffffff;
        border: 1px solid #e9ecef;
        border-left: 4px solid #adb5bd;
        border-radius: 12px;
        padding: 12px;
        margin-bottom: 8px;
        box-shadow: var(--shadow-sm);
    }
    .compare-card.compare-positive {
        border-color: #d1e7dd;
        border-left-color: #198754;
        background: #f4fbf7;
    }
    .compare-card.compare-watch {
        border-color: #ffe69c;
        border-left-color: #f59f00;
        background: #fffaf0;
    }
    .compare-card.compare-risk {
        border-color: #f1c0c7;
        border-left-color: #dc3545;
        background: #fff5f5;
    }
    .compare-card-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 10px;
    }
    .compare-card-stock {
        font-size: 16px;
        font-weight: 700;
        color: #31333F;
        line-height: 1.2;
    }
    .compare-card-badge {
        font-size: 11px;
        font-weight: 700;
        color: #0d6efd;
        background: #e7f1ff;
        border-radius: 999px;
        padding: 3px 8px;
        white-space: nowrap;
    }
    .compare-card-badge.compare-positive {
        color: #0f5132;
        background: #d1e7dd;
    }
    .compare-card-badge.compare-watch {
        color: #7c5700;
        background: #fff3cd;
    }
    .compare-card-badge.compare-risk {
        color: #842029;
        background: #f8d7da;
    }
    .compare-card-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }
    .compare-card-item {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 8px 10px;
    }
    .compare-card-label {
        font-size: 11px;
        color: #6c757d;
        margin-bottom: 4px;
        line-height: 1.2;
    }
    .compare-card-value {
        font-size: 13px;
        font-weight: 700;
        color: #31333F;
        line-height: 1.3;
        word-break: break-word;
    }
    .bottom-nav-note {
        font-size: 12px;
        color: #6c757d;
        text-align: center;
        margin: 4px 0 8px 0;
    }
    .section-anchor {
        display: block;
        position: relative;
        top: -10px;
        visibility: hidden;
    }
    .home-sort-hint {
        font-size: 11px;
        color: #6c757d;
        margin: 1px 0 4px 0;
    }
    .home-summary-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 4px;
        margin: 4px 0 8px 0;
    }
    .home-summary-item {
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 6px 8px;
    }
    .home-summary-item .label {
        font-size: 10px;
        color: #6c757d;
        margin-bottom: 2px;
        line-height: 1.2;
    }
    .home-summary-item .value {
        font-size: 13px;
        font-weight: 700;
        color: #31333F;
        line-height: 1.15;
    }
    .home-stock-shell {
        background: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 8px 10px;
        margin-bottom: 8px;
        box-shadow: var(--shadow-sm);
    }
    .home-stock-shell.active {
        border-color: #86b7fe;
        background: #f8fbff;
    }
    .home-stock-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
    }
    .home-stock-title {
        font-size: 16px;
        font-weight: 800;
        color: #31333F;
        line-height: 1.1;
    }
    .home-stock-badge {
        font-size: 11px;
        font-weight: 700;
        color: #166534;
        background: #dcfce7;
        border-radius: 999px;
        padding: 2px 6px;
        white-space: nowrap;
    }
    .home-stock-metrics {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 6px;
        margin-top: 6px;
    }
    .home-stock-metric {
        background: #a3d977;
        border: 1px solid #7cb342;
        border-radius: 8px;
        padding: 6px 7px;
    }
    .home-stock-metric .label {
        font-size: 10px;
        color: #244313;
        margin-bottom: 2px;
        line-height: 1.15;
    }
    .home-stock-metric .value {
        font-size: 12px;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.2;
    }
    .home-detail-panel {
        margin: 6px 0 10px 0;
        padding: 8px;
        border: 1px solid #dbeafe;
        border-radius: 10px;
        background: #ffffff;
    }
    .home-avg-note {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: #fff3bf;
        color: #7c5700;
        font-size: 11px;
        font-weight: 700;
        margin-top: 2px;
    }
    div[data-baseweb="select"] > div {
        min-height: 44px;
        border-radius: 8px;
    }

    @media (max-width: 768px) {
        .main .block-container { padding: var(--mobile-padding) !important; padding-bottom: 88px !important; max-width: 100% !important; }
        div[data-testid="stHorizontalBlock"] { flex-direction: column !important; }
        div[data-testid="stHorizontalBlock"] > div { width: 100% !important; margin-bottom: 6px; }
        table { font-size: 12px; }
        th, td { padding: 8px; }
        .compact-grid { gap: 6px; margin: 6px 0 10px 0; }
        .compact-card, .signal-card { padding: 9px 10px; border-radius: 8px; }
        .compact-card .label { font-size: 11px; }
        .compact-card .value { font-size: 16px; }
        .compact-card .sub, .signal-card .meta { font-size: 11px; }
        .signal-card .title { font-size: 12px; }
        .nav-card { padding: 9px 10px; border-radius: 10px; }
        .nav-card .nav-title { font-size: 13px; }
        .nav-card .nav-badge { font-size: 9px; padding: 2px 6px; }
        .nav-card .nav-desc { font-size: 11px; padding-left: 16px; }
        .compare-card { padding: 10px; border-radius: 10px; }
        .compare-card-stock { font-size: 14px; }
        .compare-card-badge { font-size: 10px; padding: 2px 6px; }
        .compare-card-grid { gap: 6px; }
        .compare-card-item { padding: 7px 8px; }
        .compare-card-label { font-size: 10px; }
        .compare-card-value { font-size: 12px; }
        .bottom-nav-note { font-size: 11px; margin: 2px 0 6px 0; }
        .stButton>button { font-size: 11px; min-height: 30px; padding: 5px 8px !important; }
        .home-sort-hint { font-size: 10px; margin-bottom: 4px; }
        .home-summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; margin: 2px 0 6px 0; }
        .home-summary-item { padding: 6px 7px; border-radius: 7px; }
        .home-summary-item .label { font-size: 9px; }
        .home-summary-item .value { font-size: 12px; }
        .home-stock-shell { padding: 6px 7px; border-radius: 9px; margin-bottom: 5px; }
        .home-stock-head { margin-bottom: 4px; }
        .home-stock-title { font-size: 14px; }
        .home-stock-badge { font-size: 9px; padding: 1px 6px; }
        .home-stock-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px; }
        .home-stock-metric { padding: 5px 6px; border-radius: 7px; }
        .home-stock-metric .label { font-size: 9px; }
        .home-stock-metric .value { font-size: 11px; }
        .home-detail-panel { padding: 7px; border-radius: 9px; margin: 4px 0 8px 0; }
        .home-avg-note { font-size: 9px; padding: 1px 6px; }
    }

    @media (min-width: 1024px) {
        .main .block-container { padding: var(--desktop-padding) !important; }
    }
    .stock-row {

display:grid;

grid-template-columns:
100px
80px
80px
80px
80px
80px
80px;

gap:10px;

align-items:center;

min-width:600px;

padding:10px;

border-bottom:1px solid #ddd;

font-size:14px;

}


.stock-code {

font-weight:bold;

cursor:pointer;

}
</style>
""", unsafe_allow_html=True)

# --- 3. 數據庫連接 (Firebase) ---
def get_secrets_dict() -> Dict[str, Any]:
    try:
        return dict(st.secrets)
    except StreamlitSecretNotFoundError:
        return {}
    except Exception:
        return {}

@st.cache_resource
def get_db():
    try:
        if not firebase_admin._apps:
            secrets = get_secrets_dict()
            if "firebase" in secrets:
                firebase_cfg = secrets.get("firebase", {})
                if "json_content" in firebase_cfg:
                    try:
                        key_dict = json.loads(firebase_cfg["json_content"])
                        cred = credentials.Certificate(key_dict)
                        firebase_admin.initialize_app(cred)
                    except json.JSONDecodeError:
                        return None
                elif "private_key" in firebase_cfg:
                    try:
                        key_dict = dict(firebase_cfg)
                        if "\\n" in key_dict["private_key"]:
                            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                        cred = credentials.Certificate(key_dict)
                        firebase_admin.initialize_app(cred)
                    except Exception:
                        return None
                else:
                    return None
            elif os.path.exists("service_account.json"):
                cred = credentials.Certificate("service_account.json")
                firebase_admin.initialize_app(cred)
            else:
                return None
        db = firestore.client()
        return db
    except Exception as e:
        return None

def get_watchlist_from_db():
    try:
        now = time.time()
        cache_key = "_wl_cache_v2"
        cache_ts_key = "_wl_cache_ts_v2"
        cache_val = st.session_state.get(cache_key, None)
        cache_ts = st.session_state.get(cache_ts_key, 0.0)
        if cache_val is not None and isinstance(cache_val, dict) and (now - cache_ts) < 60.0:
            return dict(cache_val)
        db = get_db()
        if not db:
            return {}
        try:
            wl = get_watchlist_from_firestore(db)
        except Exception as e:
            try:
                doc_ref = db.collection('stock_app').document('watchlist')
                doc = doc_ref.get()
                if doc.exists:
                    wl = doc.to_dict() or {}
                else:
                    wl = {}
            except Exception:
                wl = {}
        try:
            st.session_state[cache_key] = dict(wl) if isinstance(wl, dict) else {}
            st.session_state[cache_ts_key] = now
        except Exception:
            pass
        return dict(wl) if isinstance(wl, dict) else {}
    except Exception:
        return {}


def update_stock_in_db(symbol, params=None):
    db = get_db()
    if not db:
        st.error("無法連接數據庫：Firebase 未初始化，請檢查 secrets 或 service_account.json")
        return False
    try:
        saved_symbol = save_watchlist_symbol(db, symbol, params)
        st.toast(f"已同步 {saved_symbol}", icon="☁️")
        try:
            st.session_state.pop("_wl_cache_v2", None)
            st.session_state.pop("_wl_cache_ts_v2", None)
        except Exception:
            pass
        return True
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        if len(err_msg) > 300:
            err_msg = err_msg[:300] + "..."
        st.error(f"收藏失敗：{symbol} 無法寫入資料庫。\n錯誤：{err_msg}")
        return False


def remove_stock_from_db(symbol):
    db = get_db()
    if not db:
        st.error("無法連接數據庫：Firebase 未初始化，請檢查 secrets 或 service_account.json")
        return False
    try:
        removed_symbol = delete_watchlist_symbol(db, symbol)
        st.toast(f"已移除 {removed_symbol}", icon="🗑️")
        try:
            st.session_state.pop("_wl_cache_v2", None)
            st.session_state.pop("_wl_cache_ts_v2", None)
        except Exception:
            pass
        return True
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        if len(err_msg) > 300:
            err_msg = err_msg[:300] + "..."
        st.error(f"移除失敗：{symbol} 無法從資料庫刪除。\n錯誤：{err_msg}")
        return False

# --- 4. 輔助功能與邏輯 ---
def clean_ticker_input(symbol):
    return str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")

def get_yahoo_ticker(symbol):
    if symbol.isdigit(): return f"{symbol.zfill(4)}.HK"
    return symbol

def send_telegram_msg(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload)
        if not resp.ok: return False, f"Error {resp.status_code}: {resp.text}"
        return True, "OK"
    except Exception as e: return False, str(e)

def calculate_willr(high, low, close, period):
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    denom = (highest_high - lowest_low).where((highest_high - lowest_low) != 0)
    wr = -100 * ((highest_high - close) / denom)
    return wr

def is_consecutive_down(close: pd.Series, days: int = 6) -> bool:
    try:
        if close is None or len(close) < (days + 1):
            return False
        diffs = close.diff().tail(days).dropna()
        if len(diffs) < days:
            return False
        return bool((diffs < 0).all())
    except Exception:
        return False

def _trend_score(price: float, sma7: float, sma14: float, sma28: float) -> int:
    score = 0
    if pd.notna(sma7) and pd.notna(sma14) and float(sma7) > float(sma14):
        score += 1
    if pd.notna(sma14) and pd.notna(sma28) and float(sma14) > float(sma28):
        score += 1
    if pd.notna(price) and pd.notna(sma7) and float(price) > float(sma7):
        score += 1
    return score

def _trend_icon(score: int) -> str:
    if score >= 3:
        return "⬆️⬆️⬆️"
    if score == 2:
        return "⬆️⬆️"
    if score == 1:
        return "⬆️"
    return "⬇️⬇️⬇️"

def _mr_rating(mr_pct: float) -> str:
    v = abs(float(mr_pct)) if pd.notna(mr_pct) else 0.0
    if v > 5:
        return "🔴 極度"
    if 3 < v <= 5:
        return "🟠 中度"
    if 1 < v <= 3:
        return "🟡 輕度"
    return "🟢 正常"

def _mr_recommendation(trend_icon: str, mr_pct: float) -> str:
    v = abs(float(mr_pct)) if pd.notna(mr_pct) else 0.0
    if trend_icon == "⬆️⬆️⬆️" and (1 < v <= 5):
        return "⭐⭐⭐"
    if trend_icon == "⬆️⬆️" and (2 < v <= 6):
        return "⭐⭐"
    if trend_icon == "⬇️⬇️⬇️" and v > 3:
        return "⚠️ 謹慎"
    return "⭐"

def _cdm_metrics(df: pd.DataFrame, params: dict) -> dict:
    out = {
        "configured": False,
        "status": "⚙️ 未配置",
        "target": np.nan,
        "diff_pct": np.nan,
        "tor_ok": None,
        "sma_ok": None,
        "confidence": 0.0,
        "tor_info": "TOR: N/A",
    }

    try:
        b1_s = params.get("box1_start")
        b1_e = params.get("box1_end")
        b2_s = params.get("box2_start")
        b2_e = params.get("box2_end")
        if not (b1_s and b1_e and b2_s and b2_e):
            return out

        CDM_COEF1, CDM_COEF2 = 0.7, 0.5
        s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
        s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)

        def _parse_float(v):
            try:
                if v is None:
                    return np.nan
                if isinstance(v, str) and (not v.strip()):
                    return np.nan
                return float(v)
            except Exception:
                return np.nan

        p1_avg_override = _parse_float(params.get("cdm_p1_avg_override"))
        p2_avg_override = _parse_float(params.get("cdm_p2_avg_override"))

        sma1_calc = df[(df.index >= s1) & (df.index <= e1)]["Close"].mean()
        sma2_calc = df[(df.index >= s2) & (df.index <= e2)]["Close"].mean()

        sma1 = p1_avg_override if (pd.notna(p1_avg_override) and p1_avg_override > 0) else sma1_calc
        sma2 = p2_avg_override if (pd.notna(p2_avg_override) and p2_avg_override > 0) else sma2_calc

        t1_days = (e1 - s1).days
        n_days = (pd.to_datetime(datetime.now().date()) - s1).days
        curr_price = float(df["Close"].iloc[-1]) if len(df) else np.nan
        if (n_days <= 0) or (pd.isna(curr_price)) or (curr_price == 0) or pd.isna(sma1) or pd.isna(sma2):
            return out

        p_target = (sma1 * CDM_COEF1 * (t1_days / n_days)) + (sma2 * CDM_COEF2 * ((n_days - t1_days) / n_days))
        diff_pct = (float(p_target) - float(curr_price)) / float(curr_price) * 100

        tor_ok = None
        tor_info = "TOR: N/A"
        if "Turnover_Rate" in df.columns and len(df) >= 20:
            curr_tor = df["Turnover_Rate"].iloc[-1]
            avg20_tor = df["Turnover_Rate"].tail(20).mean()
            if pd.notna(curr_tor) and pd.notna(avg20_tor) and float(avg20_tor) > 0:
                threshold_tor = float(avg20_tor) / 5
                tor_ok = float(curr_tor) < float(threshold_tor)
                tor_info = f"TOR: {float(curr_tor):.2f}% (< {float(threshold_tor):.2f}%)"

        sma57 = df["Close"].rolling(57).mean().iloc[-1] if len(df) >= 57 else np.nan
        sma106 = df["Close"].rolling(106).mean().iloc[-1] if len(df) >= 106 else np.nan
        sma_ok = False
        if pd.notna(sma57) and pd.notna(sma106) and float(sma106) != 0 and float(sma57) != 0:
            sma_ok = (
                abs(float(sma57) - float(sma106)) / abs(float(sma106)) < 0.05
                and abs(float(curr_price) - float(sma57)) / abs(float(sma57)) < 0.05
                and abs(float(curr_price) - float(sma106)) / abs(float(sma106)) < 0.05
            )

        abs_diff = abs(float(diff_pct))
        if (abs_diff < 5) and (tor_ok is True) and (sma_ok is True):
            status = "🔴 觸發"
        elif 5 <= abs_diff < 8:
            status = "⏳ 待觀察"
        else:
            status = "❌ 未觸發"

        confidence = (1 - min(abs_diff, 10) / 10) * 40
        confidence += (30 if (tor_ok is True) else 0)
        confidence += (30 if (sma_ok is True) else 0)

        out.update(
            {
                "configured": True,
                "status": status,
                "target": float(p_target) if pd.notna(p_target) else np.nan,
                "diff_pct": float(diff_pct) if pd.notna(diff_pct) else np.nan,
                "tor_ok": tor_ok,
                "sma_ok": bool(sma_ok),
                "confidence": float(confidence),
                "tor_info": tor_info,
            }
        )
        return out
    except Exception:
        return out

def _build_cdm_signal_series(
    df: pd.DataFrame,
    params: Dict[str, Any],
    cdm_threshold: float,
) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["cdm_signal"] = False
    out["cdm_target"] = np.nan
    out["cdm_diff_pct"] = np.nan
    out["cdm_tor_ok"] = False
    out["cdm_sma_ok"] = False

    b1_s = params.get("box1_start")
    b1_e = params.get("box1_end")
    b2_s = params.get("box2_start")
    b2_e = params.get("box2_end")
    if not (b1_s and b1_e and b2_s and b2_e):
        return out

    def _parse_float(v):
        try:
            if v is None:
                return np.nan
            if isinstance(v, str) and (not v.strip()):
                return np.nan
            return float(v)
        except Exception:
            return np.nan

    try:
        CDM_COEF1, CDM_COEF2 = 0.7, 0.5
        s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
        s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)

        sma1_calc = df[(df.index >= s1) & (df.index <= e1)]["Close"].mean()
        sma2_calc = df[(df.index >= s2) & (df.index <= e2)]["Close"].mean()

        p1_avg_override = _parse_float(params.get("cdm_p1_avg_override"))
        p2_avg_override = _parse_float(params.get("cdm_p2_avg_override"))
        sma1 = p1_avg_override if (pd.notna(p1_avg_override) and p1_avg_override > 0) else sma1_calc
        sma2 = p2_avg_override if (pd.notna(p2_avg_override) and p2_avg_override > 0) else sma2_calc

        if pd.isna(sma1) or pd.isna(sma2):
            return out

        t1_days = (e1 - s1).days
        if t1_days <= 0:
            return out

        n_days = (df.index.to_series().apply(lambda d: (pd.to_datetime(d) - s1).days)).astype(float)
        valid_n = n_days.where(n_days > 0)
        p_target = (sma1 * CDM_COEF1 * (t1_days / valid_n)) + (sma2 * CDM_COEF2 * ((valid_n - t1_days) / valid_n))
        out["cdm_target"] = p_target
        out["cdm_diff_pct"] = (p_target - df["Close"]) / df["Close"].replace(0, np.nan) * 100

        if "Turnover_Rate" in df.columns:
            curr_tor = df["Turnover_Rate"]
            avg20_tor = df["Turnover_Rate"].rolling(20).mean()
            threshold_tor = avg20_tor / 5
            out["cdm_tor_ok"] = (curr_tor < threshold_tor) & pd.notna(curr_tor) & pd.notna(threshold_tor)

        sma57 = df["Close"].rolling(57).mean()
        sma106 = df["Close"].rolling(106).mean()
        out["cdm_sma_ok"] = (
            (abs(sma57 - sma106) / abs(sma106) < 0.05)
            & (abs(df["Close"] - sma57) / abs(sma57) < 0.05)
            & (abs(df["Close"] - sma106) / abs(sma106) < 0.05)
        ).fillna(False)

        out["cdm_signal"] = (
            (out["cdm_diff_pct"].abs() < float(cdm_threshold))
            & (out["cdm_tor_ok"] == True)
            & (out["cdm_sma_ok"] == True)
        ).fillna(False)
        return out
    except Exception:
        return out

def _build_mr_series(df: pd.DataFrame) -> pd.Series:
    sma7 = df["Close"].rolling(7).mean()
    sma14 = df["Close"].rolling(14).mean()
    sma28 = df["Close"].rolling(28).mean()
    sma57 = df["Close"].rolling(57).mean()
    sma106 = df["Close"].rolling(106).mean()
    sma212 = df["Close"].rolling(212).mean()
    avgp_vals = pd.concat([df["Close"], sma7, sma14, sma28, sma57, sma106, sma212], axis=1)
    avg_avgp = avgp_vals.mean(axis=1, skipna=True)
    mr_pct = (df["Close"] / avg_avgp.replace(0, np.nan) - 1) * 100
    return mr_pct

def _build_fzm_signal_series(df: pd.DataFrame, wr_threshold: float) -> pd.Series:
    sma7 = df["Close"].rolling(7).mean()
    sma14 = df["Close"].rolling(14).mean()
    wr35 = calculate_willr(df["High"], df["Low"], df["Close"], 35)
    signal = (df["Close"] > sma7) & (df["Close"] > sma14) & (wr35 < float(wr_threshold))
    return signal.fillna(False)

class BacktestResults:
    def __init__(self, trades: List[Dict[str, Any]], capital: float):
        self.trades = trades
        self.capital = float(capital)

    @property
    def total_return(self) -> float:
        if not self.trades:
            return 0.0
        total_pnl = sum(float(t.get("pnl_hkd", 0.0)) for t in self.trades)
        denom = (len(self.trades) * self.capital) if self.capital else 0.0
        return (total_pnl / denom * 100) if denom else 0.0

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if float(t.get("pnl_hkd", 0.0)) > 0)
        return wins / len(self.trades) * 100

    @property
    def monthly_avg_return(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        start = pd.to_datetime(self.trades[0]["entry_date"])
        end = pd.to_datetime(self.trades[-1]["exit_date"])
        months = (end - start).days / 30.0
        return self.total_return / months if months > 0 else 0.0

    @property
    def annualized_return(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        start = pd.to_datetime(self.trades[0]["entry_date"])
        end = pd.to_datetime(self.trades[-1]["exit_date"])
        days = (end - start).days
        return (self.total_return * (365.25 / days)) if days > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        equity = []
        cum = 0.0
        for t in self.trades:
            cum += float(t.get("pnl_hkd", 0.0))
            equity.append(self.capital + cum)
        if not equity:
            return 0.0
        peaks = np.maximum.accumulate(equity)
        drawdowns = (peaks - equity) / np.where(peaks == 0, np.nan, peaks) * 100
        mdd = np.nanmax(drawdowns) if len(drawdowns) else 0.0
        return float(mdd) if pd.notna(mdd) else 0.0

    @property
    def profit_factor(self) -> float:
        win_sum = sum(float(t.get("pnl_hkd", 0.0)) for t in self.trades if float(t.get("pnl_hkd", 0.0)) > 0)
        lose_sum = abs(sum(float(t.get("pnl_hkd", 0.0)) for t in self.trades if float(t.get("pnl_hkd", 0.0)) < 0))
        if lose_sum == 0:
            return float("inf") if win_sum > 0 else 0.0
        return win_sum / lose_sum

    @property
    def avg_winning_trade(self) -> float:
        wins = [float(t.get("pnl_pct", 0.0)) for t in self.trades if float(t.get("pnl_hkd", 0.0)) > 0]
        return float(np.mean(wins)) if wins else 0.0

    @property
    def avg_losing_trade(self) -> float:
        loses = [float(t.get("pnl_pct", 0.0)) for t in self.trades if float(t.get("pnl_hkd", 0.0)) < 0]
        return float(np.mean(loses)) if loses else 0.0

    @property
    def win_streak(self) -> int:
        best = 0
        cur = 0
        for t in self.trades:
            if float(t.get("pnl_hkd", 0.0)) > 0:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    @property
    def loss_streak(self) -> int:
        best = 0
        cur = 0
        for t in self.trades:
            if float(t.get("pnl_hkd", 0.0)) < 0:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    @property
    def sharpe_ratio(self) -> float:
        rets = [float(t.get("pnl_pct", 0.0)) for t in self.trades]
        if len(rets) < 2:
            return 0.0
        mean = float(np.mean(rets))
        std = float(np.std(rets))
        return (mean / std * np.sqrt(252)) if std > 0 else 0.0

    def confidence_score(self) -> float:
        score = (
            min(self.win_rate, 100) * 0.3
            + min(self.annualized_return / 2, 100) * 0.3
            + (100 - min(self.max_drawdown * 5, 100)) * 0.2
            + min(self.sharpe_ratio * 10, 100) * 0.2
        )
        return float(min(max(score, 0), 100))

class BacktestEngine:
    def __init__(
        self,
        df: pd.DataFrame,
        signals: pd.DataFrame,
        capital: float,
        commission_rate: float,
        sell_config: Dict[str, Any],
        combined_logic: str,
    ):
        self.df = df
        self.signals = signals
        self.capital = float(capital)
        self.commission_rate = float(commission_rate)
        self.sell_config = sell_config
        self.combined_logic = combined_logic
        self.trades: List[Dict[str, Any]] = []
        self.position: Optional[Dict[str, Any]] = None

    def _buy_signal(self, i: int) -> bool:
        row = self.signals.iloc[i]
        selected = []
        if row.get("use_cdm", False):
            selected.append(bool(row.get("cdm", False)))
        if row.get("use_fzm", False):
            selected.append(bool(row.get("fzm", False)))
        if row.get("use_mr", False):
            selected.append(bool(row.get("mr", False)))
        if not selected:
            return False
        if row.get("use_combined", False):
            if self.combined_logic == "同時觸發 (AND)":
                return all(selected)
            return any(selected)
        return any(selected)

    def _signal_type(self, i: int) -> str:
        row = self.signals.iloc[i]
        types = []
        if row.get("use_cdm", False) and bool(row.get("cdm", False)):
            types.append("CDM")
        if row.get("use_fzm", False) and bool(row.get("fzm", False)):
            types.append("FZM")
        if row.get("use_mr", False) and bool(row.get("mr", False)):
            types.append("MR")
        return "+".join(types) if types else "N/A"

    def _should_sell(self, i: int) -> tuple[bool, str]:
        if not self.position:
            return False, ""
        entry_price = float(self.position["entry_price"])
        entry_idx = int(self.position["entry_idx"])
        price = float(self.df["Close"].iloc[i])
        pnl_pct = (price - entry_price) / entry_price * 100 if entry_price else 0.0
        sell_type = self.sell_config.get("type")

        if sell_type == "profit_target":
            if pnl_pct >= float(self.sell_config.get("value", 5)):
                return True, "止盈"
        elif sell_type == "stop_loss":
            if pnl_pct <= float(self.sell_config.get("value", -3)):
                return True, "止損"
        elif sell_type == "time_based":
            hold = int(self.sell_config.get("value", 5))
            if i >= entry_idx + hold:
                return True, "時間"
        elif sell_type == "signal_reverse":
            if i > entry_idx and (not self._buy_signal(i)):
                return True, "信號反轉"
        return False, ""

    def run(self) -> BacktestResults:
        for i in range(len(self.df)):
            if self.position is None:
                if self._buy_signal(i):
                    entry_price = float(self.df["Close"].iloc[i])
                    self.position = {
                        "entry_date": self.df.index[i],
                        "entry_price": entry_price,
                        "entry_idx": i,
                        "signal_type": self._signal_type(i),
                    }
            else:
                should, reason = self._should_sell(i)
                if should:
                    entry_price = float(self.position["entry_price"])
                    exit_price = float(self.df["Close"].iloc[i])
                    raw_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0
                    net_pct = raw_pct - (2 * float(self.commission_rate))
                    pnl_hkd = self.capital * (net_pct / 100.0)
                    self.trades.append(
                        {
                            "entry_date": self.position["entry_date"],
                            "exit_date": self.df.index[i],
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl_pct": float(net_pct),
                            "pnl_hkd": float(pnl_hkd),
                            "signal_type": self.position.get("signal_type", "N/A"),
                            "exit_reason": reason,
                            "holding_days": int(i - int(self.position["entry_idx"])),
                        }
                    )
                    self.position = None
        return BacktestResults(self.trades, self.capital)

def _default_backtest_params() -> Dict[str, Any]:
    return {
        "use_cdm": True,
        "use_fzm": True,
        "use_mr": True,
        "use_combined": False,
        "combine_logic": "任意一個觸發 (OR)",
        "cdm_threshold": 5.0,
        "mr_threshold": 3.0,
        "wr_threshold": -80.0,
        "sell_logic": "🎯 止盈 (+5% 目標)",
        "capital": 10000,
        "commission_rate": 0.2,
    }

@st.cache_data(ttl=600)
def run_backtest_cached(
    symbol: str,
    df_slice: pd.DataFrame,
    params: Dict[str, Any],
    watchlist_params: Dict[str, Any],
) -> Dict[str, Any]:
    cdm_series = _build_cdm_signal_series(df_slice, watchlist_params, float(params.get("cdm_threshold", 5.0)))
    mr_pct = _build_mr_series(df_slice)
    mr_signal = mr_pct.abs() > float(params.get("mr_threshold", 3.0))
    fzm_signal = _build_fzm_signal_series(df_slice, float(params.get("wr_threshold", -80.0)))

    signals = pd.DataFrame(index=df_slice.index)
    signals["cdm"] = cdm_series["cdm_signal"]
    signals["fzm"] = fzm_signal
    signals["mr"] = mr_signal.fillna(False)
    signals["use_cdm"] = bool(params.get("use_cdm", True))
    signals["use_fzm"] = bool(params.get("use_fzm", True))
    signals["use_mr"] = bool(params.get("use_mr", True))
    signals["use_combined"] = bool(params.get("use_combined", False))

    sell_config = {
        "🎯 止盈 (+5% 目標)": {"type": "profit_target", "value": 5},
        "🎯 止盈 (+5%)": {"type": "profit_target", "value": 5},
        "🛑 止損 (-3% 止損)": {"type": "stop_loss", "value": -3},
        "🛑 止損 (-3%)": {"type": "stop_loss", "value": -3},
        "⏱️ 時間 (5 交易日)": {"type": "time_based", "value": 5},
        "⏱️ 時間 (5日)": {"type": "time_based", "value": 5},
        "🔄 策略反轉信號": {"type": "signal_reverse", "value": None},
    }[params.get("sell_logic", "🎯 止盈 (+5% 目標)")]

    engine = BacktestEngine(
        df=df_slice,
        signals=signals,
        capital=float(params.get("capital", 10000)),
        commission_rate=float(params.get("commission_rate", 0.2)),
        sell_config=sell_config,
        combined_logic=str(params.get("combine_logic", "任意一個觸發 (OR)")),
    )
    results = engine.run()

    return {
        "results": results,
        "trades": results.trades,
        "signals": signals,
        "mr_pct": mr_pct,
        "cdm_target": cdm_series["cdm_target"],
        "cdm_diff_pct": cdm_series["cdm_diff_pct"],
    }

class StrategyComparisonResult:
    def __init__(self, strategy_name: str, results: BacktestResults, trades: List[Dict[str, Any]]):
        self.strategy_name = strategy_name
        self.results = results
        self.trades = trades

    @property
    def annual_return(self) -> float:
        return float(self.results.annualized_return)

    @property
    def monthly_return(self) -> float:
        return float(self.results.monthly_avg_return)

    @property
    def win_rate(self) -> float:
        return float(self.results.win_rate)

    @property
    def max_drawdown(self) -> float:
        return float(self.results.max_drawdown)

    @property
    def trades_count(self) -> int:
        return int(len(self.trades))

    @property
    def sharpe_ratio(self) -> float:
        return float(self.results.sharpe_ratio)

    @property
    def profit_factor(self) -> float:
        return float(self.results.profit_factor)

    @property
    def avg_winning(self) -> float:
        return float(self.results.avg_winning_trade)

    @property
    def avg_losing(self) -> float:
        return float(self.results.avg_losing_trade)

    @property
    def win_streak(self) -> int:
        return int(self.results.win_streak)

    @property
    def loss_streak(self) -> int:
        return int(self.results.loss_streak)

    @property
    def rank_score(self) -> float:
        score = (
            min(self.win_rate, 100) * 0.25
            + min(self.annual_return / 2, 100) * 0.30
            + (100 - min(self.max_drawdown * 5, 100)) * 0.25
            + min(self.sharpe_ratio * 10, 100) * 0.20
        )
        return float(min(max(score, 0), 100))

    @property
    def rating(self) -> str:
        s = self.rank_score
        if s >= 85:
            return "🟢 強烈推薦"
        if s >= 75:
            return "🟡 中等推薦"
        if s >= 65:
            return "🔵 可考慮"
        return "🔴 不推薦"

def _strategy_profile(strategy_name: str) -> Dict[str, str]:
    profiles = {
        "CDM": {
            "principle": "基於價格目標預測模型 (CDM)：根據波段均價推算目標價，結合成交量(換手率)與中長均線接近度判斷機會，偏差小且條件滿足時進場。",
            "scene": "中長線 / 偏保守",
            "difficulty": "簡單",
            "freq": "中等",
            "false_signal": "中等",
        },
        "FZM": {
            "principle": "基於 Williams %R 超賣反彈：當 WR 進入超賣且股價站上 SMA7/14 時進場，適合短線反彈或波段。",
            "scene": "短線 / 波段",
            "difficulty": "中等",
            "freq": "低",
            "false_signal": "低",
        },
        "MR": {
            "principle": "基於均線偏離率 (MR)：當股價相對多均線均值出現明顯偏離時進場，偏離回歸或達到賣出條件出場，偏向偏離套利。",
            "scene": "偏離 / 較高頻",
            "difficulty": "複雜",
            "freq": "高",
            "false_signal": "高",
        },
    }
    return profiles.get(strategy_name, {})

def _apply_strategy_to_params(strategy_name: str, base_params: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(base_params)
    p["use_combined"] = False
    p["combine_logic"] = "任意一個觸發 (OR)"
    p["use_cdm"] = strategy_name == "CDM"
    p["use_fzm"] = strategy_name == "FZM"
    p["use_mr"] = strategy_name == "MR"
    if strategy_name == "CDM":
        p["cdm_threshold"] = float(p.get("cdm_threshold", 5.0) or 5.0)
    if strategy_name == "FZM":
        p["wr_threshold"] = float(p.get("wr_threshold", -80.0) or -80.0)
    if strategy_name == "MR":
        p["mr_threshold"] = float(p.get("mr_threshold", 3.0) or 3.0)
    return p

def _equity_curve_from_trades(trades: List[Dict[str, Any]]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["date", "cum_pct"])
    rows = []
    cum = 0.0
    for t in trades:
        cum += float(t.get("pnl_pct", 0.0))
        rows.append({"date": pd.to_datetime(t["exit_date"]), "cum_pct": cum})
    return pd.DataFrame(rows)

def _compute_recovery_days(curve_df: pd.DataFrame) -> float:
    if curve_df is None or curve_df.empty:
        return np.nan
    c = curve_df.sort_values("date").reset_index(drop=True)
    equity = c["cum_pct"].astype(float).values
    peaks = np.maximum.accumulate(equity)
    dd = peaks - equity
    if len(dd) == 0:
        return np.nan
    trough_idx = int(np.argmax(dd))
    if dd[trough_idx] <= 0:
        return 0.0
    peak_value = peaks[trough_idx]
    trough_date = pd.to_datetime(c.loc[trough_idx, "date"])
    rec_idx = None
    for j in range(trough_idx + 1, len(equity)):
        if equity[j] >= peak_value:
            rec_idx = j
            break
    if rec_idx is None:
        return np.nan
    rec_date = pd.to_datetime(c.loc[rec_idx, "date"])
    return float((rec_date - trough_date).days)

def _recent_performance(trades: List[Dict[str, Any]], end_date: date, days: int = 30) -> Dict[str, Any]:
    if not trades:
        return {"win_rate": 0.0, "winning_trades": 0, "total_trades": 0, "monthly_return": 0.0, "max_loss": 0.0}
    end_dt = pd.to_datetime(end_date)
    start_dt = end_dt - pd.Timedelta(days=int(days))
    recent = [t for t in trades if pd.to_datetime(t["exit_date"]) >= start_dt]
    if not recent:
        return {"win_rate": 0.0, "winning_trades": 0, "total_trades": 0, "monthly_return": 0.0, "max_loss": 0.0}
    wins = [t for t in recent if float(t.get("pnl_hkd", 0.0)) > 0]
    pnl_pcts = [float(t.get("pnl_pct", 0.0)) for t in recent]
    win_rate = (len(wins) / len(recent) * 100) if recent else 0.0
    monthly_return = float(np.sum(pnl_pcts))
    max_loss = float(np.min(pnl_pcts)) if pnl_pcts else 0.0
    return {
        "win_rate": float(win_rate),
        "winning_trades": int(len(wins)),
        "total_trades": int(len(recent)),
        "monthly_return": float(monthly_return),
        "max_loss": float(max_loss),
    }

@st.cache_data(ttl=600)
def run_strategy_comparison_cached(
    symbol: str,
    df_slice: pd.DataFrame,
    compare_capital: float,
    compare_commission: float,
    compare_sell_logic: str,
    cdm_threshold: float,
    mr_threshold: float,
    wr_threshold: float,
    watchlist_params: Dict[str, Any],
) -> Dict[str, Any]:
    base = {
        "use_cdm": False,
        "use_fzm": False,
        "use_mr": False,
        "use_combined": False,
        "combine_logic": "任意一個觸發 (OR)",
        "cdm_threshold": float(cdm_threshold),
        "mr_threshold": float(mr_threshold),
        "wr_threshold": float(wr_threshold),
        "sell_logic": compare_sell_logic,
        "capital": float(compare_capital),
        "commission_rate": float(compare_commission),
    }

    params_cdm = dict(base)
    params_cdm["use_cdm"] = True
    params_fzm = dict(base)
    params_fzm["use_fzm"] = True
    params_mr = dict(base)
    params_mr["use_mr"] = True

    out_cdm = run_backtest_cached(symbol, df_slice, params_cdm, watchlist_params)
    out_fzm = run_backtest_cached(symbol, df_slice, params_fzm, watchlist_params)
    out_mr = run_backtest_cached(symbol, df_slice, params_mr, watchlist_params)

    r_cdm: BacktestResults = out_cdm["results"]
    r_fzm: BacktestResults = out_fzm["results"]
    r_mr: BacktestResults = out_mr["results"]

    results = [
        StrategyComparisonResult("CDM", r_cdm, out_cdm["trades"]),
        StrategyComparisonResult("FZM", r_fzm, out_fzm["trades"]),
        StrategyComparisonResult("MR", r_mr, out_mr["trades"]),
    ]

    return {
        "results": results,
        "curves": {
            "CDM": _equity_curve_from_trades(out_cdm["trades"]),
            "FZM": _equity_curve_from_trades(out_fzm["trades"]),
            "MR": _equity_curve_from_trades(out_mr["trades"]),
        },
    }

def render_backtest_page(
    df: pd.DataFrame,
    current_code: str,
    watchlist_data: Dict[str, Any],
):
    if "backtest_params" not in st.session_state:
        st.session_state.backtest_params = _default_backtest_params()
    if "strategy_compare_params" not in st.session_state:
        st.session_state.strategy_compare_params = {}

    p = dict(st.session_state.backtest_params)

    min_d = df.index.min().date()
    max_d = df.index.max().date()

    sync_date_window_state("bt_start", "bt_end", min_d, max_d)

    show_settings = True
    show_single = True
    show_compare = True
    show_recommend = True

    if show_settings:
        render_scroll_anchor("backtest-settings")
        st.markdown("### ⚙️ 回測設定")

        c1, c2, c3, c4, c5 = st.columns([1.5, 1.5, 0.8, 0.8, 0.8])
        with c1:
            st.session_state.bt_start = st.date_input("開始日期", value=st.session_state.bt_start, min_value=min_d, max_value=max_d, key=f"bt_start_{current_code}")
        with c2:
            st.session_state.bt_end = st.date_input("結束日期", value=st.session_state.bt_end, min_value=min_d, max_value=max_d, key=f"bt_end_{current_code}")
        with c3:
            if st.button("⏪ 1Y", use_container_width=True, key=f"bt_1y_{current_code}"):
                st.session_state.bt_end = max_d
                st.session_state.bt_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=365)).date())
                st.rerun()
        with c4:
            if st.button("⏪ 2Y", use_container_width=True, key=f"bt_2y_{current_code}"):
                st.session_state.bt_end = max_d
                st.session_state.bt_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=730)).date())
                st.rerun()
        with c5:
            if st.button("⏪ ALL", use_container_width=True, key=f"bt_all_{current_code}"):
                st.session_state.bt_start = min_d
                st.session_state.bt_end = max_d
                st.rerun()

        st.markdown("**🎲 策略選擇**")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            p["use_cdm"] = st.checkbox("CDM 策略", value=bool(p.get("use_cdm", True)), key=f"bt_use_cdm_{current_code}")
        with s2:
            p["use_fzm"] = st.checkbox("FZM 策略 (超底)", value=bool(p.get("use_fzm", True)), key=f"bt_use_fzm_{current_code}")
        with s3:
            p["use_mr"] = st.checkbox("MR 策略 (偏離)", value=bool(p.get("use_mr", True)), key=f"bt_use_mr_{current_code}")
        with s4:
            p["use_combined"] = st.checkbox("組合策略", value=bool(p.get("use_combined", False)), key=f"bt_use_combined_{current_code}")

        if p["use_combined"]:
            p["combine_logic"] = st.radio("組合邏輯", ["任意一個觸發 (OR)", "同時觸發 (AND)"], index=0, key=f"bt_combine_logic_{current_code}")
        else:
            p["combine_logic"] = "任意一個觸發 (OR)"

        st.markdown("**⚙️ 進階參數**")
        a1, a2, a3 = st.columns(3)
        with a1:
            p["cdm_threshold"] = st.slider("CDM 偏差閾值 (%)", min_value=2.0, max_value=10.0, value=float(p.get("cdm_threshold", 5.0)), step=0.5, key=f"bt_cdm_th_{current_code}")
        with a2:
            p["mr_threshold"] = st.slider("MR 偏離閾值 (%)", min_value=1.0, max_value=8.0, value=float(p.get("mr_threshold", 3.0)), step=0.5, key=f"bt_mr_th_{current_code}")
        with a3:
            p["wr_threshold"] = st.slider("FZM WR 閾值", min_value=-100, max_value=-50, value=int(p.get("wr_threshold", -80)), step=5, key=f"bt_wr_th_{current_code}")

        st.markdown("**📈 交易邏輯**")
        t1, t2 = st.columns(2)
        with t1:
            p["sell_logic"] = st.radio(
                "選擇賣出條件",
                ["🎯 止盈 (+5% 目標)", "🛑 止損 (-3% 止損)", "⏱️ 時間 (5 交易日)", "🔄 策略反轉信號"],
                index=["🎯 止盈 (+5% 目標)", "🛑 止損 (-3% 止損)", "⏱️ 時間 (5 交易日)", "🔄 策略反轉信號"].index(p.get("sell_logic", "🎯 止盈 (+5% 目標)")),
                key=f"bt_sell_logic_{current_code}",
            )
        with t2:
            p["capital"] = st.number_input("交易本金 (HKD)", min_value=1000, max_value=1000000, value=int(p.get("capital", 10000)), step=1000, key=f"bt_capital_{current_code}")
            p["commission_rate"] = st.number_input("手續費率 (%)", min_value=0.0, max_value=1.0, value=float(p.get("commission_rate", 0.2)), step=0.05, key=f"bt_comm_{current_code}")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("📥 導入預設", use_container_width=True, key=f"bt_preset_{current_code}"):
                st.session_state.backtest_params = _default_backtest_params()
                st.rerun()
        with b2:
            if st.button("✅ 保存設定", type="primary", use_container_width=True, key=f"bt_save_{current_code}"):
                st.session_state.backtest_params = p
                st.toast("已保存回測設定", icon="✅")

    start_date = st.session_state.bt_start
    end_date = st.session_state.bt_end
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    df_bt = df[(df.index >= pd.to_datetime(start_date)) & (df.index <= pd.to_datetime(end_date))].copy()

    if show_single:
        render_scroll_anchor("backtest-single")
        st.markdown("### 📊 單策略回測")
        if len(df_bt) < 50:
            st.warning("回測數據不足（至少需要 50 個交易日）。")
        else:
            p = dict(st.session_state.backtest_params)
            c_run, c_opt = st.columns(2)
            with c_run:
                run_backtest = st.button("🔄 重新計算", type="primary", use_container_width=True, key=f"bt_run_{current_code}")
            with c_opt:
                run_opt = st.button("🎯 智能優化", use_container_width=True, key=f"bt_opt_{current_code}")

            if run_backtest:
                with st.spinner("回測計算中..."):
                    st.session_state.backtest_output = run_backtest_cached(current_code, df_bt, p, watchlist_data.get(current_code, {}))

            if run_opt:
                with st.spinner("參數優化中..."):
                    cdm_thresholds = [3, 4, 5, 6, 7]
                    mr_thresholds = [1.5, 2, 2.5, 3, 3.5, 4]
                    wr_thresholds = [-70, -75, -80, -85, -90]
                    results = []
                    base = dict(p)
                    for cdm_th in cdm_thresholds:
                        for mr_th in mr_thresholds:
                            for wr_th in wr_thresholds:
                                trial = dict(base)
                                trial["cdm_threshold"] = float(cdm_th)
                                trial["mr_threshold"] = float(mr_th)
                                trial["wr_threshold"] = float(wr_th)
                                out = run_backtest_cached(current_code, df_bt, trial, watchlist_data.get(current_code, {}))
                                r: BacktestResults = out["results"]
                                score = (
                                    r.win_rate * 0.3
                                    + min(r.annualized_return / 2, 100) * 0.3
                                    + (100 - min(r.max_drawdown * 5, 100)) * 0.2
                                    + min(r.sharpe_ratio * 10, 100) * 0.2
                                )
                                results.append({"cdm": cdm_th, "mr": mr_th, "wr": wr_th, "score": score, "r": r})
                    results.sort(key=lambda x: x["score"], reverse=True)
                    st.session_state.backtest_opt_results = results
                    top = results[:3]
                    st.success("智能優化完成")
                    for i, item in enumerate(top, 1):
                        rr: BacktestResults = item["r"]
                        st.write(
                            f"參數組合{i}: CDM={item['cdm']}% / MR={item['mr']}% / WR={item['wr']} | 勝率 {rr.win_rate:.1f}% | 年化 {rr.annualized_return:+.1f}% | 回撤 {rr.max_drawdown:.1f}% | 評分 {item['score']:.1f}/100"
                        )

                    heat = pd.DataFrame(results)
                    cdm_vals = sorted(set(heat["cdm"]))
                    mr_vals = sorted(set(heat["mr"]))
                    mat = np.zeros((len(mr_vals), len(cdm_vals)))
                    for _, row in heat.iterrows():
                        cdm_idx = cdm_vals.index(row["cdm"])
                        mr_idx = mr_vals.index(row["mr"])
                        mat[mr_idx][cdm_idx] = row["r"].win_rate
                    fig = go.Figure(data=go.Heatmap(z=mat, x=cdm_vals, y=mr_vals, colorscale="RdYlGn", colorbar=dict(title="勝率 (%)")))
                    fig.update_layout(title="參數組合勝率熱力圖 (WR 已混合)", xaxis_title="CDM 偏差閾值 (%)", yaxis_title="MR 偏離閾值 (%)", height=400)
                    st.plotly_chart(fig, use_container_width=True)

            out = st.session_state.get("backtest_output")
            if not out:
                st.info("先到「回測設定」設定參數，然後點擊「重新計算」。")
            else:
                results: BacktestResults = out["results"]
                trades = out["trades"]

                st.write("---")
                k1, k2, k3, k4, k5 = st.columns(5)
                with k1:
                    st.metric("總盈虧", f"{results.total_return:+.1f}%")
                with k2:
                    st.metric("月平均收益", f"{results.monthly_avg_return:+.2f}%")
                with k3:
                    st.metric("年化收益", f"{results.annualized_return:+.1f}%")
                with k4:
                    st.metric("最大回撤", f"{results.max_drawdown:.1f}%")
                with k5:
                    st.metric("勝率", f"{results.win_rate:.1f}%")

                st.divider()
                s1, s2, s3 = st.columns(3)
                with s1:
                    st.markdown(
                        f"**交易統計**\n\n- 總交易次數: {len(trades)}\n- 勝利次數: {sum(1 for t in trades if float(t.get('pnl_hkd', 0)) > 0)}\n- 失敗次數: {sum(1 for t in trades if float(t.get('pnl_hkd', 0)) < 0)}"
                    )
                with s2:
                    st.markdown(
                        f"**收益分析**\n\n- 平均獲利: {results.avg_winning_trade:+.2f}%\n- 平均虧損: {results.avg_losing_trade:+.2f}%\n- 盈虧比: {results.profit_factor:.2f}:1"
                    )
                with s3:
                    conf = results.confidence_score()
                    stars = "⭐" * int(conf / 25)
                    st.markdown(f"**風險評估**\n\n- 連勝紀錄: {results.win_streak} 次\n- 連敗紀錄: {results.loss_streak} 次\n- 信心指數: {stars} ({conf:.0f}/100)")

                st.write("---")
                st.markdown("### 策略曲線與交易信號")
                if trades:
                    curve = _equity_curve_from_trades(trades)
                    fig_curve = go.Figure()
                    fig_curve.add_trace(go.Scatter(x=curve["date"], y=curve["cum_pct"], mode="lines+markers", name="策略累積收益(%)"))
                    fig_curve.update_layout(height=350, template="plotly_white", yaxis_title="累積收益(%)", xaxis_title="日期")
                    st.plotly_chart(fig_curve, use_container_width=True)

                    fig_sig = go.Figure()
                    fig_sig.add_trace(go.Candlestick(x=df_bt.index, open=df_bt["Open"], high=df_bt["High"], low=df_bt["Low"], close=df_bt["Close"], name="K線"))
                    for t in trades:
                        fig_sig.add_trace(go.Scatter(x=[t["entry_date"]], y=[t["entry_price"]], mode="markers", marker=dict(symbol="triangle-up", color="green", size=12), showlegend=False))
                        fig_sig.add_trace(go.Scatter(x=[t["exit_date"]], y=[t["exit_price"]], mode="markers", marker=dict(symbol="triangle-down", color="red", size=12), showlegend=False))
                    fig_sig.update_layout(height=520, template="plotly_white", xaxis_rangeslider_visible=False, title="K線圖 + 交易信號")
                    st.plotly_chart(fig_sig, use_container_width=True)
                else:
                    st.info("此區間內沒有產生任何交易。")

                st.write("---")
                st.markdown("### 詳細交易列表")
                if trades:
                    rows = []
                    for i, t in enumerate(trades, 1):
                        rows.append(
                            {
                                "序號": i,
                                "買入日期": pd.to_datetime(t["entry_date"]).strftime("%Y-%m-%d"),
                                "賣出日期": pd.to_datetime(t["exit_date"]).strftime("%Y-%m-%d"),
                                "買入價": f"{float(t['entry_price']):.2f}",
                                "賣出價": f"{float(t['exit_price']):.2f}",
                                "收益%": f"{float(t['pnl_pct']):+.2f}%",
                                "盈虧": "✅ 獲利" if float(t.get("pnl_hkd", 0.0)) > 0 else "❌ 虧損",
                                "原因": str(t.get("signal_type", "")),
                                "賣出原因": str(t.get("exit_reason", "")),
                                "持倉(交易日)": int(t.get("holding_days", 0)),
                            }
                        )
                    df_tr = pd.DataFrame(rows)
                    st.dataframe(df_tr, use_container_width=True, hide_index=True)
                    st.download_button("📥 導出 CSV", data=df_tr.to_csv(index=False).encode("utf-8-sig"), file_name=f"交易明細_{current_code}_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

    if show_compare:
        render_scroll_anchor("backtest-compare")
        st.markdown("### 🆚 策略對標")
        if "cmp_start" not in st.session_state:
            st.session_state.cmp_start = st.session_state.bt_start
        if "cmp_end" not in st.session_state:
            st.session_state.cmp_end = st.session_state.bt_end
        sync_date_window_state("cmp_start", "cmp_end", min_d, max_d)

        c1, c2, c3, c4, c5 = st.columns([1.5, 1.5, 0.7, 0.7, 0.7])
        with c1:
            st.session_state.cmp_start = st.date_input("開始日期", value=st.session_state.cmp_start, min_value=min_d, max_value=max_d, key=f"cmp_start_{current_code}")
        with c2:
            st.session_state.cmp_end = st.date_input("結束日期", value=st.session_state.cmp_end, min_value=min_d, max_value=max_d, key=f"cmp_end_{current_code}")
        with c3:
            if st.button("⏪ 1Y", use_container_width=True, key=f"cmp_1y_{current_code}"):
                st.session_state.cmp_end = max_d
                st.session_state.cmp_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=365)).date())
                st.rerun()
        with c4:
            if st.button("⏪ 2Y", use_container_width=True, key=f"cmp_2y_{current_code}"):
                st.session_state.cmp_end = max_d
                st.session_state.cmp_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=730)).date())
                st.rerun()
        with c5:
            if st.button("⏪ ALL", use_container_width=True, key=f"cmp_all_{current_code}"):
                st.session_state.cmp_start = min_d
                st.session_state.cmp_end = max_d
                st.rerun()

        cs = st.session_state.cmp_start
        ce = st.session_state.cmp_end
        if cs > ce:
            cs, ce = ce, cs
        df_cmp = df[(df.index >= pd.to_datetime(cs)) & (df.index <= pd.to_datetime(ce))].copy()
        trading_days = len(df_cmp)
        span_years = (pd.to_datetime(ce) - pd.to_datetime(cs)).days / 365.0
        st.caption(f"⏱️ 時間段概況: 共 {trading_days} 個交易日，時間跨度: {span_years:.1f} 年")

        p_cmp = dict(st.session_state.strategy_compare_params or {})
        if not p_cmp:
            p_cmp = {
                "capital": float(p.get("capital", 10000)),
                "commission_rate": float(p.get("commission_rate", 0.2)),
                "sell_logic": str(p.get("sell_logic", "🎯 止盈 (+5% 目標)")),
                "cdm_threshold": float(p.get("cdm_threshold", 5.0)),
                "mr_threshold": float(p.get("mr_threshold", 3.0)),
                "wr_threshold": float(p.get("wr_threshold", -80.0)),
            }

        st.markdown("**⚙️ 共同參數 (所有策略適用)**")
        x1, x2, x3 = st.columns(3)
        with x1:
            p_cmp["capital"] = st.number_input("交易本金 (HKD)", min_value=1000, max_value=1000000, value=int(p_cmp.get("capital", 10000)), step=1000, key=f"cmp_cap_{current_code}")
        with x2:
            p_cmp["commission_rate"] = st.number_input("手續費率 (%)", min_value=0.0, max_value=1.0, value=float(p_cmp.get("commission_rate", 0.2)), step=0.05, key=f"cmp_comm_{current_code}")
        with x3:
            sell_opts = ["🎯 止盈 (+5%)", "🛑 止損 (-3%)", "⏱️ 時間 (5日)"]
            current_sell = p_cmp.get("sell_logic", "🎯 止盈 (+5%)")
            if current_sell not in sell_opts:
                if current_sell == "🎯 止盈 (+5% 目標)":
                    current_sell = "🎯 止盈 (+5%)"
                elif current_sell == "🛑 止損 (-3% 止損)":
                    current_sell = "🛑 止損 (-3%)"
                elif current_sell == "⏱️ 時間 (5 交易日)":
                    current_sell = "⏱️ 時間 (5日)"
                else:
                    current_sell = "🎯 止盈 (+5%)"
            p_cmp["sell_logic"] = st.radio("賣出邏輯", sell_opts, index=sell_opts.index(current_sell), key=f"cmp_sell_{current_code}", help="所有策略採用相同賣出邏輯（公平對比）")

        st.markdown("**進階閾值 (用於對標)**")
        y1, y2, y3 = st.columns(3)
        with y1:
            p_cmp["cdm_threshold"] = st.slider("CDM 偏差閾值 (%)", min_value=2.0, max_value=10.0, value=float(p_cmp.get("cdm_threshold", 5.0)), step=0.5, key=f"cmp_cdm_th_{current_code}")
        with y2:
            p_cmp["mr_threshold"] = st.slider("MR 偏離閾值 (%)", min_value=1.0, max_value=8.0, value=float(p_cmp.get("mr_threshold", 3.0)), step=0.5, key=f"cmp_mr_th_{current_code}")
        with y3:
            p_cmp["wr_threshold"] = st.slider("FZM WR 閾值", min_value=-100, max_value=-50, value=int(p_cmp.get("wr_threshold", -80)), step=5, key=f"cmp_wr_th_{current_code}")

        st.session_state.strategy_compare_params = p_cmp

        b1, b2, b3 = st.columns(3)
        with b1:
            run_cmp = st.button("🆚 開始對標 (全部策略)", type="primary", use_container_width=True, key=f"cmp_run_{current_code}")
        with b2:
            if st.button("🔄 清空結果", use_container_width=True, key=f"cmp_clear_{current_code}"):
                st.session_state.comparison_results = None
                st.rerun()
        export_clicked = False
        with b3:
            export_clicked = st.button("📥 導出對比報告", use_container_width=True, key=f"cmp_export_{current_code}")

        if len(df_cmp) < 50:
            st.warning("對標數據不足（至少需要 50 個交易日）。")
        else:
            if run_cmp:
                with st.spinner("策略對標計算中..."):
                    st.session_state.comparison_results = run_strategy_comparison_cached(
                        current_code,
                        df_cmp,
                        float(p_cmp["capital"]),
                        float(p_cmp["commission_rate"]),
                        str(p_cmp["sell_logic"]),
                        float(p_cmp["cdm_threshold"]),
                        float(p_cmp["mr_threshold"]),
                        float(p_cmp["wr_threshold"]),
                        watchlist_data.get(current_code, {}),
                    )

        comp_out = st.session_state.get("comparison_results")
        if comp_out:
            results_list: List[StrategyComparisonResult] = comp_out["results"]
            ranked = sorted(results_list, key=lambda r: r.rank_score, reverse=True)

            st.write("---")
            st.markdown("### 🆚 三大策略核心指標對比")
            cols = st.columns(3)
            for idx, r in enumerate(ranked):
                with cols[idx]:
                    rank_emoji = ["🥇", "🥈", "🥉"][idx]
                    if idx == 0:
                        bg_color, border_color = "#d4edda", "#28a745"
                    elif idx == 1:
                        bg_color, border_color = "#fff3cd", "#ffc107"
                    else:
                        bg_color, border_color = "#f8d7da", "#dc3545"

                    card_html = f"""
                    <div style="
                        border: 3px solid {border_color};
                        border-radius: 10px;
                        padding: 18px;
                        background-color: {bg_color};
                        margin-bottom: 10px;
                    ">
                        <div style="text-align: center;">
                            <h3 style="margin: 0; color: {border_color};">{rank_emoji} {r.strategy_name} 策略 {rank_emoji}</h3>
                            <div style="color: #666; font-size: 12px; margin-top: 6px;">
                                年化收益 <b>{r.annual_return:+.1f}%</b> ｜ 勝率 <b>{r.win_rate:.1f}%</b>
                            </div>
                        </div>
                        <hr style="border: none; border-top: 1px solid {border_color}; margin: 12px 0;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 13px;">
                            <div>最大回撤: <b>{r.max_drawdown:.1f}%</b></div>
                            <div>交易數: <b>{r.trades_count}</b></div>
                            <div>夏普比: <b>{r.sharpe_ratio:.2f}</b></div>
                            <div>盈虧比: <b>{r.profit_factor:.2f}:1</b></div>
                        </div>
                        <hr style="border: none; border-top: 1px solid {border_color}; margin: 12px 0;">
                        <div style="text-align: center;">
                            <div style="font-weight: 700;">⭐ 評級: {r.rating}</div>
                            <div style="color: #666; font-size: 12px;">綜合評分: {r.rank_score:.1f}/100</div>
                        </div>
                    </div>
                    """
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button("📊 詳情", use_container_width=True, key=f"cmp_detail_{current_code}_{r.strategy_name}"):
                            st.session_state[f"cmp_show_{current_code}_{r.strategy_name}"] = not st.session_state.get(f"cmp_show_{current_code}_{r.strategy_name}", False)
                    with d2:
                        if st.button(f"✅ 採用 {r.strategy_name}", use_container_width=True, key=f"cmp_adopt_{current_code}_{r.strategy_name}"):
                            st.session_state.selected_strategy = r.strategy_name
                            st.session_state.backtest_params = _apply_strategy_to_params(r.strategy_name, st.session_state.backtest_params)
                            st.success(f"已採用 {r.strategy_name} 策略到回測設定")

                    show_detail = bool(st.session_state.get(f"cmp_show_{current_code}_{r.strategy_name}", False))
                    with st.expander(f"{r.strategy_name} 詳細交易與統計", expanded=show_detail):
                        prof = _strategy_profile(r.strategy_name)
                        if prof:
                            st.write(f"策略原理：{prof.get('principle','')}")
                            st.write(f"適用場景：{prof.get('scene','')}")
                        if r.trades:
                            tdf = pd.DataFrame(r.trades).copy()
                            show_cols = [c for c in ["entry_date", "exit_date", "entry_price", "exit_price", "pnl_pct", "exit_reason", "holding_days"] if c in tdf.columns]
                            if show_cols:
                                tdf = tdf[show_cols]
                            st.dataframe(tdf.tail(30), use_container_width=True, hide_index=True)
                        else:
                            st.info("此時間段內沒有交易。")

            st.caption(
                f"💡 對標說明：所有策略基於相同時間段 ({cs} ~ {ce})，共同參數（本金 {int(p_cmp['capital'])} HKD，手續費 {float(p_cmp['commission_rate']):.2f}%），賣出邏輯 {p_cmp['sell_logic']}。"
            )

            st.write("---")
            st.markdown("### 📈 三大策略累積收益曲線對比")
            curves = comp_out["curves"]
            fig = go.Figure()
            colors = {"CDM": "#1f77b4", "FZM": "#ff7f0e", "MR": "#2ca02c"}
            for r in ranked:
                cdf = curves.get(r.strategy_name)
                if cdf is None or cdf.empty:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=cdf["date"],
                        y=cdf["cum_pct"],
                        mode="lines+markers",
                        name=f"{r.strategy_name} (年化 {r.annual_return:+.1f}%)",
                        line=dict(color=colors.get(r.strategy_name, "#666"), width=2),
                    )
                )
            if not df_cmp.empty:
                base = (df_cmp["Close"] / float(df_cmp["Close"].iloc[0]) - 1) * 100
                fig.add_trace(go.Scatter(x=df_cmp.index, y=base, mode="lines", name="買入持有", line=dict(color="#888", dash="dash")))
            fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
            fig.update_layout(height=420, template="plotly_white", yaxis_title="累積收益(%)", xaxis_title="日期", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

            st.write("---")
            st.markdown("### 📊 詳細對比表格")
            by_name = {r.strategy_name: r for r in results_list}
            curves = comp_out["curves"]
            rec_days_vals = {k: _compute_recovery_days(curves.get(k)) for k in ["CDM", "FZM", "MR"] if k in by_name}

            def _best(values: Dict[str, float], higher_is_better: bool) -> str:
                items = [(k, v) for k, v in values.items() if pd.notna(v)]
                if not items:
                    return ""
                best_k, _ = (max(items, key=lambda x: x[1]) if higher_is_better else min(items, key=lambda x: x[1]))
                return best_k

            annual_vals = {k: by_name[k].annual_return for k in ["CDM", "FZM", "MR"] if k in by_name}
            win_vals = {k: by_name[k].win_rate for k in ["CDM", "FZM", "MR"] if k in by_name}
            mdd_vals = {k: by_name[k].max_drawdown for k in ["CDM", "FZM", "MR"] if k in by_name}
            sharpe_vals = {k: by_name[k].sharpe_ratio for k in ["CDM", "FZM", "MR"] if k in by_name}
            pf_vals = {k: by_name[k].profit_factor for k in ["CDM", "FZM", "MR"] if k in by_name}
            avgw_vals = {k: by_name[k].avg_winning for k in ["CDM", "FZM", "MR"] if k in by_name}
            avgl_vals = {k: by_name[k].avg_losing for k in ["CDM", "FZM", "MR"] if k in by_name}
            conf_vals = {k: by_name[k].rank_score for k in ["CDM", "FZM", "MR"] if k in by_name}
            tc_vals = {k: float(by_name[k].trades_count) for k in ["CDM", "FZM", "MR"] if k in by_name}

            best_annual = _best(annual_vals, True)
            best_win = _best(win_vals, True)
            best_mdd = _best(mdd_vals, False)
            best_rec = _best({k: v for k, v in rec_days_vals.items() if pd.notna(v)}, False)
            best_sharpe = _best(sharpe_vals, True)
            best_pf = _best(pf_vals, True)
            best_avgw = _best(avgw_vals, True)
            best_avgl = _best(avgl_vals, True)
            best_conf = _best(conf_vals, True)
            best_tc = _best(tc_vals, False)
            win_streak_vals = {k: float(by_name[k].win_streak) for k in ["CDM", "FZM", "MR"] if k in by_name}
            loss_streak_vals = {k: float(by_name[k].loss_streak) for k in ["CDM", "FZM", "MR"] if k in by_name}
            best_wstreak = _best(win_streak_vals, True)
            best_lstreak = _best(loss_streak_vals, False)

            def _fmt(name: str, v: float, suffix: str = "", best: str = "") -> str:
                if pd.isna(v):
                    return "-"
                mark = " ✅" if (best and name == best) else ""
                if suffix == "%":
                    return f"{float(v):+.1f}%{mark}"
                if suffix == "p":
                    return f"{float(v):.2f}{mark}"
                if suffix == "n":
                    return f"{int(v)}{mark}"
                if suffix == "d":
                    return f"{int(v)} 天{mark}"
                return f"{float(v):.2f}{mark}"

            rows = []
            for metric_name, vals, suffix, best in [
                ("年化收益", annual_vals, "%", best_annual),
                ("月平均收益", {k: by_name[k].monthly_return for k in by_name}, "%", _best({k: by_name[k].monthly_return for k in by_name}, True)),
                ("勝率", win_vals, "%", best_win),
                ("平均獲利", avgw_vals, "%", best_avgw),
                ("平均虧損", avgl_vals, "%", best_avgl),
                ("盈虧比", pf_vals, "p", best_pf),
                ("最大回撤", mdd_vals, "%", best_mdd),
                ("回撤恢復天數", rec_days_vals, "d", best_rec),
                ("夏普比率", sharpe_vals, "p", best_sharpe),
                ("信心指數", conf_vals, "p", best_conf),
                ("交易次數", tc_vals, "n", best_tc),
                ("連勝紀錄", win_streak_vals, "n", best_wstreak),
                ("連敗紀錄", loss_streak_vals, "n", best_lstreak),
            ]:
                rows.append(
                    {
                        "指標": metric_name,
                        "CDM": _fmt("CDM", vals.get("CDM", np.nan), suffix=suffix, best=best),
                        "FZM": _fmt("FZM", vals.get("FZM", np.nan), suffix=suffix, best=best),
                        "MR": _fmt("MR", vals.get("MR", np.nan), suffix=suffix, best=best),
                    }
                )
            prof_scene = {"CDM": "中長線", "FZM": "短線", "MR": "偏離"}
            prof_diff = {"CDM": "簡單", "FZM": "中等", "MR": "複雜"}
            prof_freq = {"CDM": "中等", "FZM": "低", "MR": "高"}
            prof_false = {"CDM": "中等", "FZM": "低", "MR": "高"}
            rows.extend(
                [
                    {"指標": "適用場景", "CDM": prof_scene["CDM"], "FZM": prof_scene["FZM"], "MR": prof_scene["MR"]},
                    {"指標": "參數調整難度", "CDM": prof_diff["CDM"] + " ✅", "FZM": prof_diff["FZM"], "MR": prof_diff["MR"]},
                    {"指標": "信號頻率", "CDM": prof_freq["CDM"], "FZM": prof_freq["FZM"] + " ✅", "MR": prof_freq["MR"]},
                    {"指標": "虛假信號比例", "CDM": prof_false["CDM"], "FZM": prof_false["FZM"] + " ✅", "MR": prof_false["MR"]},
                ]
            )
            df_tbl = pd.DataFrame(rows)
            st.dataframe(df_tbl, use_container_width=True, hide_index=True)

            if export_clicked:
                try:
                    import openpyxl

                    output = BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df_tbl.to_excel(writer, sheet_name="對比指標", index=False)
                        for r in results_list:
                            if not r.trades:
                                continue
                            tdf = pd.DataFrame(r.trades)
                            tdf.to_excel(writer, sheet_name=f"{r.strategy_name}_trades", index=False)
                    output.seek(0)
                    st.download_button(
                        "📥 下載 Excel 對比報告",
                        data=output.getvalue(),
                        file_name=f"策略對標_{current_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except Exception:
                    st.download_button(
                        "📥 下載 CSV 對比報告",
                        data=df_tbl.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"策略對標_{current_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

    if show_recommend:
        render_scroll_anchor("backtest-recommend")
        st.markdown("### 🎯 策略推薦")
        comp_out = st.session_state.get("comparison_results")
        if not comp_out:
            st.info("先到「策略對標」執行對標，才能生成推薦。")
        else:
            results_list: List[StrategyComparisonResult] = comp_out["results"]
            ranked = sorted(results_list, key=lambda r: r.rank_score, reverse=True)
            best = ranked[0]
            second = ranked[1] if len(ranked) > 1 else None
            worst = ranked[-1] if len(ranked) > 2 else None

            st.markdown(f"#### 🥇 推薦策略: {best.strategy_name} ({best.rating}) - 綜合評分 {best.rank_score:.1f}/100")
            prof = _strategy_profile(best.strategy_name)
            if prof:
                st.markdown(f"**策略原理**：{prof.get('principle','')}")
                st.markdown(f"**適用場景**：{prof.get('scene','')}")

            def _advantages(x: StrategyComparisonResult, all_r: List[StrategyComparisonResult]) -> List[str]:
                adv = []
                if x.annual_return == max(r.annual_return for r in all_r):
                    adv.append(f"年化收益最高 ({x.annual_return:+.1f}%)")
                if x.win_rate == max(r.win_rate for r in all_r):
                    adv.append(f"勝率最高 ({x.win_rate:.1f}%)")
                if x.max_drawdown == min(r.max_drawdown for r in all_r):
                    adv.append(f"最大回撤最小 ({x.max_drawdown:.1f}%)")
                if x.trades_count == min(r.trades_count for r in all_r):
                    adv.append("交易次數最少，手續費負擔較低")
                if x.sharpe_ratio == max(r.sharpe_ratio for r in all_r):
                    adv.append(f"風險調整收益最優 (夏普比 {x.sharpe_ratio:.2f})")
                return adv

            def _disadvantages(x: StrategyComparisonResult, all_r: List[StrategyComparisonResult]) -> List[str]:
                dis = []
                if x.max_drawdown > min(r.max_drawdown for r in all_r) * 1.2:
                    dis.append(f"最大回撤偏大 ({x.max_drawdown:.1f}%)")
                if x.trades_count > min(r.trades_count for r in all_r) * 1.6:
                    dis.append("交易次數偏多，手續費負擔較高")
                if x.win_rate < 60:
                    dis.append(f"勝率偏低 ({x.win_rate:.1f}%)")
                return dis

            st.write("---")
            st.markdown("**優點**")
            for a in _advantages(best, ranked):
                st.write(f"- ✅ {a}")
            st.markdown("**缺點**")
            for d in _disadvantages(best, ranked):
                st.write(f"- ❌ {d}")

            st.write("---")
            st.markdown("### 💡 操作建議")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.write("**1️⃣【首選】**")
                st.write(f"採用 {best.strategy_name} 策略")
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button(f"✅ 採用 {best.strategy_name}", use_container_width=True, key=f"rec_adopt_best_{current_code}"):
                        st.session_state.selected_strategy = best.strategy_name
                        st.session_state.backtest_params = _apply_strategy_to_params(best.strategy_name, st.session_state.backtest_params)
                        st.success(f"已採用 {best.strategy_name} 策略到回測設定")
                with b2:
                    if st.button("🔄 交叉驗證", use_container_width=True, key=f"rec_cv_{current_code}"):
                        cs = st.session_state.get("cmp_start", st.session_state.get("bt_start"))
                        ce = st.session_state.get("cmp_end", st.session_state.get("bt_end"))
                        if cs and ce:
                            cs_dt = pd.to_datetime(cs)
                            ce_dt = pd.to_datetime(ce)
                            if cs_dt > ce_dt:
                                cs_dt, ce_dt = ce_dt, cs_dt
                            span = ce_dt - cs_dt
                            cv_end = cs_dt
                            cv_start = cs_dt - span
                            df_cv = df[(df.index >= cv_start) & (df.index <= cv_end)].copy()
                            if len(df_cv) >= 50:
                                p_cmp = dict(st.session_state.strategy_compare_params or {})
                                st.session_state.cv_results = run_strategy_comparison_cached(
                                    current_code,
                                    df_cv,
                                    float(p_cmp.get("capital", 10000)),
                                    float(p_cmp.get("commission_rate", 0.2)),
                                    str(p_cmp.get("sell_logic", "🎯 止盈 (+5%)")),
                                    float(p_cmp.get("cdm_threshold", 5.0)),
                                    float(p_cmp.get("mr_threshold", 3.0)),
                                    float(p_cmp.get("wr_threshold", -80.0)),
                                    watchlist_data.get(current_code, {}),
                                )
                            else:
                                st.warning("交叉驗證區間數據不足（至少 50 個交易日）。")
                with b3:
                    if st.button("📊 查看詳細回測", use_container_width=True, key=f"rec_view_bt_{current_code}"):
                        st.session_state.backtest_params = _apply_strategy_to_params(best.strategy_name, st.session_state.backtest_params)
                        st.session_state.backtest_output = run_backtest_cached(current_code, df_bt, st.session_state.backtest_params, watchlist_data.get(current_code, {}))
                        st.success("已切換到單策略回測並重新計算")

                cv_out = st.session_state.get("cv_results")
                if cv_out:
                    cv_ranked = sorted(cv_out["results"], key=lambda r: r.rank_score, reverse=True)
                    with st.expander("交叉驗證結果（前一個同長度區間）", expanded=False):
                        for r in cv_ranked:
                            st.write(f"{r.strategy_name} | 年化 {r.annual_return:+.1f}% | 勝率 {r.win_rate:.1f}% | 回撤 {r.max_drawdown:.1f}% | 評分 {r.rank_score:.1f}/100")
            with c2:
                st.write("**2️⃣【備選】**")
                if second:
                    st.write(f"{second.strategy_name} | 評分 {second.rank_score:.1f}/100")
            with c3:
                st.write("**3️⃣【風險管理】**")
                st.write("回測不代表未來，請務必設定止損並控制倉位。")

            st.write("---")
            st.warning("⚠️ 回測數據基於歷史，無法保證未來表現；市場環境變化時最優策略可能改變。請避免過度槓桿，並控制單次虧損在總資金 2% 以內。")

            prof = _strategy_profile(best.strategy_name)
            if prof:
                st.write("---")
                st.markdown("### 📊 策略特性分析")
                st.markdown(f"**【策略原理】**\n\n{prof.get('principle','')}")
                st.markdown("**【參數設置】**")
                p_cmp = dict(st.session_state.strategy_compare_params or {})
                st.write(f"CDM 閾值: {float(p_cmp.get('cdm_threshold', 5.0)):.1f}% | MR 閾值: {float(p_cmp.get('mr_threshold', 3.0)):.1f}% | WR 閾值: {float(p_cmp.get('wr_threshold', -80.0)):.0f} | 賣出: {str(p_cmp.get('sell_logic',''))}")
                ce = st.session_state.get("cmp_end", st.session_state.get("bt_end", max_d))
                recent = _recent_performance(best.trades, ce, days=30)
                st.markdown("**【最近表現】(最近 30 天)**")
                st.write(f"勝率: {recent['win_rate']:.0f}% ({recent['winning_trades']}/{recent['total_trades']} 筆交易獲利)")
                st.write(f"月均收益: {recent['monthly_return']:+.1f}%")
                st.write(f"最大單筆虧損: {recent['max_loss']:+.1f}%")

            now = datetime.now()
            next_eval = now + timedelta(days=30)
            st.caption(f"📌 最後更新: {now.strftime('%Y-%m-%d %H:%M')}｜🔄 下次自動評估: {next_eval.strftime('%Y-%m-%d')}")


@st.cache_data(ttl=300)
def get_comparison_data(watchlist_codes: List[str], ref_date: str, watchlist_params: Dict[str, Any]) -> Dict[str, Any]:
    comparison_data = {}
    ref_dt = pd.to_datetime(ref_date)

    for ticker in watchlist_codes:
        yt = get_yahoo_ticker(ticker)
        try:
            df = yf.download(yt, period="3y", progress=False, auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[df.index <= ref_dt]
            if df is None or df.empty or len(df) < 30:
                continue

            curr_close = float(df["Close"].iloc[-1])
            prev_close = df["Close"].shift(1).iloc[-1]
            prev_close = float(prev_close) if pd.notna(prev_close) and float(prev_close) != 0 else np.nan
            chg_pct = ((curr_close - prev_close) / prev_close * 100) if pd.notna(prev_close) else np.nan

            sma7 = df["Close"].rolling(7).mean().iloc[-1] if len(df) >= 7 else np.nan
            sma14 = df["Close"].rolling(14).mean().iloc[-1] if len(df) >= 14 else np.nan
            sma28 = df["Close"].rolling(28).mean().iloc[-1] if len(df) >= 28 else np.nan
            sma57 = df["Close"].rolling(57).mean().iloc[-1] if len(df) >= 57 else np.nan
            sma106 = df["Close"].rolling(106).mean().iloc[-1] if len(df) >= 106 else np.nan
            sma212 = df["Close"].rolling(212).mean().iloc[-1] if len(df) >= 212 else np.nan

            avgp_vals = [curr_close, sma7, sma14, sma28, sma57, sma106, sma212]
            valid_avgp = [float(v) for v in avgp_vals if pd.notna(v) and float(v) > 0]
            avg_avgp = (sum(valid_avgp) / len(valid_avgp)) if valid_avgp else np.nan
            mr_pct = ((curr_close / avg_avgp) - 1) * 100 if pd.notna(avg_avgp) and float(avg_avgp) != 0 else np.nan

            amp0 = np.nan
            if pd.notna(prev_close) and float(prev_close) != 0:
                amp0 = (float(df["High"].iloc[-1]) - float(df["Low"].iloc[-1])) / float(prev_close) * 100

            amp_series = (df["High"] - df["Low"]) / df["Close"].shift(1).replace(0, np.nan) * 100
            amp_rolling = []
            for p in [7, 14, 28, 57, 106, 212]:
                v = amp_series.rolling(p).mean().iloc[-1] if len(amp_series) >= p else np.nan
                amp_rolling.append(float(v) if pd.notna(v) else np.nan)
            valid_amp = [v for v in amp_rolling if pd.notna(v) and v > 0]
            avg_amp = (sum(valid_amp) / len(valid_amp)) if valid_amp else np.nan
            amp_mr_pct = ((float(amp0) / float(avg_amp)) - 1) * 100 if pd.notna(amp0) and pd.notna(avg_amp) and float(avg_amp) != 0 else np.nan

            amp_level = "🟢 低"
            if pd.notna(avg_amp) and pd.notna(amp0) and float(avg_amp) != 0:
                ratio = float(amp0) / float(avg_amp)
                if ratio > 1.5:
                    amp_level = "🔴 高"
                elif 1.2 < ratio <= 1.5:
                    amp_level = "🟠 中等"

            risk_level = "🟡 低風險"
            if pd.notna(amp_mr_pct):
                if float(amp_mr_pct) > 50:
                    risk_level = "🔴 高風險"
                elif 20 < float(amp_mr_pct) <= 50:
                    risk_level = "🟠 中風險"
                elif float(amp_mr_pct) <= 20:
                    risk_level = "🟡 低風險"
                if float(amp_mr_pct) < -20:
                    risk_level = "🟢 超低風險"

            trend_score = _trend_score(curr_close, sma7, sma14, sma28)
            trend_icon = _trend_icon(trend_score)

            cdm = _cdm_metrics(df, watchlist_params.get(ticker, {}))

            comparison_data[ticker] = {
                "ticker": ticker,
                "price": curr_close,
                "change_pct": float(chg_pct) if pd.notna(chg_pct) else np.nan,
                "sma7": float(sma7) if pd.notna(sma7) else np.nan,
                "sma14": float(sma14) if pd.notna(sma14) else np.nan,
                "sma28": float(sma28) if pd.notna(sma28) else np.nan,
                "trend_score": trend_score,
                "trend_icon": trend_icon,
                "mr_pct": float(mr_pct) if pd.notna(mr_pct) else np.nan,
                "mr_rating": _mr_rating(mr_pct),
                "mr_reco": _mr_recommendation(trend_icon, mr_pct),
                "amp0": float(amp0) if pd.notna(amp0) else np.nan,
                "avg_amp": float(avg_amp) if pd.notna(avg_amp) else np.nan,
                "amp_mr_pct": float(amp_mr_pct) if pd.notna(amp_mr_pct) else np.nan,
                "amp_level": amp_level,
                "risk_level": risk_level,
                "amp_pred": (
                    f"{float(avg_amp) * 0.8:.2f}% - {float(avg_amp) * 1.2:.2f}%"
                    if pd.notna(avg_amp)
                    else "-"
                ),
                "cdm_status": cdm["status"],
                "cdm_target": cdm["target"],
                "cdm_diff_pct": cdm["diff_pct"],
                "cdm_tor_ok": cdm["tor_ok"],
                "cdm_confidence": cdm["confidence"],
                "cdm_tor_info": cdm["tor_info"],
            }
        except Exception:
            continue

    return comparison_data

def _apply_comparison_filters(df: pd.DataFrame, filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if not filters:
        return df

    out = df.copy()

    trend = filters.get("trend")
    if trend:
        allowed = set()
        for t in trend:
            if "⬆️⬆️⬆️" in t:
                allowed.add("⬆️⬆️⬆️")
            elif "⬆️⬆️" in t:
                allowed.add("⬆️⬆️")
            elif "⬆️" in t:
                allowed.add("⬆️")
            elif "⬇️" in t:
                allowed.add("⬇️⬇️⬇️")
        if allowed:
            out = out[out["趨勢"].isin(allowed)]

    mr = filters.get("mr")
    if mr and "MR級別" in out.columns:
        allowed = set([m.split(" ")[0] for m in mr])
        out = out[out["MR級別"].str.split(" ").str[0].isin(allowed)]

    cdm = filters.get("cdm")
    if cdm and "CDM狀態" in out.columns:
        allowed = set([c.split(" ")[0] for c in cdm])
        out = out[out["CDM狀態"].str.split(" ").str[0].isin(allowed)]

    return out

def _render_table_with_ticker_buttons(title: str, rows: list[dict], columns: list[tuple[str, str]]):
    st.subheader(title)
    if not rows:
        st.info("無資料")
        return
    st.caption("卡片模式：手機可直向滑動查看，點擊股票即可進入單股分析。")

    def _card_variant(row: dict) -> str:
        trend = str(row.get("趨勢", ""))
        cdm = str(row.get("CDM狀態", ""))
        reco = str(row.get("推薦度", ""))
        action = str(row.get("推薦操作", ""))
        mr_level = str(row.get("MR級別", ""))
        risk = str(row.get("風險等級", ""))
        amp_level = str(row.get("級別", ""))
        if "買入重點" in action or "⭐⭐⭐" in reco or cdm.startswith("🔴 觸發") or trend == "⬆️⬆️⬆️":
            return "compare-positive"
        if "⏳" in cdm or "可考慮" in action or "觀望" in action or "⭐⭐" in reco or trend == "⬆️⬆️" or "🟠" in amp_level:
            return "compare-watch"
        if "⚠️" in reco or "謹慎" in action or trend == "⬇️⬇️⬇️" or "🔴" in risk or "🔴" in mr_level or cdm.startswith("❌"):
            return "compare-risk"
        return "compare-watch" if trend == "⬆️" or "🟠" in mr_level else ""

    for idx in range(0, len(rows), 2):
        pair = rows[idx:idx + 2]
        row_cols = st.columns(len(pair))
        for col, r in zip(row_cols, pair):
            t = str(r.get("股票", ""))
            variant = _card_variant(r)
            badge = (
                r.get("排名")
                or r.get("CDM狀態")
                or r.get("推薦度")
                or r.get("趨勢")
                or ""
            )
            metrics_html = "".join(
                [
                    (
                        f'<div class="compare-card-item">'
                        f'<div class="compare-card-label">{col_label}</div>'
                        f'<div class="compare-card-value">{r.get(col_key, "-")}</div>'
                        f'</div>'
                    )
                    for col_key, col_label in columns
                ]
            )
            col.markdown(
                f"""
                <div class="compare-card {variant}">
                    <div class="compare-card-head">
                        <div class="compare-card-stock">{t}</div>
                        <div class="compare-card-badge {variant}">{badge}</div>
                    </div>
                    <div class="compare-card-grid">{metrics_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if col.button(f"查看 {t}", key=f"compare_nav_{title}_{t}_{r.get('_row_id', '')}", use_container_width=True):
                set_current_page("stock", t)
                st.rerun()

def render_comparison_page(watchlist_list: List[str], watchlist_data: Dict[str, Any]):
    st.title("📊 港股收藏夾對比面板")
    show_trend = True
    show_mr = True
    show_cdm = True
    show_amp = True
    show_score = True

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        if st.button("🏠 回到主頁面", use_container_width=True):
            set_current_page("home")
            st.rerun()
    with col2:
        if st.button("🔄 刷新數據", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with col4:
        if st.button("🔧 篩選設定", use_container_width=True):
            st.session_state.show_filter = not st.session_state.get("show_filter", False)
    download_slot = col3.empty()

    st.write("---")

    if st.session_state.get("show_filter", False):
        with st.expander("🔧 篩選設定", expanded=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                filter_trend = st.multiselect(
                    "篩選趨勢",
                    ["⬆️⬆️⬆️ 強勢", "⬆️⬆️ 上升", "⬆️ 弱勢", "⬇️ 下跌"],
                    default=["⬆️⬆️⬆️ 強勢", "⬆️⬆️ 上升"],
                )
            with c2:
                filter_mr = st.multiselect(
                    "篩選偏差",
                    ["🔴 極度", "🟠 中度", "🟡 輕度", "🟢 正常"],
                    default=["🔴 極度", "🟠 中度"],
                )
            with c3:
                filter_cdm = st.multiselect(
                    "篩選 CDM 狀態",
                    ["🔴 觸發", "⏳ 待觀察", "❌ 未觸發", "⚙️ 未配置"],
                    default=["🔴 觸發", "⏳ 待觀察"],
                )
            if st.button("✅ 應用篩選", use_container_width=True):
                st.session_state.comparison_filters = {"trend": filter_trend, "mr": filter_mr, "cdm": filter_cdm}

    with st.spinner("彙總對比數據中..."):
        comp = get_comparison_data(watchlist_list, st.session_state.ref_date.strftime("%Y-%m-%d"), watchlist_data)

    if not comp:
        st.warning("無法獲取對比數據（可能是網路或資料不足）。")
        return

    base_rows = []
    for t, d in comp.items():
        base_rows.append(
            {
                "股票": t,
                "現價": d["price"],
                "變化%": d["change_pct"],
                "SMA7": d["sma7"],
                "SMA14": d["sma14"],
                "SMA28": d["sma28"],
                "趨勢": d["trend_icon"],
                "趨勢分數": d["trend_score"],
                "AvgP MR%": d["mr_pct"],
                "MR級別": d["mr_rating"],
                "推薦度": d["mr_reco"],
                "CDM狀態": d["cdm_status"],
                "CDM目標價": d["cdm_target"],
                "CDM偏差%": d["cdm_diff_pct"],
                "TOR信號": ("✅" if d["cdm_tor_ok"] is True else "❌" if d["cdm_tor_ok"] is False else "-"),
                "信心度": d["cdm_confidence"],
                "AMP(%)": d["amp0"],
                "Avg AMP": d["avg_amp"],
                "AMP MR%": d["amp_mr_pct"],
                "級別": d["amp_level"],
                "預測振幅": d["amp_pred"],
                "風險等級": d["risk_level"],
            }
        )

    df_base = pd.DataFrame(base_rows)

    filters = st.session_state.get("comparison_filters")

    df_trend = df_base[["股票", "現價", "變化%", "SMA7", "SMA14", "SMA28", "趨勢", "趨勢分數"]].copy()
    df_trend["現價"] = df_trend["現價"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
    df_trend["變化%"] = df_trend["變化%"].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}%")
    for k in ["SMA7", "SMA14", "SMA28"]:
        df_trend[k] = df_trend[k].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
    df_trend = df_trend.sort_values("趨勢分數", ascending=False).drop(columns=["趨勢分數"])
    df_trend = _apply_comparison_filters(df_trend, filters)

    trend_rows = []
    for idx, row in df_trend.iterrows():
        trend_rows.append({**row.to_dict(), "_row_id": str(idx)})
    if show_trend:
        render_scroll_anchor("comparison-trend")
        _render_table_with_ticker_buttons(
            "📈 【SMA 上升趨勢排序】",
            trend_rows,
            [("現價", "現價"), ("變化%", "變化%"), ("SMA7", "SMA7"), ("SMA14", "SMA14"), ("SMA28", "SMA28"), ("趨勢", "趨勢")],
        )

    df_mr = df_base[["股票", "現價", "AvgP MR%", "MR級別", "趨勢", "推薦度", "趨勢分數"]].copy()
    df_mr["現價"] = df_mr["現價"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
    df_mr["AvgP MR%"] = df_mr["AvgP MR%"].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}%")
    df_mr["_abs_mr"] = df_base["AvgP MR%"].abs()
    df_mr = df_mr.sort_values(["_abs_mr", "趨勢分數"], ascending=[False, False]).drop(columns=["_abs_mr", "趨勢分數"])
    df_mr = _apply_comparison_filters(df_mr.rename(columns={"趨勢": "趨勢"}), filters)
    mr_rows = []
    for rank, (idx, row) in enumerate(df_mr.iterrows(), start=1):
        r = row.to_dict()
        r["排名"] = rank
        mr_rows.append({**r, "_row_id": str(idx)})
    if show_mr:
        render_scroll_anchor("comparison-mr")
        _render_table_with_ticker_buttons(
            "💰 【MR 偏差排序 - 機會大小】",
            mr_rows,
            [("排名", "排名"), ("現價", "現價"), ("AvgP MR%", "AvgP MR%"), ("MR級別", "評級"), ("趨勢", "上升勢"), ("推薦度", "推薦")],
        )

    df_cdm = df_base[["股票", "CDM狀態", "CDM目標價", "CDM偏差%", "TOR信號", "信心度", "趨勢"]].copy()
    df_cdm["CDM目標價"] = df_cdm["CDM目標價"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
    df_cdm["CDM偏差%"] = df_cdm["CDM偏差%"].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}%")
    df_cdm["信心度"] = df_cdm["信心度"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.0f}%")
    df_cdm = _apply_comparison_filters(df_cdm, filters)
    cdm_rows = []
    for idx, row in df_cdm.iterrows():
        cdm_rows.append({**row.to_dict(), "_row_id": str(idx)})
    if show_cdm:
        render_scroll_anchor("comparison-cdm")
        _render_table_with_ticker_buttons(
            "🔴 【CDM 觸發狀態 - 即時機會】",
            cdm_rows,
            [("CDM狀態", "CDM狀態"), ("CDM目標價", "目標價"), ("CDM偏差%", "偏差%"), ("TOR信號", "TOR信號"), ("信心度", "信心度")],
        )

    df_amp = df_base[["股票", "AMP(%)", "AMP MR%", "級別", "預測振幅", "風險等級", "趨勢"]].copy()
    df_amp["_amp_mr_sort"] = df_base["AMP MR%"]
    df_amp["AMP(%)"] = df_amp["AMP(%)"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}%")
    df_amp["AMP MR%"] = df_amp["AMP MR%"].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.0f}%")
    df_amp = df_amp.sort_values("_amp_mr_sort", ascending=False).drop(columns=["_amp_mr_sort"])
    df_amp = _apply_comparison_filters(df_amp, filters)
    amp_rows = []
    for idx, row in df_amp.iterrows():
        amp_rows.append({**row.to_dict(), "_row_id": str(idx)})
    if show_amp:
        render_scroll_anchor("comparison-amp")
        _render_table_with_ticker_buttons(
            "📊 【振幅對比 - 交易機會大小】",
            amp_rows,
            [("AMP(%)", "AMP(%)"), ("AMP MR%", "AMP MR%"), ("級別", "級別"), ("預測振幅", "預測振幅"), ("風險等級", "風險等級")],
        )

    def _trend_points(icon: str) -> float:
        if icon == "⬆️⬆️⬆️":
            return 10.0
        if icon == "⬆️⬆️":
            return 7.0
        if icon == "⬆️":
            return 5.0
        return 2.0

    def _cdm_points(status: str) -> float:
        if "🔴" in status:
            return 10.0
        if "⏳" in status:
            return 6.0
        if "❌" in status:
            return 2.0
        return 0.0

    def _dev_points(trend_icon: str, mr_pct: float) -> float:
        if pd.isna(mr_pct):
            return 0.0
        v = abs(float(mr_pct))
        if v <= 1:
            return 4.0
        if 1 < v <= 3:
            return 7.0
        if 3 < v <= 5:
            return 10.0 if trend_icon in ("⬆️⬆️⬆️", "⬆️⬆️") else 6.0
        return 8.0 if trend_icon in ("⬆️⬆️⬆️", "⬆️⬆️") else 4.0

    def _amp_points(trend_icon: str, amp_level: str) -> float:
        if "🔴" in amp_level or "🟠" in amp_level:
            return 10.0 if trend_icon in ("⬆️⬆️⬆️", "⬆️⬆️") else 4.0
        if "🟢" in amp_level:
            return 3.0
        return 0.0

    score_rows = []
    for r in base_rows:
        tr = r.get("趨勢", "⬇️⬇️⬇️")
        mr_v = r.get("AvgP MR%")
        cdm_s = r.get("CDM狀態", "⚙️ 未配置")
        amp_level = r.get("級別", "🟢 低")
        score = (
            _trend_points(tr) * 0.25
            + _dev_points(tr, mr_v) * 0.30
            + _cdm_points(cdm_s) * 0.25
            + _amp_points(tr, amp_level) * 0.20
        )
        if score >= 8.5:
            action = "🟢 買入重點"
        elif 7.0 <= score < 8.5:
            action = "🟡 可考慮"
        elif 5.5 <= score < 7.0:
            action = "🔵 觀望"
        else:
            action = "🔴 謹慎"

        score_rows.append(
            {
                "股票": r["股票"],
                "評分": float(score),
                "趨勢": tr,
                "偏差": r.get("MR級別", "-"),
                "振幅": r.get("級別", "-"),
                "推薦操作": action,
                "CDM": cdm_s,
            }
        )

    df_score = pd.DataFrame(score_rows).sort_values("評分", ascending=False)
    df_score = _apply_comparison_filters(df_score.rename(columns={"CDM": "CDM狀態", "偏差": "MR級別"}), filters).rename(
        columns={"CDM狀態": "CDM", "MR級別": "偏差"}
    )
    score_table_rows = []
    for rank, (idx, row) in enumerate(df_score.iterrows(), start=1):
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else str(rank)
        score_table_rows.append(
            {
                "_row_id": str(idx),
                "股票": row["股票"],
                "排名": medal,
                "評分": f"{float(row['評分']):.2f}",
                "趨勢": row["趨勢"],
                "偏差": row["偏差"],
                "振幅": row["振幅"],
                "推薦操作": row["推薦操作"],
            }
        )
    if show_score:
        render_scroll_anchor("comparison-score")
        _render_table_with_ticker_buttons(
            "⭐ 【綜合評分排序 - 當日最佳機會】",
            score_table_rows,
            [("排名", "排名"), ("評分", "評分"), ("趨勢", "趨勢"), ("偏差", "偏差"), ("振幅", "振幅"), ("推薦操作", "推薦操作")],
        )

    try:
        import openpyxl

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_trend.to_excel(writer, sheet_name="SMA趨勢", index=False)
            df_mr.drop(columns=["趨勢"], errors="ignore").to_excel(writer, sheet_name="MR偏差", index=False)
            df_cdm.to_excel(writer, sheet_name="CDM狀態", index=False)
            df_amp.to_excel(writer, sheet_name="振幅對比", index=False)
            df_score.to_excel(writer, sheet_name="綜合評分", index=False)
        output.seek(0)

        download_slot.download_button(
            label="⬇️ 下載報告",
            data=output.getvalue(),
            file_name=f"港股對比報告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception:
        csv_data = df_base.to_csv(index=False).encode("utf-8-sig")
        download_slot.download_button(
            label="⬇️ 下載報告(CSV)",
            data=csv_data,
            file_name=f"港股對比報告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    colf1, colf2 = st.columns([3, 1])
    with colf1:
        st.caption(f"📌 最後更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (已同步)")
    with colf2:
        st.caption("💡 點擊股票代號可查看詳細圖表")

# v9.6 新增：模擬買賣盤數據
def simulate_bs_data(df, tsi):
    """
    TSI: Total Shares Issued (發行股本)
    基於 Volume 模擬 MMB, MMS, RTB, RTS
    """
    if tsi is None or tsi == 0:
        return df
    
    # 簡單模擬：成交量分配與大戶/散戶比例
    vol = df['Volume'].fillna(0)

    # 定義模擬權重 (假設值)
    df['UBTB'] = vol * 0.15 
    df['BTB']  = vol * 0.25 
    df['RIB']  = vol * 0.10 
    
    df['UBTS'] = vol * 0.15 
    df['BTS']  = vol * 0.25 
    df['RIS']  = vol * 0.10 

    # 套用公式
    denom = float(tsi)
    df['MMB'] = (df['UBTB'] * 0.9 + df['BTB'] * 0.7) / denom * 100
    df['RTB'] = (df['UBTB'] * 0.1 + df['BTB'] * 0.3 + df['RIB']) / denom * 100
    df['MMS'] = (df['UBTS'] * 0.1 + df['BTS'] * 0.7) / denom * 100
    df['RTS'] = (df['UBTS'] * 0.1 + df['BTS'] * 0.3 + df['RIS']) / denom * 100

    return df

def run_analysis_logic(df, symbol, params):
    # 參數設定
    CDM_COEF1, CDM_COEF2, CDM_THRESHOLD = 0.7, 0.5, 0.05
    curr_price = df['Close'].iloc[-1]
    today = datetime.now().date()
    down6_trigger = is_consecutive_down(df["Close"], 6)
    tor_down5_trigger = bool("Turnover_Rate" in df.columns and is_consecutive_down(df["Turnover_Rate"], 5))
    
    # CDM 運算
    cdm_status, target_price_str, diff_str = "未設定參數", "N/A", "N/A"
    b1_s = params.get('box1_start')
    b1_e = params.get('box1_end')
    b2_s = params.get('box2_start')
    b2_e = params.get('box2_end')

    def _parse_float(v):
        try:
            if v is None:
                return np.nan
            if isinstance(v, str) and (not v.strip()):
                return np.nan
            return float(v)
        except Exception:
            return np.nan

    p1_avg_override = _parse_float(params.get('cdm_p1_avg_override'))
    p2_avg_override = _parse_float(params.get('cdm_p2_avg_override'))

    if b1_s and b1_e and b2_s and b2_e:
        try:
            s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
            s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)
            sma1_calc = df[(df.index >= s1) & (df.index <= e1)]['Close'].mean()
            sma2_calc = df[(df.index >= s2) & (df.index <= e2)]['Close'].mean()

            sma1 = p1_avg_override if (pd.notna(p1_avg_override) and p1_avg_override > 0) else sma1_calc
            sma2 = p2_avg_override if (pd.notna(p2_avg_override) and p2_avg_override > 0) else sma2_calc

            t1_days = (e1 - s1).days
            n_days = (pd.to_datetime(today) - s1).days

            if n_days > 0:
                p_target = (sma1 * CDM_COEF1 * (t1_days / n_days)) + (sma2 * CDM_COEF2 * ((n_days - t1_days) / n_days))
                if pd.notna(p_target) and p_target != 0 and pd.notna(curr_price) and curr_price:
                    diff = abs(p_target - curr_price) / curr_price
                    diff_pct = (p_target - curr_price) / curr_price * 100

                    tor_cond = False
                    tor_info = "TOR: N/A"
                    if "Turnover_Rate" in df.columns and len(df) >= 20:
                        curr_tor = df["Turnover_Rate"].iloc[-1]
                        avg20_tor = df["Turnover_Rate"].tail(20).mean()
                        if pd.notna(curr_tor) and pd.notna(avg20_tor) and avg20_tor > 0:
                            threshold_tor = avg20_tor / 5
                            tor_cond = float(curr_tor) < float(threshold_tor)
                            tor_info = f"TOR: {float(curr_tor):.2f}% (< {float(threshold_tor):.2f}%)"

                    sma57 = df["Close"].rolling(57).mean().iloc[-1] if len(df) >= 57 else np.nan
                    sma106 = df["Close"].rolling(106).mean().iloc[-1] if len(df) >= 106 else np.nan

                    sma_cond = False
                    if pd.notna(sma57) and pd.notna(sma106) and sma57 and sma106:
                        sma_cond = (
                            abs(float(sma57) - float(sma106)) / abs(float(sma106)) < 0.05
                            and abs(float(curr_price) - float(sma57)) / abs(float(sma57)) < 0.05
                            and abs(float(curr_price) - float(sma106)) / abs(float(sma106)) < 0.05
                        )

                    target_price_str = f"{p_target:.2f}"
                    diff_str = f"{diff_pct:+.2f}"
                    cdm_status = "🔴 <b>觸發</b>" if (diff < CDM_THRESHOLD and tor_cond and sma_cond) else "未觸發"
        except:
            pass
    
    # FZM 運算
    df['SMA7'] = df['Close'].rolling(7).mean()
    df['SMA14'] = df['Close'].rolling(14).mean()
    df['WillR'] = calculate_willr(df['High'], df['Low'], df['Close'], 35)
    
    val_sma7, val_sma14 = df['SMA7'].iloc[-1], df['SMA14'].iloc[-1]
    val_willr = df['WillR'].iloc[-1]
    lowest_low = df['Low'].tail(5).min()
    
    cond_a = (curr_price > val_sma7) and (curr_price > val_sma14)
    cond_b = (val_willr < -80) 
    fzm_status = "🔴 <b>觸發</b>" if (cond_a and cond_b) else "未觸發"
    trend_str = "站上雙均線" if cond_a else "均線下方"
    down6_status = "🔴 <b>觸發</b>" if down6_trigger else "未觸發"
    tor_down5_status = "🔴 <b>觸發</b>" if tor_down5_trigger else "未觸發"
    tor_latest = df["Turnover_Rate"].iloc[-1] if "Turnover_Rate" in df.columns and len(df) else np.nan

    report = f"""<b>[股票警示] {symbol} 分析報告</b>
<b>1. CDM: {cdm_status}</b> (目標: {target_price_str}, 偏差: {diff_str}%, {tor_info})
<b>2. FZM: {fzm_status}</b> (WR: {val_willr:.2f}, {trend_str})
<b>3. 連跌6日: {down6_status}</b>
<b>4. 換手率連跌5日: {tor_down5_status}</b> (TOR: {'-' if pd.isna(tor_latest) else f'{float(tor_latest):.2f}%'} )
建議止損: {lowest_low:.2f}
"""
    return report

@st.cache_resource(show_spinner=False)
def get_float_provider() -> CSVFloatProvider:
    """Return the cached CSV-backed float metadata provider."""
    csv_path = Path(__file__).resolve().parent / "metadata" / "float.csv"
    return CSVFloatProvider(csv_path)

@st.cache_resource(show_spinner=False)
def get_share_base_provider() -> CompositeShareBaseProvider:
    """Return the cached provider chain for turnover share-base lookups."""
    metadata_dir = Path(__file__).resolve().parent / "metadata"
    return CompositeShareBaseProvider(
        [
            CSVShareBaseProvider(metadata_dir / "share_base.csv"),
            YahooShareBaseProvider(),
        ]
    )

def get_turnover_share_lookup(ticker_obj) -> ShareBaseLookupResult:
    """Resolve turnover denominator with override-first share-base behavior."""
    ticker = clean_ticker_input(getattr(ticker_obj, "ticker", ""))
    try:
        provider = get_share_base_provider()
        return provider.get_share_base(ticker_obj)
    except Exception as exc:
        LOGGER.warning("Share-base lookup failed for %s: %s", ticker, exc)
        return ShareBaseLookupResult(
            ticker=ticker,
            share_base=None,
            method=None,
            warning=f"Unable to resolve turnover share base for ticker {ticker}.",
            source="provider",
            confidence="low",
        )

def get_turnover_share_base(ticker_obj):
    """Preserve the existing API by returning only the resolved share-base value."""
    return get_turnover_share_lookup(ticker_obj).share_base


def _resolve_share_base_post(df: pd.DataFrame, symbol: str,
                             fallback_avg_tor_pct: float = 0.35,
                             fallback_window: int = 120):
    """
    後置補齊 share_base：所有 Route（native/yfinance/stooq/sina）拿到 df 後都應該呼叫。
    策略：
      1) 先試 Composite Provider（CSV share_base.csv → YahooShareBaseProvider via Ticker.info）。
      2) 仍 None → 用 df 最近 N 日 Volume 均值 ÷ (fallback_avg_tor_pct / 100) 反推近似 share_base。
         例如港股日均約 0.35% 換手率，則 share_base ≈ avg_volume / 0.0035。
    回傳 (share_base, approx_note)：
      approx_note = None   → 精確值（Provider 回傳）
      approx_note = "APPROX_Xpct_windowY" → 近似值，X% 換手率 + Y 日平均成交量反推
      approx_note = "NO_VOLUME" → 連 Volume 都沒有，TOR 仍不可算
    """
    approx_note = None
    share_base = None
    try:
        t_obj = yf.Ticker(symbol)
        share_base = get_turnover_share_base(t_obj)
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

def clamp_date_to_range(value, min_d: date, max_d: date, fallback: date) -> date:
    try:
        parsed = pd.to_datetime(value)
        if pd.isna(parsed):
            return fallback
        value_date = parsed.date()
    except Exception:
        return fallback
    if value_date < min_d:
        return min_d
    if value_date > max_d:
        return max_d
    return value_date

def sync_date_window_state(start_key: str, end_key: str, min_d: date, max_d: date, lookback_days: int = 365):
    default_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=lookback_days)).date())
    start_value = clamp_date_to_range(st.session_state.get(start_key), min_d, max_d, default_start)
    end_value = clamp_date_to_range(st.session_state.get(end_key), min_d, max_d, max_d)
    if start_value > end_value:
        start_value, end_value = end_value, start_value
    st.session_state[start_key] = start_value
    st.session_state[end_key] = end_value

_YF_LAST_ERROR: Dict[str, Any] = {}
_NATIVE_DOWNLOAD_STATS: Dict[str, Any] = {"native_attempts": 0, "native_success": 0,
                                          "yf_attempts": 0, "yf_success": 0}
_YF_PERSIST_ERR_LOG = []  # [(time, symbol, route, detail)]
_YF_NATIVE_STEP_LOG = []  # [(time, symbol, stage, message)]
_YF_LOG_LOCK = _YF_SESS_MGR._lock if hasattr(_YF_SESS_MGR, "_lock") else None

def _yf_append_log(log_list: list, payload, limit: int = 20):
    try:
        if _YF_LOG_LOCK: _YF_LOG_LOCK.acquire(timeout=0.5)
        log_list.append(payload)
        while len(log_list) > limit:
            log_list.pop(0)
    except Exception:
        pass
    finally:
        try:
            if _YF_LOG_LOCK and _YF_LOG_LOCK.locked(): _YF_LOG_LOCK.release()
        except Exception:
            pass

def _yf_log_step(symbol: str, stage: str, message: str):
    # 性能優化：首頁 N 支股票串行下載會把 step log 塞爆；收斂到最近 12 條，足夠 debug 又不會拖慢 rerun
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

def _native_yahoo_chart_download(symbol, range_: str = "5y", interval: str = "1d", timeout: int = 25):
    """
    Route 1（優先）: 原生 requests 打 Yahoo v8 chart API。
    只保留美國 query1/query2 × events/basic = 4 endpoints（HK mirror 404/.hk DNS 不存在已拔掉）。
    + 4 UA 隨機 + Referer + Accept-Language + step log 每步全記。
    """
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


def _native_stooq_download(symbol: str, period_years: int = 5, timeout: int = 25):
    """
    Route 3（Yahoo 雙路線全失敗的最終備援）：Stooq 歷史 CSV API。
    完全不需要 cookie / crumb / UA 擬態！HK 股格式 00290.HK。
    """
    from io import StringIO
    from datetime import datetime, timedelta
    _yf_log_step(symbol, "stooq.init", f"period={period_years}y symbol={symbol}")
    try:
        stooq_sym = symbol.replace(".HK", "^HK").replace(".hk", "^HK") if False else symbol
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


def _try_yfinance_download(symbol, period: str = "5y", timeout: int = 30):
    """
    備援路線 2：改用 yf.Ticker(symbol).history(repair=True, auto_adjust=False)
    repair=True 會自動修 Yahoo 偶爾回的壞資料，比 yf.download() 更穩。
    """
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
            _persist_last_error(symbol, "yfinance", f"Ticker.history failed → fallback download()")
            df = yf.download(symbol, period=period, progress=False, auto_adjust=False, timeout=timeout, actions=False)
        if df is None or df.empty:
            raise RuntimeError("yfinance returned empty DataFrame")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        share_base = None
        try:
            t2 = yf.Ticker(symbol)
            share_base = get_turnover_share_base(t2)
        except Exception:
            share_base = None
        return df, share_base
    except Exception as exc:
        msg = str(exc) or ""
        name = type(exc).__name__
        short = f"{name}: {msg[:180]}"
        _persist_last_error(symbol, "yfinance", short)
        raise RuntimeError(short) from exc


def _native_sina_download(symbol: str, timeout: int = 25):
    """
    Route 4（Yahoo+Stooq 全失敗的最終備援）：新浪財經 HK 歷史 K 線 JSON API。
    完全不需要 crumb / cookie；HK 股 symbol: hk{4位數字}，例如 hk00290 → 00290.HK。
    接口：https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=hk00290&scale=240&ma=no&datalen=1500
    """
    import json as _json
    import re
    _yf_log_step(symbol, "sina.init", f"symbol={symbol}")
    try:
        digits = re.sub(r"\D", "", symbol)
        if not digits:
            raise RuntimeError(f"sina: symbol {symbol} 沒數字")
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


@st.cache_data(ttl=900)
def get_data_v7(symbol, end_date):
    sym_upper = str(symbol).strip().upper()

    # Step A: prefer SQLite persistent cache (daemon pre-fetched). max_age=10min = within trading session.
    is_cached = False
    if _CACHE_LAYER_OK and _get_cached_ohlcv is not None:
        try:
            df_cache, sb_cache, cache_status = _get_cached_ohlcv(sym_upper, end_date=end_date, max_age_sec=10*60, bump_stats=True)
            if df_cache is not None and len(df_cache) > 10 and (cache_status in ("HIT", "STALE")):
                return df_cache, sb_cache, True
            if cache_status == "MISS" and _request_async_fetch is not None:
                try:
                    _request_async_fetch(sym_upper)
                except Exception:
                    pass
        except Exception as _exc_cache_read:
            LOGGER.warning("cache read failed for %s (fallback to live): %s", sym_upper, _exc_cache_read)

    # Step B: live download fallback (original route stack 1..4 with retries). Preserved for 1st-user request when daemon is slow.
    last_err = None

    if _YF_SESS_MGR.should_skip(symbol):
        return None, None

    result_df, result_share_base = None, None
    source_route_guess: Optional[str] = None
    for attempt in range(3):
        # --- Route 1: 優先走原生 requests（不需要 crumb，最穩定） ---
        _NATIVE_DOWNLOAD_STATS["native_attempts"] = _NATIVE_DOWNLOAD_STATS.get("native_attempts", 0) + 1
        try:
            df, share_base = _native_yahoo_chart_download(symbol, range_="5y", interval="1d", timeout=25)
            df = df[df.index <= pd.to_datetime(end_date)]
            if df is not None and len(df) > 5:
                if share_base is None or not (pd.notna(share_base) and float(share_base) > 0):
                    share_base, _ = _resolve_share_base_post(df, symbol)
                _YF_SESS_MGR.record_success(symbol)
                _NATIVE_DOWNLOAD_STATS["native_success"] = _NATIVE_DOWNLOAD_STATS.get("native_success", 0) + 1
                _persist_last_error(symbol, "native", f"OK rows={len(df)}")
                result_df, result_share_base = df, share_base
                source_route_guess = "native"
                break
        except Exception as exc_native:
            last_err = exc_native

        # --- Route 2: 原生失敗，才 fallback 到 yfinance.download ---
        _NATIVE_DOWNLOAD_STATS["yf_attempts"] = _NATIVE_DOWNLOAD_STATS.get("yf_attempts", 0) + 1
        try:
            df, share_base = _try_yfinance_download(symbol, period="5y", timeout=30)
            df = df[df.index <= pd.to_datetime(end_date)]
            if df is not None and len(df) > 5:
                if share_base is None or not (pd.notna(share_base) and float(share_base) > 0):
                    share_base, _ = _resolve_share_base_post(df, symbol)
                _YF_SESS_MGR.record_success(symbol)
                _NATIVE_DOWNLOAD_STATS["yf_success"] = _NATIVE_DOWNLOAD_STATS.get("yf_success", 0) + 1
                _persist_last_error(symbol, "yfinance", f"OK rows={len(df)}")
                result_df, result_share_base = df, share_base
                source_route_guess = "yfinance"
                break
        except Exception as exc_yf:
            last_err = exc_yf

        # --- Route 3: Yahoo 雙路線全失敗 → 最終備援 Stooq CSV（完全不需要 crumb） ---
        _NATIVE_DOWNLOAD_STATS["stooq_attempts"] = _NATIVE_DOWNLOAD_STATS.get("stooq_attempts", 0) + 1
        try:
            df, share_base = _native_stooq_download(symbol, period_years=5, timeout=25)
            df = df[df.index <= pd.to_datetime(end_date)]
            if df is not None and len(df) > 5:
                if share_base is None or not (pd.notna(share_base) and float(share_base) > 0):
                    share_base, _ = _resolve_share_base_post(df, symbol)
                _YF_SESS_MGR.record_success(symbol)
                _NATIVE_DOWNLOAD_STATS["stooq_success"] = _NATIVE_DOWNLOAD_STATS.get("stooq_success", 0) + 1
                _persist_last_error(symbol, "stooq", f"OK rows={len(df)}")
                result_df, result_share_base = df, share_base
                source_route_guess = "stooq"
                break
        except Exception as exc_stooq:
            last_err = exc_stooq

        # --- Route 4: Yahoo + Stooq 全失敗 → 新浪財經 HK 歷史 K 線 JSON（完全不需要 crumb） ---
        _NATIVE_DOWNLOAD_STATS["sina_attempts"] = _NATIVE_DOWNLOAD_STATS.get("sina_attempts", 0) + 1
        try:
            df, share_base = _native_sina_download(symbol, timeout=25)
            df = df[df.index <= pd.to_datetime(end_date)]
            if df is not None and len(df) > 5:
                if share_base is None or not (pd.notna(share_base) and float(share_base) > 0):
                    share_base, _ = _resolve_share_base_post(df, symbol)
                _YF_SESS_MGR.record_success(symbol)
                _NATIVE_DOWNLOAD_STATS["sina_success"] = _NATIVE_DOWNLOAD_STATS.get("sina_success", 0) + 1
                _persist_last_error(symbol, "sina", f"OK rows={len(df)}")
                result_df, result_share_base = df, share_base
                source_route_guess = "sina"
                break
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

    # Step C: if live download SUCCESS → populate SQLite cache now so next user/request will HIT immediately.
    if result_df is not None and len(result_df) > 10 and _CACHE_LAYER_OK and _upsert_ohlcv is not None:
        try:
            _upsert_ohlcv(sym_upper, result_df, share_base=result_share_base, source=(source_route_guess or "live"))
        except Exception as _exc_cache_write:
            LOGGER.warning("cache write failed for %s: %s", sym_upper, _exc_cache_write)

    if result_df is None and last_err is not None:
        _YF_SESS_MGR.record_failure(symbol, cooldown_sec=180)
        _persist_last_error(symbol, "final", f"ALL 3 attempts failed | last={type(last_err).__name__}: {str(last_err)[:160]}")
        return None, None, False

    return result_df, result_share_base, False

def _compute_home_snapshot_for_stock(ticker: str, df: pd.DataFrame, share_base) -> Optional[Dict[str, Any]]:
    if df is None or df.empty or len(df) < 2:
        return None

    required_cols = ["Close", "High", "Low"]
    for col in required_cols:
        if col not in df.columns:
            return None

    work_df = df.copy(deep=False)
    for col in required_cols + (["Volume"] if "Volume" in work_df.columns else []):
        work_df[col] = pd.to_numeric(work_df[col], errors="coerce")

    valid_mask = pd.notna(work_df["Close"]) & (work_df["Close"].astype(float) != 0)
    work_df = work_df.loc[valid_mask]

    if work_df.empty or len(work_df) < 2:
        return None

    close = work_df["Close"].astype(float)
    raw_current_close = close.iloc[-1]
    current_close = float(raw_current_close) if pd.notna(raw_current_close) and float(raw_current_close) != 0 else float("nan")
    raw_prev_close = close.shift(1).iloc[-1]
    prev_close = float(raw_prev_close) if pd.notna(raw_prev_close) and float(raw_prev_close) != 0 else float("nan")

    def pct_change(current_value, base_value):
        try:
            cv = float(current_value)
            bv = float(base_value)
        except Exception:
            return float("nan")
        if pd.isna(cv) or pd.isna(bv) or bv == 0:
            return float("nan")
        return (cv / bv - 1) * 100

    dev_periods = [3, 7, 14, 28, 57, 106]
    dev_values = {"Dev 0": pct_change(current_close, prev_close)}
    for p in dev_periods:
        if len(close) > p:
            shifted = close.shift(p).iloc[-1]
            base_value = float(shifted) if pd.notna(shifted) and float(shifted) != 0 else float("nan")
        else:
            base_value = float("nan")
        dev_values[f"Dev {p}"] = pct_change(current_close, base_value)

    periods_sma = [7, 14, 28, 57, 106]
    sma_values = {}
    for p in periods_sma:
        if len(close) >= p:
            sma = close.rolling(p).mean().iloc[-1]
        else:
            sma = float("nan")
        sma_values[f"SMA {p}"] = float(sma) if pd.notna(sma) else float("nan")

    prev_close_series = close.shift(1).replace(0, float("nan"))
    if "High" in work_df.columns and "Low" in work_df.columns:
        work_high = pd.to_numeric(work_df["High"], errors="coerce").astype(float)
        work_low = pd.to_numeric(work_df["Low"], errors="coerce").astype(float)
        work_df["AMP"] = (work_high - work_low) / prev_close_series * 100
    else:
        work_df["AMP"] = float("nan")
    amp_last = work_df["AMP"].iloc[-1]
    amp_values = {"Amp 0": float(amp_last) if pd.notna(amp_last) else float("nan")}
    for p in periods_sma:
        if len(work_df) >= p:
            amp = work_df["AMP"].tail(p).mean()
        else:
            amp = float("nan")
        amp_values[f"Amp {p}"] = float(amp) if pd.notna(amp) else float("nan")

    tor_values = {f"TOR {p}": float("nan") for p in [0, 7, 14, 28, 57, 106]}
    tor_approx_note: Optional[str] = None
    work_df, turnover_status, turnover_reason = apply_turnover_rate(work_df, share_base)
    if turnover_status != TURNOVER_STATUS_CALCULATED and (share_base is None or not (pd.notna(share_base) and float(share_base) > 0)):
        try:
            approx_base, approx_note = _resolve_share_base_post(work_df, get_yahoo_ticker(ticker))
            if approx_base is not None and approx_note and approx_note != "NO_VOLUME":
                work_df, turnover_status, turnover_reason = apply_turnover_rate(work_df, approx_base)
                share_base = approx_base
                tor_approx_note = approx_note
        except Exception:
            pass
    if turnover_status == TURNOVER_STATUS_CALCULATED and "Turnover_Rate" in work_df.columns:
        tor_last = work_df["Turnover_Rate"].iloc[-1]
        tor_values["TOR 0"] = float(tor_last) if pd.notna(tor_last) else float("nan")
        for p in periods_sma:
            if len(work_df) >= p:
                tor = work_df["Turnover_Rate"].tail(p).mean()
            else:
                tor = float("nan")
            tor_values[f"TOR {p}"] = float(tor) if pd.notna(tor) else float("nan")

    dev_history = []
    history_start = max(0, len(work_df) - 6)
    for row_pos in range(history_start, len(work_df)):
        row_close_raw = close.iloc[row_pos]
        row_close = float(row_close_raw) if pd.notna(row_close_raw) and float(row_close_raw) != 0 else float("nan")
        if row_pos > 0:
            row_prev_raw = close.iloc[row_pos - 1]
            row_prev = float(row_prev_raw) if pd.notna(row_prev_raw) and float(row_prev_raw) != 0 else float("nan")
        else:
            row_prev = float("nan")

        row_values = {
            "Code": ticker,
            "CPRD": row_prev,
            "Dev 0": pct_change(row_close, row_prev),
        }
        for p in dev_periods:
            base_pos = row_pos - p
            if base_pos >= 0:
                base_raw = close.iloc[base_pos]
                base_value = float(base_raw) if pd.notna(base_raw) and float(base_raw) != 0 else float("nan")
            else:
                base_value = float("nan")
            row_values[f"Dev {p}"] = pct_change(row_close, base_value)
        dev_history.append(row_values)

    return {
        "summary": {
            "Code": ticker,
            "CPRD": prev_close,
            **dev_values,
        },
        "detail": {
            "ticker": ticker,
            "date": work_df.index[-1].strftime("%Y-%m-%d"),
            "current_price": current_close,
            "cp": prev_close,
            "dev": dev_values,
            "dev_history": dev_history,
            "tor": tor_values,
            "tor_status": turnover_status,
            "tor_reason": turnover_reason,
            "tor_approx_note": tor_approx_note,
            "share_base": float(share_base) if share_base is not None else None,
            "amp": amp_values,
            "sma": sma_values,
        },
    }

@st.cache_data(ttl=900)
def get_home_watchlist_snapshot(watchlist_codes: List[str], ref_date: str) -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    details: Dict[str, Dict[str, Any]] = {}
    diagnostic: Dict[str, str] = {}

    for ticker in watchlist_codes:
        yt = get_yahoo_ticker(ticker)
        try:
            res = get_data_v7(yt, ref_date)
            if isinstance(res, tuple) and len(res) >= 3:
                df, share_base, is_cached = res[0], res[1], res[2]
            elif isinstance(res, tuple):
                df, share_base, is_cached = res[0], res[1], False
            else:
                df, share_base, is_cached = res, None, False
        except Exception as exc:
            exc_name = type(exc).__name__
            exc_msg = str(exc) or ""
            if "RateLimit" in exc_name or "Too Many Requests" in exc_msg:
                diagnostic[ticker] = "Yahoo 限流（YFRateLimitError）：請稍後再按刷新按鈕"
            elif "Invalid Crumb" in exc_msg or "Unauthorized" in exc_msg:
                diagnostic[ticker] = "Yahoo 暫時拒絕連線（Invalid Crumb/Unauthorized）：約 5-10 分鐘後再試"
            elif "delisted" in exc_msg.lower():
                diagnostic[ticker] = f"Yahoo 回傳 possibly delisted：請確認 {ticker} 代號是否正確"
            else:
                diagnostic[ticker] = f"{exc_name}：{exc_msg[:80]}"
            # Error occurred (tried live and failed): backoff to avoid hammering Yahoo on next ticker.
            time.sleep(random.uniform(0.8, 1.8))
            continue
        if df is None:
            diagnostic[ticker] = "數據載入失敗（Yahoo 可能暫不可用）"
            if not is_cached:
                time.sleep(random.uniform(0.5, 1.1))
            continue
        raw_len = len(df)
        snapshot = _compute_home_snapshot_for_stock(ticker, df, share_base)
        if not snapshot:
            diagnostic[ticker] = f"有效交易日不足：載入 {raw_len} 列，過濾 NaN/0 後不足 2 列可計算"
            if not is_cached:
                time.sleep(random.uniform(0.3, 0.7))
            continue
        summaries.append(snapshot["summary"])
        details[ticker] = snapshot["detail"]
        # Success: if fetched from live download, small randomized delay to avoid hammering Yahoo.
        # If read from SQLite cache, skip delay entirely to keep home page instant.
        if not is_cached:
            time.sleep(random.uniform(0.35, 0.95))

    return {"summaries": summaries, "details": details, "diagnostic": diagnostic}

def set_current_page(page: str, code: Optional[str] = None):
    st.session_state.current_page = page
    if code is not None:
        st.session_state.current_view = clean_ticker_input(code)
    st.session_state.comparison_mode = (page == "comparison")
    if page == "stock" and code is not None:
        st.session_state.stock_section = "header"

def is_home_context_page(page: str) -> bool:
    return page in {"home", "home_detail"}

def _home_fmt_num(value):
    return "-" if pd.isna(value) else f"{float(value):.2f}"

def _home_fmt_pct(value):
    return "-" if pd.isna(value) else f"{float(value):+.2f}%"

def _home_green_style(df: pd.DataFrame, fmt_map: Dict[str, str]):
    return (
        df.style
        .format(fmt_map, na_rep="-")
        .set_properties(**{
            "background-color": "#a3d977",
            "color": "#0f172a",
            "font-weight": "600",
        })
    )


def calc_pmax_dev_matrix(df: pd.DataFrame,
                         pmax_window: int = 106,
                         s_divisor: int = 24,
                         s_min_num: int = 3,
                         s_max_num: int = 9,
                         avg_window: int = 3,
                         num_rows: int = 3):
    """
    對應圖片 D-2 綠色表格：
      Pm        = 最近 pmax_window 日 (High+Close 先取再 max) 的最高值 (= Pmax(106))
      S1..S7    = Pm × k/s_divisor，k = s_min_num..s_max_num
      Avg3[t]   = close[t-avg_window+1 : t+1] 滾動平均（含 t 當日）
      Sn[t]     = S1..S7 中與 Avg3[t] 絕對差最小者
      三元組     = S[n-1], Sn, S[n+1]；邊界 Sn=S1 退 S1/S2/S3；Sn=S7 退 S5/S6/S7
      Dev(%)    = (Avg3 - S) / S × 100
      輸出列    = 最近 num_rows 個交易日（由舊到新 → 最後一列=最新）
    """
    result = {
        "ok": False,
        "reason": "",
        "pm": None,
        "pm_window": pmax_window,
        "s_cols": [],          # ["S1","S2",...,"S7"]
        "s_values": {},        # {"S1": 17.64, ..., "S7": 52.91}
        "rows": [],            # 最新 num_rows 列，每列: {date, avg3, sn_idx, tri_idx0..2, dev:{Sx: float or nan}}
    }
    if df is None or df.empty:
        result["reason"] = "df is empty"
        return result
    try:
        work = df.copy()
        if "Close" not in work.columns:
            result["reason"] = "missing Close column"
            return result
        work["_close"] = pd.to_numeric(work["Close"], errors="coerce")
        if "High" in work.columns:
            work["_hi"] = pd.to_numeric(work["High"], errors="coerce")
            hi_series = work["_hi"]
        else:
            hi_series = work["_close"]
        # Pm = 近 pmax_window 日 (max(close,high) 的最高值)
        top = min(len(work), pmax_window)
        if top < 30:
            result["reason"] = f"僅 {len(work)} 列，不足計算 Pmax({pmax_window}) 所需數據"
            return result
        recent = work.tail(top)
        combined = pd.concat([recent["_close"].replace(0, np.nan),
                              hi_series.tail(top).replace(0, np.nan)], axis=1)
        combined_max = combined.max(axis=1, skipna=True).dropna()
        if combined_max.empty:
            result["reason"] = "無法取得最高價"
            return result
        Pm = float(combined_max.max())
        if not np.isfinite(Pm) or Pm <= 0:
            result["reason"] = f"Pm={Pm} 非合理正數"
            return result
        result["pm"] = Pm
        s_cols = []
        s_vals = {}
        for idx, k in enumerate(range(s_min_num, s_max_num + 1)):
            name = f"S{idx + 1}"
            s_cols.append(name)
            s_vals[name] = float(Pm * k / s_divisor)
        result["s_cols"] = s_cols
        result["s_values"] = s_vals
        S_values_ordered = [s_vals[name] for name in s_cols]
        N_S = len(s_cols)  # 7

        if len(work) < avg_window:
            result["reason"] = f"列數 {len(work)} 小於 Avg 視窗 {avg_window}"
            return result

        work["_avg3"] = work["_close"].rolling(window=avg_window, min_periods=avg_window).mean()

        # 為每列計算 Sn 與三元組 Dev(%)
        tri_cols_map = {}    # date -> tri_idx_list [n-1, n, n+1]
        dev_all_dicts = []   # list of dict 同 df 長度，每個 key=Sx value=float or nan
        sn_idx_list = []
        avg3_list = []
        dates = pd.to_datetime(work.index)

        for t in range(len(work)):
            avg3 = work["_avg3"].iloc[t]
            avg3_list.append(avg3)
            if pd.isna(avg3):
                sn_idx_list.append(None)
                dev_all_dicts.append({})
                continue
            # 找 Sn：絕對差最小
            best_idx = 0
            best_abs = float("inf")
            for i in range(N_S):
                d = abs(float(avg3) - S_values_ordered[i])
                if d < best_abs:
                    best_abs = d
                    best_idx = i
            sn_idx_list.append(best_idx)
            # 三元組邊界處理
            if best_idx == 0:          # Sn = S1
                tri = [0, 1, 2]
            elif best_idx == N_S - 1:  # Sn = S7
                tri = [N_S - 3, N_S - 2, N_S - 1]
            else:
                tri = [best_idx - 1, best_idx, best_idx + 1]
            tri_cols_map[t] = tri
            # Dev = (Avg3 - S) / S * 100
            d_dict = {}
            for j in tri:
                S_j = S_values_ordered[j]
                if S_j <= 0 or not np.isfinite(S_j):
                    d_dict[s_cols[j]] = float("nan")
                else:
                    d_dict[s_cols[j]] = (float(avg3) - S_j) / S_j * 100.0
            dev_all_dicts.append(d_dict)

        # 取出最近 num_rows 列（由舊到新；最後一列=今天）
        total = len(work)
        pick_start = max(0, total - num_rows)
        rows_out = []
        for t in range(pick_start, total):
            date_str = dates[t].strftime("%Y-%m-%d") if pd.notna(dates[t]) else ""
            avg3 = avg3_list[t]
            sn_idx = sn_idx_list[t]
            tri = tri_cols_map.get(t)
            row = {
                "date": date_str,
                "avg3": float(avg3) if (avg3 is not None and pd.notna(avg3)) else None,
                "sn_idx": sn_idx,
                "tri_idx": list(tri) if tri is not None else None,
                "dev": dev_all_dicts[t],
            }
            rows_out.append(row)
        result["rows"] = rows_out
        result["ok"] = True
        return result
    except Exception as exc:
        result["ok"] = False
        result["reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return result


def render_pmax_dev_table(matrix, prefix: str = ""):
    """把 calc_pmax_dev_matrix 的結果渲染成圖中 D-2 綠色風格表格（原生 HTML，顏色樣式與 A3D977 接近）"""
    if matrix is None:
        st.info("無 Pmax Dev 矩陣數據。")
        return
    if not matrix.get("ok"):
        st.info(f"Pmax Dev 矩陣未產生：{matrix.get('reason') or ''}")
        return
    s_cols = list(matrix.get("s_cols") or [])
    s_vals = matrix.get("s_values") or {}
    rows = list(matrix.get("rows") or [])
    Pm = matrix.get("pm")
    if not s_cols or not rows or Pm is None:
        st.info("Pmax Dev 矩陣：缺少必要欄位。")
        return
    # CSS：綠色基底，參考原圖
    css = f"""
    <style>
    .{prefix}pm-dev-wrap {{ margin: 4px 0 10px 0; }}
    table.{prefix}pm-dev {{
        width: 100%;
        border-collapse: collapse;
        font-family: Arial, Helvetica, sans-serif;
        font-size: 14px;
        color: #0f172a;
    }}
    table.{prefix}pm-dev th, table.{prefix}pm-dev td {{
        border: 1px solid #6cbf4b;
        padding: 8px 10px;
        text-align: center;
        vertical-align: middle;
        background: #a3d977;
    }}
    table.{prefix}pm-dev th {{
        background: #7fbf5a;
        font-weight: 800;
        text-align: left;
    }}
    table.{prefix}pm-dev td.pm-date-cell {{
        background: #7fbf5a;
        font-weight: 800;
        text-align: left;
        white-space: nowrap;
    }}
    table.{prefix}pm-dev td.tri-cell {{
        background: #b8e290;
    }}
    table.{prefix}pm-dev td.empty-cell {{
        background: #ffffff;
        color: #94a3b8;
        border-color: #cbd5e1;
    }}
    table.{prefix}pm-dev .small-note {{
        font-size: 11px;
        color: #475569;
        margin: 2px 0 6px 0;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    parts = []
    # 小節資訊：Pm / S 候選值（一行說明）
    s_show = "、".join([f"{n}={float(s_vals.get(n, 0)):.2f}" for n in s_cols])
    parts.append(f'<div class="{prefix}pm-dev-wrap">')
    parts.append(f'<div class="{prefix}small-note">Pm=Pmax({matrix.get("pm_window") or 106})={float(Pm):.2f}；候選 {s_show}；三元組=Sn 前1/Sn/Sn 後1（S1/S7 時 fallback）。</div>')
    parts.append(f'<table class="{prefix}pm-dev">')
    # 表頭：Pm/日期合併格 + S1..S7
    parts.append("<thead><tr>")
    parts.append(f'<th rowspan="2">Date / Avg3</th>')
    for n in s_cols:
        sv = s_vals.get(n, 0)
        parts.append(f"<th>{n}={float(sv):.2f}</th>")
    parts.append("</tr>")
    parts.append("</thead>")
    parts.append("<tbody>")
    for r in rows:
        # 第一列：date + tri 標題 (Dev S(n-1)/Dev Sn/Dev S(n+1))
        tri = r.get("tri_idx") or []
        dev_dict = r.get("dev") or {}
        date_str = str(r.get("date") or "")
        avg3 = r.get("avg3")
        avg3_s = f"{float(avg3):.2f}" if (avg3 is not None and pd.notna(avg3)) else "N/A"
        parts.append("<tr>")
        parts.append(f'<td class="pm-date-cell">{date_str}<br><span style="font-weight:500;font-size:12px">Avg3={avg3_s}</span></td>')
        if tri:
            labels = ["Dev S(n−1)", "Dev Sn", "Dev S(n+1)"]
        else:
            labels = []
        for j in range(len(s_cols)):
            if j in tri and tri and labels:
                pos = tri.index(j)
                label = labels[pos] if pos < len(labels) else ""
                parts.append(f'<td class="tri-cell" style="font-weight:700">{label}</td>')
            else:
                parts.append('<td class="empty-cell"></td>')
        parts.append("</tr>")
        # 第二列：Dev(%) 數值（只有三元組有值；其它空白）
        parts.append("<tr>")
        parts.append(f'<td class="pm-date-cell">Dev(%)</td>')
        for j, name in enumerate(s_cols):
            if tri and j in tri and name in dev_dict:
                v = dev_dict.get(name)
                if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
                    parts.append('<td class="tri-cell">-</td>')
                else:
                    color = "#166534" if float(v) >= 0 else "#991b1b"
                    parts.append(f'<td class="tri-cell" style="color:{color};font-weight:700">{float(v):+.2f}%</td>')
            else:
                parts.append('<td class="empty-cell">—</td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


PMAX_20_FIXED_INDICES: list = [
    0.625, 0.583, 0.542, 0.500, 0.458, 0.417, 0.396, 0.375, 0.354, 0.333,
    0.313, 0.292, 0.271, 0.250, 0.229, 0.208, 0.188, 0.167, 0.146, 0.125,
]

CAL_TARGET_RED_VALUE: float = 3.5197

_PMAX_INDEX6_CSS_DESKTOP_INJECTED_FLAG_KEY = "__p6index6_css_desktop_injected_20260829__"
_PMAX_INDEX6_CSS_DESKTOP = """
<style>
.p6d_wrap {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin: 4px 0 10px 0;
    align-items: flex-start;
}
.p6d_left {
    flex: 0 0 30%;
    min-width: 260px;
}
.p6d_right {
    flex: 1 1 66%;
    min-width: 560px;
    overflow-x: auto;
}
@media (max-width: 959px) {
    .p6d_left  { flex: 1 1 100%; min-width: 0; }
    .p6d_right { flex: 1 1 100%; min-width: 0; }
}
table.p6d_tbl {
    width: 100%;
    border-collapse: collapse;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 13px;
    color: #0f172a;
}
table.p6d_tbl th, table.p6d_tbl td {
    border: 1px solid #6cbf4b;
    padding: 6px 8px;
    text-align: right;
    background: #a3d977;
    vertical-align: middle;
}
table.p6d_tbl th {
    background: #7fbf5a;
    font-weight: 800;
    text-align: left;
}
table.p6d_tbl td.date-cell,
table.p6d_tbl td.base-cell {
    background: #7fbf5a;
    font-weight: 700;
    text-align: left;
    white-space: nowrap;
}
table.p6d_tbl td.empty {
    background: #ffffff;
    color: #94a3b8;
    border-color: #cbd5e1;
    text-align: center;
}
table.p6d_tbl td.dev-pos { color: #166534; font-weight: 700; }
table.p6d_tbl td.dev-neg { color: #991b1b; font-weight: 700; }
table.p6d_tbl td.cal-red-box {
    border: 2.5px solid #dc2626 !important;
    box-shadow: inset 0 0 0 1px #fca5a5;
    background: #fee2e2;
}
.p6d_note {
    font-size: 11px;
    color: #475569;
    margin: 2px 0 6px 0;
}
.p6d_title {
    font-size: 14px;
    font-weight: 800;
    margin: 0 0 4px 0;
    color: #0f172a;
}
</style>
"""


def _ensure_global_css_pmax_index6_desktop():
    if not st.session_state.get(_PMAX_INDEX6_CSS_DESKTOP_INJECTED_FLAG_KEY, False):
        st.markdown(_PMAX_INDEX6_CSS_DESKTOP, unsafe_allow_html=True)
        st.session_state[_PMAX_INDEX6_CSS_DESKTOP_INJECTED_FLAG_KEY] = True


def calc_pmax_index6_matrix(df: pd.DataFrame,
                            pmax_window: int = 106,
                            avg_window: int = 3,
                            dev_offsets: list = None,
                            recent_rows: int = 12):
    """
    Approved APP-20260829-001-PMAX6DEV M1 + M2.

    M1 (Dev 偏移方向 強制向歷史):
      Devk[t] = (Close[t] - Avg3[t - k]) / Avg3[t - k] * 100%
      k = 0,1,2,3,4,5 (預設 dev_offsets = [0,1,2,3,4,5])
      若 t - k < 0 → NaN

    M2 (20 Index 硬編碼): 使用 PMAX_20_FIXED_INDICES，不得用 linspace 近似。

    2026-08-29 性能優化：整塊用 pandas 向量化（rolling + shift + multiply），
    避免 Python for-loop 每行 6 次 iloc，提速 5~12x。
    """
    dev_offsets = dev_offsets if dev_offsets is not None else [0, 1, 2, 3, 4, 5]
    res = {
        "ok": False,
        "reason": "",
        "pm": None,
        "pm_window": pmax_window,
        "index_rows": [],
        "time_rows": [],
        "dev_offsets": list(dev_offsets),
        "cal_match": {"date": None, "k": None, "value": None, "abs_err": None},
    }
    if df is None or df.empty:
        res["reason"] = "df empty"
        return res
    try:
        cols_req = ["Close"]
        missing = [c for c in cols_req if c not in df.columns]
        if missing:
            res["reason"] = f"missing columns: {missing}"
            return res
        close_s = pd.to_numeric(df["Close"], errors="coerce")
        if "High" in df.columns:
            hi_s = pd.to_numeric(df["High"], errors="coerce")
        else:
            hi_s = close_s.copy()
        if "Turnover_Rate" in df.columns:
            tur_s = pd.to_numeric(df["Turnover_Rate"], errors="coerce")
        else:
            tur_s = pd.Series(np.nan, index=df.index)
        if "AMP" in df.columns:
            amp_s = pd.to_numeric(df["AMP"], errors="coerce")
        elif "High" in df.columns and "Low" in df.columns and "Close" in df.columns:
            prev_close = close_s.shift(1).replace(0, np.nan)
            hi = pd.to_numeric(df["High"], errors="coerce")
            lo = pd.to_numeric(df["Low"], errors="coerce")
            amp_s = (hi - lo) / prev_close * 100.0
        else:
            amp_s = pd.Series(np.nan, index=df.index)

        top = min(len(df), pmax_window)
        if top < 30:
            res["reason"] = f"僅 {len(df)} 列，不足 Pmax({pmax_window}) 需要的最低長度 30"
            return res

        pmax_close = close_s.tail(top).replace(0, np.nan)
        pmax_hi = hi_s.tail(top).replace(0, np.nan)
        combined = pd.concat([pmax_close, pmax_hi], axis=1)
        daily_max = combined.max(axis=1, skipna=True).dropna()
        if daily_max.empty:
            res["reason"] = "無法計算 Pmax (全部 NaN)"
            return res
        Pm = float(daily_max.max())
        if not np.isfinite(Pm) or Pm <= 0:
            res["reason"] = f"Pm={Pm} 非合理正數"
            return res
        res["pm"] = Pm

        idx_rows = []
        for i, v in enumerate(PMAX_20_FIXED_INDICES):
            idx_rows.append({"idx": i, "index": float(v), "pm_x_index": float(Pm * float(v))})
        res["index_rows"] = idx_rows

        avg3 = close_s.rolling(window=avg_window, min_periods=avg_window).mean()
        dates_idx = pd.to_datetime(df.index)

        T = len(df)
        pick_start = max(0, T - recent_rows)
        n_pick = T - pick_start
        if n_pick <= 0:
            res["ok"] = True
            return res

        pick_close_arr = close_s.values[pick_start:T]
        pick_avg3_arr = avg3.values[pick_start:T]
        pick_tur_arr = tur_s.values[pick_start:T]
        pick_amp_arr = amp_s.values[pick_start:T]
        pick_dates_arr = dates_idx.values[pick_start:T]

        dev_arrays = {}
        offsets_int = [int(k) for k in dev_offsets]
        for k in offsets_int:
            if k == 0:
                avg3_ref_arr = avg3.values[pick_start:T]
            else:
                src_start = max(0, pick_start - k)
                src_slice = avg3.values[src_start:max(0, T - k)]
                pad = n_pick - len(src_slice)
                if pad > 0:
                    avg3_ref_arr = np.concatenate([np.full(pad, np.nan), src_slice])
                else:
                    avg3_ref_arr = src_slice.copy()
            diff = pick_close_arr - avg3_ref_arr
            div = np.divide(diff, avg3_ref_arr, out=np.full_like(diff, np.nan, dtype=float),
                            where=(np.isfinite(avg3_ref_arr) & (avg3_ref_arr != 0)))
            dev_arrays[k] = np.multiply(div, 100.0, out=np.full_like(div, np.nan, dtype=float),
                                        where=(np.isfinite(div)))

        best_err = float("inf")
        best_meta = {"date": None, "k": None, "value": None, "abs_err": None}
        t_rows = []
        dev_arrays_np = {k: dev_arrays[k] for k in offsets_int}
        close_finite = np.isfinite(pick_close_arr)
        offsets_arr = np.array(offsets_int, dtype=int)
        for i in range(n_pick):
            ts = pick_dates_arr[i]
            try:
                date_s = pd.Timestamp(ts).strftime("%Y-%m-%d")
            except Exception:
                date_s = ""
            close_v = pick_close_arr[i] if (close_finite[i]) else None
            tur_raw = pick_tur_arr[i]
            tur_v = float(tur_raw) if (np.isfinite(tur_raw)) else None
            amp_raw = pick_amp_arr[i]
            amp_v = float(amp_raw) if (np.isfinite(amp_raw)) else None
            avg3_raw = pick_avg3_arr[i]
            avg3_t = float(avg3_raw) if (np.isfinite(avg3_raw) and avg3_raw != 0) else None
            dev_dict = {}
            for k in offsets_int:
                dv = dev_arrays_np[k][i]
                dev_dict[k] = float(dv) if np.isfinite(dv) else float("nan")
                if best_err > 0 and np.isfinite(dv):
                    err = abs(float(dv) - CAL_TARGET_RED_VALUE)
                    if err < best_err:
                        best_err = err
                        best_meta = {
                            "date": date_s,
                            "k": int(k),
                            "value": float(dv),
                            "abs_err": float(err),
                        }
            # AvgDev = (Dev0 + Dev1 + Dev2 + Dev3 + Dev4 + Dev5) / 6
            _dev_flist = []
            for k in offsets_int:
                _dv = dev_dict.get(k)
                if _dv is not None and isinstance(_dv, float) and np.isfinite(_dv):
                    _dev_flist.append(float(_dv))
            if _dev_flist:
                avg_dev = float(sum(_dev_flist)) / 6.0
            else:
                avg_dev = float("nan")
            t_rows.append({
                "date": date_s,
                "close": float(close_v) if close_v is not None else None,
                "tur": tur_v,
                "amp": amp_v,
                "avg3_t": avg3_t,
                "dev": dev_dict,
                "avg_dev": avg_dev,
            })
        res["time_rows"] = t_rows
        if best_meta.get("date") is not None:
            res["cal_match"] = best_meta
        res["ok"] = True
        return res
    except Exception as exc:
        res["ok"] = False
        res["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


def render_pmax_index6_panel(matrix, prefix: str = "p6d_"):
    """桌面 render：flex row 30% 左（20 Index 格點）70% 右（Dev0~5 12 日時序 + 紅框自動校準）
    2026-08-29 性能優化：CSS 全局只注入一次（@st.cache_data 之外用 streamlit 全域 inline <style> key）
    避免每支股票 rerun 都重複 ~2KB inline style，顯著減少 HTML 體積與 CLS。"""
    if matrix is None:
        st.info("Pmax 20×6 矩陣：未產生數據")
        return
    if not matrix.get("ok"):
        st.info(f"Pmax 20×6 矩陣未產生：{matrix.get('reason') or ''}")
        return
    Pm = matrix.get("pm")
    idx_rows = list(matrix.get("index_rows") or [])
    t_rows = list(matrix.get("time_rows") or [])
    offsets = list(matrix.get("dev_offsets") or [0, 1, 2, 3, 4, 5])
    cal_match = matrix.get("cal_match") or {}
    cal_date = cal_match.get("date")
    cal_k = cal_match.get("k")
    if not idx_rows or not t_rows or Pm is None:
        st.info("Pmax 20×6 矩陣：缺少必要欄位")
        return
    _ensure_global_css_pmax_index6_desktop()
    parts = []
    parts.append(f'<div class="{prefix}wrap">')
    parts.append(f'<div class="{prefix}left">')
    parts.append(f'<div class="{prefix}title">🟩 20 固定格點 (Pmax × Index)</div>')
    parts.append(f'<div class="{prefix}note">Pmax(106)={float(Pm):.2f}；Index 硬編碼 20 階 (M2 約束)</div>')
    parts.append(f'<table class="{prefix}tbl">')
    parts.append("<thead><tr><th>#</th><th>Index</th><th>Pm×Index</th></tr></thead><tbody>")
    for r in idx_rows:
        parts.append(
            f"<tr><td class='base-cell'>{int(r['idx'])+1}</td>"
            f"<td>{float(r['index']):.3f}</td>"
            f"<td>{float(r['pm_x_index']):.2f}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    parts.append(f'<div class="{prefix}right">')
    parts.append(f'<div class="{prefix}title">🟦 最近 {len(t_rows)} 日 · 6 個時間視角 Dev(%)</div>')
    mdate = cal_match.get("date")
    mk = cal_match.get("k")
    mval = cal_match.get("value")
    merr = cal_match.get("abs_err")
    if mdate is not None and mk is not None and mval is not None and merr is not None and float(merr) < 0.5:
        parts.append(f'<div class="{prefix}note">Devk[t]=(Close[t]-Avg3[t−k])/Avg3[t−k]·100%（M1 向歷史偏移 k；禁止未來函數）｜🎯 紅框自動校準：{str(mdate)} Dev{mk}={float(mval):+.4f}%（目標 {CAL_TARGET_RED_VALUE}，誤差 {float(merr):.4f}）</div>')
    else:
        parts.append(f'<div class="{prefix}note">Devk[t]=(Close[t]-Avg3[t−k])/Avg3[t−k]·100%（M1 向歷史偏移 k）｜🎯 未命中校準點 {CAL_TARGET_RED_VALUE}（若有 8/11 數據會自動畫紅框）</div>')
    parts.append(f'<table class="{prefix}tbl">')
    head_row = ["<th>Date</th><th>Close</th><th>TUR</th><th>Amp(%)</th><th>AvgDev</th>"]
    for k in offsets:
        head_row.append(f"<th>Dev{k}</th>")
    parts.append(f"<thead><tr>{''.join(head_row)}</tr></thead><tbody>")
    for r in t_rows:
        ds = r.get("date") or ""
        is_cal_date = (cal_date is not None and ds == cal_date)
        dev = r.get("dev") or {}
        avg_dev_v = r.get("avg_dev")
        cells = [
            f"<td class='date-cell'>{ds}</td>",
            f"<td>{_fmt(r.get('close'), 2)}</td>",
            f"<td>{_fmt(r.get('tur'), 4)}</td>",
            f"<td>{_fmt(r.get('amp'), 2)}</td>",
        ]
        # AvgDev cell (between Amp and Dev0)
        if avg_dev_v is None or (isinstance(avg_dev_v, float) and not np.isfinite(avg_dev_v)) or pd.isna(avg_dev_v):
            cells.append("<td class='empty'>—</td>")
        else:
            _avg_cls = "dev-pos" if float(avg_dev_v) >= 0 else "dev-neg"
            cells.append(f"<td class='{_avg_cls}' style='font-weight:700;'>{float(avg_dev_v):+.2f}%</td>")
        for k in offsets:
            v = dev.get(int(k))
            if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
                cells.append("<td class='empty'>—</td>")
                continue
            cls = "dev-pos" if float(v) >= 0 else "dev-neg"
            extra_cls = ""
            if is_cal_date and cal_k is not None and int(k) == int(cal_k):
                extra_cls = " cal-red-box"
            cells.append(f"<td class='{cls}{extra_cls}'>{float(v):+.2f}%</td>")
        parts.append(f"<tr>{''.join(cells)}</tr>")
    parts.append("</tbody></table></div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _fmt(v, decimals: int = 2):
    if v is None:
        return "-"
    try:
        x = float(v)
        if not np.isfinite(x):
            return "-"
        return f"{x:.{decimals}f}"
    except Exception:
        return "-"


COT_5_FIXED_TI: list = [7, 14, 27, 57, 106]

_COT_DESKTOP_CSS_FLAG_KEY = "__cot_desktop_css_injected_20260902__"
_COT_DESKTOP_CSS = """
<style>
.cotd_wrap { width: 100%; margin: 6px 0 10px 0; display: block; }
.cotd_block { margin-bottom: 10px; }
.cotd_title { font-size: 14px; font-weight: 800; margin: 0 0 5px 0; color: #0f172a; }
.cotd_note { font-size: 11px; color: #475569; margin: 2px 0 5px 0; }
table.cotd_tbl { width: 100%; border-collapse: collapse; font-family: Arial, Helvetica, sans-serif; font-size: 13px; color: #0f172a; }
table.cotd_tbl th, table.cotd_tbl td { border: 1px solid #6cbf4b; padding: 6px 6px; text-align: right; background: #a3d977; vertical-align: middle; }
table.cotd_tbl th { background: #7fbf5a; font-weight: 700; text-align: left; white-space: nowrap; }
table.cotd_tbl td.cotd_label { background: #7fbf5a; font-weight: 700; text-align: left; white-space: nowrap; }
table.cotd_tbl td.cotd_empty { background: #ffffff; color: #94a3b8; border-color: #cbd5e1; text-align: center; }
table.cotd_tbl td.cotd_u { color: #166534; font-weight: 800; background: #bbf7d0; }
table.cotd_tbl td.cotd_d { color: #991b1b; font-weight: 800; background: #fecaca; }
table.cotd_tbl td.cotd_majority_u { color: #166534; font-weight: 900; background: #86efac; text-align: center; font-size: 14px; }
table.cotd_tbl td.cotd_majority_d { color: #991b1b; font-weight: 900; background: #f87171; text-align: center; font-size: 14px; }
.cotd_pos { color: #166534; font-weight: 700; }
.cotd_neg { color: #991b1b; font-weight: 700; }
</style>
"""


def _ensure_global_css_cot_desktop():
    if not st.session_state.get(_COT_DESKTOP_CSS_FLAG_KEY, False):
        st.markdown(_COT_DESKTOP_CSS, unsafe_allow_html=True)
        st.session_state[_COT_DESKTOP_CSS_FLAG_KEY] = True


def _rate(v, decimals=3):
    try:
        x = float(v)
        if not np.isfinite(x):
            return "—"
        return f"{x * 100.0:.{decimals}f}%"
    except Exception:
        return "—"


def _direction_class(x):
    try:
        v = float(x)
        return "cotd_pos" if v >= 0 else "cotd_neg"
    except Exception:
        return "cotd_empty"


def calc_cot_ti5_vector(df: pd.DataFrame, ti_list: list = None):
    ti_list = list(ti_list) if ti_list is not None else list(COT_5_FIXED_TI)
    res = {
        "ok": False,
        "reason": "",
        "ti_list": list(ti_list),
        "last_date": None,
        "last_close": None,
        "cot_a_row": {},
        "ud_per_ti": {},
        "cot_b_row": {},
        "ud_majority": "",
        "trailing_nan_skipped": 0,
    }
    if df is None or df.empty:
        res["reason"] = "df empty"
        return res
    try:
        if "Close" not in df.columns:
            res["reason"] = "missing Close column"
            return res
        work = df.copy(deep=False)
        close_s = pd.to_numeric(work["Close"], errors="coerce").replace(0, np.nan)
        N = len(close_s)
        if N < 2:
            res["reason"] = "N < 2"
            return res
        valid_arr_finite = np.isfinite(close_s.to_numpy(dtype=float, copy=False))
        valid_positions = np.flatnonzero(valid_arr_finite)
        if valid_positions.size == 0:
            res["reason"] = "no valid Close (all rows NaN/0)"
            return res
        n = int(valid_positions[-1])
        skipped = (N - 1) - n
        res["trailing_nan_skipped"] = int(skipped)
        pn_val = float(close_s.iloc[n])
        pn = float(pn_val)
        try:
            ts = close_s.index[n]
            res["last_date"] = pd.Timestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            res["last_date"] = None
        res["last_close"] = pn
        close_arr = close_s.to_numpy(dtype=float, copy=False)
        cot_a: dict = {}
        ud_per: dict = {}
        cot_b: dict = {}
        u_cnt = 0
        d_cnt = 0
        for ti in ti_list:
            ti_i = int(ti)
            if ti_i <= 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            src = n - ti_i
            if src < 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            base = float(close_arr[src])
            if not np.isfinite(base) or base <= 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            w = close_arr[src:(n + 1)]
            w_f = w[np.isfinite(w)]
            if w_f.size == 0:
                cot_a[ti] = float("nan")
                ud_per[ti] = ""
                cot_b[ti] = float("nan")
                continue
            w_min = float(np.min(w_f))
            w_max = float(np.max(w_f))
            diff_a = pn - base
            cot_a[ti] = (diff_a / base) / float(ti_i)
            if pn > base:
                direction = "U"
                u_cnt += 1
                cot_b[ti] = ((pn - w_min) / w_min) / float(ti_i) if (np.isfinite(w_min) and w_min > 0) else float("nan")
            elif pn < base:
                direction = "D"
                d_cnt += 1
                cot_b[ti] = ((pn - w_max) / w_max) / float(ti_i) if (np.isfinite(w_max) and w_max > 0) else float("nan")
            else:
                direction = ""
                cot_b[ti] = float("nan")
            ud_per[ti] = direction
        res["cot_a_row"] = cot_a
        res["ud_per_ti"] = ud_per
        res["cot_b_row"] = cot_b
        if u_cnt > d_cnt:
            res["ud_majority"] = "U"
        elif d_cnt > u_cnt:
            res["ud_majority"] = "D"
        else:
            res["ud_majority"] = ""
        res["ok"] = True
        return res
    except Exception as exc:
        res["ok"] = False
        res["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


def render_cot_2blocks(cot_matrix, prefix: str = "cotd_"):
    if cot_matrix is None:
        st.info("COT 矩陣：未產生數據")
        return
    if not cot_matrix.get("ok"):
        st.info(f"COT 矩陣未產生：{cot_matrix.get('reason') or ''}")
        return
    ti_list = list(cot_matrix.get("ti_list") or COT_5_FIXED_TI)
    cot_a = cot_matrix.get("cot_a_row") or {}
    ud_per = cot_matrix.get("ud_per_ti") or {}
    cot_b = cot_matrix.get("cot_b_row") or {}
    ud_maj = str(cot_matrix.get("ud_majority") or "")
    last_dt = cot_matrix.get("last_date")
    last_cp = cot_matrix.get("last_close")
    _ensure_global_css_cot_desktop()
    parts = []
    parts.append(f'<div class="{prefix}wrap">')
    parts.append(f'<div class="{prefix}block">')
    parts.append(f'<div class="{prefix}title">🟩 COT · 每日化股價變化速率（TI∈{str(ti_list)}）</div>')
    if last_dt is not None and last_cp is not None:
        parts.append(f'<div class="{prefix}note">Pn（{last_dt} Close/CP）={_fmt(last_cp, 2)}；COT=((Pn−(Pn−TI))/(Pn−TI))/TI（每日化，單位%/日，3 位小數）</div>')
    parts.append(f'<table class="{prefix}tbl">')
    hdr_a = ["<th>指標</th>"] + [f"<th>COT {ti}</th>" for ti in ti_list]
    parts.append(f"<thead><tr>{''.join(hdr_a)}</tr></thead><tbody>")
    row_a = [f'<td class="{prefix}label">COT（每日化%）</td>']
    for ti in ti_list:
        v = cot_a.get(ti)
        if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
            row_a.append(f'<td class="{prefix}empty">—</td>')
        else:
            cls = _direction_class(v)
            row_a.append(f'<td class="{cls}">{_rate(v, 3)}</td>')
    parts.append(f"<tr>{''.join(row_a)}</tr>")
    parts.append("</tbody></table></div>")
    parts.append(f'<div class="{prefix}block">')
    parts.append(f'<div class="{prefix}title">🟩 上升 / 下降趨勢點擇（U 用窗口 min；D 用窗口 max）</div>')
    parts.append(f'<div class="{prefix}note">U=Pn>(Pn−TI)→COTu；D=Pn<(Pn−TI)→COTd；U/D 格=5 TI 多數決</div>')
    parts.append(f'<table class="{prefix}tbl">')
    hdr_b = ["<th>U/D</th>"] + [f"<th>COT {ti}</th>" for ti in ti_list]
    parts.append(f"<thead><tr>{''.join(hdr_b)}</tr></thead><tbody>")
    if ud_maj == "U":
        maj_cell = f'<td class="{prefix}majority_u">U</td>'
    elif ud_maj == "D":
        maj_cell = f'<td class="{prefix}majority_d">D</td>'
    else:
        maj_cell = f'<td class="{prefix}empty">—</td>'
    row_b = [maj_cell]
    for ti in ti_list:
        d = str(ud_per.get(ti) or "")
        v = cot_b.get(ti)
        if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
            row_b.append(f'<td class="{prefix}empty">—</td>')
        else:
            if d == "U":
                cls = f"{prefix}u"
            elif d == "D":
                cls = f"{prefix}d"
            else:
                cls = _direction_class(v)
            row_b.append(f'<td class="{cls}">{_rate(v, 3)}</td>')
    parts.append(f"<tr>{''.join(row_b)}</tr>")
    parts.append("</tbody></table></div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_home_snapshot_detail_page(ticker: str):
    st.title(f"📌 {ticker} 統計數據")
    top_cols = st.columns([1, 1.2, 2.2])
    with top_cols[0]:
        if st.button("🏠 返回主頁", use_container_width=True, key=f"home_detail_back_{ticker}"):
            st.session_state.home_selected_ticker = ticker
            queue_scroll_to_anchor(st.session_state.get("home_return_anchor", get_home_stock_anchor_id(ticker)))
            set_current_page("home")
            st.rerun()
    with top_cols[1]:
        if st.button("📈 前往單股", use_container_width=True, key=f"home_detail_stock_{ticker}"):
            set_current_page("stock", ticker)
            st.rerun()
    with top_cols[2]:
        st.caption("此頁一次性展示 Dev / TOR / Amp / SMA 全部統計資料。")

    snapshot = get_home_watchlist_snapshot([ticker], str(st.session_state.ref_date))
    selected_detail = snapshot.get("details", {}).get(ticker)
    if not selected_detail:
        st.warning("目前無法取得這支股票的首頁統計數據。")
        return

    detail_header_html = (
        '<div class="home-detail-panel">'
        f'<div class="home-stock-head"><div class="home-stock-title">📌 {ticker} 統計數據</div>'
        f'<div class="home-stock-badge">{selected_detail["date"]}</div></div>'
        f'<div class="home-summary-strip">'
        f'<div class="home-summary-item"><div class="label">Current price</div><div class="value">{_home_fmt_num(selected_detail["current_price"])}</div></div>'
        f'<div class="home-summary-item"><div class="label">CP</div><div class="value">{_home_fmt_num(selected_detail["cp"])}</div></div>'
        f'<div class="home-summary-item"><div class="label">Dev 57</div><div class="value">{_home_fmt_pct(selected_detail["dev"].get("Dev 57"))}</div></div>'
        f'<div class="home-summary-item"><div class="label">Dev 106</div><div class="value">{_home_fmt_pct(selected_detail["dev"].get("Dev 106"))}</div></div>'
        f'</div>'
        '<span class="home-avg-note">TOR / Amp 的 7、14、28、57、106 為區間平均值</span>'
        '</div>'
    )
    st.markdown(detail_header_html, unsafe_allow_html=True)

    dev_history = selected_detail.get("dev_history", [])
    dev_history_df = pd.DataFrame(dev_history)
    dev_base_columns = [
        "Code",
        "CPRD",
        "Dev 0",
        "Dev 3",
        "Dev 7",
        "Dev 14",
        "Dev 28",
    ]
    dev_extended_columns = ["Dev 57", "Dev 106"]
    show_extended_key = f"home_detail_show_dev_extended_{ticker}"
    show_extended = bool(st.session_state.get(show_extended_key, True))

    if st.button(
        "顯示 Dev 57 / Dev 106" if not show_extended else "隱藏 Dev 57 / Dev 106",
        key=f"home_detail_toggle_dev_{ticker}",
        use_container_width=False,
    ):
        st.session_state[show_extended_key] = not show_extended
        st.rerun()

    visible_dev_columns = dev_base_columns + (
        dev_extended_columns if show_extended else []
    )
    dev_history_df = dev_history_df.reindex(columns=visible_dev_columns)

    st.markdown(
        """
        <style>
        .home-dev-history-note {
            font-size: 11px;
            color: #6c757d;
            margin: -4px 0 4px 0;
        }
        .merged-summary-table {
            width: 100%;
            border-collapse: collapse;
            font-family: 'Arial', sans-serif;
            font-size: 14px;
            margin-bottom: 8px;
        }
        .merged-summary-table th, .merged-summary-table td {
            border: 1px solid #dee2e6;
            padding: 10px 8px;
            text-align: center;
            vertical-align: middle;
            color: #0f172a;
        }
        .merged-summary-table td:first-child,
        .merged-summary-table th:first-child {
            text-align: left;
            font-weight: 700;
            width: 140px;
            background: #ffffff;
        }
        .merged-summary-table tr.section-title th {
            font-weight: 800;
            color: #ffffff;
            letter-spacing: 0.5px;
        }
        .merged-summary-table .grp-sma-title { background: #1976d2; }
        .merged-summary-table .grp-sma-head  { background: #bbdefb; color: #0d47a1; }
        .merged-summary-table .grp-sma-data  { background: #e3f2fd; }
        .merged-summary-table .grp-amp-title { background: #f57c00; }
        .merged-summary-table .grp-amp-head  { background: #ffe0b2; color: #e65100; }
        .merged-summary-table .grp-amp-data  { background: #fff3e0; }
        .merged-summary-table .grp-tor-title { background: #388e3c; }
        .merged-summary-table .grp-tor-head  { background: #c8e6c9; color: #1b5e20; }
        .merged-summary-table .grp-tor-data  { background: #e8f5e9; }
        .merged-summary-table .no-val { color: #94a3b8; font-style: italic; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="home-dev-history-note">顯示最近 6 個交易日；Dev 57 / Dev 106 可按鈕展開。</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Dev")
    dev_fmt_map = {
        "CPRD": "{:.2f}",
        "Dev 0": "{:+.2f}%",
        "Dev 3": "{:+.2f}%",
        "Dev 7": "{:+.2f}%",
        "Dev 14": "{:+.2f}%",
        "Dev 28": "{:+.2f}%",
        "Dev 57": "{:+.2f}%",
        "Dev 106": "{:+.2f}%",
    }
    st.dataframe(
        _home_green_style(
            dev_history_df,
            {column: dev_fmt_map[column] for column in visible_dev_columns if column in dev_fmt_map},
        ),
        hide_index=True,
        use_container_width=True,
        height=248,
    )

    # --- 合併總表：SMA | Amp | TOR 水平拼接 + 分組色 ---
    _d = selected_detail["date"]
    _sma_cols = ["CP", "SMA 7", "SMA 14", "SMA 28", "SMA 57"]
    _amp_cols = ["Amp 0", "Amp 7", "Amp 14", "Amp 28", "Amp 57", "Amp 106"]
    _tor_cols = ["TOR 0", "TOR 7", "TOR 14", "TOR 28", "TOR 57", "TOR 106"]
    _sma_vals = {"CP": selected_detail.get("cp")}
    for _c in _sma_cols[1:]: _sma_vals[_c] = selected_detail["sma"].get(_c)
    _amp_vals = {_c: selected_detail["amp"].get(_c) for _c in _amp_cols}
    _tor_vals = {_c: selected_detail["tor"].get(_c) for _c in _tor_cols}

    def _fmt_num(v):
        try:
            if v is None: return '<span class="no-val">None</span>'
            if pd.isna(v): return '<span class="no-val">None</span>'
            return f"{float(v):.2f}"
        except Exception:
            return '<span class="no-val">None</span>'

    def _fmt_pct(v):
        try:
            if v is None: return '<span class="no-val">None</span>'
            if pd.isna(v): return '<span class="no-val">None</span>'
            return f"{float(v):.2f}%"
        except Exception:
            return '<span class="no-val">None</span>'

    _html = ['<table class="merged-summary-table">']
    _html.append('<thead>')
    _html.append('<tr class="section-title">'
                 '<th rowspan="2">Date</th>'
                 f'<th class="grp-sma-title" colspan="{len(_sma_cols)}">SMA</th>'
                 f'<th class="grp-amp-title" colspan="{len(_amp_cols)}">Amp</th>'
                 f'<th class="grp-tor-title" colspan="{len(_tor_cols)}">TOR</th>'
                 '</tr>')
    _html.append('<tr>' +
                 "".join([f'<th class="grp-sma-head">{c}</th>' for c in _sma_cols]) +
                 "".join([f'<th class="grp-amp-head">{c}</th>' for c in _amp_cols]) +
                 "".join([f'<th class="grp-tor-head">{c}</th>' for c in _tor_cols]) +
                 '</tr>')
    _html.append('</thead><tbody>')
    _row_cells = [f"<td>{_d}</td>"]
    _row_cells += [f'<td class="grp-sma-data">{_fmt_num(_sma_vals[c])}</td>' for c in _sma_cols]
    _row_cells += [f'<td class="grp-amp-data">{_fmt_pct(_amp_vals[c])}</td>' for c in _amp_cols]
    _row_cells += [f'<td class="grp-tor-data">{_fmt_pct(_tor_vals[c])}</td>' for c in _tor_cols]
    _html.append("<tr>" + "".join(_row_cells) + "</tr>")
    _html.append("</tbody></table>")
    st.markdown("### 📋 綜合總表（SMA / Amp / TOR）")
    st.markdown("".join(_html), unsafe_allow_html=True)

    if selected_detail.get("tor_status") != TURNOVER_STATUS_CALCULATED:
        st.caption(
            f"TOR unavailable for {ticker}: {selected_detail.get('tor_reason') or 'No valid share base or volume.'}"
        )
    else:
        approx_note = selected_detail.get("tor_approx_note")
        if approx_note and approx_note != "NO_VOLUME" and str(approx_note).startswith("APPROX_"):
            try:
                parts = str(approx_note).split("_")
                pct_part = parts[1] if len(parts) > 1 else "0.35pct"
                win_part = parts[2] if len(parts) > 2 else "window120"
                pct_disp = pct_part.replace("pct", "%")
                win_disp = win_part.replace("window", "")
                st.caption(
                    f"TOR ≈ 近似值（以近 {win_disp} 日平均成交量 ÷ 平均換手率 {pct_disp} 反推流通股本；"
                    f"若需精確值，請在 metadata/share_base.csv 手動填入 {ticker} 之 issued_shares）"
                )
            except Exception:
                st.caption("TOR ≈ 近似值（依 Volume / 平均換手率推算；精確值請寫入 metadata/share_base.csv）")
        else:
            sb = selected_detail.get("share_base")
            try:
                if sb is not None and pd.notna(sb) and float(sb) > 0:
                    disp = f"{float(sb):,.0f}"
                else:
                    disp = "N/A"
            except Exception:
                disp = "N/A"
            st.caption(f"TOR 精確值（share base: {disp}）")

def queue_scroll_to_anchor(anchor_id: str):
    st.session_state.pending_scroll_target = anchor_id
    st.session_state.pending_scroll_token = int(st.session_state.get("pending_scroll_token", 0)) + 1

def render_scroll_anchor(anchor_id: str):
    st.markdown(f'<span id="{anchor_id}" class="section-anchor"></span>', unsafe_allow_html=True)

def render_section_anchor_nav(title: str, caption: str, sections: List[tuple], key_prefix: str):
    with st.expander(title, expanded=False):
        st.caption(caption)
        cols = st.columns(2)
        for idx, (anchor_id, label) in enumerate(sections):
            with cols[idx % 2]:
                if st.button(label, key=f"{key_prefix}_{anchor_id}", use_container_width=True):
                    queue_scroll_to_anchor(anchor_id)
                    st.rerun()

def get_home_stock_anchor_id(ticker: str) -> str:
    safe_ticker = "".join(ch if ch.isalnum() else "-" for ch in str(ticker))
    return f"home-stock-{safe_ticker}"

def consume_pending_scroll_anchor():
    anchor_id = st.session_state.pop("pending_scroll_target", None)
    if not anchor_id:
        return
    scroll_token = int(st.session_state.pop("pending_scroll_token", 0))
    components.html(
        f"""
        <script>
        const anchorId = {json.dumps(anchor_id)};
        const scrollToken = {json.dumps(scroll_token)};
        const doc = window.parent.document;
        const win = window.parent;
        const scrollToAnchor = () => {{
            const target = doc.getElementById(anchorId);
            if (!target) {{
                return false;
            }}
            target.scrollIntoView({{ behavior: "smooth", block: "start" }});
            return true;
        }};
        const retriggerHashScroll = () => {{
            try {{
                const clearUrl = new URL(win.location.href);
                clearUrl.hash = "";
                win.history.replaceState(null, "", clearUrl.toString());
                win.setTimeout(() => {{
                    const targetUrl = new URL(win.location.href);
                    targetUrl.hash = anchorId;
                    win.history.replaceState(null, "", targetUrl.toString());
                    scrollToAnchor();
                }}, 40);
            }} catch (e) {{
                scrollToAnchor();
            }}
        }};
        const kickScroll = () => {{
            retriggerHashScroll();
            if (win.requestAnimationFrame) {{
                win.requestAnimationFrame(() => scrollToAnchor());
                win.requestAnimationFrame(() => win.requestAnimationFrame(() => scrollToAnchor()));
            }}
        }};

        [0, 160, 420, 900, 1600].forEach((delay) => {{
            win.setTimeout(kickScroll, delay);
        }});
        </script>
        """,
        height=0,
    )

def render_pending_scroll_here(anchor_id: str):
    pending_anchor = st.session_state.get("pending_scroll_target")
    if pending_anchor != anchor_id:
        return
    st.session_state.pop("pending_scroll_target", None)
    scroll_token = int(st.session_state.pop("pending_scroll_token", 0))
    components.html(
        f"""
        <script>
        const anchorId = {json.dumps(anchor_id)};
        const scrollToken = {json.dumps(scroll_token)};
        const doc = window.parent.document;
        const win = window.parent;
        const scrollToAnchor = () => {{
            const target = doc.getElementById(anchorId);
            if (!target) {{
                return false;
            }}
            target.scrollIntoView({{ behavior: "smooth", block: "start" }});
            return true;
        }};
        const retriggerHashScroll = () => {{
            try {{
                const clearUrl = new URL(win.location.href);
                clearUrl.hash = "";
                win.history.replaceState(null, "", clearUrl.toString());
                win.setTimeout(() => {{
                    const targetUrl = new URL(win.location.href);
                    targetUrl.hash = anchorId;
                    win.history.replaceState(null, "", targetUrl.toString());
                    scrollToAnchor();
                }}, 40);
            }} catch (e) {{
                scrollToAnchor();
            }}
        }};
        const kickScroll = () => {{
            retriggerHashScroll();
            if (win.requestAnimationFrame) {{
                win.requestAnimationFrame(() => scrollToAnchor());
                win.requestAnimationFrame(() => win.requestAnimationFrame(() => scrollToAnchor()));
            }}
        }};

        [0, 160, 420, 900, 1600, 2400].forEach((delay) => {{
            win.setTimeout(kickScroll, delay);
        }});
        </script>
        """,
        height=0,
    )


def render_top_navigation():
    current_page = st.session_state.get("current_page", "home")
    home_active = is_home_context_page(current_page)

    st.caption("快捷導航")
    quick_cols = st.columns(3)
    with quick_cols[0]:
        if st.button("🏠 總覽", key="quick_nav_home", use_container_width=True, type="primary" if home_active else "secondary"):
            set_current_page("home")
            st.rerun()
    with quick_cols[1]:
        if st.button("📈 單股", key="quick_nav_stock", use_container_width=True, type="primary" if current_page == "stock" else "secondary"):
            set_current_page("stock")
            st.rerun()
    with quick_cols[2]:
        if st.button("🧪 回測", key="quick_nav_backtest", use_container_width=True, type="primary" if current_page == "backtest" else "secondary"):
            set_current_page("backtest")
            st.rerun()
    st.write("---")

def render_bottom_navigation():
    current_page = st.session_state.get("current_page", "home")
    home_active = is_home_context_page(current_page)
    st.write("---")
    st.markdown('<div class="bottom-nav-note">底部快捷導航：看完內容可直接切換，不用再拉回頁首。</div>', unsafe_allow_html=True)
    labels = {
        "home": "🏠 總覽",
        "stock": "📈 單股",
        "backtest": "🧪 回測",
    }
    active_labels = {
        "home": "● 總覽",
        "stock": "● 單股",
        "backtest": "● 回測",
    }
    bottom_cols = st.columns(3)
    with bottom_cols[0]:
        if st.button(active_labels["home"] if home_active else labels["home"], key="bottom_nav_home", use_container_width=True, type="primary" if home_active else "secondary"):
            set_current_page("home")
            st.rerun()
    with bottom_cols[1]:
        if st.button(active_labels["stock"] if current_page == "stock" else labels["stock"], key="bottom_nav_stock", use_container_width=True, type="primary" if current_page == "stock" else "secondary"):
            set_current_page("stock")
            st.rerun()
    with bottom_cols[2]:
        if st.button(active_labels["backtest"] if current_page == "backtest" else labels["backtest"], key="bottom_nav_backtest", use_container_width=True, type="primary" if current_page == "backtest" else "secondary"):
            set_current_page("backtest")
            st.rerun()

def render_navigation_expander():
    current_page = st.session_state.get("current_page", "home")
    page_defs = [
        {
            "title": "🏠 總覽",
            "page": "home",
            "desc": ["收藏股總覽卡片", "刷新所有數據", "快速進入比較模式"],
            "hint": "先看整體，再決定下一步",
        },
        {
            "title": "📊 比較模式",
            "page": "comparison",
            "desc": ["SMA 趨勢排序", "MR / CDM / 振幅對比", "綜合評分與下載報告"],
            "hint": "適合橫向比較收藏股",
        },
        {
            "title": "📈 單股分析",
            "page": "stock",
            "desc": ["價格摘要與 K 線圖", "快速信號", "數據列表"],
            "hint": "適合查看單一股票細節",
        },
        {
            "title": "🧪 歷史回測",
            "page": "backtest",
            "desc": ["回測設定", "單策略回測", "策略對標與推薦"],
            "hint": "適合驗證策略表現",
        },
        {
            "title": "⚙️ 設定",
            "page": "settings",
            "desc": ["Telegram 設定", "SMA 參數", "基準日期"],
            "hint": "集中管理分析與通知設定",
        },
    ]

    with st.expander("導航", expanded=False):
        st.caption("按頁面由上到下切換，適合手機瀏覽時快速找到功能。")
        for item in page_defs:
            btn_type = "primary" if current_page == item["page"] else "secondary"
            badge = "目前頁面" if current_page == item["page"] else item["hint"]
            desc_html = "".join([f"<li>{line}</li>" for line in item["desc"]])
            st.markdown(
                f"""
                <div class="nav-card {'active' if current_page == item['page'] else ''}">
                    <div class="nav-top">
                        <div class="nav-title">{item['title']}</div>
                        <div class="nav-badge">{badge}</div>
                    </div>
                    <ul class="nav-desc">{desc_html}</ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(item["title"], key=f"sidebar_nav_{item['page']}", use_container_width=True, type=btn_type):
                set_current_page(item["page"])
                st.rerun()
def render_stock_section_navigation() -> str:
    sections = [
        ("stock-header", "股票名字位置"),
        ("stock-sma-line", "SMA線"),
        ("stock-quick", "快速信號"),
        ("stock-data", "數據列表"),
        ("stock-interactive", "互動模式"),
        ("stock-sma-matrix", "SMA Matrix"),
        ("stock-price-interface", "Price界面"),
        ("stock-turnover", "Turnover Rate"),
        ("stock-cdm", "CDM"),
    ]
    render_section_anchor_nav("單股導航", "點擊後自動滾動到對應區段，保留整頁內容連續瀏覽。", sections, "stock_anchor")
    return "all"

def render_comparison_section_navigation() -> str:
    sections = [
        ("comparison-trend", "SMA趨勢"),
        ("comparison-mr", "MR偏差"),
        ("comparison-cdm", "CDM狀態"),
        ("comparison-amp", "振幅對比"),
        ("comparison-score", "綜合評分"),
    ]
    render_section_anchor_nav("比較頁導航", "點擊後自動滾動到對應區段，適合快速查看不同排序表。", sections, "comparison_anchor")
    return "trend"

def render_backtest_section_navigation() -> str:
    sections = [
        ("backtest-settings", "回測設定"),
        ("backtest-single", "單策略回測"),
        ("backtest-compare", "策略對標"),
        ("backtest-recommend", "策略推薦"),
    ]
    render_section_anchor_nav("回測導航", "點擊後自動滾動到對應區段，方便在設定、對標與推薦間切換。", sections, "backtest_anchor")
    return "settings"

def render_home_section_navigation(watchlist_list: List[str]) -> str:
    if not watchlist_list:
        render_navigation_expander()
        return "home"
    sections = [(get_home_stock_anchor_id(ticker), ticker) for ticker in watchlist_list]
    render_section_anchor_nav("總覽導航", "按收藏股票快速定位到首頁對應區塊，保留整頁連續瀏覽。", sections, "home_anchor")
    return "home"

def render_sidebar_context_navigation(watchlist_list: List[str]):
    current_page = st.session_state.get("current_page", "home")
    if current_page == "stock":
        render_stock_section_navigation()
    elif current_page == "comparison":
        render_comparison_section_navigation()
    elif current_page == "backtest":
        render_backtest_section_navigation()
    elif is_home_context_page(current_page):
        render_home_section_navigation(watchlist_list)
    else:
        render_navigation_expander()


def render_settings_page():
    st.title("⚙️ 設定")

    st.subheader("✈️ Telegram 設定")
    s1, s2 = st.columns(2)
    with s1:
        tg_token_page = st.text_input("Bot Token", value=st.session_state.get("tg_token", ""), type="password", key="settings_tg_token")
    with s2:
        tg_chat_id_page = st.text_input("Chat ID", value=st.session_state.get("tg_chat_id", ""), key="settings_tg_chat_id")
    st.session_state.tg_token = tg_token_page
    st.session_state.tg_chat_id = tg_chat_id_page

    st.write("---")
    st.subheader("📐 分析參數")
    p1, p2 = st.columns(2)
    with p1:
        st.session_state.sma1 = int(st.number_input("SMA 1", min_value=1, value=int(st.session_state.get("sma1", 20)), key="settings_sma1"))
    with p2:
        st.session_state.sma2 = int(st.number_input("SMA 2", min_value=1, value=int(st.session_state.get("sma2", 50)), key="settings_sma2"))

    st.write("---")
    st.subheader("📅 基準日期")
    settings_date = st.date_input("基準日期", value=st.session_state.ref_date, key="settings_ref_date")
    if settings_date != st.session_state.ref_date:
        st.session_state.ref_date = settings_date
        st.rerun()

    st.write("---")
    st.subheader("🧭 使用方式")
    st.markdown(
        "- `首頁總覽`：查看收藏股的總覽卡片\n"
        "- `比較模式`：對收藏股做橫向對比\n"
        "- `單股分析`：查看單一股票的圖表與快速信號\n"
        "- `歷史回測`：執行回測、策略對標與推薦\n"
        "- `設定`：集中管理 Telegram、SMA 與日期參數"
    )

def render_backtest_hub_page(current_code: str, watchlist_data: Dict[str, Any], watchlist_list: List[str]):
    st.title("🧪 歷史回測")
    input_col, btn_col = st.columns([4, 1])
    with input_col:
        ticker_input = st.text_input("輸入股票代號", value=current_code or "", placeholder="例如: 700", key="backtest_page_ticker")
    with btn_col:
        st.write("")
        if st.button("前往單股", use_container_width=True, key="backtest_go_stock"):
            if ticker_input:
                set_current_page("stock", ticker_input)
                st.rerun()

    if ticker_input:
        cleaned = clean_ticker_input(ticker_input)
        if cleaned and cleaned != current_code:
            st.session_state.current_view = cleaned
            current_code = cleaned

    if not current_code:
        st.info("請先輸入或從左側收藏清單選擇股票，然後開始回測。")
        if watchlist_list:
            st.caption("快速選擇收藏股")
            cols = st.columns(min(4, len(watchlist_list)))
            for idx, ticker in enumerate(watchlist_list[:8]):
                with cols[idx % len(cols)]:
                    if st.button(ticker, key=f"bt_pick_{ticker}", use_container_width=True):
                        set_current_page("backtest", ticker)
                        st.rerun()
        return

    yahoo_ticker = get_yahoo_ticker(current_code)
    df_share = get_data_v7(yahoo_ticker, st.session_state.ref_date)
    df = df_share[0] if isinstance(df_share, tuple) else df_share
    share_base = df_share[1] if isinstance(df_share, tuple) else None
    if df is None or len(df) <= 5:
        st.warning("無法取得足夠數據進行回測。")
        return
    render_backtest_page(df, current_code, watchlist_data)

# --- 5. 初始化 Session State ---
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = "home"
if "comparison_mode" not in st.session_state:
    st.session_state.comparison_mode = False
if "stock_section" not in st.session_state:
    st.session_state.stock_section = "all"
if "comparison_section" not in st.session_state:
    st.session_state.comparison_section = "trend"
if "backtest_section" not in st.session_state:
    st.session_state.backtest_section = "settings"
if "show_filter" not in st.session_state:
    st.session_state.show_filter = False
if "comparison_filters" not in st.session_state:
    st.session_state.comparison_filters = {}

def handle_sidebar_search():
    search_input = st.session_state.get("search_bar", "")
    if not search_input:
        return
    cleaned = clean_ticker_input(search_input)
    if cleaned:
        set_current_page("stock", cleaned)

secrets = get_secrets_dict()
telegram_cfg = secrets.get("telegram", {}) if isinstance(secrets.get("telegram", {}), dict) else {}
if "tg_token" not in st.session_state:
    st.session_state.tg_token = telegram_cfg.get("token", "")
if "tg_chat_id" not in st.session_state:
    st.session_state.tg_chat_id = telegram_cfg.get("chat_id", "")
if "sma1" not in st.session_state:
    st.session_state.sma1 = 20
if "sma2" not in st.session_state:
    st.session_state.sma2 = 50

# --- 6. 側邊欄 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    # 版本可視標記：用戶一眼就能看出 redeploy 成功了沒
    try:
        _build_caption = (
            f"🛠️ Build: {_APP_BUILD.get('commit','?')}  "
            f"| yfinance: {_APP_BUILD.get('yf_version','?')}  "
            f"| {_APP_BUILD.get('time','?')}"
        )
        st.caption(_build_caption)
        st.caption(f"💡 如果沒看到上面 Build 號 = Streamlit 仍在跑舊版！請做 Clear cache + Redeploy")
    except Exception:
        pass
    nav_slot = st.empty()
    
    # 🔚 結束版本標記 ———
    # Telegram 設定
    with st.expander("✈️ Telegram 設定", expanded=False):
        st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.get("tg_token", ""), type="password", key="sidebar_tg_token")
        st.session_state.tg_chat_id = st.text_input("Chat ID", value=st.session_state.get("tg_chat_id", ""), key="sidebar_tg_chat_id")
        
        if st.button("🚀 發送單股報告", type="primary"):
            if st.session_state.current_view and st.session_state.tg_token and st.session_state.tg_chat_id:
                yt = get_yahoo_ticker(st.session_state.current_view)
                with st.spinner("分析中..."):
                    try:
                        d = yf.download(yt, period="2y", progress=False, auto_adjust=False)
                        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
                        try:
                            t_obj = yf.Ticker(yt)
                            share_base = get_turnover_share_base(t_obj)
                            d, turnover_status, turnover_reason = apply_turnover_rate(d, share_base)
                            if turnover_status != TURNOVER_STATUS_CALCULATED:
                                LOGGER.info(
                                    "Telegram report TOR unavailable for %s: %s (%s)",
                                    yt,
                                    turnover_status,
                                    turnover_reason,
                                )
                        except Exception as exc:
                            LOGGER.warning("Unable to attach TOR for Telegram report %s: %s", yt, exc)
                        if len(d) > 50:
                            w = get_watchlist_from_db()
                            msg = run_analysis_logic(d, st.session_state.current_view, w.get(st.session_state.current_view, {}))
                            ok, res = send_telegram_msg(st.session_state.tg_token, st.session_state.tg_chat_id, msg)
                            if ok: st.toast("Sent!", icon="✅")
                            else: st.error(res)
                        else: st.error("數據不足")
                    except Exception as e: st.error(str(e))
            else:
                st.toast("請先選擇股票並設定 Token", icon="⚠️")

    st.divider()
    
    # 日期與搜尋
    new_date = st.date_input("基準日期", value=st.session_state.ref_date)
    if new_date != st.session_state.ref_date:
        st.session_state.ref_date = new_date
        st.rerun()

    st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar", on_change=handle_sidebar_search)

    watchlist_data = get_watchlist_from_db()
    watchlist_list = list(watchlist_data.keys()) if watchlist_data else []

    with nav_slot.container():
        render_sidebar_context_navigation(watchlist_list)

    st.divider()
    
    # 收藏夾導航
    st.markdown(
        """
        <style>
        .watchlist-inline-row>div {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: stretch !important;
            gap: 6px !important;
        }
        .watchlist-inline-row [data-testid="column"] {
            width: auto !important;
            flex: 1 1 auto !important;
            min-width: 0 !important;
        }
        .watchlist-inline-row [data-testid="column"]+[data-testid="column"] {
            flex: 0 0 auto !important;
            width: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    st.subheader(f"我的收藏 ({len(watchlist_list)})")
    _mode_tip = (f"🎯 渲染模式：原生 HTML form inline-flex（V9，保證同行不拆行）  "
                 f"|  Build: {_APP_BUILD.get('commit','?')}  "
                 f"|  yfinance: {_APP_BUILD.get('yf_version','?')}{'  [1.x detected → native requests fallback 🔥]' if _YF_IS_BROKEN_V1 else ''}")
    st.caption(_mode_tip)
    if watchlist_list:
        for ticker in watchlist_list:
            _btns_style = (
                "display:flex;flex-direction:row;flex-wrap:nowrap;"
                "align-items:stretch;gap:6px;width:100%;margin:0 0 6px 0;"
            )
            _nav_style = (
                "flex:1 1 auto;min-width:0;height:42px;font-size:16px;"
                "font-weight:600;border:1px solid rgba(49,51,63,0.2);border-radius:6px;"
                "background-color:#FFFFFF;color:#31333F;cursor:pointer;"
                "white-space:nowrap;padding:4px 10px;"
            )
            _del_style = (
                "flex:0 0 48px;width:48px;height:42px;font-size:18px;"
                "border:1px solid rgba(49,51,63,0.2);border-radius:6px;"
                "background-color:#FFFFFF;color:#d9534f;cursor:pointer;"
                "white-space:nowrap;padding:0;"
            )
            _html = f"""
            <form method="get" style="{_btns_style}" onsubmit="return true;">
              <input type="hidden" name="wl_ticker" value="{ticker}">
              <button type="submit" name="wl_action" value="nav" style="{_nav_style}">{ticker}</button>
              <button type="submit" name="wl_action" value="del" style="{_del_style}" title="取消收藏 {ticker}">🗑️</button>
            </form>
            """
            st.markdown(_html, unsafe_allow_html=True)
    else:
        st.caption("暫無收藏")
    
    st.divider()
    if st.button("🏠 回到總覽 (Overview)", use_container_width=True):
        st.session_state.current_view = ""
        set_current_page("home")
        st.rerun()

    st.divider()
    st.session_state.sma1 = int(st.number_input("SMA 1", value=int(st.session_state.get("sma1", 20)), key="sidebar_sma1"))
    st.session_state.sma2 = int(st.number_input("SMA 2", value=int(st.session_state.get("sma2", 50)), key="sidebar_sma2"))

    st.divider()
    try:
        _a1_token = _a1_read_gh_token()
        if not _a1_token:
            _a1_status_html = """
            <details>
              <summary style="cursor:pointer;color:#6b7280;">⚪ A1: 未設定 GH_PAT (skip)</summary>
              <div style="margin-top:8px;font-size:12px;color:#6b7280;">
                Cloud 端請至 Streamlit Secrets 設定 <code>GH_PAT</code>；
                本機請設定環境變數。未設定時自動退回舊 live Yahoo 模式。
              </div>
            </details>
            """
        elif _ARTIFACT_SYNC_OK:
            _a1_status_html = f"""
            <details>
              <summary style="cursor:pointer;color:#16a34a;">🟢 A1 Synced @ {_ARTIFACT_LAST_SYNC_TS or 'N/A'}</summary>
              <div style="margin-top:8px;font-size:12px;color:#374151;">
                cached = {_ARTIFACT_CACHED_N} 支 | mode = cache-hit (L2 SQLite)
                <br>TTL = 9 min | artifact = <code>{_GH_ARTIFACT_NAME}</code>
              </div>
            </details>
            """
        else:
            _err = _ARTIFACT_LAST_ERROR or "unknown error"
            _a1_status_html = f"""
            <details>
              <summary style="cursor:pointer;color:#ca8a04;">🟡 A1 sync failed | fallback live mode</summary>
              <div style="margin-top:8px;font-size:12px;color:#6b7280;">
                reason = {_err}
                <br>下次首頁 reload 會自動重試（TTL 9 min）
              </div>
            </details>
            """
        st.markdown(_a1_status_html, unsafe_allow_html=True)
    except Exception:
        pass

# --- 7. 主程式邏輯 ---

# 原生 HTML form query params 導航：完全不依賴 Streamlit widget wrapper，保證同行不換行
try:
    _qp = st.query_params.to_dict() if hasattr(st, "query_params") else {}
except Exception:
    _qp = {}
if _qp:
    _action = str(_qp.get("wl_action", [""])[0] if isinstance(_qp.get("wl_action"), list) else _qp.get("wl_action", "")).strip()
    _tick = str(_qp.get("wl_ticker", [""])[0] if isinstance(_qp.get("wl_ticker"), list) else _qp.get("wl_ticker", "")).strip()
    if _tick and _action in ("nav", "del"):
        try:
            st.query_params.clear()
        except Exception:
            pass
        if _action == "nav":
            st.session_state.current_view = _tick
            set_current_page("stock", _tick)
            st.rerun()
        elif _action == "del":
            if remove_stock_from_db(_tick):
                st.rerun()

current_code = st.session_state.current_view
current_page = st.session_state.current_page
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')
sma1 = int(st.session_state.get("sma1", 20))
sma2 = int(st.session_state.get("sma2", 50))

if current_page != "home_detail":
    render_top_navigation()

# === 主頁面路由 ===
if current_page == "settings":
    render_settings_page()

elif current_page == "comparison":
    if not watchlist_list:
        st.title("📊 港股收藏夾對比面板")
        st.info("👈 您的收藏清單為空，請先從左側加入股票。")
    else:
        render_comparison_page(watchlist_list, watchlist_data)

elif current_page == "backtest":
    render_backtest_hub_page(current_code, watchlist_data, watchlist_list)

elif current_page == "home_detail":
    if not current_code:
        st.warning("尚未選擇要查看的股票。")
        if st.button("🏠 返回主頁", key="home_detail_empty_back", use_container_width=True):
            set_current_page("home")
            st.rerun()
    else:
        render_home_snapshot_detail_page(current_code)

elif current_page == "home":
    st.title("📊 港股 SMA 矩陣 - 收藏總覽")
    
    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        snapshot = get_home_watchlist_snapshot(watchlist_list, str(st.session_state.ref_date))
        summary_rows = snapshot.get("summaries", [])
        diagnostic = snapshot.get("diagnostic", {}) or {}

        c_btn_1, c_btn_2 = st.columns(2)
        with c_btn_1:
            if st.button("🔄 刷新所有數據", use_container_width=True):
                get_home_watchlist_snapshot.clear()
                st.rerun()
        with c_btn_2:
            if st.button("📊 比較模式", use_container_width=True, type="primary"):
                set_current_page("comparison")
                st.rerun()
        st.write("---")

        if diagnostic:
            with st.expander(f"⚠️ {len(diagnostic)} 支股票暫無數據", expanded=False):
                for tk, msg in sorted(diagnostic.items()):
                    st.caption(f"- `{tk}`：{msg}")

        if not summary_rows:
            st.warning("目前沒有足夠數據可生成收藏股列表。請稍後再試，或檢查收藏清單中的股票代號是否正確。")
            sorted_rows = []
        else:
            sort_options = ["Dev 3", "Dev 7", "Dev 14", "Dev 28"]
            if "home_sort_metric" not in st.session_state or st.session_state.home_sort_metric not in sort_options:
                st.session_state.home_sort_metric = "Dev 3"
            if "home_sort_desc" not in st.session_state:
                st.session_state.home_sort_desc = True

            sort_cols = st.columns([1, 1, 1, 1, 1])
            for idx, option in enumerate(sort_options):
                with sort_cols[idx]:
                    if st.button(
                        option,
                        key=f"home_sort_btn_{option}",
                        use_container_width=True,
                        type="primary" if st.session_state.home_sort_metric == option else "secondary",
                    ):
                        st.session_state.home_sort_metric = option
                        st.rerun()
            with sort_cols[4]:
                if st.button(
                    "由高到低" if st.session_state.home_sort_desc else "由低到高",
                    key="home_sort_toggle",
                    use_container_width=True,
                    type="secondary",
                ):
                    st.session_state.home_sort_desc = not st.session_state.home_sort_desc
                    st.rerun()

            selected_sort = st.session_state.home_sort_metric
            sorted_rows = sorted(
                summary_rows,
                key=lambda row: float(row.get(selected_sort)) if pd.notna(row.get(selected_sort)) else float("-inf"),
                reverse=bool(st.session_state.home_sort_desc),
            )
            available_codes = [row["Code"] for row in sorted_rows]
            if st.session_state.get("home_selected_ticker") not in available_codes:
                st.session_state.home_selected_ticker = available_codes[0]

            def _fmt_num(value):
                return "-" if pd.isna(value) else f"{float(value):.2f}"

            def _fmt_pct(value):
                return "-" if pd.isna(value) else f"{float(value):+.2f}%"

        if sorted_rows:
            # ============================================================
            # Home stock cards: keep all 7 fields on one horizontal row.
            # A hidden marker inside each row lets CSS identify the exact
            # Streamlit HorizontalBlock without depending on Streamlit's
            # generated aria-labels or container DOM classes.
            # ============================================================
            st.markdown(
                """
                <style>
                /* Compact table-like Home stock list.
                   Desktop: 7 equal columns.
                   Mobile: same 7 columns, horizontally scrollable. */
                .home-stock-table-header {
                    display: grid;
                    grid-template-columns: repeat(7, minmax(0, 1fr));
                    width: 100%;
                    min-width: 0;
                    overflow-x: auto;
                    box-sizing: border-box;
                    border: 1px solid #d9dee5;
                    border-bottom: 0;
                    border-radius: 6px 6px 0 0;
                    background: #f5f7fa;
                }

                .home-stock-table-header > div {
                    min-width: 0;
                    padding: 3px 4px;
                    border-right: 1px solid #d9dee5;
                    text-align: center;
                    font-size: 10px;
                    line-height: 18px;
                    color: #667085;
                    white-space: nowrap;
                    box-sizing: border-box;
                }

                .home-stock-table-header > div:last-child {
                    border-right: 0;
                }

                div[class*="st-key-home_stock_card_"] {
                    width: 100% !important;
                    max-width: 100% !important;
                    min-width: 0 !important;
                    overflow: visible !important;
                    box-sizing: border-box !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    border: 0 !important;
                    border-radius: 0 !important;
                    background: transparent !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker) {
                    flex-direction: row !important;
                    flex-wrap: nowrap !important;
                    width: 100% !important;
                    max-width: 100% !important;
                    min-width: 0 !important;
                    overflow-x: auto !important;
                    overflow-y: hidden !important;
                    gap: 0 !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    box-sizing: border-box !important;
                    border-left: 1px solid #d9dee5 !important;
                    border-right: 1px solid #d9dee5 !important;
                    border-bottom: 1px solid #e4e7ec !important;
                    -webkit-overflow-scrolling: touch !important;
                    background: white !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                > div[data-testid="stColumn"] {
                    flex: 1 1 0 !important;
                    width: auto !important;
                    min-width: 78px !important;
                    max-width: none !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    box-sizing: border-box !important;
                    border-right: 1px solid #e4e7ec !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                > div[data-testid="stColumn"]:last-child {
                    border-right: 0 !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker) .stock-cell {
                    width: 100% !important;
                    min-width: 78px !important;
                    height: 25px !important;
                    padding: 2px 3px !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    text-align: center !important;
                    font-size: 11px !important;
                    line-height: 18px !important;
                    font-weight: 500 !important;
                    color: #111827 !important;
                    -webkit-text-fill-color: #111827 !important;
                    background: #ffffff !important;
                    white-space: nowrap !important;
                    box-sizing: border-box !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                .stButton {
                    margin: 0 !important;
                    padding: 0 !important;
                }

                div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                .stButton > button {
                    width: 100% !important;
                    min-width: 78px !important;
                    max-width: none !important;
                    min-height: 25px !important;
                    height: 25px !important;
                    padding: 2px 4px !important;
                    margin: 0 !important;
                    border: 0 !important;
                    border-radius: 0 !important;
                    box-shadow: none !important;
                    white-space: nowrap !important;
                    font-size: 11px !important;
                    line-height: 18px !important;
                    box-sizing: border-box !important;
                }

                .home-stock-card-marker {
                    display: none !important;
                }

                @media (max-width: 768px) {
                    .home-stock-table-header {
                        grid-template-columns: repeat(7, 78px);
                        width: max-content;
                        min-width: 546px;
                    }

                    .home-stock-table-header > div {
                        width: 78px;
                        min-width: 78px;
                        font-size: 9px;
                        line-height: 17px;
                        padding: 2px 3px;
                    }

                    div[class*="st-key-home_stock_card_"] {
                        width: 100% !important;
                        max-width: 100% !important;
                        min-width: 0 !important;
                        overflow: visible !important;
                    }

                    div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker) {
                        width: max-content !important;
                        min-width: 546px !important;
                        max-width: none !important;
                        overflow-x: auto !important;
                        overflow-y: hidden !important;
                        flex-wrap: nowrap !important;
                        -webkit-overflow-scrolling: touch !important;
                        touch-action: pan-x !important;
                    }

                    div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                    > div[data-testid="stColumn"] {
                        flex: 0 0 78px !important;
                        width: 78px !important;
                        min-width: 78px !important;
                        max-width: 78px !important;
                    }

                    div[data-testid="stHorizontalBlock"]:has(.home-stock-card-marker)
                    .stock-cell {
                        color: #111827 !important;
                        -webkit-text-fill-color: #111827 !important;
                        background: #ffffff !important;
                    }
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                """
                <div class="home-stock-table-header">
                    <div>Code</div>
                    <div>CPRD</div>
                    <div>Dev 0</div>
                    <div>Dev 3</div>
                    <div>Dev 7</div>
                    <div>Dev 14</div>
                    <div>Dev 28</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            for row in sorted_rows:
                ticker = str(row["Code"])
                safe_ticker = "".join(ch if ch.isalnum() else "_" for ch in ticker)

                render_scroll_anchor(get_home_stock_anchor_id(ticker))

                with st.container(key=f"home_stock_card_{safe_ticker}"):
                    cols = st.columns([1, 1, 1, 1, 1, 1, 1])

                    # Hidden CSS hook inside this exact HorizontalBlock.
                    with cols[0]:
                        st.markdown(
                            '<span class="home-stock-card-marker" aria-hidden="true"></span>',
                            unsafe_allow_html=True,
                        )
                        if st.button(
                            ticker,
                            key=f"home_code_{ticker}",
                            use_container_width=True,
                        ):
                            st.session_state.home_selected_ticker = ticker
                            st.session_state.home_return_anchor = (
                                get_home_stock_anchor_id(ticker)
                            )
                            set_current_page("home_detail", ticker)
                            st.rerun()

                    with cols[1]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_num(row.get("CPRD", None))}</div>',
                            unsafe_allow_html=True,
                        )

                    with cols[2]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_pct(row.get("Dev 0", None))}</div>',
                            unsafe_allow_html=True,
                        )

                    with cols[3]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_pct(row.get("Dev 3", None))}</div>',
                            unsafe_allow_html=True,
                        )

                    with cols[4]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_pct(row.get("Dev 7", None))}</div>',
                            unsafe_allow_html=True,
                        )

                    with cols[5]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_pct(row.get("Dev 14", None))}</div>',
                            unsafe_allow_html=True,
                        )

                    with cols[6]:
                        st.markdown(
                            f'<div class="stock-cell">{_fmt_pct(row.get("Dev 28", None))}</div>',
                            unsafe_allow_html=True,
                        )

elif not current_code:
    st.title("📈 單股分析")
    st.info("請先從左側輸入股票代號或點擊收藏清單，再查看單股功能。")

else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)
    show_header = True
    show_quick = True
    show_data = True
    show_interactive = True
    show_sma_line = True
    show_sma_matrix = True
    show_price_interface = True
    show_turnover = True
    show_cdm = True

    render_scroll_anchor("stock-header")
    col_t, col_b = st.columns([0.85, 0.15])
    with col_t: st.title(f"📊 {display_ticker}")
    with col_b:
        st.write("")
        is_in_watchlist = current_code in watchlist_list
        if is_in_watchlist:
            if st.button("★ 已收藏", type="primary", use_container_width=True):
                if remove_stock_from_db(current_code):
                    st.rerun()
        else:
            if st.button("☆ 加入", use_container_width=True):
                if update_stock_in_db(current_code):
                    st.rerun()

    df_share = get_data_v7(yahoo_ticker, st.session_state.ref_date)
    df = df_share[0] if isinstance(df_share, tuple) else df_share
    share_base = df_share[1] if isinstance(df_share, tuple) else None

    if df is None or len(df) <= 5:
        import time as _t_now
        _extra_info = []
        _extra_info.append(f"🛠️  Build: {_APP_BUILD.get('commit','?')}  |  yfinance: {_APP_BUILD.get('yf_version','?')}")
        _extra_info.append(f"🔎  Yahoo ticker 送出: `{yahoo_ticker}`  |  原代碼: `{current_code}`")
        try:
            until = _YF_SESS_MGR._error_until.get(yahoo_ticker, 0.0) or _YF_SESS_MGR._error_until.get(current_code, 0.0)
            left = max(0, int(until - _t_now.time()))
            if left > 0:
                _extra_info.append(f"⌛ Error 降級中：{left}s 後自動重試（節省 Yahoo 配額）")
        except Exception:
            pass
        try:
            ec = _YF_SESS_MGR._error_count.get(yahoo_ticker, 0) or _YF_SESS_MGR._error_count.get(current_code, 0)
            if ec:
                _extra_info.append(f"⚠️ 連續失敗次數: {ec}")
        except Exception:
            pass
        try:
            _last = _YF_LAST_ERROR.get(yahoo_ticker) or _YF_LAST_ERROR.get(current_code) or _YF_LAST_ERROR.get(yahoo_ticker.replace(".HK","").replace(".hk",""))
            if _last:
                _extra_info.append(f"🧭 最後嘗試 [{_last.get('route','?')}] @ {_last.get('time','?')}：{_last.get('detail','')}")
        except Exception:
            pass
        try:
            n_at = _NATIVE_DOWNLOAD_STATS.get("native_attempts", 0)
            n_ok = _NATIVE_DOWNLOAD_STATS.get("native_success", 0)
            yf_at = _NATIVE_DOWNLOAD_STATS.get("yf_attempts", 0)
            yf_ok = _NATIVE_DOWNLOAD_STATS.get("yf_success", 0)
            if (n_at + yf_at) > 0:
                s_at = _NATIVE_DOWNLOAD_STATS.get("stooq_attempts", 0)
                s_ok = _NATIVE_DOWNLOAD_STATS.get("stooq_success", 0)
                si_at = _NATIVE_DOWNLOAD_STATS.get("sina_attempts", 0)
                si_ok = _NATIVE_DOWNLOAD_STATS.get("sina_success", 0)
                _extra_info.append(f"📊 下載統計：native {n_ok}/{n_at}  |  yfinance {yf_ok}/{yf_at}  |  stooq {s_ok}/{s_at}  |  sina {si_ok}/{si_at}（本 app instance 累計）")
        except Exception:
            pass
        try:
            _matches_step = []
            for _t, _sym, _stg, _msg in reversed(_YF_NATIVE_STEP_LOG):
                if _sym == yahoo_ticker or _sym == current_code:
                    _matches_step.append(f"[{_t}] {_stg} → {_msg}")
                if len(_matches_step) >= 24:
                    break
            if _matches_step:
                _extra_info.append("🔧 --- DEBUG STEP LOG (最新→最舊，限前 24 條) ---")
                for _l in _matches_step:
                    _extra_info.append("🔧 " + _l)
        except Exception:
            pass
        try:
            _matches_perr = []
            for _t, _sym, _rt, _det in reversed(_YF_PERSIST_ERR_LOG):
                if _sym == yahoo_ticker or _sym == current_code:
                    _matches_perr.append(f"[{_t}] <{_rt}> {_det}")
                if len(_matches_perr) >= 12:
                    break
            if _matches_perr:
                _extra_info.append("🚨 --- PERSIST ERRORS (限前 12 條) ---")
                for _l in _matches_perr:
                    _extra_info.append("🚨 " + _l)
        except Exception:
            pass
        st.error("⚠️ 載入失敗：Yahoo Finance 暫時拒絕連線（Invalid Crumb / 401 Unauthorized）。已自動切 Stooq 備援；若仍失敗請按下方按鈕重試。")
        for _line in _extra_info:
            st.caption(_line)
        if st.button("🔄 重試載入數據（清除 blacklist + cache）", use_container_width=True, key="stock_retry_df"):
            for _tk in (yahoo_ticker, current_code):
                try:
                    _YF_SESS_MGR._error_count.pop(_tk, None)
                    _YF_SESS_MGR._error_until.pop(_tk, None)
                except Exception:
                    pass
            get_data_v7.clear()
            st.rerun()
    else:
        # 0. 基礎計算
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma: df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
        if f'SMA_{sma1}' not in df.columns: df[f'SMA_{sma1}'] = df['Close'].rolling(sma1).mean()
        if f'SMA_{sma2}' not in df.columns: df[f'SMA_{sma2}'] = df['Close'].rolling(sma2).mean()

        df, turnover_status, turnover_reason = apply_turnover_rate(df, share_base)
        if turnover_status != TURNOVER_STATUS_CALCULATED and (share_base is None or not (pd.notna(share_base) and float(share_base) > 0)):
            try:
                approx_base, approx_note = _resolve_share_base_post(df, yahoo_ticker)
                if approx_base is not None and approx_note and approx_note != "NO_VOLUME":
                    df, turnover_status, turnover_reason = apply_turnover_rate(df, approx_base)
                    share_base = approx_base
                    st.session_state[f"tor_approx_{current_code}"] = approx_note
            except Exception:
                pass
        has_turnover = turnover_status == TURNOVER_STATUS_CALCULATED
        if has_turnover:
            # 增加 v9.6 的 BS Analysis 計算
            df = simulate_bs_data(df, share_base)

        prev_close_series = df['Close'].shift(1).replace(0, np.nan)
        df['AMP'] = (df['High'] - df['Low']) / prev_close_series * 100

        for p in periods_sma: df[f'Sum_{p}'] = df['Volume'].rolling(p).sum()
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']

        # 1. 導航與圖表
        c_nav_prev, c_nav_mid, c_nav_next = st.columns([1, 4, 1])
        with c_nav_prev:
            if st.button("◀ 前一交易日", use_container_width=True):
                if len(df) >= 2:
                    st.session_state.ref_date = df.index[-2].date()
                    st.rerun()
        with c_nav_mid:
            st.markdown(f"<h3 style='text-align: center; margin: 0;'>基準日: {df.index[-1].strftime('%Y-%m-%d')}</h3>", unsafe_allow_html=True)
        with c_nav_next:
            if st.button("後一交易日 ▶", use_container_width=True):
                st.session_state.ref_date += timedelta(days=1)
                st.rerun()
        
        st.divider()

        def _last_valid(series):
            s = pd.to_numeric(series, errors="coerce").replace(0, np.nan).dropna()
            return float(s.iloc[-1]) if len(s) >= 1 else float("nan")

        def _nth_last_valid(series, n_from_last):
            s = pd.to_numeric(series, errors="coerce").replace(0, np.nan).dropna()
            idx = len(s) - 1 - n_from_last
            return float(s.iloc[idx]) if idx >= 0 else float("nan")

        curr_close = _last_valid(df["Close"])
        prev_close_raw = _nth_last_valid(df["Close"], 1)
        prev_close = prev_close_raw if pd.notna(prev_close_raw) else None
        curr_open = _last_valid(df["Open"]) if "Open" in df.columns else float("nan")
        curr_high = _last_valid(df["High"]) if "High" in df.columns else float("nan")
        curr_low = _last_valid(df["Low"]) if "Low" in df.columns else float("nan")

        has_prev_close = prev_close is not None and pd.notna(prev_close) and prev_close != 0
        chg = (curr_close - prev_close) if (pd.notna(curr_close) and has_prev_close) else float("nan")
        pct = (chg / prev_close * 100) if (pd.notna(chg) and has_prev_close) else float("nan")
        amp = ((curr_high - curr_low) / prev_close * 100) if (pd.notna(curr_high) and pd.notna(curr_low) and has_prev_close) else float("nan")

        def _fmt_price(v, decimals=3):
            if pd.isna(v):
                return "-"
            return f"{float(v):.{decimals}f}"

        def _fmt_signed(v, decimals=3, suffix=""):
            if pd.isna(v):
                return "-"
            return f"{float(v):+.{decimals}f}{suffix}"

        def _fmt_pct(v, decimals=2):
            if pd.isna(v):
                return "-"
            return f"{float(v):+.{decimals}f}%"

        def _chg_class(v):
            if not pd.notna(v):
                return ""
            return "pos" if v >= 0 else "neg"

        delta_cls = _chg_class(chg)
        summary_cards = f"""
        <div class="compact-grid">
            <div class="compact-card">
                <div class="label">現價</div>
                <div class="value">{_fmt_price(curr_close)}</div>
                <div class="sub {delta_cls}">{_fmt_signed(chg)} ({_fmt_pct(pct)})</div>
            </div>
            <div class="compact-card">
                <div class="label">前收市</div>
                <div class="value">{_fmt_price(prev_close) if has_prev_close else "-"}</div>
            </div>
            <div class="compact-card">
                <div class="label">開市</div>
                <div class="value">{_fmt_price(curr_open)}</div>
            </div>
            <div class="compact-card">
                <div class="label">波幅(AA)</div>
                <div class="value">{_fmt_pct(amp)}</div>
            </div>
            <div class="compact-card">
                <div class="label">最高</div>
                <div class="value">{_fmt_price(curr_high)}</div>
            </div>
            <div class="compact-card">
                <div class="label">最低</div>
                <div class="value">{_fmt_price(curr_low)}</div>
            </div>
        </div>
        """
        if show_header:
            st.markdown(summary_cards, unsafe_allow_html=True)

        end_date_dt = pd.to_datetime(st.session_state.ref_date)
        start_date_6m = end_date_dt - timedelta(days=180)
        display_df = df[df.index >= start_date_6m]

        fig_main = go.Figure()
        fig_main.add_trace(
            go.Candlestick(
                x=display_df.index,
                open=display_df["Open"],
                high=display_df["High"],
                low=display_df["Low"],
                close=display_df["Close"],
                name="K線",
            )
        )
        if "SMA_7" in display_df.columns:
            fig_main.add_trace(go.Scatter(x=display_df.index, y=display_df["SMA_7"], line=dict(color="orange"), name="SMA 7"))
        if "SMA_14" in display_df.columns:
            fig_main.add_trace(go.Scatter(x=display_df.index, y=display_df["SMA_14"], line=dict(color="blue"), name="SMA 14"))
        fig_main.update_layout(height=520, xaxis_rangeslider_visible=True, template="plotly_white", dragmode="pan", uirevision=f"main_price_{current_code}")
        if show_header:
            st.plotly_chart(fig_main, use_container_width=True, config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "responsive": True})

        render_scroll_anchor("stock-quick")
        if show_quick:
            st.markdown("**快速信號**")
        df_sig = df.tail(260).copy()
        df_sig["WR35"] = calculate_willr(df_sig["High"], df_sig["Low"], df_sig["Close"], 35)
        last_sig = df_sig.iloc[-1]

        val_sma7 = last_sig.get("SMA_7", np.nan)
        val_sma14 = last_sig.get("SMA_14", np.nan)
        val_wr35 = last_sig.get("WR35", np.nan)

        cond_above = (pd.notna(val_sma7) and pd.notna(val_sma14) and (curr_close > float(val_sma7)) and (curr_close > float(val_sma14)))
        cond_wr = (pd.notna(val_wr35) and (float(val_wr35) < -80))
        fzm_trigger = bool(cond_above and cond_wr)
        down6_trigger = is_consecutive_down(df_sig["Close"], 6)
        tor_down5_trigger = bool("Turnover_Rate" in df_sig.columns and is_consecutive_down(df_sig["Turnover_Rate"], 5))

        labels = ["Price", "SMA7", "SMA14", "SMA28", "SMA57", "SMA106", "SMA212"]
        vals = [
            float(curr_close),
            last_sig.get("SMA_7", np.nan),
            last_sig.get("SMA_14", np.nan),
            last_sig.get("SMA_28", np.nan),
            last_sig.get("SMA_57", np.nan),
            last_sig.get("SMA_106", np.nan),
            last_sig.get("SMA_212", np.nan),
        ]
        valid_vals = [float(v) for v in vals if pd.notna(v)]
        avg_of_avgs = (sum(valid_vals) / len(valid_vals)) if valid_vals else 0.0

        mr_count = 0
        mr_trigger = False
        mr_rows = []
        if avg_of_avgs:
            for label, v in zip(labels, vals):
                if pd.notna(v):
                    mr_val = (float(v) - avg_of_avgs) / avg_of_avgs * 100
                    if mr_val > 0.62:
                        mr_count += 1
                    mr_rows.append({"項目": label, "值": float(v), "MR(%)": mr_val})
            mr_trigger = mr_count >= 3

        signal_cards = f"""
        <div class="compact-grid">
            <div class="signal-card {'trigger' if fzm_trigger else 'idle'}">
                <div class="title">超底(FZM)：{'🔴 觸發' if fzm_trigger else '未觸發'}</div>
                <div class="meta">WR35: {'-' if pd.isna(val_wr35) else f'{float(val_wr35):.2f}'}</div>
                <div class="meta">SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}</div>
            </div>
            <div class="signal-card {'trigger' if mr_trigger else 'idle'}">
                <div class="title">振蕩(MR)：{'🔴 觸發' if mr_trigger else '未觸發'}</div>
                <div class="meta">{f'基準均價: {avg_of_avgs:.3f}' if avg_of_avgs else '基準均價: -'}</div>
                <div class="meta">高乖離數(>0.62%): {mr_count}</div>
            </div>
            <div class="signal-card {'trigger' if down6_trigger else 'idle'}">
                <div class="title">連跌6日：{'🔴 觸發' if down6_trigger else '未觸發'}</div>
                <div class="meta">最近 6 個交易日收市價連續下跌</div>
            </div>
            <div class="signal-card {'trigger' if tor_down5_trigger else 'idle'}">
                <div class="title">換手率連跌5日：{'🔴 觸發' if tor_down5_trigger else '未觸發'}</div>
                <div class="meta">最近 5 個交易日 TOR 連續下降</div>
            </div>
        </div>
        """
        if show_quick:
            st.markdown(signal_cards, unsafe_allow_html=True)
            if mr_rows:
                with st.expander("信號詳情", expanded=False):
                    st.dataframe(pd.DataFrame(mr_rows), hide_index=True, use_container_width=True)

        if show_data:
            render_scroll_anchor("stock-data")
            st.write("---")
            tab_data, tab_backtest = st.tabs(["📋 數據列表", "🧪 歷史回測"])
            with tab_data:
                # ---- L4 第 1 塊（批准 APP-20260829-001-PMAX6DEV）：Pmax(106) 20 固定格點 × Dev0~5 六欄 12 日時序雙層並排
                try:
                    pm6_matrix = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3,
                                                          dev_offsets=[0,1,2,3,4,5], recent_rows=12)
                    st.markdown("##### 🟩 Pmax 20 固定格點 × Dev0~5 六視角（D-2 · 批准版）")
                    render_pmax_index6_panel(pm6_matrix, prefix=f"p6desk_{current_code.replace('.','_')}_")
                except Exception as exc_p6:
                    st.info(f"Pmax 20×6 矩陣暫時無法計算：{type(exc_p6).__name__}: {str(exc_p6)[:160]}")
                st.write("")

                # ---- L4 第 1-b 塊（2026-09-02 COT 綠區 A + 綠區 B：5 TI 每日化速率 + U/D 趨勢點擇多數決）
                try:
                    cot5 = calc_cot_ti5_vector(df, ti_list=list(COT_5_FIXED_TI))
                    st.markdown("##### 🟩 COT 每日化股價變化速率 × 趨勢 U/D 點擇（5 TI={7,14,27,57,106}）")
                    render_cot_2blocks(cot5, prefix=f"cotdesk_{current_code.replace('.','_')}_")
                except Exception as exc_cot:
                    st.info(f"COT 5 TI 矩陣暫時無法計算：{type(exc_cot).__name__}: {str(exc_cot)[:160]}")
                st.write("")

                # ---- L4 第 2 塊：舊版 Sn 三元組 Dev 矩陣（可摺疊，避免資訊過載）
                with st.expander("🟩 Pmax / Sn 三元組偏差矩陣（舊版，可選查看）", expanded=False):
                    try:
                        pmax_dev_matrix = calc_pmax_dev_matrix(df, pmax_window=106, s_divisor=24,
                                                                s_min_num=3, s_max_num=9,
                                                                avg_window=3, num_rows=3)
                        render_pmax_dev_table(pmax_dev_matrix, prefix=f"d2desk_old_{current_code}_")
                    except Exception as exc_d2:
                        st.info(f"Sn 三元組 Dev 矩陣暫時無法計算：{type(exc_d2).__name__}: {str(exc_d2)[:120]}")
                st.write("")

                # ---- L4 第 3 塊：原始數據列表（最近 60 日；2026-09-02 格式校準：YYMMDD；Close→CP；TUR3小數；Amp→Amp 2小數）
                display_df = df.copy().tail(60).reset_index()
                date_col = display_df.columns[0]
                display_df["Date"] = pd.to_datetime(display_df[date_col]).dt.strftime("%y%m%d")
                if date_col != "Date":
                    display_df = display_df.drop(columns=[date_col])

                rename_map = {
                    "Close": "CP",
                    "Turnover_Rate": "TUR",
                    "AMP": "Amp",
                }
                show_cols = [c for c in ["Date", "Close", "Turnover_Rate", "AMP"] if c in display_df.columns]
                if show_cols:
                    display_df = display_df[show_cols].rename(columns=rename_map)
                    if "TUR" in display_df.columns:
                        display_df["TUR"] = pd.to_numeric(display_df["TUR"], errors="coerce").round(3)
                    if "Amp" in display_df.columns:
                        display_df["Amp"] = pd.to_numeric(display_df["Amp"], errors="coerce").round(2)
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.info("無可顯示欄位。")
            with tab_backtest:
                render_backtest_page(df, current_code, watchlist_data)

        if show_interactive:
            render_scroll_anchor("stock-interactive")
            with st.expander("互動模式控制區", expanded=True):
                min_date = df.index.min().date() if len(df) else st.session_state.ref_date
                max_date = df.index.max().date() if len(df) else st.session_state.ref_date
                default_end = max_date
                default_start = default_end - timedelta(days=90)
                if default_start < min_date:
                    default_start = min_date

                c_range_1, c_range_2 = st.columns(2)
                with c_range_1:
                    range_start = st.date_input(
                        "開始日期",
                        value=default_start,
                        min_value=min_date,
                        max_value=max_date,
                        key=f"interactive_range_start_{current_code}",
                    )
                with c_range_2:
                    range_end = st.date_input(
                        "結束日期",
                        value=default_end,
                        min_value=min_date,
                        max_value=max_date,
                        key=f"interactive_range_end_{current_code}",
                    )

                if range_start > range_end:
                    range_start, range_end = range_end, range_start

                df_range = df[(df.index >= pd.to_datetime(range_start)) & (df.index <= pd.to_datetime(range_end))].copy()

                st.markdown("**A-B-C 調整浪 / 二次探底 預測器**")

                def align_to_prev_trading_day(d):
                    ts = pd.to_datetime(d)
                    idx = df.index[df.index <= ts]
                    return idx.max() if len(idx) else None

                default_date_p1_start = range_start
                default_date_p1_end = min(range_start + timedelta(days=30), range_end)
                default_date_p2_end = range_end

                c_abc_d1, c_abc_d2 = st.columns(2)
                with c_abc_d1:
                    date_p1_start = st.date_input(
                        "P1 起跌點日期",
                        value=default_date_p1_start,
                        min_value=min_date,
                        max_value=max_date,
                        key=f"abc_date_p1_start_{current_code}",
                    )
                with c_abc_d2:
                    date_p1_end = st.date_input(
                        "P1 止跌點日期",
                        value=default_date_p1_end,
                        min_value=min_date,
                        max_value=max_date,
                        key=f"abc_date_p1_end_{current_code}",
                    )

                date_p2_end = st.date_input(
                    "P2 反彈結束日期",
                    value=default_date_p2_end,
                    min_value=min_date,
                    max_value=max_date,
                    key=f"abc_date_p2_end_{current_code}",
                )

                p1_start_ts = align_to_prev_trading_day(date_p1_start)
                p1_end_ts = align_to_prev_trading_day(date_p1_end)
                p2_end_ts = align_to_prev_trading_day(date_p2_end)

                if (p1_start_ts is None) or (p1_end_ts is None) or (p2_end_ts is None):
                    st.warning("所選日期找不到對應交易日，請調整日期")
                else:
                    st.write(
                        f"實際採用交易日：P1_start={p1_start_ts.date()}，P1_end={p1_end_ts.date()}，P2_end={p2_end_ts.date()}"
                    )

                    price_p1_high_auto = float(df.loc[p1_start_ts, "High"]) if p1_start_ts in df.index else np.nan
                    price_p1_low_auto = float(df.loc[p1_end_ts, "Low"]) if p1_end_ts in df.index else np.nan

                    price_p2_high_auto = np.nan
                    if p1_end_ts <= p2_end_ts:
                        p2_slice = df.loc[p1_end_ts:p2_end_ts]
                        if not p2_slice.empty and "High" in p2_slice.columns:
                            price_p2_high_auto = float(p2_slice["High"].max())

                    c_abc_p1, c_abc_p2, c_abc_p3 = st.columns(3)
                    with c_abc_p1:
                        price_p1_high = st.number_input(
                            "P1 起跌點價格 (High)",
                            value=float(price_p1_high_auto) if pd.notna(price_p1_high_auto) else 0.0,
                            min_value=0.0,
                            format="%.3f",
                            key=f"abc_price_p1_high_{current_code}",
                        )
                    with c_abc_p2:
                        price_p1_low = st.number_input(
                            "P1 止跌點價格 (Low)",
                            value=float(price_p1_low_auto) if pd.notna(price_p1_low_auto) else 0.0,
                            min_value=0.0,
                            format="%.3f",
                            key=f"abc_price_p1_low_{current_code}",
                        )
                    with c_abc_p3:
                        price_p2_high = st.number_input(
                            "P2 反彈最高價格 (P1_end~P2_end 高點)",
                            value=float(price_p2_high_auto) if pd.notna(price_p2_high_auto) else 0.0,
                            min_value=0.0,
                            format="%.3f",
                            key=f"abc_price_p2_high_{current_code}",
                        )

                    delta_t = (p1_end_ts.date() - p1_start_ts.date()).days
                    delta_p = float(price_p1_high) - float(price_p1_low)
                    price_p1_avg = (float(price_p1_high) + float(price_p1_low)) / 2.0

                    c_abc_m1, c_abc_m2, c_abc_m3 = st.columns(3)
                    c_abc_m1.metric("P1 天數 delta_t", "-" if delta_t <= 0 else f"{delta_t}")
                    c_abc_m2.metric("P1 跌幅 delta_p", "-" if delta_p <= 0 else f"{delta_p:.3f}")
                    c_abc_m3.metric("P1 均價 avg", "-" if delta_t <= 0 else f"{price_p1_avg:.3f}")

                    if delta_t <= 0:
                        st.error("日期順序錯誤：P1 止跌點日期必須晚於 P1 起跌點日期")
                    elif delta_p <= 0:
                        st.error("價格順序錯誤：P1 起跌點價格必須大於 P1 止跌點價格")
                    else:
                        ratios = [("A", 0.618), ("B", 1.0), ("C", 1.618)]
                        rows = []
                        for scenario, r in ratios:
                            n_days = int(round(delta_t * r))
                            target_date_cal = p2_end_ts.date() + timedelta(days=n_days)
                            target_date_trade_ts = align_to_prev_trading_day(target_date_cal)
                            target_date_trade = target_date_trade_ts.date().isoformat() if target_date_trade_ts is not None else "-"
                            target_price = float(price_p2_high) - (delta_p * r)
                            rows.append(
                                {
                                    "情境": scenario,
                                    "比例": r,
                                    "預測天數": n_days,
                                    "見底日期(曆)": target_date_cal.isoformat(),
                                    "見底日期(交易)": target_date_trade,
                                    "見底價格": target_price,
                                }
                            )

                        out_df = pd.DataFrame(rows)
                        out_df["見底價格"] = out_df["見底價格"].map(lambda x: f"{float(x):.3f}")
                        st.dataframe(out_df, hide_index=True, use_container_width=True)

            # 2. CDM 設定
            if is_in_watchlist:
                with st.expander("⚙️ 設定 CDM 自動檢測參數", expanded=False):
                    curr_params = watchlist_data.get(current_code, {})

                    def _pdate(key):
                        v = curr_params.get(key)
                        try:
                            return pd.to_datetime(v).date() if v else None
                        except Exception:
                            return None

                    def _pfloat(key):
                        try:
                            v = curr_params.get(key)
                            if v is None:
                                return 0.0
                            if isinstance(v, str) and (not v.strip()):
                                return 0.0
                            return float(v)
                        except Exception:
                            return 0.0

                    def align_to_prev_trading_day(d):
                        ts = pd.to_datetime(d)
                        idx = df.index[df.index <= ts]
                        return idx.max() if len(idx) else None

                    min_d = df.index.min().date()
                    max_d = df.index.max().date()

                    def clamp_date(d):
                        if d is None:
                            return None
                        if d < min_d:
                            return min_d
                        if d > max_d:
                            return max_d
                        return d

                    default_range_start = clamp_date(max_d - timedelta(days=90))
                    default_range_end = max_d
                    default_p1_start = clamp_date(max_d - timedelta(days=120))
                    default_p1_end = clamp_date(max_d - timedelta(days=60))

                    st.markdown("**互動區間**")
                    c_rng_1, c_rng_2 = st.columns(2)
                    with c_rng_1:
                        saved_range_start = clamp_date(_pdate("interactive_range_start"))
                        new_range_start = st.date_input(
                            "開始日期",
                            value=saved_range_start or default_range_start,
                            min_value=min_d,
                            max_value=max_d,
                            key=f"cdm_range_start_{current_code}",
                        )
                    with c_rng_2:
                        saved_range_end = clamp_date(_pdate("interactive_range_end"))
                        new_range_end = st.date_input(
                            "結束日期",
                            value=saved_range_end or default_range_end,
                            min_value=min_d,
                            max_value=max_d,
                            key=f"cdm_range_end_{current_code}",
                        )

                    if new_range_start > new_range_end:
                        new_range_start, new_range_end = new_range_end, new_range_start

                    st.markdown("**P1 / P2 波段輸入（用於 CDM 與 ABC）**")
                    c_d1, c_d2 = st.columns(2)
                    with c_d1:
                        saved_p1_start = clamp_date(_pdate("abc_date_p1_start"))
                        new_date_p1_start = st.date_input(
                            "P1 起跌點日期",
                            value=saved_p1_start or default_p1_start,
                            min_value=min_d,
                            max_value=max_d,
                            key=f"cdm_abc_p1_start_{current_code}",
                        )
                    with c_d2:
                        saved_p1_end = clamp_date(_pdate("abc_date_p1_end"))
                        new_date_p1_end = st.date_input(
                            "P1 止跌點日期",
                            value=saved_p1_end or default_p1_end,
                            min_value=min_d,
                            max_value=max_d,
                            key=f"cdm_abc_p1_end_{current_code}",
                        )

                    new_date_p2_end = st.date_input(
                        "P2 反彈結束日期",
                        value=_pdate("abc_date_p2_end") or df.index.max().date(),
                        min_value=df.index.min().date(),
                        max_value=df.index.max().date(),
                        key=f"cdm_abc_p2_end_{current_code}",
                    )

                    p1_start_ts = align_to_prev_trading_day(new_date_p1_start)
                    p1_end_ts = align_to_prev_trading_day(new_date_p1_end)
                    p2_end_ts = align_to_prev_trading_day(new_date_p2_end)

                    if (p1_start_ts is None) or (p1_end_ts is None) or (p2_end_ts is None):
                        st.warning("所選日期找不到對應交易日，請調整日期")

                    price_p1_high_auto = float(df.loc[p1_start_ts, "High"]) if (p1_start_ts is not None and p1_start_ts in df.index) else 0.0
                    price_p1_low_auto = float(df.loc[p1_end_ts, "Low"]) if (p1_end_ts is not None and p1_end_ts in df.index) else 0.0

                    price_p2_high_auto = 0.0
                    if (p1_end_ts is not None) and (p2_end_ts is not None) and (p1_end_ts <= p2_end_ts):
                        p2_slice = df.loc[p1_end_ts:p2_end_ts]
                        if (not p2_slice.empty) and ("High" in p2_slice.columns):
                            price_p2_high_auto = float(p2_slice["High"].max())

                    c_p1, c_p2, c_p3 = st.columns(3)
                    with c_p1:
                        new_price_p1_high = st.number_input(
                            "P1 起跌點價格 (High)",
                            value=_pfloat("abc_price_p1_high") or price_p1_high_auto,
                            min_value=0.0,
                            format="%.3f",
                            key=f"cdm_abc_price_p1_high_{current_code}",
                        )
                    with c_p2:
                        new_price_p1_low = st.number_input(
                            "P1 止跌點價格 (Low)",
                            value=_pfloat("abc_price_p1_low") or price_p1_low_auto,
                            min_value=0.0,
                            format="%.3f",
                            key=f"cdm_abc_price_p1_low_{current_code}",
                        )
                    with c_p3:
                        new_price_p2_high = st.number_input(
                            "P2 反彈最高價格 (P1_end~P2_end 高點)",
                            value=_pfloat("abc_price_p2_high") or price_p2_high_auto,
                            min_value=0.0,
                            format="%.3f",
                            key=f"cdm_abc_price_p2_high_{current_code}",
                        )

                    p1_avg_calc = 0.0
                    p2_avg_calc = 0.0
                    if (p1_start_ts is not None) and (p1_end_ts is not None) and (p1_start_ts <= p1_end_ts):
                        p1_avg_calc = float(df.loc[p1_start_ts:p1_end_ts]["Close"].mean())
                    if (p1_end_ts is not None) and (p2_end_ts is not None) and (p1_end_ts <= p2_end_ts):
                        p2_avg_calc = float(df.loc[p1_end_ts:p2_end_ts]["Close"].mean())

                    c_avg_1, c_avg_2 = st.columns(2)
                    with c_avg_1:
                        st.metric("P1 均價(計算)", "-" if not p1_avg_calc else f"{p1_avg_calc:.3f}")
                        new_cdm_p1_avg_override = st.number_input(
                            "P1 均價(手動覆蓋, 0=不用)",
                            value=_pfloat("cdm_p1_avg_override"),
                            min_value=0.0,
                            format="%.3f",
                            key=f"cdm_p1_avg_override_{current_code}",
                        )
                    with c_avg_2:
                        st.metric("P2 均價(計算)", "-" if not p2_avg_calc else f"{p2_avg_calc:.3f}")
                        new_cdm_p2_avg_override = st.number_input(
                            "P2 均價(手動覆蓋, 0=不用)",
                            value=_pfloat("cdm_p2_avg_override"),
                            min_value=0.0,
                            format="%.3f",
                            key=f"cdm_p2_avg_override_{current_code}",
                        )

                    if st.button("💾 儲存參數", key=f"save_cdm_{current_code}"):
                        box1_start = str(new_date_p1_start)
                        box1_end = str(new_date_p1_end)
                        box2_start = str(new_date_p1_end)
                        box2_end = str(new_date_p2_end)

                        if update_stock_in_db(
                            current_code,
                            {
                                "interactive_range_start": str(new_range_start),
                                "interactive_range_end": str(new_range_end),
                                "abc_date_p1_start": str(new_date_p1_start),
                                "abc_date_p1_end": str(new_date_p1_end),
                                "abc_date_p2_end": str(new_date_p2_end),
                                "abc_price_p1_high": float(new_price_p1_high),
                                "abc_price_p1_low": float(new_price_p1_low),
                                "abc_price_p2_high": float(new_price_p2_high),
                                "cdm_p1_avg_override": float(new_cdm_p1_avg_override),
                                "cdm_p2_avg_override": float(new_cdm_p2_avg_override),
                                "box1_start": box1_start,
                                "box1_end": box1_end,
                                "box2_start": box2_start,
                                "box2_end": box2_end,
                            },
                        ):
                            st.rerun()


        # --- D. 數據呈現 ---
        req_len = min(13, len(df))
        if req_len < 2:
            st.warning("數據長度不足")
        else:
            data_slice = df.iloc[-req_len:][::-1]
            
            # 1. Curve
            curve_data = df.iloc[-7:]
            fig_sma_trend = go.Figure()
            colors_map = {7: '#FF6B6B', 14: '#FFA500', 28: '#FFD700', 57: '#4CAF50', 106: '#2196F3', 212: '#9C27B0'}
            for p in periods_sma:
                col_name = f'SMA_{p}'
                if col_name in curve_data.columns:
                    fig_sma_trend.add_trace(go.Scatter(x=curve_data.index, y=curve_data[col_name], mode='lines', name=f"SMA({p})", line=dict(color=colors_map.get(p, 'grey'), width=2)))
            fig_sma_trend.update_layout(height=350, margin=dict(l=10, r=10, t=30, b=10), title="SMA 曲線 (近7個交易日)", template="plotly_white", legend=dict(orientation="h", y=1.1), dragmode="pan", uirevision=f"sma_trend_{current_code}")
            if show_sma_line:
                render_scroll_anchor("stock-sma-line")
                st.plotly_chart(fig_sma_trend, use_container_width=True, config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "responsive": True})

           # 2. SMA Matrix (New Format v10.0)
            if show_sma_matrix:
                render_scroll_anchor("stock-sma-matrix")
                st.subheader("📋 SMA Matrix")
            
            # 定義列與對應的 Interval
            matrix_intervals = [7, 14, 28, 57, 106, 212]
            headers = ["2", "3", "4", "5", "6", "7"] # 對應 Day 2 - Day 7
            
            # 預先計算需要的數據，存入字典以利後續提取
            matrix_data = {}
            current_close = df['Close'].iloc[-1]
            
            for p in matrix_intervals:
                col = f'SMA_{p}'
                if col in df.columns:
                    series = df[col].tail(14).dropna()
                    val_curr = df[col].iloc[-1]
                    val_curr = float(val_curr) if pd.notna(val_curr) else 0.0
                    val_max = float(series.max()) if len(series) else 0.0
                    val_min = float(series.min()) if len(series) else 0.0
                    # SMAC (%) = (股價 - SMA) / SMA
                    smac_val = ((current_close - val_curr) / val_curr) * 100 if val_curr else 0.0
                else:
                    val_curr = val_max = val_min = smac_val = 0.0
                
                matrix_data[p] = {
                    "max": val_max,
                    "min": val_min,
                    "sma": val_curr,
                    "smac": smac_val
                }

            # 構建 HTML 表格
            sma_html = '<table class="big-font-table">'
            sma_html += '<thead><tr><th>Day</th>' + "".join([f"<th>{h}</th>" for h in headers]) + '</tr></thead><tbody>'
            sma_html += '<tr><td><b>P</b></td>' + "".join([f"<td>SMA {p}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Interval</b></td>' + "".join([f"<td>{p}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Max</b></td>' + "".join([f"<td>{matrix_data[p]['max']:.2f}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Min</b></td>' + "".join([f"<td>{matrix_data[p]['min']:.2f}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>SMA</b></td>' + "".join([f"<td><b>{matrix_data[p]['sma']:.2f}</b></td>" for p in matrix_intervals]) + '</tr>'
            
            # SMAC Rows
            sma_html += '<tr><td><b>SMAC (%)</b></td>'
            for p in matrix_intervals:
                val = matrix_data[p]['smac']
                color_class = 'pos-val' if val > 0 else 'neg-val'
                sma_html += f'<td class="{color_class}">{val:.2f}%</td>'
            sma_html += '</tr>'
            
            # SMAC Differences
            base_smas = {14: matrix_data[14]['sma'], 28: matrix_data[28]['sma'], 57: matrix_data[57]['sma']}
            for base_p, base_val in base_smas.items():
                sma_html += f'<tr><td><b>SMAC{base_p} (%)</b></td>'
                for p in matrix_intervals:
                    curr_sma = matrix_data[p]['sma']
                    if base_val and curr_sma and pd.notna(base_val) and pd.notna(curr_sma):
                        val = ((curr_sma - base_val) / base_val) * 100
                        color_class = 'pos-val' if val > 0 else 'neg-val'
                        sma_html += f'<td class="{color_class}">{val:.2f}%</td>'
                    else:
                        sma_html += '<td>-</td>'
                sma_html += '</tr>'

            sma_html += "</tbody></table>"
            if show_sma_matrix:
                st.markdown(sma_html, unsafe_allow_html=True)
            
          # --- NEW: Price Interface Data List (修正版) ---
            st.write("") # Spacer
            
            # ==========================================
            # A. Price (AvgP) 計算
            # ==========================================
            # Avg0 = Close, Avg1-6 = SMA [7, 14, 28, 57, 106, 212]
            avgp_vals = [current_close] # Avg0
            for p in matrix_intervals:
                val = matrix_data[p]['sma'] if matrix_data[p]['sma'] else 0.0
                avgp_vals.append(val)
            
            # 計算 Avg(AvgP) = (Avg0 + ... + Avg6) / 7
            valid_avgp_vals = [v for v in avgp_vals if v and v > 0]
            avg_avg_p = (sum(valid_avgp_vals) / len(valid_avgp_vals)) if valid_avgp_vals else 0.0
            
            # 計算 AvgP MR = (AvgP / Avg) - 1
            # 包含 AvgP MR0 到 AvgP MR6
            avgp_mr_vals = []
            for v in avgp_vals:
                if avg_avg_p != 0 and v:
                    # 數學上 (v - avg) / avg 等同於 (v / avg) - 1
                    mr = (v / avg_avg_p) - 1
                else:
                    mr = 0
                avgp_mr_vals.append(mr * 100) # 轉百分比
            
            valid_avgp_mr_vals = [abs(v) for v in avgp_mr_vals if pd.notna(v)]
            avg_avgp_mr_total = (sum(valid_avgp_mr_vals) / len(valid_avgp_mr_vals)) if valid_avgp_mr_vals else 0.0

            # ==========================================
            # B. AMP (Amplitude) 計算 (修正公式)
            # ==========================================
            prev_close_series = df['Close'].shift(1).replace(0, np.nan)
            df['AMP'] = (df['High'] - df['Low']) / prev_close_series * 100
            
            # 1. 準備 AMP0 (當日)
            val_amp0 = df['AMP'].iloc[-1]
            val_amp0 = float(val_amp0) if pd.notna(val_amp0) else 0.0
            
            # 2. 準備 AMP1 ~ AMP6 (對應 SMA 週期的歷史平均振幅)
            amp_rolling_vals = [] 
            for p in matrix_intervals:
                # 計算過去 p 天的 AMP 平均值
                val = df['AMP'].rolling(p).mean().iloc[-1]
                amp_rolling_vals.append(float(val) if pd.notna(val) else 0.0)
            
            # 3. 計算 AVG Amp (根據圖片公式)
            # 公式：AVG Amp = (Amp1 + Amp2 + Amp3 + Amp4 + Amp5 + Amp6) / 6
            # ⚠️ 關鍵修正：排除 AMP0
            valid_rolling = [v for v in amp_rolling_vals if v and v > 0]
            avg_amp = (sum(valid_rolling) / len(valid_rolling)) if valid_rolling else 0.0
            
            # 4. 計算 AMP MR
            # 公式：MR = (AMPn / AVG Amp) - 1
            amp_mr_vals = []
            
            # 4a. 計算 AMP MR0 (AMP0 / Avg - 1)
            if avg_amp != 0:
                mr0 = (val_amp0 / avg_amp) - 1
            else:
                mr0 = 0
            amp_mr_vals.append(mr0 * 100)
            
            # 4b. 計算 AMP MR1 ~ MR6
            for v in amp_rolling_vals:
                if avg_amp != 0 and v:
                    mr = (v / avg_amp) - 1
                else:
                    mr = 0
                amp_mr_vals.append(mr * 100)

            # 5. 整合顯示數據
            # AvgP 部分
            row1_headers = ["Avg(AvgP)", "Avg0", "Avg1", "Avg2", "Avg3", "Avg4", "Avg5", "Avg6"]
            row1_data = [avg_avg_p] + avgp_vals
            
            row2_headers = ["AvgP MR", "AvgP MR0", "AvgP MR1", "AvgP MR2", "AvgP MR3", "AvgP MR4", "AvgP MR5", "AvgP MR6"]
            row2_data = [avg_avgp_mr_total] + avgp_mr_vals

            # AMP 部分
            # 注意：列表順序為 [平均值, AMP0, AMP1...AMP6]
            row3_headers = ["Avg(AMP)", "AMP0", "AMP1", "AMP2", "AMP3", "AMP4", "AMP5", "AMP6"]
            row3_data = [avg_amp] + [val_amp0] + amp_rolling_vals
            
            # MR 部分：列表順序為 [MR總平均(自訂), MR0, MR1...MR6]
            avg_amp_mr_total = sum(amp_mr_vals) / len(amp_mr_vals)
            row4_headers = ["AMP MR", "AMP MR0", "AMP MR1", "AMP MR2", "AMP MR3", "AMP MR4", "AMP MR5", "AMP MR6"]
            row4_data = [avg_amp_mr_total] + amp_mr_vals

            # ==========================================
            # C. 渲染 HTML 表格
            # ==========================================
            pi_html = '<table class="big-font-table" style="margin-top: 20px;">'
            
            # Title
            pi_html += '<tr><td colspan="8" class="section-title">Price 界面 數據列表</td></tr>'
            
            # Row 1: AvgP Data (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row1_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}</td>" for d in row1_data]) + '</tr>'
            
            # Row 2: AvgP MR (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row2_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}%</td>" for d in row2_data]) + '</tr>'
            
            # Row 3: AMP Data (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row3_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}</td>" for d in row3_data]) + '</tr>'

            # Row 4: AMP MR (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row4_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}%</td>" for d in row4_data]) + '</tr>'
            
            pi_html += '</table>'
            if show_price_interface:
                render_scroll_anchor("stock-price-interface")
                st.markdown(pi_html, unsafe_allow_html=True)

            # 3. Turnover Matrix (此行不用複製，已存在於你的代碼下方)


            # 3. Turnover Matrix
            if show_turnover:
                render_scroll_anchor("stock-turnover")
                st.subheader("📋 Turnover Rate Matrix")
                if not has_turnover:
                    reason_text = turnover_reason or "無法取得有效的 share base。"
                    st.error(f"無法計算 Turnover Rate：{reason_text}")
                elif len(data_slice) < 13:
                    st.warning("數據不足 13 個交易日，無法顯示 Turnover Matrix。")
                else:
                    dates_d2_d7 = [data_slice.index[i].strftime('%m-%d') for i in range(1, 7)]
                    vals_d2_d7 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(1, 7)]
                    dates_d8_d13 = [data_slice.index[i].strftime('%m-%d') for i in range(7, 13)]
                    vals_d8_d13 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(7, 13)]
                    intervals_tor = [7, 14, 28, 57, 106, 212]
                    sums = [f"{df['Turnover_Rate'].tail(p).sum():.2f}%" for p in intervals_tor]
                    maxs = [f"{df['Turnover_Rate'].tail(p).max():.2f}%" for p in intervals_tor]
                    mins = [f"{df['Turnover_Rate'].tail(p).min():.2f}%" for p in intervals_tor]
                    avgs = [f"{df['Turnover_Rate'].tail(p).mean():.2f}%" for p in intervals_tor]
                    avg_tor_7 = f"{df['Turnover_Rate'].mean():.2f}%"
                    tor_html = '<table class="big-font-table">'
                    tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 2<br><small>{dates_d2_d7[0]}</small></th><th>Day 3<br><small>{dates_d2_d7[1]}</small></th><th>Day 4<br><small>{dates_d2_d7[2]}</small></th><th>Day 5<br><small>{dates_d2_d7[3]}</small></th><th>Day 6<br><small>{dates_d2_d7[4]}</small></th><th>Day 7<br><small>{dates_d2_d7[5]}</small></th></tr>'
                    tor_html += f'<tr><td>{vals_d2_d7[0]}</td><td>{vals_d2_d7[1]}</td><td>{vals_d2_d7[2]}</td><td>{vals_d2_d7[3]}</td><td>{vals_d2_d7[4]}</td><td>{vals_d2_d7[5]}</td></tr>'
                    tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 8<br><small>{dates_d8_d13[0]}</small></th><th>Day 9<br><small>{dates_d8_d13[1]}</small></th><th>Day 10<br><small>{dates_d8_d13[2]}</small></th><th>Day 11<br><small>{dates_d8_d13[3]}</small></th><th>Day 12<br><small>{dates_d8_d13[4]}</small></th><th>Day 13<br><small>{dates_d8_d13[5]}</small></th></tr>'
                    tor_html += f'<tr><td>{vals_d8_d13[0]}</td><td>{vals_d8_d13[1]}</td><td>{vals_d8_d13[2]}</td><td>{vals_d8_d13[3]}</td><td>{vals_d8_d13[4]}</td><td>{vals_d8_d13[5]}</td></tr></table><br>'
                    tor_html += '<table class="big-font-table"><tr style="background-color: #ffe0b2;"><th>Metrics</th>' + "".join([f"<th>Int: {p}</th>" for p in intervals_tor]) + '</tr>'
                    tor_html += f'<tr><td><b>Sum(TOR)</b></td>' + "".join([f"<td>{v}</td>" for v in sums]) + '</tr>'
                    tor_html += f'<tr><td><b>Max</b></td>' + "".join([f"<td>{v}</td>" for v in maxs]) + '</tr>'
                    tor_html += f'<tr><td><b>Min</b></td>' + "".join([f"<td>{v}</td>" for v in mins]) + '</tr>'
                    tor_html += f'<tr style="background-color: #c8e6c9;"><td><b>AVG Label</b></td><td>AVGTOR 1</td><td>AVGTOR 2</td><td>AVGTOR 3</td><td>AVGTOR 4</td><td>AVGTOR 5</td><td>AVGTOR 6</td></tr>'
                    tor_html += f'<tr><td><b>AVGTOR</b></td>' + "".join([f"<td>{v}</td>" for v in avgs]) + '</tr></table>'
                    tor_html += f'<table class="big-font-table" style="margin-top: 10px;"><tr style="background-color: #c8e6c9;"><th style="width:50%">AVGTOR 7 (Total Average)</th><th style="width:50%">Data</th></tr><tr><td>{avg_tor_7}</td><td>{avg_tor_7}</td></tr></table>'
                    st.markdown(tor_html, unsafe_allow_html=True)

    if show_cdm:
        render_scroll_anchor("stock-cdm")
        st.markdown("---")
        st.markdown("### 📈 CDM 目標價偏差(%)")

    curr_params = watchlist_data.get(current_code, {})

    def _pfloat(v):
        try:
            if v is None:
                return 0.0
            if isinstance(v, str) and (not v.strip()):
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    band2_peak = _pfloat(curr_params.get("abc_price_p2_high"))

    b1_s = curr_params.get("box1_start")
    b1_e = curr_params.get("box1_end")
    b2_s = curr_params.get("box2_start")
    b2_e = curr_params.get("box2_end")

    if not band2_peak:
        if show_cdm:
            st.info("請先到『⚙️ 設定 CDM 自動檢測參數』輸入 Band2 峰值價格（P2 反彈最高價格），才會顯示 CDM 偏差曲線與列表。")
    elif not (b1_s and b1_e and b2_s and b2_e):
        if show_cdm:
            st.info("請先完成 CDM 的 Box 1/Box 2 日期設定，才會顯示 CDM 偏差曲線與列表。")
    else:
        try:
            s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
            s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)

            sma1 = df[(df.index >= s1) & (df.index <= e1)]["Close"].mean()
            sma2 = df[(df.index >= s2) & (df.index <= e2)]["Close"].mean()
            t1_days = (e1 - s1).days

            last_14 = df.tail(14).copy()
            rows = []
            for d, r in last_14.iterrows():
                n_days = (pd.to_datetime(d) - s1).days
                actual = float(r["Close"]) if pd.notna(r.get("Close")) else np.nan
                if (n_days <= 0) or (not actual) or pd.isna(actual):
                    continue

                p_target = (sma1 * 0.7 * (t1_days / n_days)) + (sma2 * 0.5 * ((n_days - t1_days) / n_days))
                diff_pct = (p_target - actual) / actual * 100

                rows.append(
                    {
                        "日期": pd.to_datetime(d).date().isoformat(),
                        "實際價": actual,
                        "計算價": float(p_target) if pd.notna(p_target) else np.nan,
                        "偏差(%)": float(diff_pct) if pd.notna(diff_pct) else np.nan,
                    }
                )

            if not rows:
                if show_cdm:
                    st.warning("近 14 天無法計算（可能是 Box1 起點太新或資料不足）。")
            else:
                out_df = pd.DataFrame(rows)
                out_df["實際價"] = out_df["實際價"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.3f}")
                out_df["計算價"] = out_df["計算價"].map(lambda x: "-" if pd.isna(x) else f"{float(x):.3f}")
                out_df["偏差(%)"] = out_df["偏差(%)"].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}%")

                fig_cdm = go.Figure()
                fig_cdm.add_trace(
                    go.Scatter(
                        x=pd.to_datetime(out_df["日期"]),
                        y=pd.to_numeric(out_df["偏差(%)"].str.replace("%", ""), errors="coerce"),
                        mode="lines+markers",
                        name="(計算-實際)/實際",
                    )
                )
                fig_cdm.update_layout(
                    height=360,
                    template="plotly_white",
                    dragmode="pan",
                    uirevision=f"cdm_diff_{current_code}",
                    margin=dict(l=10, r=10, t=30, b=10),
                    yaxis_title="%",
                )
                fig_cdm.update_xaxes(rangeslider_visible=False)

                if show_cdm:
                    st.plotly_chart(
                        fig_cdm,
                        use_container_width=True,
                        config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "responsive": True},
                    )
                    st.dataframe(out_df, hide_index=True, use_container_width=True)
        except Exception as e:
            if show_cdm:
                st.error(str(e))

if current_page != "home_detail":
    render_bottom_navigation()
consume_pending_scroll_anchor()
