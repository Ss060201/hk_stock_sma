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
import os
from io import BytesIO
from typing import Any, Dict, List, Optional
from streamlit.errors import StreamlitSecretNotFoundError

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

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
    div[data-baseweb="select"] > div {
        min-height: 44px;
        border-radius: 8px;
    }

    @media (max-width: 768px) {
        .main .block-container { padding: var(--mobile-padding) !important; padding-bottom: 88px !important; max-width: 100% !important; }
        div[data-testid="stHorizontalBlock"] { flex-direction: column !important; }
        div[data-testid="stHorizontalBlock"] > div { width: 100% !important; margin-bottom: 12px; }
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
        .stButton>button { font-size: 13px; min-height: 42px; padding: 10px 12px !important; }
    }

    @media (min-width: 1024px) {
        .main .block-container { padding: var(--desktop-padding) !important; }
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
    db = get_db()
    if not db: return {}
    try:
        doc_ref = db.collection('stock_app').document('watchlist')
        doc = doc_ref.get()
        if doc.exists: return doc.to_dict()
        else: return {}
    except: return {}

def update_stock_in_db(symbol, params=None):
    db = get_db()
    if not db:
        st.error("無法連接數據庫")
        return
    doc_ref = db.collection('stock_app').document('watchlist')
    data = {
        symbol: params
        if params
        else {
            "box1_start": "",
            "box1_end": "",
            "box2_start": "",
            "box2_end": "",
            "interactive_range_start": "",
            "interactive_range_end": "",
            "abc_date_p1_start": "",
            "abc_date_p1_end": "",
            "abc_date_p2_end": "",
            "abc_price_p1_high": 0.0,
            "abc_price_p1_low": 0.0,
            "abc_price_p2_high": 0.0,
            "cdm_p1_avg_override": 0.0,
            "cdm_p2_avg_override": 0.0,
        }
    }
    doc_ref.set(data, merge=True)
    st.toast(f"已同步 {symbol}", icon="☁️")

def remove_stock_from_db(symbol):
    db = get_db()
    if not db: return
    doc_ref = db.collection('stock_app').document('watchlist')
    doc_ref.update({symbol: firestore.DELETE_FIELD})
    st.toast(f"已移除 {symbol}", icon="🗑️")

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

    def _clamp_backtest_date(value, fallback):
        try:
            parsed = pd.to_datetime(value).date() if value is not None else fallback
        except Exception:
            parsed = fallback
        if parsed < min_d:
            return min_d
        if parsed > max_d:
            return max_d
        return parsed

    if "bt_start" not in st.session_state:
        st.session_state.bt_start = max(min_d, (pd.to_datetime(max_d) - timedelta(days=365)).date())
    if "bt_end" not in st.session_state:
        st.session_state.bt_end = max_d
    st.session_state.bt_start = _clamp_backtest_date(
        st.session_state.get("bt_start"),
        max(min_d, (pd.to_datetime(max_d) - timedelta(days=365)).date()),
    )
    st.session_state.bt_end = _clamp_backtest_date(
        st.session_state.get("bt_end"),
        max_d,
    )
    if st.session_state.bt_start > st.session_state.bt_end:
        st.session_state.bt_start, st.session_state.bt_end = st.session_state.bt_end, st.session_state.bt_start

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
        st.session_state.cmp_start = _clamp_backtest_date(
            st.session_state.get("cmp_start"),
            st.session_state.bt_start,
        )
        st.session_state.cmp_end = _clamp_backtest_date(
            st.session_state.get("cmp_end"),
            st.session_state.bt_end,
        )
        if st.session_state.cmp_start > st.session_state.cmp_end:
            st.session_state.cmp_start, st.session_state.cmp_end = st.session_state.cmp_end, st.session_state.cmp_start

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
                    st.markdown(card_html, unsafe_allow_html=True)

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

@st.cache_data(ttl=900)
def get_data_v7(symbol, end_date):
    try:
        df = yf.download(symbol, period="5y", auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[df.index <= pd.to_datetime(end_date)]
        t = yf.Ticker(symbol)
        try:
            s = t.fast_info.get('shares', None)
        except Exception:
            s = t.info.get('sharesOutstanding', None)
        return df, s
    except Exception:
        return None, None

def _compute_home_snapshot_for_stock(ticker: str, df: pd.DataFrame, shares_outstanding) -> Optional[Dict[str, Any]]:
    if df is None or df.empty or len(df) < 2:
        return None

    work_df = df.copy()
    close = work_df["Close"].astype(float)
    current_close = float(close.iloc[-1])
    prev_close = close.shift(1).iloc[-1]
    prev_close = float(prev_close) if pd.notna(prev_close) and float(prev_close) != 0 else np.nan

    def pct_change(current_value, base_value):
        if pd.isna(base_value) or float(base_value) == 0:
            return np.nan
        return (float(current_value) / float(base_value) - 1) * 100

    dev_periods = [3, 7, 14, 28, 57, 106]
    dev_values = {"Dev 0": pct_change(current_close, prev_close)}
    for p in dev_periods:
        base_value = close.shift(p).iloc[-1] if len(close) > p else np.nan
        dev_values[f"Dev {p}"] = pct_change(current_close, base_value)

    periods_sma = [7, 14, 28, 57, 106]
    sma_values = {}
    for p in periods_sma:
        sma = close.rolling(p).mean().iloc[-1] if len(close) >= p else np.nan
        sma_values[f"SMA {p}"] = float(sma) if pd.notna(sma) else np.nan

    prev_close_series = close.shift(1).replace(0, np.nan)
    work_df["AMP"] = (work_df["High"] - work_df["Low"]) / prev_close_series * 100
    amp_values = {"Amp 0": float(work_df["AMP"].iloc[-1]) if pd.notna(work_df["AMP"].iloc[-1]) else np.nan}
    for p in periods_sma:
        amp = work_df["AMP"].tail(p).mean() if len(work_df) >= p else np.nan
        amp_values[f"Amp {p}"] = float(amp) if pd.notna(amp) else np.nan

    tor_values = {f"TOR {p}": np.nan for p in [0, 7, 14, 28, 57, 106]}
    if shares_outstanding and float(shares_outstanding) != 0:
        work_df["Turnover_Rate"] = work_df["Volume"] / float(shares_outstanding) * 100
        tor_values["TOR 0"] = float(work_df["Turnover_Rate"].iloc[-1]) if pd.notna(work_df["Turnover_Rate"].iloc[-1]) else np.nan
        for p in periods_sma:
            tor = work_df["Turnover_Rate"].tail(p).mean() if len(work_df) >= p else np.nan
            tor_values[f"TOR {p}"] = float(tor) if pd.notna(tor) else np.nan

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
            "tor": tor_values,
            "amp": amp_values,
            "sma": sma_values,
        },
    }

