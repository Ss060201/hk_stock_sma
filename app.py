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

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣 v9.7 (整合版)", page_icon="📈", layout="wide")

# --- 2. CSS 樣式 (合併 v9.4 與 v9.6) ---
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
    .stButton>button { width: 100%; height: 3em; font-size: 18px; }
</style>
""", unsafe_allow_html=True)

# --- 3. 數據庫連接 (Firebase) ---
@st.cache_resource
def get_db():
    try:
        if not firebase_admin._apps:
            if "firebase" in st.secrets:
                if "json_content" in st.secrets["firebase"]:
                    try:
                        key_dict = json.loads(st.secrets["firebase"]["json_content"])
                        cred = credentials.Certificate(key_dict)
                        firebase_admin.initialize_app(cred)
                    except json.JSONDecodeError:
                        return None
                elif "private_key" in st.secrets["firebase"]:
                    try:
                        key_dict = dict(st.secrets["firebase"])
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
    data = {symbol: params if params else {
        "box1_start": "", "box1_end": "",
        "box2_start": "", "box2_end": ""
    }}
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
    
    # CDM 運算
    cdm_status, target_price_str, diff_str = "未設定參數", "N/A", "N/A"
    b1_s = params.get('box1_start')
    b1_e = params.get('box1_end')
    b2_s = params.get('box2_start')
    b2_e = params.get('box2_end')

    if b1_s and b1_e and b2_s and b2_e:
        try:
            s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
            s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)
            sma1 = df[(df.index >= s1) & (df.index <= e1)]['Close'].mean()
            sma2 = df[(df.index >= s2) & (df.index <= e2)]['Close'].mean()
            t1_days = (e1 - s1).days
            n_days = (pd.to_datetime(today) - s1).days
            
            if n_days > 0:
                p_target = (sma1 * CDM_COEF1 * (t1_days/n_days)) + (sma2 * CDM_COEF2 * ((n_days - t1_days)/n_days))
                if pd.notna(p_target) and p_target != 0:
                    diff = abs(curr_price - p_target) / p_target
                    target_price_str = f"{p_target:.2f}"
                    diff_str = f"{diff*100:.2f}"
                    cdm_status = "🔴 <b>觸發</b>" if diff < CDM_THRESHOLD else "未觸發"
        except: pass
    
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

    report = f"""<b>[股票警示] {symbol} 分析報告</b>
