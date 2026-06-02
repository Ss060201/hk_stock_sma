import streamlit as st
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
from typing import Dict, Any, Optional, List
from firebase_admin.exceptions import FirebaseError

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

# --- 輔助功能 ---
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
        if watchlist_list:
            for ticker in watchlist_list:
                if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                    st.session_state.current_view = ticker
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
                    
                    t_obj = yf.Ticker(yt)
                    try: tsi = t_obj.fast_info.get('shares', None)
                    except: tsi = None
                    if tsi is None: 
                        try: tsi = t_obj.info.get('sharesOutstanding', 100000000)
                        except: tsi = 100000000
                    
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
            btn_label = "★" if is_in_watchlist else "☆"
            if st.button(btn_label, use_container_width=True, key="mobile_fav"):
                if is_in_watchlist:
                    remove_stock_from_db(current_code)
                else:
                    update_stock_in_db(current_code)
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
                    remove_stock_from_db(current_code)
                    st.rerun()
            else:
                if st.button("☆ 加入", use_container_width=True):
                    update_stock_in_db(current_code)
                    st.rerun()
    
    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        try:
            df = yf.download(symbol, period="3y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex): 
                df.columns = df.columns.get_level_values(0)
            df = df[df.index <= pd.to_datetime(end_date)]
            t = yf.Ticker(symbol)
            try: s = t.fast_info.get('shares', None)
            except: s = t.info.get('sharesOutstanding', None)
            return df, s
        except: 
            return None, None
    
    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)
    
    if df is not None and len(df) > 5:
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma: 
            df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
        if f'SMA_{sma1}' not in df.columns: 
            df[f'SMA_{sma1}'] = df['Close'].rolling(sma1).mean()
        if f'SMA_{sma2}' not in df.columns: 
            df[f'SMA_{sma2}'] = df['Close'].rolling(sma2).mean()
        
        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
            df = simulate_bs_data(df, shares_outstanding)
        else:
            df['Turnover_Rate'] = 0.0
        
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
        curr_close = float(df['Close'].iloc[-1])
        prev_close = df['Close'].shift(1).iloc[-1]
        prev_close = float(prev_close) if pd.notna(prev_close) else 0.0
        curr_open = float(df['Open'].iloc[-1])
        curr_high = float(df['High'].iloc[-1])
        curr_low = float(df['Low'].iloc[-1])
        chg = (curr_close - prev_close) if prev_close else 0.0
        pct = (chg / prev_close * 100) if prev_close else 0.0
        amp = ((curr_high - curr_low) / prev_close * 100) if prev_close else 0.0
        
        if is_mobile:
            st.metric("現價", f"{curr_close:.3f}", f"{chg:+.3f} ({pct:+.2f}%)")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("開市", f"{curr_open:.3f}")
            with col2:
                st.metric("最高", f"{curr_high:.3f}")
            with col3:
                st.metric("最低", f"{curr_low:.3f}")
        else:
            c_sum_1, c_sum_2 = st.columns(2)
            with c_sum_1:
                st.metric("現價", f"{curr_close:.3f}", f"{chg:+.3f} ({pct:+.2f}%)")
                st.metric("前收市", f"{prev_close:.3f}" if prev_close else "-")
                st.metric("波幅(AA)", f"{amp:.2f}%" if prev_close else "-")
            with c_sum_2:
                st.metric("開市", f"{curr_open:.3f}")
                st.metric("最高", f"{curr_high:.3f}")
                st.metric("最低", f"{curr_low:.3f}")
        
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
