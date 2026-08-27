import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os
import time as _time_mod
import random as _rand_mod
from pathlib import Path
from tempfile import gettempdir
from typing import Dict, Any, Optional, List
from firebase_admin.exceptions import FirebaseError
from providers import CSVShareBaseProvider, CompositeShareBaseProvider, YahooShareBaseProvider
from turnover_utils import TURNOVER_STATUS_CALCULATED, apply_turnover_rate
from watchlist_storage import (
    delete_watchlist_symbol,
    get_watchlist_from_firestore,
    save_watchlist_symbol,
)

# ===== [改动1] 导入移动端优化工具 =====
from mobile_optimizer import (
    setup_page, 
    action_buttons, 
    responsive_cols, 
    responsive_table,
    responsive_chart,
    init_mobile_optimizer
)

# ===== [改动2] 页面初始化 (替代 st.set_page_config) =====
setup_page(
    title="港股 SMA 矩陣 v9.7",
    icon="📈",
    layout="auto",
    initial_sidebar_state="auto"
)

optimizer = init_mobile_optimizer()
is_mobile = st.session_state.get('is_mobile', False)

# yfinance crumb 穩定化：指定 TZ cache 到可寫 temp 目錄 + 升級 session UA
try:
    _yf_tz_dir_m = Path(gettempdir()) / "hk_stock_sma_yf_tzcache_m"
    _yf_tz_dir_m.mkdir(parents=True, exist_ok=True)
    try:
        yf.set_tz_cache_location(str(_yf_tz_dir_m))
    except Exception:
        pass
except Exception:
    pass
_YF_UAS_M = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
]

# yfinance session 共享管理器 + 錯誤黑名單 (連續失敗 2 次後 M 秒內不重試)
class _YFSessionManager_M:
    def __init__(self):
        self._sessions = []
        self._last_refresh = 0.0
        self._error_count: Dict[str, int] = {}
        self._error_until: Dict[str, float] = {}
        self._lock = None
        try:
            import threading as _th_m
            self._lock = _th_m.RLock()
        except Exception:
            self._lock = None

    def _acquire(self):
        if self._lock is not None:
            self._lock.acquire()

    def _release(self):
        if self._lock is not None:
            self._lock.release()

    def _maybe_refresh_sessions(self):
        now = _time_mod.time()
        if self._sessions and (now - self._last_refresh) < 600:
            return
        new_sessions = []
        try:
            for ua in _YF_UAS_M:
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
                yf_sess_getter = getattr(yf, "_get_session", None)
                if callable(yf_sess_getter):
                    try:
                        cur = yf_sess_getter()
                        if cur is not None and new_sessions:
                            cur.headers.update(new_sessions[0].headers)
                    except Exception:
                        pass
        except Exception:
            pass

    def should_skip(self, ticker):
        self._acquire()
        try:
            until = self._error_until.get(ticker, 0.0)
            if until and _time_mod.time() < until:
                return True
            return False
        finally:
            self._release()

    def get_session(self):
        self._acquire()
        try:
            self._maybe_refresh_sessions()
            if self._sessions:
                return self._sessions[_rand_mod.randint(0, len(self._sessions) - 1)]
            return None
        finally:
            self._release()

    def record_success(self, ticker):
        self._acquire()
        try:
            self._error_count[ticker] = 0
            self._error_until.pop(ticker, None)
        finally:
            self._release()

    def record_failure(self, ticker, cooldown_sec=180):
        self._acquire()
        try:
            c = (self._error_count.get(ticker, 0) or 0) + 1
            self._error_count[ticker] = c
            if c >= 2:
                self._error_until[ticker] = _time_mod.time() + cooldown_sec
        finally:
            self._release()

_YF_SESS_MGR_M = _YFSessionManager_M()

_APP_BUILD_M = {
    "commit": "7aeffb8+steplog",
    "time": "2026-08-28 20:42",
    "tag": "原生8endpoint+隨機UA+每步step log+persist err log顯示",
}
try:
    _APP_BUILD_M["yf_version"] = getattr(yf, "__version__", "n/a")
except Exception:
    _APP_BUILD_M["yf_version"] = "n/a"

# yfinance 版本緊急守門員：1.x 直接 fallback 原生 requests
try:
    _yfv_parts_m = [int(p) for p in (getattr(yf, "__version__", "0.0.0") or "0.0.0").split(".") if p.isdigit()]
    _YF_VER_MAJOR_M = _yfv_parts_m[0] if _yfv_parts_m else 0
except Exception:
    _YF_VER_MAJOR_M = 0
_YF_IS_BROKEN_V1_M = _YF_VER_MAJOR_M >= 1