@st.cache_data(ttl=900)
def get_home_watchlist_snapshot(watchlist_codes: List[str], ref_date: str) -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    details: Dict[str, Dict[str, Any]] = {}

    for ticker in watchlist_codes:
        df, shares_outstanding = get_data_v7(get_yahoo_ticker(ticker), ref_date)
        snapshot = _compute_home_snapshot_for_stock(ticker, df, shares_outstanding)
        if not snapshot:
            continue
        summaries.append(snapshot["summary"])
        details[ticker] = snapshot["detail"]

    return {"summaries": summaries, "details": details}

def set_current_page(page: str, code: Optional[str] = None):
    st.session_state.current_page = page
    if code is not None:
        st.session_state.current_view = clean_ticker_input(code)
    st.session_state.comparison_mode = (page == "comparison")
    if page == "stock" and code is not None:
        st.session_state.stock_section = "header"

def queue_scroll_to_anchor(anchor_id: str):
    st.session_state.pending_scroll_target = anchor_id

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

def render_section_anchor_nav_frontend(title: str, caption: str, sections: List[tuple], key_prefix: str):
    with st.expander(title, expanded=False):
        st.caption(caption)
        rows = (len(sections) + 1) // 2
        height = max(84, rows * 56 + 16)
        buttons_html = "".join(
            [
                f'<button type="button" class="anchor-btn" data-anchor="{anchor_id}">{label}</button>'
                for anchor_id, label in sections
            ]
        )
        components.html(
            f"""
            <style>
              .anchor-grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 10px;
              }}
              .anchor-btn {{
                width: 100%;
                min-height: 42px;
                padding: 10px 12px;
                border: 1px solid rgba(49, 51, 63, 0.2);
                border-radius: 8px;
                background: #ffffff;
                color: #31333F;
                font-size: 13px;
                cursor: pointer;
              }}
              .anchor-btn:active {{
                transform: translateY(1px);
              }}
            </style>
            <div class="anchor-grid" id="{key_prefix}_grid">{buttons_html}</div>
            <script>
              const grid = document.getElementById({json.dumps(f"{key_prefix}_grid")});
              const scrollToAnchor = (anchorId) => {{
                const doc = window.parent.document;
                const el = doc.getElementById(anchorId);
                if (!el) return false;
                el.scrollIntoView({{ behavior: "smooth", block: "start" }});
                return true;
              }};
              grid?.addEventListener("click", (e) => {{
                const btn = e.target.closest("button[data-anchor]");
                if (!btn) return;
                const anchorId = btn.getAttribute("data-anchor");
                if (!anchorId) return;
                if (scrollToAnchor(anchorId)) return;
                let attempts = 0;
                const timer = setInterval(() => {{
                  attempts += 1;
                  if (scrollToAnchor(anchorId) || attempts >= 20) clearInterval(timer);
                }}, 150);
              }});
            </script>
            """,
            height=height,
        )

