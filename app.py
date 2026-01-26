import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import requests

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股矩陣 Pro v7.7 (Fast)", page_icon="⚡", layout="wide")

# URL 狀態管理
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""
# 初始化日期基準
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()

# --- 2. 輔助函數 ---
def clean_ticker_input(symbol):
    # 移除空白、.HK 後綴，確保是純數字或英數
    s = str(symbol).strip().upper().replace(" ", "").replace(".HK", "")
    return s

def get_yahoo_ticker(symbol):
    # 針對港股：如果是純數字，補齊 4 位並加 .HK
    if symbol.isdigit():
        return f"{symbol.zfill(4)}.HK"
    return symbol

def toggle_watchlist(ticker):
    clean_code = clean_ticker_input(ticker)
    if clean_code in st.session_state.watchlist:
        st.session_state.watchlist.remove(clean_code)
        st.toast(f'已移除 {clean_code}', icon="🗑️")
    else:
        st.session_state.watchlist.append(clean_code)
        st.toast(f'已收藏 {clean_code}', icon="⭐")

# --- CSS 樣式 (大字體手機優化) ---
def render_custom_css():
    st.markdown("""
        <style>
        .big-font-table { width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px; }
        .big-font-table th { background-color: #f0f2f6; color: #31333F; font-weight: bold; padding: 8px; border: 1px solid #ddd; font-size: 16px; text-align: center; }
        .big-font-table td { padding: 10px; border: 1px solid #ddd; text-align: center; font-size: 18px; color: #000; }
        .highlight-row { background-color: #e8f5e9; }
        .section-header { background-color: #31333F; color: white !important; font-size: 16px; text-align: left !important; padding-left: 10px !important; }
        .table-container { overflow-x: auto; }
        .stButton button { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. 側邊欄 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    st.caption(f"基準日: {st.session_state.ref_date}")
    
    search_input = st.text_input("輸入股票代號", placeholder="例如: 5 或 0005", key="search_bar")
    if search_input:
        cleaned = clean_ticker_input(search_input)
        if cleaned: st.session_state.current_view = cleaned

    st.divider()
    st.subheader(f"收藏 ({len(st.session_state.watchlist)})")
    if st.session_state.watchlist:
        for ticker in st.session_state.watchlist:
            if st.button(ticker, key=f"nav_{ticker}"):
                st.session_state.current_view = ticker

    st.divider()
    st.caption("SMA 參數")
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 核心數據獲取 (優化版：只下載一次) ---
@st.cache_data(ttl=3600) # 緩存 1 小時，避免重複下載
def fetch_stock_data_raw(symbol):
    """
    下載完整的歷史數據 (5年)，不進行日期過濾。
    這樣切換日期時不需要重新下載。
    """
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'})

    max_retries = 3
    df = pd.DataFrame()
    shares = None

    for attempt in range(max_retries):
        try:
            # 下載 5 年數據，確保 SMA212 絕對夠用
            df = yf.download(symbol, period="5y", auto_adjust=False, session=session, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                break
        except Exception:
            time.sleep(1 + attempt) # 失敗退避

    if df.empty:
        return None, None

    # 獲取股本
    try:
        ticker_obj = yf.Ticker(symbol, session=session)
        shares = ticker_obj.fast_info.get('shares', None)
        if shares is None:
            shares = ticker_obj.info.get('sharesOutstanding', None)
    except:
        pass
        
    return df, shares

# --- 5. 數據處理 (記憶體運算) ---
def process_data_for_date(raw_df, target_date, shares_outstanding):
    """
    在記憶體中切割數據，不聯網。
    """
    # 1. 切割日期：取 <= target_date 的數據
    target_dt = pd.to_datetime(target_date)
    df = raw_df[raw_df.index <= target_dt].copy()
    
    if df.empty:
        return None, "日期早於上市日"
    
    if len(df) < 215:
        return None, f"歷史數據不足 (僅 {len(df)} 天)，無法計算 SMA212"

    # 2. 計算 SMA
    periods = [7, 14, 28, 57, 106, 212]
    for p in periods:
        df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

    # 3. 安全除法函數
    def safe_div(n, d): return np.where(d != 0, n / d, 0)

    # 4. SMAC
    df['SMAC_1'] = (1 - safe_div(df['SMA_7'], df['SMA_57'])) * 100
    df['SMAC_2'] = safe_div((df['SMA_14'] - df['SMA_7']), df['SMA_106']) * 100
    df['SMAC_3'] = safe_div((df['SMA_28'] - df['SMA_14']), df['SMA_106']) * 100
    df['SMAC_4'] = safe_div((df['SMA_57'] - df['SMA_28']), df['SMA_106']) * 100
    df['SMAC_5'] = safe_div((df['SMA_106'] - df['SMA_57']), df['SMA_106']) * 100
    df['SMAC_6'] = safe_div(df['SMA_7'], df['SMA_106']) * 100

    # 5. Turnover
    if shares_outstanding:
        df['TOR'] = (df['Volume'] / shares_outstanding) * 100
    else:
        df['TOR'] = 0
        
    for p in periods:
        df[f'Sum_TOR_{p}'] = df['TOR'].rolling(window=p).sum()
        df[f'Max_TOR_{p}'] = df['TOR'].rolling(window=p).max()
        df[f'Min_TOR_{p}'] = df['TOR'].rolling(window=p).min()

    # 6. AVGTOR
    df['AVGTOR_1'] = safe_div((df['SMA_14'] - df['SMA_7']), df['SMA_106'])
    df['AVGTOR_2'] = safe_div((df['SMA_28'] - df['SMA_14']), df['SMA_106']) / 2
    df['AVGTOR_3'] = safe_div((df['SMA_57'] - df['SMA_28']), df['SMA_106']) * 7 / 29
    df['AVGTOR_4'] = safe_div((df['SMA_106'] - df['SMA_57']), df['SMA_106']) / 7
    df['AVGTOR_7'] = 0

    return df, None

# --- 6. 主程式 ---
render_custom_css()
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

if not current_code:
    st.title("港股矩陣 Pro v7.7")
    st.info("👈 請輸入代號")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    c1, c2 = st.columns([0.8, 0.2])
    with c1: st.title(f"📊 {display_ticker}")
    with c2:
        if st.button("收藏/移除", use_container_width=True):
            toggle_watchlist(current_code)
            st.rerun()

    # --- 步驟 1: 下載完整數據 (只執行一次) ---
    with st.spinner("正在連線數據庫..."):
        raw_df, shares = fetch_stock_data_raw(yahoo_ticker)

    # 檢查下載結果
    if raw_df is None or raw_df.empty:
        st.error(f"❌ 無法獲取 {yahoo_ticker} 數據。")
        st.warning("排查建議：\n1. 確認代號正確 (如 0005)\n2. Yahoo Finance 可能暫時封鎖，請等待 1 分鐘後重試。")
    else:
        # 手動輸入股本補救
        if shares is None:
            with st.sidebar:
                st.warning("⚠️ 缺流通股數")
                man_shares = st.number_input("手動輸入股數", 0, value=0)
                if man_shares > 0: shares = man_shares

        # --- 步驟 2: 記憶體切割與計算 (秒級運算) ---
        df, err_msg = process_data_for_date(raw_df, st.session_state.ref_date, shares)

        if df is None:
            st.error(f"⚠️ 計算失敗: {err_msg}")
        else:
            # 獲取實際交易日 (自動對齊)
            curr = df.iloc[-1]
            actual_date = df.index[-1].date()
            
            # 提示日期校正
            if actual_date != st.session_state.ref_date:
                st.toast(f"已自動校正至最近交易日: {actual_date}", icon="📅")

            # --- 步驟 3: 構建 HTML 表格 ---
            periods = [7, 14, 28, 57, 106, 212]
            
            # SMA Matrix Data
            sma_hist_h = "".join([f"<th>D{i}</th>" for i in range(2, 8)])
            sma_hist_d = "".join([f"<td>{df['Close'].iloc[-i]:.2f}</td>" for i in range(2, 8)])
            
            sma_rows = ""
            for p in periods:
                pmax = df['Close'].rolling(p).max().iloc[-1]
                pmin = df['Close'].rolling(p).min().iloc[-1]
                sma_rows += f"<tr><td>{p}</td><td>{pmax:.2f}</td><td>{pmin:.2f}</td><td style='color:blue;font-weight:bold'>{curr[f'SMA_{p}']:.2f}</td></tr>"

            smac_lbl = "".join([f"<th>SMAC{i}</th>" for i in range(1, 7)])
            smac_dat = "".join([f"<td>{curr[f'SMAC_{i}']:.2f}%</td>" for i in range(1, 7)])

            # Turnover Matrix Data
            tr1_lbl = "".join([f"<th>D{i}</th>" for i in range(2, 8)])
            tr1_dat = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(2, 8)])
            tr2_lbl = "".join([f"<th>D{i}</th>" for i in range(8, 14)])
            tr2_dat = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(8, 14)])
            
            int_lbl = "".join([f"<th>{p}</th>" for p in periods])
            sum_tor = "".join([f"<td>{curr[f'Sum_TOR_{p}']:.2f}%</td>" for p in periods])
            max_tor = "".join([f"<td>{curr[f'Max_TOR_{p}']:.3f}%</td>" for p in periods])
            min_tor = "".join([f"<td>{curr[f'Min_TOR_{p}']:.3f}%</td>" for p in periods])
            
            avg_lbl = "".join([f"<th>AVG{i}</th>" for i in range(1, 7)])
            avg_dat = "".join([f"<td>{curr[f'AVGTOR_{i}']:.4f}</td>" for i in range(1, 7)])

            # --- 步驟 4: 介面渲染 ---
            
            # 上部：控制 + 曲線
            c_ctrl, c_curve = st.columns([0.25, 0.75])
            with c_ctrl:
                st.write("#### 日期控制")
                if st.button("◀ -1天", use_container_width=True):
                    st.session_state.ref_date -= timedelta(days=1)
                    st.rerun()
                st.markdown(f"<div style='text-align:center;font-size:18px;font-weight:bold;margin:10px 0;color:#333'>{actual_date}</div>", unsafe_allow_html=True)
                if st.button("▶ +1天", use_container_width=True):
                    st.session_state.ref_date += timedelta(days=1)
                    st.rerun()

            with c_curve:
                curve_df = df.tail(30)
                fig = go.Figure()
                for p in [7, 28, 106]:
                    fig.add_trace(go.Scatter(x=curve_df.index, y=curve_df[f'SMA_{p}'], name=f"SMA{p}", mode='lines'))
                fig.add_trace(go.Scatter(x=curve_df.index, y=curve_df['TOR'], name="TOR%", line=dict(dash='dot', width=1), yaxis="y2"))
                fig.update_layout(height=300, margin=dict(t=10,b=10,l=10,r=10), legend=dict(orientation="h", y=1.1),
                                  yaxis2=dict(overlaying="y", side="right", showgrid=False))
                st.plotly_chart(fig, use_container_width=True)

            st.divider()

            # 下部：矩陣 Tab
            tab_main, tab_chart = st.tabs(["📊 核心矩陣", "📉 K線"])

            with tab_main:
                st.markdown("### 1. SMA Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">Close History (Day 2-7)</th></tr>
                        <tr class="highlight-row">{sma_hist_h}</tr><tr>{sma_hist_d}</tr>
                    </table>
                    <table class="big-font-table">
                        <thead><tr class="highlight-row"><th>P</th><th>Max</th><th>Min</th><th>SMA</th></tr></thead>
                        <tbody>{sma_rows}</tbody>
                    </table>
                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">SMAC (%)</th></tr>
                        <tr class="highlight-row">{smac_lbl}</tr><tr>{smac_dat}</tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("### 2. Turnover Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="highlight-row">{tr1_lbl}</tr><tr>{tr1_dat}</tr>
                        <tr class="highlight-row">{tr2_lbl}</tr><tr>{tr2_dat}</tr>
                        
                        <tr class="section-header"><th colspan="6">Interval Stats</th></tr>
                        <tr class="highlight-row">{int_lbl}</tr>
                        <tr><td colspan="6" style="background:#eee;text-align:left;font-weight:bold">Sum (TOR)</td></tr><tr>{sum_tor}</tr>
                        <tr><td colspan="6" style="background:#eee;text-align:left;font-weight:bold">Max (TOR)</td></tr><tr>{max_tor}</tr>
                        <tr><td colspan="6" style="background:#eee;text-align:left;font-weight:bold">Min (TOR)</td></tr><tr>{min_tor}</tr>
                        
                        <tr class="section-header"><th colspan="6">AVGTOR</th></tr>
                        <tr class="highlight-row">{avg_lbl}</tr><tr>{avg_dat}</tr>
                        <tr><th colspan="6">AVGTOR 7</th></tr><tr><td colspan="6">{curr['AVGTOR_7']:.4f}</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

            with tab_chart:
                fig_k = go.Figure(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
                st.plotly_chart(fig_k, use_container_width=True)