# --- CSS 樣式 ---
st.markdown("""
<style>
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
    .big-font-table td:first-child {
        font-weight: bold;
        text-align: left;
        background-color: #fff;
        width: 140px;
    }
    .pos-val { color: #d9534f; font-weight: bold; }
    .neg-val { color: #28a745; font-weight: bold; }
    
    .header-row td {
        background-color: #ffffff !important; 
        font-weight: bold;
        color: #000;
        border-bottom: 2px solid #dee2e6;
    }
    .data-row td {
        background-color: #d4edda !important;
        color: #000;
        font-weight: normal;
    }
    .section-title {
        background-color: #FFFF00 !important;
        color: #000;
        font-weight: bold;
        text-align: left;
        padding: 10px;
        font-size: 16px;
        border: 1px solid #dee2e6;
    }
    
    .stButton>button { width: 100%; height: 3em; font-size: 18px; }
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
    
    /* 手机端优化 */
    @media (max-width: 768px) {
        .big-font-table {
            font-size: 12px !important;
        }
        .big-font-table td {
            padding: 6px !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 數據庫連接 (Firebase) ---
def get_secrets_dict() -> Dict[str, Any]:
    try:
        return dict(st.secrets)
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
    db = get_db()
    if not db:
        return {}
    try:
        return get_watchlist_from_firestore(db)
    except Exception as e:
        try:
            doc_ref = db.collection('stock_app').document('watchlist')
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict() or {}
        except Exception:
            pass
        return {}


def update_stock_in_db(symbol, params=None):
    db = get_db()
    if not db:
        st.error("無法連接數據庫：Firebase 未初始化，請檢查 secrets 或 service_account.json")
        return False
    try:
        saved_symbol = save_watchlist_symbol(db, symbol, params)
        st.toast(f"已同步 {saved_symbol}", icon="☁️")
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
        return True
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        if len(err_msg) > 300:
            err_msg = err_msg[:300] + "..."
        st.error(f"移除失敗：{symbol} 無法從資料庫刪除。\n錯誤：{err_msg}")
        return False

# --- 輔助功能 ---
def clean_ticker_input(symbol):
    return str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")

def get_yahoo_ticker(symbol):
    if symbol.isdigit(): return f"{symbol.zfill(4)}.HK"
    return symbol


@st.cache_resource(show_spinner=False)
def get_share_base_provider() -> CompositeShareBaseProvider:
    metadata_dir = Path(__file__).resolve().parent / "metadata"
    return CompositeShareBaseProvider(
        [
            CSVShareBaseProvider(metadata_dir / "share_base.csv"),
            YahooShareBaseProvider(),
        ]
    )


def get_turnover_share_base(ticker_obj):
    return get_share_base_provider().get_share_base(ticker_obj).share_base

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

def simulate_bs_data(df, tsi):
    if tsi is None or tsi == 0:
        return df
    vol = df['Volume'].fillna(0)
    df['UBTB'] = vol * 0.15 
    df['BTB']  = vol * 0.25 
    df['RIB']  = vol * 0.10 
    df['UBTS'] = vol * 0.15 
    df['BTS']  = vol * 0.25 
    df['RIS']  = vol * 0.10 
    denom = float(tsi)
    df['MMB'] = (df['UBTB'] * 0.9 + df['BTB'] * 0.7) / denom * 100
    df['RTB'] = (df['UBTB'] * 0.1 + df['BTB'] * 0.3 + df['RIB']) / denom * 100
    df['MMS'] = (df['UBTS'] * 0.1 + df['BTS'] * 0.7) / denom * 100
    df['RTS'] = (df['UBTS'] * 0.1 + df['BTS'] * 0.3 + df['RIS']) / denom * 100
    return df

# --- Session State 初始化 ---
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# ===== [改动3] 侧边栏重构 =====
if not is_mobile:
    # ===== 桌面端侧边栏 =====
    with st.sidebar:
        st.header("HK Stock Analysis")
        try:
            _build_cap_m = (
                f"🛠️ Build: {_APP_BUILD_M.get('commit','?')}  "
                f"| yfinance: {_APP_BUILD_M.get('yf_version','?')}  "
                f"| {_APP_BUILD_M.get('time','?')}"
            )
            st.caption(_build_cap_m)
            st.caption("💡 如果沒看到上面 Build 號 = Streamlit 仍在跑舊版！請做 Clear cache + Redeploy")
        except Exception:
            pass
        
        with st.expander("✈️ Telegram 設定", expanded=False):
            def_token = st.secrets["telegram"]["token"] if "telegram" in st.secrets else ""
            def_chat_id = st.secrets["telegram"]["chat_id"] if "telegram" in st.secrets else ""
            tg_token = st.text_input("Bot Token", value=def_token, type="password")
            tg_chat_id = st.text_input("Chat ID", value=def_chat_id)
            
            if st.button("🚀 發送單股報告", type="primary"):
                if st.session_state.current_view and tg_token and tg_chat_id:
                    yt = get_yahoo_ticker(st.session_state.current_view)
                    with st.spinner("分析中..."):
                        try:
                            d = yf.download(yt, period="2y", progress=False, auto_adjust=False)
                            if isinstance(d.columns, pd.MultiIndex): 
                                d.columns = d.columns.get_level_values(0)
                            try:
                                t_obj = yf.Ticker(yt)
                                share_base = get_turnover_share_base(t_obj)
                                d, _, _ = apply_turnover_rate(d, share_base)
                            except Exception:
                                pass
                            if len(d) > 50:
                                w = get_watchlist_from_db()
                                st.info("Telegram 功能在此版本中简化了")
                            else: 
                                st.error("數據不足")
                        except Exception as e: 
                            st.error(str(e))
                else:
                    st.toast("請先選擇股票並設定 Token", icon="⚠️")
        
        st.divider()
        
        new_date = st.date_input("基準日期", value=st.session_state.ref_date)
        if new_date != st.session_state.ref_date:
            st.session_state.ref_date = new_date
            st.rerun()
        
        search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
        if search_input:
            cleaned = clean_ticker_input(search_input)
            if cleaned: st.session_state.current_view = cleaned
        
        st.divider()
        
        watchlist_data = get_watchlist_from_db()
        watchlist_list = list(watchlist_data.keys()) if watchlist_data else []

        st.subheader(f"我的收藏 ({len(watchlist_list)})")
        _tip_m = (f"🎯 渲染模式：原生 HTML form inline-flex（V9，保證同行不拆行）  "
                  f"|  Build: {_APP_BUILD_M.get('commit','?')}  "
                  f"|  yfinance: {_APP_BUILD_M.get('yf_version','?')}{'  [1.x detected → native requests fallback 🔥]' if _YF_IS_BROKEN_V1_M else ''}")
        st.caption(_tip_m)
        if watchlist_list:
            for ticker in watchlist_list:
                _btns_style_m = (
                    "display:flex;flex-direction:row;flex-wrap:nowrap;"
                    "align-items:stretch;gap:6px;width:100%;margin:0 0 6px 0;"
                )
                _nav_style_m = (
                    "flex:1 1 auto;min-width:0;height:44px;font-size:16px;"
                    "font-weight:600;border:1px solid rgba(49,51,63,0.2);border-radius:6px;"
                    "background-color:#FFFFFF;color:#31333F;cursor:pointer;"
                    "white-space:nowrap;padding:4px 10px;"
                )
                _del_style_m = (
                    "flex:0 0 48px;width:48px;height:44px;font-size:18px;"
                    "border:1px solid rgba(49,51,63,0.2);border-radius:6px;"
                    "background-color:#FFFFFF;color:#d9534f;cursor:pointer;"
                    "white-space:nowrap;padding:0;"
                )
                _html_m = f"""
                <form method="get" style="{_btns_style_m}" onsubmit="return true;">
                  <input type="hidden" name="wl_ticker" value="{ticker}">
                  <button type="submit" name="wl_action" value="nav" style="{_nav_style_m}">{ticker}</button>
                  <button type="submit" name="wl_action" value="del" style="{_del_style_m}" title="取消收藏 {ticker}">🗑️</button>
                </form>
                """
                st.markdown(_html_m, unsafe_allow_html=True)
        else:
            st.caption("暫無收藏")
        
        st.divider()
        if st.button("🏠 回到總覽 (Overview)", use_container_width=True):
            st.session_state.current_view = ""
            st.rerun()
        
        st.divider()
        sma1 = st.number_input("SMA 1", value=20)
        sma2 = st.number_input("SMA 2", value=50)
else:
    # ===== [改动4] 手机端顶部导航 =====
    if not st.session_state.current_view:
        st.markdown("### 📊 港股 SMA 矩陣")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            new_date = st.date_input("基準日期", value=st.session_state.ref_date, label_visibility="collapsed")
        with col2:
            if new_date != st.session_state.ref_date:
                st.session_state.ref_date = new_date
                st.rerun()
        
        search_input = st.text_input("🔍 股票代號", placeholder="例: 700", key="search_bar_mobile")
        if search_input:
            cleaned = clean_ticker_input(search_input)
            if cleaned: 
                st.session_state.current_view = cleaned
                st.rerun()
        
        col1, col2 = st.columns(2)
        with col1:
            sma1 = st.number_input("SMA 1", value=20, label_visibility="collapsed")
        with col2:
            sma2 = st.number_input("SMA 2", value=50, label_visibility="collapsed")
    else:
        sma1 = 20
        sma2 = 50

watchlist_data = get_watchlist_from_db()
watchlist_list = list(watchlist_data.keys()) if watchlist_data else []

# 原生 HTML form query params 導航（同行保證）
try:
    _qp_m = st.query_params.to_dict() if hasattr(st, "query_params") else {}
except Exception:
    _qp_m = {}
if _qp_m:
    _a = _qp_m.get("wl_action")
    _t = _qp_m.get("wl_ticker")
    if isinstance(_a, list): _a = _a[0] if _a else ""
    if isinstance(_t, list): _t = _t[0] if _t else ""
    _a = str(_a or "").strip(); _t = str(_t or "").strip()
    if _t and _a in ("nav", "del"):
        try:
            st.query_params.clear()
        except Exception:
            pass
        if _a == "nav":
            st.session_state.current_view = _t
            st.rerun()
        elif _a == "del":
            if remove_stock_from_db(_t):
                st.rerun()

current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

# ===== [改动5] 总覽模式 =====
if not current_code:
    st.title("📊 港股 SMA 矩陣 - 收藏總覽")
    
    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        # ===== [改动5.1] 响应式按钮 =====
        buttons = [
            {"label": "🔄 刷新所有數據", "key": "refresh"},
            {"label": "📊 比較模式", "key": "compare", "type": "primary"},
        ]
        
        clicked = action_buttons(buttons, layout="auto")
        
        if clicked == "refresh":
            st.cache_clear()
            st.rerun()
        elif clicked == "compare":
            st.info("📊 比較模式功能開發中...")
        
        st.divider()
        
        # ===== [改动5.2] 卡片式显示 =====
        for ticker in watchlist_list:
            yt = get_yahoo_ticker(ticker)
            with st.spinner(f"正在分析 {ticker}..."):
                try:
                    df_w = yf.download(yt, period="1y", progress=False, auto_adjust=False)
                    if isinstance(df_w.columns, pd.MultiIndex): 
                        df_w.columns = df_w.columns.get_level_values(0)
                    
                    end_dt = pd.to_datetime(st.session_state.ref_date)
                    df_w = df_w[df_w.index <= end_dt]
                    
                    if len(df_w) > 20:
                        curr_p = df_w['Close'].iloc[-1]
                        prev_close_w = df_w['Close'].shift(1).replace(0, np.nan)
                        prev_close_last = prev_close_w.iloc[-1]
                        prev_close_last = float(prev_close_last) if pd.notna(prev_close_last) else 0.0
                        chg = (curr_p - prev_close_last) if prev_close_last else 0.0
                        pct = (chg / prev_close_last * 100) if prev_close_last else 0.0
                        
                        if is_mobile:
                            # ===== [改动5.3] 手机卡片UI =====
                            with st.container():
                                col1, col2 = st.columns([2, 1])
                                with col1:
                                    st.markdown(f"""
                                    <div style="font-size: 18px; font-weight: bold;">
                                        {ticker.upper()}
                                    </div>
                                    """, unsafe_allow_html=True)
                                    st.caption(f"Price: {curr_p:.2f}")
                                
                                with col2:
                                    chg_color = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                                    color_text = "green" if chg > 0 else "red" if chg < 0 else "gray"
                                    st.markdown(f"""
                                    <div style="text-align: right; font-weight: bold; color: {color_text};">
                                        {chg_color}<br/>{pct:+.2f}%
                                    </div>
                                    """, unsafe_allow_html=True)
                                
                                with st.expander(f"📊 詳細數據", expanded=False):
                                    intervals = [7, 14, 28, 57, 106, 212]
                                    avgp_vals = [curr_p]
                                    for p in intervals:
                                        avgp_vals.append(df_w['Close'].rolling(p).mean().iloc[-1] if len(df_w)>=p else 0)
                                    
                                    valid_avgp = [v for v in avgp_vals if v > 0]
                                    avg_avgp = sum(valid_avgp) / len(valid_avgp) if valid_avgp else 0
                                    avgp_mr_vals = [((v / avg_avgp) - 1)*100 if avg_avgp else 0 for v in avgp_vals]
                                    
                                    st.write("**SMA 價格**")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("SMA7", f"{avgp_vals[1]:.2f}")
                                    with col2:
                                        st.metric("SMA14", f"{avgp_vals[2]:.2f}")
                                    with col3:
                                        st.metric("SMA28", f"{avgp_vals[3]:.2f}")
                                    
                                    st.write("**MR 偏差%**")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("MR7", f"{avgp_mr_vals[1]:.2f}%")
                                    with col2:
                                        st.metric("MR14", f"{avgp_mr_vals[2]:.2f}%")
                                    with col3:
                                        st.metric("MR28", f"{avgp_mr_vals[3]:.2f}%")
                                
                                st.divider()
                        else:
                            # 桌面版本 - 显示完整的卡片和表格
                            st.write(f"**{ticker}** | Price: {curr_p:.2f} | Change: {pct:+.2f}%")
                            st.divider()
                
                except Exception as e: 
                    st.error(f"Error {ticker}: {e}")

# ===== [改动6] 詳細模式 =====
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)
    
    # ===== [改动6.1] 手机版头部栏 =====
    if is_mobile:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("◀", use_container_width=True, key="mobile_back"):
                st.session_state.current_view = ""
                st.rerun()
        with col2:
            st.markdown(f"<h3 style='text-align: center; margin: 0;'>{display_ticker}</h3>", unsafe_allow_html=True)
        with col3:
            is_in_watchlist = current_code in watchlist_list
            btn_label = "★ 已收藏" if is_in_watchlist else "☆ 加入"
            if st.button(btn_label, use_container_width=True, key="mobile_fav"):
                if is_in_watchlist:
                    action_ok = remove_stock_from_db(current_code)
                else:
                    action_ok = update_stock_in_db(current_code)
                if action_ok:
                    st.rerun()
    else:
        # 桌面版头部
        col_t, col_b = st.columns([0.85, 0.15])
        with col_t: 
            st.title(f"📊 {display_ticker}")
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
    
    _YF_LAST_ERROR_M: Dict[str, Any] = {}
    _NATIVE_DL_STATS_M = {"native_attempts": 0, "native_success": 0, "yf_attempts": 0, "yf_success": 0}
    _YF_PERR_LOG_M = []
    _YF_STEP_LOG_M = []
    _YF_LOG_LOCK_M = _YF_SESS_MGR_M._lock if hasattr(_YF_SESS_MGR_M, "_lock") else None

    def _yf_append_log_m(log_list, payload, limit=20):
        try:
            if _YF_LOG_LOCK_M: _YF_LOG_LOCK_M.acquire(timeout=0.5)
            log_list.append(payload)
            while len(log_list) > limit: log_list.pop(0)
        except Exception:
            pass
        finally:
            try:
                if _YF_LOG_LOCK_M and _YF_LOG_LOCK_M.locked(): _YF_LOG_LOCK_M.release()
            except Exception:
                pass

    def _yf_log_step_m(symbol, stage, msg):
        _yf_append_log_m(_YF_STEP_LOG_M,
                         (_time_mod.strftime("%H:%M:%S"), symbol, stage, (msg or "")[:260]), limit=60)

    def _persist_lerr_m(symbol: str, route: str, detail: str):
        try:
            _YF_LAST_ERROR_M[symbol] = {
                "time": _time_mod.strftime("%H:%M:%S"),
                "route": route,
                "detail": (detail or "")[:240],
            }
        except Exception:
            pass
        _yf_append_log_m(_YF_PERR_LOG_M,
                         (_time_mod.strftime("%H:%M:%S"), symbol, route, (detail or "")[:240]), limit=30)

    def _native_yahoo_chart_download_m(symbol, range_: str = "3y", interval: str = "1d", timeout: int = 25):
        from urllib.parse import urlencode as _urlenc_m
        uas_m = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
        ]
        ua_m = _rand_mod.choice(uas_m)
        _yf_log_step_m(symbol, "native.init", f"ua={ua_m[:40]}... range={range_}")
        hdrs_m = {
            "User-Agent": ua_m,
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh-Hant;q=0.9,zh;q=0.8,en-US;q=0.7,en;q=0.6",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": f"https://finance.yahoo.com/quote/{symbol}",
        }
        with requests.Session() as s_m:
            s_m.headers.update(hdrs_m)
            last_err_m = None
            try:
                _yf_log_step_m(symbol, "native.warmup1", "GET finance.yahoo.com/")
                r = s_m.get("https://finance.yahoo.com/", timeout=min(timeout, 12), allow_redirects=True)
                _yf_log_step_m(symbol, "native.warmup1", f"status={r.status_code} len={len(r.content or b'')}")
            except Exception as e:
                _yf_log_step_m(symbol, "native.warmup1", f"EXCEPTION {type(e).__name__}: {str(e)[:120]}")
                last_err_m = RuntimeError(f"warmup failed: {type(e).__name__}")
            try:
                _yf_log_step_m(symbol, "native.warmup2", "GET consent.yahoo.com")
                s_m.get("https://consent.yahoo.com/v2/collectConsent?sessionId=3_cc-session_" + str(int(_time_mod.time()*1000)),
                        timeout=min(timeout, 8), allow_redirects=True)
            except Exception as e_w:
                _yf_log_step_m(symbol, "native.warmup2", f"EXCEPTION {type(e_w).__name__}")

            p_basic_m = {"range": range_, "interval": interval,
                         "includeAdjustedClose": "false", "includePrePost": "false"}
            p_ev_m = {**p_basic_m, "events": "div%2Csplits%2CcapitalGains"}
            def make_m(host):
                return [
                    f"https://{host}/v8/finance/chart/{symbol}?{_urlenc_m(p_ev_m)}",
                    f"https://{host}/v8/finance/chart/{symbol}?{_urlenc_m(p_basic_m)}",
                ]
            urls_m = (make_m("query1.finance.yahoo.com") +
                      make_m("query2.finance.yahoo.com") +
                      make_m("hk.finance.yahoo.com") +
                      make_m("query1.finance.yahoo.com.hk"))
            _yf_log_step_m(symbol, "native.urls", f"count={len(urls_m)} first={urls_m[0].split('?')[0]}")
            for i, u in enumerate(urls_m):
                try:
                    _yf_log_step_m(symbol, f"native.req[{i}]", f"GET {u.split('//')[1].split('?')[0]}")
                    r_m = s_m.get(u, timeout=timeout, allow_redirects=True)
                    body_len = len(r_m.content or b"")
                    snip = ""
                    try: snip = (r_m.text or "")[:160]
                    except Exception: pass
                    _yf_log_step_m(symbol, f"native.req[{i}]", f"status={r_m.status_code} len={body_len} snip={snip}")
                    if r_m.status_code != 200:
                        last_err_m = RuntimeError(f"HTTP {r_m.status_code} @ {u.split('//')[1].split('?')[0][:36]} | {snip}")
                        _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                        continue
                    try:
                        d_m = r_m.json()
                    except Exception as je:
                        last_err_m = RuntimeError(f"JSON parse: {je} | head={snip}")
                        _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                        continue
                    res_l = d_m.get("chart", {}).get("result") or []
                    if not res_l:
                        err = (d_m.get("chart", {}).get("error") or {})
                        last_err_m = RuntimeError(f"empty result: code={err.get('code')} desc={str(err.get('description',''))[:100]}")
                        _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                        continue
                    res = res_l[0]
                    meta = res.get("meta") or {}
                    _yf_log_step_m(symbol, f"native.req[{i}]",
                                   f"meta symbol={meta.get('symbol')} currency={meta.get('currency')} ts_len={len(res.get('timestamp') or [])}")
                    ts_m = res.get("timestamp") or []
                    q_m = (res.get("indicators") or {}).get("quote") or []
                    if not ts_m or not q_m:
                        last_err_m = RuntimeError("missing ts/quote")
                        _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                        continue
                    q0 = q_m[0]
                    idx = pd.to_datetime(ts_m, unit="s", utc=True).tz_convert(None)
                    o_m = q0.get("open") or []
                    h_m = q0.get("high") or []
                    l_m = q0.get("low") or []
                    c_m = q0.get("close") or []
                    v_m = q0.get("volume") or []
                    n_m = min(len(idx), len(o_m), len(h_m), len(l_m), len(c_m), len(v_m))
                    if n_m < 10:
                        last_err_m = RuntimeError(f"rows too few ({n_m})")
                        _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                        continue
                    df_m = pd.DataFrame({
                        "Open": o_m[:n_m], "High": h_m[:n_m], "Low": l_m[:n_m],
                        "Close": c_m[:n_m], "Volume": v_m[:n_m],
                    }, index=idx[:n_m])
                    _yf_log_step_m(symbol, f"native.req[{i}]",
                                   f"SUCCESS rows={len(df_m)} close_last={df_m['Close'].iloc[-1] if len(df_m) else '?'}")
                    return df_m, None
                except Exception as e_ex:
                    last_err_m = RuntimeError(f"{type(e_ex).__name__}: {str(e_ex)[:180]}")
                    _persist_lerr_m(symbol, f"native[{i}]", str(last_err_m))
                    _yf_log_step_m(symbol, f"native.req[{i}]", f"EXCEPTION {type(e_ex).__name__}: {str(e_ex)[:140]}")
                    continue
        raise RuntimeError(f"native yahoo chart failed: {last_err_m}")

    def _try_yfinance_download_m(symbol, period: str = "3y", timeout: int = 30):
        try:
            sess_m = _YF_SESS_MGR_M.get_session()
            if sess_m is not None:
                try:
                    yf_sg = getattr(yf, "_get_session", None)
                    if callable(yf_sg):
                        yf_cur = yf_sg()
                        if yf_cur is not None:
                            for k, v in sess_m.headers.items():
                                try: yf_cur.headers[k] = v
                                except Exception: continue
                except Exception:
                    pass
            df = yf.download(symbol, period=period, progress=False, auto_adjust=False, timeout=timeout)
            if df is None or df.empty:
                raise RuntimeError("yfinance.download returned empty DataFrame")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            share_base = None
            try:
                t = yf.Ticker(symbol)
                share_base = get_turnover_share_base(t)
            except Exception:
                share_base = None
            return df, share_base
        except Exception as exc:
            msg = str(exc) or ""
            short = f"{type(exc).__name__}: {msg[:180]}"
            _persist_lerr_m(symbol, "yfinance", short)
            raise RuntimeError(short) from exc

    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        last_err = None
        if _YF_SESS_MGR_M.should_skip(symbol):
            return None, None
        for attempt in range(3):
            # --- Route 1: 原生 requests 優先 ---
            _NATIVE_DL_STATS_M["native_attempts"] = _NATIVE_DL_STATS_M.get("native_attempts", 0) + 1
            try:
                df, share_base = _native_yahoo_chart_download_m(symbol, range_="3y", interval="1d", timeout=25)
                df = df[df.index <= pd.to_datetime(end_date)]
                if df is not None and len(df) > 5:
                    _YF_SESS_MGR_M.record_success(symbol)
                    _NATIVE_DL_STATS_M["native_success"] = _NATIVE_DL_STATS_M.get("native_success", 0) + 1
                    _persist_lerr_m(symbol, "native", f"OK rows={len(df)}")
                    return df, share_base
            except Exception as e_n:
                last_err = e_n
            # --- Route 2: 原生失敗才 fallback yfinance ---
            _NATIVE_DL_STATS_M["yf_attempts"] = _NATIVE_DL_STATS_M.get("yf_attempts", 0) + 1
            try:
                df, share_base = _try_yfinance_download_m(symbol, period="3y", timeout=30)
                df = df[df.index <= pd.to_datetime(end_date)]
                if df is not None and len(df) > 5:
                    _YF_SESS_MGR_M.record_success(symbol)
                    _NATIVE_DL_STATS_M["yf_success"] = _NATIVE_DL_STATS_M.get("yf_success", 0) + 1
                    _persist_lerr_m(symbol, "yfinance", f"OK rows={len(df)}")
                    return df, share_base
            except Exception as e_yf:
                last_err = e_yf
            msg = str(last_err) or ""
            name = type(last_err).__name__
            if attempt < 2 and ("Invalid Crumb" in msg or "Unauthorized" in msg or "RateLimit" in name
                                or "Too Many Requests" in msg or "HTTP 40" in msg or "HTTP 5" in msg
                                or "empty" in msg.lower()):
                backoff_m = (2 ** attempt) * (1.0 + _rand_mod.random())
                _time_mod.sleep(backoff_m)
                continue
            break
        _YF_SESS_MGR_M.record_failure(symbol, cooldown_sec=180)
        _persist_lerr_m(symbol, "final", f"ALL 3 attempts failed | last={type(last_err).__name__}: {str(last_err)[:160]}")
        return None, None

    df, share_base = get_data_v7(yahoo_ticker, st.session_state.ref_date)
    
    if df is None or len(df) <= 5:
        _extra_info_m = []
        _extra_info_m.append(f"🛠️  Build: {_APP_BUILD_M.get('commit','?')}  |  yfinance: {_APP_BUILD_M.get('yf_version','?')}")
        _extra_info_m.append(f"🔎  Yahoo ticker 送出: `{yahoo_ticker}`  |  原代碼: `{current_code}`")
        try:
            until_m = _YF_SESS_MGR_M._error_until.get(yahoo_ticker, 0.0) or _YF_SESS_MGR_M._error_until.get(current_code, 0.0)
            left_m = max(0, int(until_m - _time_mod.time()))
            if left_m > 0:
                _extra_info_m.append(f"⌛ Error 降級中：{left_m}s 後自動重試（節省 Yahoo 配額）")
        except Exception:
            pass
        try:
            ec_m = _YF_SESS_MGR_M._error_count.get(yahoo_ticker, 0) or _YF_SESS_MGR_M._error_count.get(current_code, 0)
            if ec_m:
                _extra_info_m.append(f"⚠️ 連續失敗次數: {ec_m}")
        except Exception:
            pass
        try:
            lerr = _YF_LAST_ERROR_M.get(yahoo_ticker) or _YF_LAST_ERROR_M.get(current_code) or _YF_LAST_ERROR_M.get(yahoo_ticker.replace(".HK","").replace(".hk",""))
            if lerr:
                _extra_info_m.append(f"🧭 最後嘗試 [{lerr.get('route','?')}] @ {lerr.get('time','?')}：{lerr.get('detail','')}")
        except Exception:
            pass
        try:
            n_at = _NATIVE_DL_STATS_M.get("native_attempts", 0)
            n_ok = _NATIVE_DL_STATS_M.get("native_success", 0)
            y_at = _NATIVE_DL_STATS_M.get("yf_attempts", 0)
            y_ok = _NATIVE_DL_STATS_M.get("yf_success", 0)
            if (n_at + y_at) > 0:
                _extra_info_m.append(f"📊 下載統計：native {n_ok}/{n_at}  |  yfinance {y_ok}/{y_at}")
        except Exception:
            pass
        try:
            _matches_step_m = []
            for _t, _sym, _stg, _msg in reversed(_YF_STEP_LOG_M):
                if _sym == yahoo_ticker or _sym == current_code:
                    _matches_step_m.append(f"[{_t}] {_stg} → {_msg}")
                if len(_matches_step_m) >= 8: break
            if _matches_step_m:
                _extra_info_m.append("🔧 --- DEBUG STEP LOG (限前 8 條) ---")
                for _l in _matches_step_m:
                    _extra_info_m.append("🔧 " + _l)
        except Exception:
            pass
        try:
            _matches_perr_m = []
            for _t, _sym, _rt, _det in reversed(_YF_PERR_LOG_M):
                if _sym == yahoo_ticker or _sym == current_code:
                    _matches_perr_m.append(f"[{_t}] <{_rt}> {_det}")
                if len(_matches_perr_m) >= 5: break
            if _matches_perr_m:
                _extra_info_m.append("🚨 --- PERSIST ERRORS (限前 5 條) ---")
                for _l in _matches_perr_m:
                    _extra_info_m.append("🚨 " + _l)
        except Exception:
            pass
        st.error("⚠️ 載入失敗：Yahoo Finance 暫時拒絕連線（Invalid Crumb / 401 Unauthorized）。請稍後按下方按鈕重試或重整頁面。")
        for _l in _extra_info_m:
            st.caption(_l)
        if st.button("🔄 重試載入數據（清除 blacklist + cache）", use_container_width=True, key="mobile_retry_df"):
            for _tk in (yahoo_ticker, current_code):
                try:
                    _YF_SESS_MGR_M._error_count.pop(_tk, None)
                    _YF_SESS_MGR_M._error_until.pop(_tk, None)
                except Exception:
                    pass
            get_data_v7.clear()
            st.rerun()
    else:
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma: 
            df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
        if f'SMA_{sma1}' not in df.columns: 
            df[f'SMA_{sma1}'] = df['Close'].rolling(sma1).mean()
        if f'SMA_{sma2}' not in df.columns: 
            df[f'SMA_{sma2}'] = df['Close'].rolling(sma2).mean()
        
        df, turnover_status, turnover_reason = apply_turnover_rate(df, share_base)
        has_turnover = turnover_status == TURNOVER_STATUS_CALCULATED
        if has_turnover:
            df = simulate_bs_data(df, share_base)
        
        prev_close_series = df['Close'].shift(1).replace(0, np.nan)
        df['AMP'] = (df['High'] - df['Low']) / prev_close_series * 100
        
        for p in periods_sma: 
            df[f'Sum_{p}'] = df['Volume'].rolling(p).sum()
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']
        
        # ===== [改动6.2] 导航栏 =====
        if is_mobile:
            if st.button("◀ 返回總覽", use_container_width=True):
                st.session_state.current_view = ""
                st.rerun()
            st.caption(f"📅 {df.index[-1].strftime('%Y-%m-%d')}")
        else:
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
        
        # ===== [改动6.3] 关键指标 =====
        def _last_valid_m(series):
            s = pd.to_numeric(series, errors="coerce").replace(0, np.nan).dropna()
            return float(s.iloc[-1]) if len(s) >= 1 else float("nan")

        def _nth_last_valid_m(series, n_from_last):
            s = pd.to_numeric(series, errors="coerce").replace(0, np.nan).dropna()
            idx = len(s) - 1 - n_from_last
            return float(s.iloc[idx]) if idx >= 0 else float("nan")

        curr_close = _last_valid_m(df["Close"])
        prev_close_raw = _nth_last_valid_m(df["Close"], 1)
        prev_close = prev_close_raw if pd.notna(prev_close_raw) else None
        curr_open = _last_valid_m(df["Open"]) if "Open" in df.columns else float("nan")
        curr_high = _last_valid_m(df["High"]) if "High" in df.columns else float("nan")
        curr_low = _last_valid_m(df["Low"]) if "Low" in df.columns else float("nan")

        has_prev_close = prev_close is not None and pd.notna(prev_close) and prev_close != 0
        chg = (curr_close - prev_close) if (pd.notna(curr_close) and has_prev_close) else float("nan")
        pct = (chg / prev_close * 100) if (pd.notna(chg) and has_prev_close) else float("nan")
        amp = ((curr_high - curr_low) / prev_close * 100) if (pd.notna(curr_high) and pd.notna(curr_low) and has_prev_close) else float("nan")

        def _fmt_price(v, decimals=3):
            if pd.isna(v):
                return "-"
            return f"{float(v):.{decimals}f}"

        def _fmt_chg_line(chg_val, pct_val, decimals_chg=3, decimals_pct=2):
            if pd.isna(chg_val) or pd.isna(pct_val):
                return "-"
            return f"{float(chg_val):+.{decimals_chg}f} ({float(pct_val):+.{decimals_pct}f}%)"

        def _fmt_amp(v, decimals=2):
            if pd.isna(v):
                return "-"
            return f"{float(v):.{decimals}f}%"

        if is_mobile:
            st.metric(
                "現價",
                _fmt_price(curr_close),
                _fmt_chg_line(chg, pct),
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("開市", _fmt_price(curr_open))
            with col2:
                st.metric("最高", _fmt_price(curr_high))
            with col3:
                st.metric("最低", _fmt_price(curr_low))
        else:
            c_sum_1, c_sum_2 = st.columns(2)
            with c_sum_1:
                st.metric(
                    "現價",
                    _fmt_price(curr_close),
                    _fmt_chg_line(chg, pct),
                )
                st.metric(
                    "前收市",
                    _fmt_price(prev_close) if has_prev_close else "-",
                )
                st.metric("波幅(AA)", _fmt_amp(amp))
            with c_sum_2:
                st.metric("開市", _fmt_price(curr_open))
                st.metric("最高", _fmt_price(curr_high))
                st.metric("最低", _fmt_price(curr_low))
        
        # ===== [改动6.4] 响应式图表 =====
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
        fig_main.update_layout(
            height=520 if not is_mobile else 350, 
            xaxis_rangeslider_visible=True, 
            template="plotly_white", 
            dragmode="pan", 
            uirevision=f"main_price_{current_code}"
        )
        
        responsive_chart(fig_main, title="K線圖", height="auto")
        
        # ===== [改动6.5] 快速信號 =====
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
        
        if is_mobile:
            st.write(f"超底(FZM): {'🔴 觸發' if fzm_trigger else '未觸發'}")
            st.write(f"WR35: {'-' if pd.isna(val_wr35) else f'{float(val_wr35):.2f}'}")
            st.write(f"SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}")
        else:
            c_sig_1, c_sig_2 = st.columns(2)
            with c_sig_1:
                st.markdown(f"超底(FZM): {'🔴 觸發' if fzm_trigger else '未觸發'}")
                st.write(f"WR35: {'-' if pd.isna(val_wr35) else f'{float(val_wr35):.2f}'}")
                st.write(f"SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}")
            with c_sig_2:
                st.markdown(f"振蕩(MR): 計算中...")
        
        st.info("📊 詳細數據表格開發中... (SMA 矩陣、Turnover Rate 等)")
    else:
        st.error("❌ 無法取得足夠的數據")

# ===== [改动7] 底部导航 (手机端) =====
if is_mobile:
    st.markdown("---")
    st.markdown("### 📱 快速導航")
    nav_cols = st.columns(4)
    nav_items = [
        {"label": "🏠Home", "key": "home"},
        {"label": "📊Detail", "key": "detail"},
        {"label": "💼Fav", "key": "fav"},
        {"label": "⚙️More", "key": "more"},
    ]
    
    for col, item in zip(nav_cols, nav_items):
        with col:
            if st.button(item["label"], use_container_width=True, key=f"nav_{item['key']}"):
                if item["key"] == "home":
                    st.session_state.current_view = ""
                    st.rerun()
                else:
                    st.info(f"✓ {item['label']} 頁面開發中...")

# ===== 开发者工具 =====
optimizer.toggle_mobile_mode()