def get_home_stock_anchor_id(ticker: str) -> str:
    safe_ticker = "".join(ch if ch.isalnum() else "-" for ch in str(ticker))
    return f"home-stock-{safe_ticker}"

def consume_pending_scroll_anchor():
    anchor_id = st.session_state.pop("pending_scroll_target", None)
    if not anchor_id:
        return
    components.html(
        f"""
        <script>
        const anchorId = {json.dumps(anchor_id)};
        let attempts = 0;
        const scrollToAnchor = () => {{
            const doc = window.parent.document;
            const target = doc.getElementById(anchorId);
            if (target) {{
                target.scrollIntoView({{ behavior: "smooth", block: "start" }});
                return true;
            }}
            return false;
        }};
        if (!scrollToAnchor()) {{
            const timer = setInterval(() => {{
                attempts += 1;
                if (scrollToAnchor() || attempts >= 20) {{
                    clearInterval(timer);
                }}
            }}, 150);
        }}
        </script>
        """,
        height=0,
    )


def render_top_navigation():
    current_page = st.session_state.get("current_page", "home")

    st.caption("快捷導航")
    quick_cols = st.columns(3)
    with quick_cols[0]:
        if st.button("🏠 總覽", key="quick_nav_home", use_container_width=True, type="primary" if current_page == "home" else "secondary"):
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
        if st.button(active_labels["home"] if current_page == "home" else labels["home"], key="bottom_nav_home", use_container_width=True, type="primary" if current_page == "home" else "secondary"):
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
    render_section_anchor_nav_frontend("單股導航", "點擊後自動滾動到對應區段，保留整頁內容連續瀏覽。", sections, "stock_anchor")
    return "all"

def render_comparison_section_navigation() -> str:
    sections = [
        ("comparison-trend", "SMA趨勢"),
        ("comparison-mr", "MR偏差"),
        ("comparison-cdm", "CDM狀態"),
        ("comparison-amp", "振幅對比"),
        ("comparison-score", "綜合評分"),
    ]
    render_section_anchor_nav_frontend("比較頁導航", "點擊後自動滾動到對應區段，適合快速查看不同排序表。", sections, "comparison_anchor")
    return "trend"

def render_backtest_section_navigation() -> str:
    sections = [
        ("backtest-settings", "回測設定"),
        ("backtest-single", "單策略回測"),
        ("backtest-compare", "策略對標"),
        ("backtest-recommend", "策略推薦"),
    ]
    render_section_anchor_nav_frontend("回測導航", "點擊後自動滾動到對應區段，方便在設定、對標與推薦間切換。", sections, "backtest_anchor")
    return "settings"

def render_home_section_navigation(watchlist_list: List[str]) -> str:
    if not watchlist_list:
        render_navigation_expander()
        return "home"
    sections = [(get_home_stock_anchor_id(ticker), ticker) for ticker in watchlist_list]
    render_section_anchor_nav_frontend("總覽導航", "按收藏股票快速定位到首頁對應區塊，保留整頁連續瀏覽。", sections, "home_anchor")
    return "home"

def render_sidebar_context_navigation(watchlist_list: List[str]):
    current_page = st.session_state.get("current_page", "home")
    if current_page == "stock":
        render_stock_section_navigation()
    elif current_page == "comparison":
        render_comparison_section_navigation()
    elif current_page == "backtest":
        render_backtest_section_navigation()
    elif current_page == "home":
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
    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)
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
        st.rerun()

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
    nav_slot = st.empty()
    
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
                            try:
                                shares_outstanding = t_obj.fast_info.get('shares', None)
                            except Exception:
                                shares_outstanding = None
                            if not shares_outstanding:
                                shares_outstanding = t_obj.info.get('sharesOutstanding', None)
                            if shares_outstanding:
                                d["Turnover_Rate"] = (d["Volume"] / float(shares_outstanding)) * 100
                        except Exception:
                            pass
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
    
    st.subheader(f"我的收藏 ({len(watchlist_list)})")
    if watchlist_list:
        for ticker in watchlist_list:
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                set_current_page("stock", ticker)
                st.rerun()
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