<b>1. CDM: {cdm_status}</b> (目標: {target_price_str}, 偏差: {diff_str}%)
<b>2. FZM: {fzm_status}</b> (WR: {val_willr:.2f}, {trend_str})
建議止損: {lowest_low:.2f}
"""
    return report

# --- 5. 初始化 Session State ---
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# --- 6. 側邊欄 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    # Telegram 設定
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
                        d = yf.download(yt, period="6mo", progress=False, auto_adjust=False)
                        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
                        if len(d) > 50:
                            w = get_watchlist_from_db()
                            msg = run_analysis_logic(d, st.session_state.current_view, w.get(st.session_state.current_view, {}))
                            ok, res = send_telegram_msg(tg_token, tg_chat_id, msg)
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

    search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
    if search_input:
        cleaned = clean_ticker_input(search_input)
        if cleaned: st.session_state.current_view = cleaned

    st.divider()
    
    # 收藏夾導航
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

# --- 7. 主程式邏輯 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

# === 模式 A: 總覽模式 (v9.6 Logic) ===
if not current_code:
    st.title("📊 港股 SMA 矩陣 - 收藏總覽")
    
    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        if st.button("🔄 刷新所有數據"): st.rerun()
        st.write("---")
        
        # 遍歷收藏清單，顯示卡片
        for ticker in watchlist_list:
            yt = get_yahoo_ticker(ticker)
            with st.spinner(f"正在分析 {ticker}..."):
                try:
                    df_w = yf.download(yt, period="1y", progress=False, auto_adjust=False)
                    if isinstance(df_w.columns, pd.MultiIndex): df_w.columns = df_w.columns.get_level_values(0)
                    # 切割日期
                    end_dt = pd.to_datetime(st.session_state.ref_date)
                    df_w = df_w[df_w.index <= end_dt]

                    # 獲取 TSI
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
                        intervals = [7, 14, 28, 57, 106, 212]

                        # 1. Price Logic
                        avgp_vals = [curr_p]
                        for p in intervals:
                            avgp_vals.append(df_w['Close'].rolling(p).mean().iloc[-1] if len(df_w)>=p else 0)
                        valid_avgp = [v for v in avgp_vals if v > 0]
                        avg_avgp = sum(valid_avgp) / len(valid_avgp) if valid_avgp else 0
                        avgp_mr_vals = [((v / avg_avgp) - 1)*100 if avg_avgp else 0 for v in avgp_vals]

                        # 2. AMP Logic
                        df_w['AMP'] = (df_w['High'] - df_w['Low']) / prev_close_w * 100
                        val_amp0 = df_w['AMP'].iloc[-1]
                        amp_rolling_vals = []
                        for p in intervals:
                            amp_rolling_vals.append(df_w['AMP'].rolling(p).mean().iloc[-1] if len(df_w)>=p else 0)
                        
                        valid_rolling = [v for v in amp_rolling_vals if v > 0]
                        avg_amp = sum(valid_rolling) / len(valid_rolling) if valid_rolling else 0
                        amp_mr_vals = [((val_amp0 / avg_amp) - 1)*100 if avg_amp else 0] # MR0
                        for v in amp_rolling_vals:
                            amp_mr_vals.append(((v / avg_amp) - 1)*100 if avg_amp else 0)

                        # 3. Buy/Sell Analysis (v9.6 New Feature)
                        df_w = simulate_bs_data(df_w, tsi)
                        last_7 = df_w.iloc[-7:][::-1]
                        
                        # Data Prep
                        days_mmb = [f"{x:.4f}%" for x in last_7['MMB'].tolist()]
                        days_mms = [f"{x:.4f}%" for x in last_7['MMS'].tolist()]
                        days_rtb = [f"{x:.4f}%" for x in last_7['RTB'].tolist()]
                        days_rts = [f"{x:.4f}%" for x in last_7['RTS'].tolist()]
                        
                        while len(days_mmb) < 7: days_mmb.append("-")
                        while len(days_mms) < 7: days_mms.append("-")
                        while len(days_rtb) < 7: days_rtb.append("-")
                        while len(days_rts) < 7: days_rts.append("-")

                        sum_mmb, sum_mms, sum_rtb, sum_rts = [], [], [], []
                        for p in intervals:
                            if len(df_w) >= p:
                                sum_mmb.append(f"{df_w['MMB'].tail(p).sum():.4f}%")
                                sum_mms.append(f"{df_w['MMS'].tail(p).sum():.4f}%")
                                sum_rtb.append(f"{df_w['RTB'].tail(p).sum():.4f}%")
                                sum_rts.append(f"{df_w['RTS'].tail(p).sum():.4f}%")
                            else:
                                for l in [sum_mmb, sum_mms, sum_rtb, sum_rts]: l.append("-")

                        # --- Card HTML ---
                        html = f'<div style="margin-bottom: 30px; border: 1px solid #ddd; padding: 15px; border-radius: 8px; background-color: #f9f9f9;">'
                        chg_color = "#2ca02c" if chg > 0 else "#d62728" if chg < 0 else "#666"
                        html += f'<h4 style="margin-top:0;">{ticker} <span style="font-size:0.8em; color:#666;">Price: {curr_p:.2f}</span> <span style="font-size:0.8em; color:{chg_color};">({chg:+.2f}, {pct:+.2f}%)</span></h4>'
                        
                        # Price & AMP Table
                        html += '<table class="big-font-table">'
                        html += '<tr class="header-row"><td>Metric</td><td>Base</td><td>0</td><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td></tr>'
                        html += '<tr class="data-row"><td><b>AvgP</b></td><td>{:.2f}</td>'.format(avg_avgp) + "".join([f"<td>{v:.2f}</td>" for v in avgp_vals]) + '</tr>'
                        html += '<tr class="data-row"><td><b>AvgP MR</b></td><td>-</td>' + "".join([f"<td class='{'pos-val' if v>0 else 'neg-val'}'>{v:.2f}%</td>" for v in avgp_mr_vals]) + '</tr>'
                        html += '<tr class="data-row"><td><b>AMP MR</b></td><td>{:.2f}</td>'.format(avg_amp) + "".join([f"<td class='{'pos-val' if v>0 else 'neg-val'}'>{v:.2f}%</td>" for v in amp_mr_vals]) + '</tr>'
                        html += '</table>'

                        # BS Analysis Table
                        html += '<table class="big-font-table" style="margin-top: 10px;">'
                        html += '<tr class="header-row"><td>Day</td><td>0</td><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td></tr>'
                        for name, data in [("MMB", days_mmb), ("MMS", days_mms), ("RTB", days_rtb), ("RTS", days_rts)]:
                            html += f'<tr class="data-row"><td style="background-color:#fff !important; font-weight:bold;">{name}</td>' + "".join([f"<td>{d}</td>" for d in data]) + '</tr>'
                        html += '</table>'
                        
                        html += '</div>'
                        st.markdown(html, unsafe_allow_html=True)

                except Exception as e: st.error(f"Error {ticker}: {e}")

# === 模式 B: 單股詳細模式 (v9.4 + v9.6 Merged) ===
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

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

    # Reuse data fetching
    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        try:
            df = yf.download(symbol, period="3y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[df.index <= pd.to_datetime(end_date)]
            t = yf.Ticker(symbol)
            try: s = t.fast_info.get('shares', None)
            except: s = t.info.get('sharesOutstanding', None)
            return df, s
        except: return None, None

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

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("現價", f"{curr_close:.3f}", f"{chg:+.3f} ({pct:+.2f}%)")
        m2.metric("前收市", f"{prev_close:.3f}" if prev_close else "-")
        m3.metric("開市", f"{curr_open:.3f}")
        m4.metric("最高", f"{curr_high:.3f}")
        m5.metric("最低", f"{curr_low:.3f}")
        st.metric("波幅(AA)", f"{amp:.2f}%" if prev_close else "-")

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

            if df_range.empty:
                st.warning("選取時段沒有數據")
            else:
                periods_interactive = [7, 14, 28, 57, 106, 212]
                for p in periods_interactive:
                    df_range[f"SMA{p}"] = df_range["Close"].rolling(window=p).mean()
                df_range["WR"] = calculate_willr(df_range["High"], df_range["Low"], df_range["Close"], 35)

                last = df_range.iloc[-1]
                curr_price_r = float(last["Close"]) if pd.notna(last["Close"]) else np.nan

                st.markdown("**時段 SMA（最後一天）**")
                sma_cols = st.columns(6)
                for i, p in enumerate(periods_interactive):
                    v = last.get(f"SMA{p}", np.nan)
                    sma_cols[i].metric(f"SMA{p}", "-" if pd.isna(v) else f"{float(v):.3f}")

                val_sma7 = last.get("SMA7", np.nan)
                val_sma14 = last.get("SMA14", np.nan)
                val_wr = last.get("WR", np.nan)

                cond_a = (curr_price_r > val_sma7) and (curr_price_r > val_sma14)
                cond_b = (val_wr < -80)
                fzm_trigger = bool(cond_a and cond_b)
                trend_str = "站上雙均線" if cond_a else "均線下方"

                labels = ["Price", "SMA7", "SMA14", "SMA28", "SMA57", "SMA106", "SMA212"]
                vals = [
                    curr_price_r,
                    last.get("SMA7", np.nan),
                    last.get("SMA14", np.nan),
                    last.get("SMA28", np.nan),
                    last.get("SMA57", np.nan),
                    last.get("SMA106", np.nan),
                    last.get("SMA212", np.nan),
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
                    if mr_count >= 3:
                        mr_trigger = True
                else:
                    for label, v in zip(labels, vals):
                        if pd.notna(v):
                            mr_rows.append({"項目": label, "值": float(v), "MR(%)": np.nan})

                st.markdown("**模式狀態（以時段最後一天計）**")
                c_mode_1, c_mode_2 = st.columns(2)
                with c_mode_1:
                    st.markdown(f"超底模式：{'🔴 觸發' if fzm_trigger else '未觸發'}")
                    st.write(f"現價: {'-' if pd.isna(curr_price_r) else f'{curr_price_r:.3f}'}")
                    st.write(f"SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}")
                    st.write(f"WillR(35): {'-' if pd.isna(val_wr) else f'{float(val_wr):.2f}'} ({trend_str})")
                with c_mode_2:
                    st.markdown(f"振蕩模式：{'🔴 觸發' if mr_trigger else '未觸發'}")
                    st.write(f"基準均價: {avg_of_avgs:.3f}" if avg_of_avgs else "基準均價: -")
                    st.write(f"高乖離數(>0.62%): {mr_count}")
                    if mr_trigger:
                        st.write("矩陣突波")

                if mr_rows:
                    st.dataframe(pd.DataFrame(mr_rows), hide_index=True, use_container_width=True)

        # 2. CDM 設定
        if is_in_watchlist:
            with st.expander("⚙️ 設定 CDM 自動監測參數", expanded=False):
                curr_params = watchlist_data.get(current_code, {})
                c1, c2 = st.columns(2)
                with c1:
                    val_b1s = pd.to_datetime(curr_params.get('box1_start')).date() if curr_params.get('box1_start') else None
                    val_b1e = pd.to_datetime(curr_params.get('box1_end')).date() if curr_params.get('box1_end') else None
                    new_b1_s = st.date_input("Box 1 Start", value=val_b1s)
                    new_b1_e = st.date_input("Box 1 End", value=val_b1e)
                with c2:
                    val_b2s = pd.to_datetime(curr_params.get('box2_start')).date() if curr_params.get('box2_start') else None
                    val_b2e = pd.to_datetime(curr_params.get('box2_end')).date() if curr_params.get('box2_end') else None
                    new_b2_s = st.date_input("Box 2 Start", value=val_b2s)
                    new_b2_e = st.date_input("Box 2 End", value=val_b2e)
                
                if st.button("💾 儲存參數"):
                    update_stock_in_db(current_code, {
                        "box1_start": str(new_b1_s) if new_b1_s else "", "box1_end": str(new_b1_e) if new_b1_e else "",
                        "box2_start": str(new_b2_s) if new_b2_s else "", "box2_end": str(new_b2_e) if new_b2_e else ""
                    })
                    st.rerun()


        # --- D. 數據呈現 ---
        req_len = 13
        if len(df) < req_len:
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
            st.plotly_chart(fig_sma_trend, use_container_width=True, config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "responsive": True})

           # 2. SMA Matrix (New Format v10.0)
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
            st.markdown(pi_html, unsafe_allow_html=True)

            # 3. Turnover Matrix (此行不用複製，已存在於你的代碼下方)


            # 3. Turnover Matrix
            st.subheader("📋 Turnover Rate Matrix")
            if not has_turnover:
                st.error("無流通股數數據。")
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

    st.markdown("---")
    st.markdown("### 📚 歷史功能與圖表")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume (Abs)", "💹 Turnover Analysis (Old)"])

    end_date_dt = pd.to_datetime(st.session_state.ref_date)
    start_date_6m = end_date_dt - timedelta(days=180)
    display_df = df[df.index >= start_date_6m]

    # Tab 1
    with tab1:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'], low=display_df['Low'], close=display_df['Close'], name='K線'))
        if f'SMA_{sma1}' in display_df.columns: fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], line=dict(color='orange'), name=f'SMA {sma1}'))
        if f'SMA_{sma2}' in display_df.columns: fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], line=dict(color='blue'), name=f'SMA {sma2}'))
        fig.update_layout(height=500, xaxis_rangeslider_visible=True, template="plotly_white", dragmode="pan", uirevision=f"hist_price_{current_code}")
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False, "responsive": True})


    # Tab 2
    with tab2:
        fig_r = go.Figure()
        if 'R1' in display_df.columns: fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R1'], name="R1 (S7/S14)"))
        if 'R2' in display_df.columns: fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R2'], name="R2 (S7/S28)"))
        st.plotly_chart(fig_r, use_container_width=True)

    # Tab 3
    with tab3:
        st.bar_chart(display_df['Volume'])

    # Tab 4
    with tab4:
        if has_turnover: st.line_chart(display_df['Turnover_Rate'])