# --- 7. 主程式邏輯 ---
current_code = st.session_state.current_view
current_page = st.session_state.current_page
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')
sma1 = int(st.session_state.get("sma1", 20))
sma2 = int(st.session_state.get("sma2", 50))

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

elif current_page == "home":
    st.title("📊 港股 SMA 矩陣 - 收藏總覽")
    
    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        snapshot = get_home_watchlist_snapshot(watchlist_list, str(st.session_state.ref_date))
        summary_rows = snapshot.get("summaries", [])
        detail_map = snapshot.get("details", {})

        c_btn_1, c_btn_2 = st.columns(2)
        with c_btn_1:
            if st.button("🔄 刷新所有數據", use_container_width=True):
                st.rerun()
        with c_btn_2:
            if st.button("📊 比較模式", use_container_width=True, type="primary"):
                set_current_page("comparison")
                st.rerun()
        st.write("---")

        if not summary_rows:
            st.warning("目前沒有足夠數據可生成收藏股列表。")
        else:
            sort_options = ["Dev 0", "Dev 3", "Dev 7", "Dev 14", "Dev 28", "Dev 57", "Dev 106"]
            if "home_sort_metric" not in st.session_state:
                st.session_state.home_sort_metric = "Dev 3"
            if "home_sort_desc" not in st.session_state:
                st.session_state.home_sort_desc = True

            ctrl_1, ctrl_2 = st.columns([1.4, 1])
            with ctrl_1:
                st.session_state.home_sort_metric = st.selectbox(
                    "排序欄位",
                    sort_options,
                    index=sort_options.index(st.session_state.home_sort_metric if st.session_state.home_sort_metric in sort_options else "Dev 3"),
                    key="home_sort_metric_select",
                )
            with ctrl_2:
                st.session_state.home_sort_desc = st.selectbox(
                    "排序方式",
                    [True, False],
                    index=0 if st.session_state.home_sort_desc else 1,
                    format_func=lambda v: "由高到低" if v else "由低到高",
                    key="home_sort_order_select",
                )

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

            st.caption("打開 App 即進入收藏股列表；點擊 Code 會在下方顯示 TOR、Amp、SMA 統計。")
            header_cols = st.columns([1.15, 1, 1, 1, 1, 1, 1, 1, 1])
            headers = ["Code", "CPRD", "Dev 0", "Dev 3", "Dev 7", "Dev 14", "Dev 28", "Dev 57", "Dev 106"]
            for col, header in zip(header_cols, headers):
                col.markdown(f"**{header}**")

            for row in sorted_rows:
                ticker = row["Code"]
                render_scroll_anchor(get_home_stock_anchor_id(ticker))
                row_cols = st.columns([1.15, 1, 1, 1, 1, 1, 1, 1, 1])
                with row_cols[0]:
                    if st.button(
                        ticker,
                        key=f"home_code_{ticker}",
                        use_container_width=True,
                        type="primary" if ticker == st.session_state.home_selected_ticker else "secondary",
                    ):
                        st.session_state.home_selected_ticker = ticker
                        st.rerun()
                row_cols[1].markdown(_fmt_num(row.get("CPRD")))
                row_cols[2].markdown(_fmt_pct(row.get("Dev 0")))
                row_cols[3].markdown(_fmt_pct(row.get("Dev 3")))
                row_cols[4].markdown(_fmt_pct(row.get("Dev 7")))
                row_cols[5].markdown(_fmt_pct(row.get("Dev 14")))
                row_cols[6].markdown(_fmt_pct(row.get("Dev 28")))
                row_cols[7].markdown(_fmt_pct(row.get("Dev 57")))
                row_cols[8].markdown(_fmt_pct(row.get("Dev 106")))
                st.divider()

            selected_ticker = st.session_state.home_selected_ticker
            detail = detail_map.get(selected_ticker)
            if detail:
                st.subheader(f"📌 {selected_ticker} 統計數據")
                meta_col_1, meta_col_2, meta_col_3 = st.columns([1.2, 1.2, 1])
                meta_col_1.metric("日期", detail["date"])
                meta_col_2.metric("Current price", _fmt_num(detail["current_price"]))
                with meta_col_3:
                    if st.button("查看單股詳情", key=f"view_stock_{selected_ticker}", use_container_width=True):
                        set_current_page("stock", selected_ticker)
                        st.rerun()

                st.caption("TOR / Amp 的 7、14、28、57、106 為區間平均值；CP 依本次實作解讀為前一交易日收盤價。")

                dev_df = pd.DataFrame([{"CPRD": detail["cp"], **detail["dev"]}])
                tor_df = pd.DataFrame([detail["tor"]])
                amp_df = pd.DataFrame([detail["amp"]])
                sma_df = pd.DataFrame(
                    [
                        {
                            "Current price": detail["current_price"],
                            "CP": detail["cp"],
                            **detail["sma"],
                        }
                    ]
                )

                st.markdown("**Dev 列表**")
                st.dataframe(
                    dev_df.style.format(
                        {
                            "CPRD": "{:.2f}",
                            "Dev 0": "{:+.2f}%",
                            "Dev 3": "{:+.2f}%",
                            "Dev 7": "{:+.2f}%",
                            "Dev 14": "{:+.2f}%",
                            "Dev 28": "{:+.2f}%",
                            "Dev 57": "{:+.2f}%",
                            "Dev 106": "{:+.2f}%",
                        },
                        na_rep="-",
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

                st.markdown("**TOR (Turn Over Ratio)**")
                st.dataframe(
                    tor_df.style.format({col: "{:.2f}%" for col in tor_df.columns}, na_rep="-"),
                    hide_index=True,
                    use_container_width=True,
                )

                st.markdown("**Amplitude**")
                st.dataframe(
                    amp_df.style.format({col: "{:.2f}%" for col in amp_df.columns}, na_rep="-"),
                    hide_index=True,
                    use_container_width=True,
                )

                st.markdown("**SMA**")
                st.dataframe(
                    sma_df.style.format({col: "{:.2f}" for col in sma_df.columns}, na_rep="-"),
                    hide_index=True,
                    use_container_width=True,
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
                remove_stock_from_db(current_code)
                st.rerun()
        else:
            if st.button("☆ 加入", use_container_width=True):
                update_stock_in_db(current_code)
                st.rerun()

    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)

    if df is not None and len(df) > 5:
        # 0. 基礎計算
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma: df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
        if f'SMA_{sma1}' not in df.columns: df[f'SMA_{sma1}'] = df['Close'].rolling(sma1).mean()
        if f'SMA_{sma2}' not in df.columns: df[f'SMA_{sma2}'] = df['Close'].rolling(sma2).mean()

        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
            # 增加 v9.6 的 BS Analysis 計算
            df = simulate_bs_data(df, shares_outstanding)
        else:
            df['Turnover_Rate'] = 0.0

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

        curr_close = float(df['Close'].iloc[-1])
        prev_close = df['Close'].shift(1).iloc[-1]
        prev_close = float(prev_close) if pd.notna(prev_close) else 0.0
        curr_open = float(df['Open'].iloc[-1])
        curr_high = float(df['High'].iloc[-1])
        curr_low = float(df['Low'].iloc[-1])
        chg = (curr_close - prev_close) if prev_close else 0.0
        pct = (chg / prev_close * 100) if prev_close else 0.0
        amp = ((curr_high - curr_low) / prev_close * 100) if prev_close else 0.0

        delta_cls = "pos" if chg >= 0 else "neg"
        summary_cards = f"""
        <div class="compact-grid">
            <div class="compact-card">
                <div class="label">現價</div>
                <div class="value">{curr_close:.3f}</div>
                <div class="sub {delta_cls}">{chg:+.3f} ({pct:+.2f}%)</div>
            </div>
            <div class="compact-card">
                <div class="label">前收市</div>
                <div class="value">{f"{prev_close:.3f}" if prev_close else "-"}</div>
            </div>
            <div class="compact-card">
                <div class="label">開市</div>
                <div class="value">{curr_open:.3f}</div>
            </div>
            <div class="compact-card">
                <div class="label">波幅(AA)</div>
                <div class="value">{f"{amp:.2f}%" if prev_close else "-"}</div>
            </div>
            <div class="compact-card">
                <div class="label">最高</div>
                <div class="value">{curr_high:.3f}</div>
            </div>
            <div class="compact-card">
                <div class="label">最低</div>
                <div class="value">{curr_low:.3f}</div>
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
                show_cols = [c for c in ["Open", "High", "Low", "Close", "Volume", "Turnover_Rate"] if c in df.columns]
                if show_cols:
                    st.dataframe(df[show_cols].tail(60), use_container_width=True)
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

                        update_stock_in_db(
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
                        )
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
                    st.error("無流通股數數據。")
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

render_bottom_navigation()
consume_pending_scroll_anchor()
