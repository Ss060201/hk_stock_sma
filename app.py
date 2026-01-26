import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import requests

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股矩陣 Pro v7.6 (Final)", page_icon="📱", layout="wide")

# URL 狀態管理
query_params = st.query_params
url_watchlist = query_params.get("watchlist", "") 
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = url_watchlist.split(",") if url_watchlist else []
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# 初始化日期基準
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()

# --- 2. 輔助函數 ---
def clean_ticker_input(symbol):
    symbol = str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")
    return symbol

def get_yahoo_ticker(symbol):
    if symbol.isdigit():
        return f"{symbol.zfill(4)}.HK"
    return symbol

def update_url():
    st.query_params["watchlist"] = ",".join(st.session_state.watchlist)

def toggle_watchlist(ticker):
    clean_code = clean_ticker_input(ticker)
    if clean_code in st.session_state.watchlist:
        st.session_state.watchlist.remove(clean_code)
        st.toast(f'已移除 {clean_code}', icon="🗑️")
    else:
        st.session_state.watchlist.append(clean_code)
        st.toast(f'已收藏 {clean_code}', icon="⭐")
    update_url()

# --- CSS 樣式 (大字體手機優化) ---
def render_custom_css():
    st.markdown("""
        <style>
        .big-font-table {
            width: 100%;
            border-collapse: collapse;
            font-family: Arial, sans-serif;
            margin-bottom: 20px;
        }
        .big-font-table th {
            background-color: #f0f2f6;
            color: #31333F;
            font-weight: bold;
            padding: 8px;
            border: 1px solid #ddd;
            font-size: 16px;
            text-align: center;
        }
        .big-font-table td {
            padding: 10px;
            border: 1px solid #ddd;
            text-align: center;
            font-size: 18px; /* 數據字體加大 */
            color: #000;
        }
        .highlight-row {
            background-color: #e8f5e9;
        }
        .section-header {
            background-color: #31333F;
            color: white !important;
            font-size: 16px;
            text-align: left !important;
            padding-left: 10px !important;
        }
        .table-container {
            overflow-x: auto;
        }
        .stButton button {
            width: 100%;
        }
        </style>
    """, unsafe_allow_html=True)

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    st.caption(f"目前基準: {st.session_state.ref_date}")
    
    search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
    if search_input:
        cleaned_search = clean_ticker_input(search_input)
        if cleaned_search: st.session_state.current_view = cleaned_search

    st.divider()
    st.subheader(f"我的收藏 ({len(st.session_state.watchlist)})")
    if st.session_state.watchlist:
        for ticker in st.session_state.watchlist:
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                st.session_state.current_view = ticker

    st.divider()
    st.caption("SMA 參數")
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')
render_custom_css()

if not current_code:
    st.title("港股矩陣 Pro v7.6")
    st.info("👈 請輸入代號開始分析")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    col_t, col_b = st.columns([0.8, 0.2])
    with col_t: st.title(f"📊 {display_ticker}")
    with col_b:
        st.write("")
        if current_code in st.session_state.watchlist:
            if st.button("★ 已收藏", type="primary", use_container_width=True):
                toggle_watchlist(current_code)
                st.rerun()
        else:
            if st.button("☆ 加入", use_container_width=True):
                toggle_watchlist(current_code)
                st.rerun()

    # --- 數據獲取 (修復版) ---
    @st.cache_data(ttl=900)
    def get_data_v76(symbol, end_date):
        # 1. 偽裝 Session (解決 Rate Limit)
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        df = pd.DataFrame()
        shares = None
        
        # 2. 重試機制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 抓取 4 年數據 (確保有足夠歷史計算 SMA212)
                df = yf.download(symbol, period="4y", auto_adjust=False, session=session, progress=False)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    break 
            except Exception:
                time.sleep(1 + attempt * 2) # 等待 1, 3, 5 秒

        # 3. 過濾日期 (邏輯：取 <= ref_date 的所有數據)
        if not df.empty:
            end_dt = pd.to_datetime(end_date)
            df_filtered = df[df.index <= end_dt]
            
            if df_filtered.empty:
                return None, None # 日期過早
            
            df = df_filtered
                
        # 4. 獲取流通股數 (雙重保險)
        try:
            ticker = yf.Ticker(symbol, session=session)
            try: shares = ticker.fast_info.get('shares', None)
            except: pass
            if shares is None:
                try: shares = ticker.info.get('sharesOutstanding', None)
                except: pass
        except:
            pass
            
        return df, shares

    with st.spinner(f"正在連線 Yahoo Finance 獲取 {display_ticker} 數據..."):
        df, shares_outstanding = get_data_v76(yahoo_ticker, st.session_state.ref_date)

    # 手動輸入股數
    if df is not None and not df.empty and shares_outstanding is None:
        with st.sidebar:
            st.warning("⚠️ API 未回傳流通股數")
            manual_shares = st.number_input("請手動輸入股數", min_value=0, value=0)
            if manual_shares > 0: shares_outstanding = manual_shares

    # --- 數據驗證與展示 ---
    if df is None or df.empty:
        st.error("⚠️ 無法獲取數據。請檢查網絡或股票代號。")
    else:
        # 檢查數據長度 (SMA 212 需要至少 212 天)
        min_required = 215 # 多留幾天緩衝
        if len(df) < min_required:
            st.error(f"⚠️ 歷史數據不足 ({len(df)} 天)，該股票上市時間太短，無法計算 212 日均線矩陣。")
        else:
            # 獲取實際交易日
            actual_date = df.index[-1].date()
            if actual_date != st.session_state.ref_date:
                st.warning(f"ℹ️ {ref_date_str} 非交易日，目前顯示最近交易日 **{actual_date}** 的數據。")

            # ==================== A. 計算邏輯 ====================
            periods_sma = [7, 14, 28, 57, 106, 212]
            
            # 1. SMA
            for p in periods_sma:
                df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

            # 2. SMAC (Convergence) %
            # 使用 np.where 防止除以 0 報錯
            def safe_div(num, den):
                return np.where(den != 0, num / den, 0)

            df['SMAC_1'] = (1 - safe_div(df['SMA_7'], df['SMA_57'])) * 100
            df['SMAC_2'] = safe_div((df['SMA_14'] - df['SMA_7']), df['SMA_106']) * 100
            df['SMAC_3'] = safe_div((df['SMA_28'] - df['SMA_14']), df['SMA_106']) * 100
            df['SMAC_4'] = safe_div((df['SMA_57'] - df['SMA_28']), df['SMA_106']) * 100
            df['SMAC_5'] = safe_div((df['SMA_106'] - df['SMA_57']), df['SMA_106']) * 100
            df['SMAC_6'] = safe_div(df['SMA_7'], df['SMA_106']) * 100

            # 3. Turnover (TOR) %
            if shares_outstanding:
                df['TOR'] = (df['Volume'] / shares_outstanding) * 100
            else:
                df['TOR'] = 0
                
            for p in periods_sma:
                df[f'Sum_TOR_{p}'] = df['TOR'].rolling(window=p).sum()
                df[f'Max_TOR_{p}'] = df['TOR'].rolling(window=p).max()
                df[f'Min_TOR_{p}'] = df['TOR'].rolling(window=p).min()

            # 4. AVGTOR
            df['AVGTOR_1'] = safe_div((df['SMA_14'] - df['SMA_7']), df['SMA_106'])
            df['AVGTOR_2'] = safe_div((df['SMA_28'] - df['SMA_14']), df['SMA_106']) / 2
            df['AVGTOR_3'] = safe_div((df['SMA_57'] - df['SMA_28']), df['SMA_106']) * 7 / 29
            df['AVGTOR_4'] = safe_div((df['SMA_106'] - df['SMA_57']), df['SMA_106']) / 7
            df['AVGTOR_5'] = 0 
            df['AVGTOR_6'] = 0 
            df['AVGTOR_7'] = 0 

            # ==================== B. 數據提取 ====================
            curr = df.iloc[-1]
            
            # --- 1. SMA Matrix Components ---
            # Horizontal: Day 2-7
            sma_hist_header = "".join([f"<th>D{i}</th>" for i in range(2, 8)])
            sma_hist_data = "".join([f"<td>{df['Close'].iloc[-i]:.2f}</td>" for i in range(2, 8)])

            # Vertical: Intervals
            sma_rows_html = ""
            for p in periods_sma:
                p_max = df['Close'].rolling(p).max().iloc[-1]
                p_min = df['Close'].rolling(p).min().iloc[-1]
                sma_val = curr[f'SMA_{p}']
                
                sma_rows_html += f"""
                <tr>
                    <td>{p}</td>
                    <td>{p_max:.2f}</td>
                    <td>{p_min:.2f}</td>
                    <td style="font-weight:bold; color:blue;">{sma_val:.2f}</td>
                </tr>
                """
            
            # SMAC Rows
            smac_labels = "".join([f"<th>SMAC{i}</th>" for i in range(1, 7)])
            smac_data = "".join([f"<td>{curr[f'SMAC_{i}']:.2f}%</td>" for i in range(1, 7)])

            # --- 2. Turnover Matrix Components ---
            # Row 1-2: Day 2-7
            tor_row1_labels = "".join([f"<th>D{i}</th>" for i in range(2, 8)])
            tor_row2_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(2, 8)])
            
            # Row 3-4: Day 8-13
            tor_row3_labels = "".join([f"<th>D{i}</th>" for i in range(8, 14)])
            tor_row4_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(8, 14)])

            # Interval Stats
            interval_labels = "".join([f"<th>{p}</th>" for p in periods_sma])
            sum_tor_data = "".join([f"<td>{curr[f'Sum_TOR_{p}']:.2f}%</td>" for p in periods_sma])
            max_tor_data = "".join([f"<td>{curr[f'Max_TOR_{p}']:.3f}%</td>" for p in periods_sma])
            min_tor_data = "".join([f"<td>{curr[f'Min_TOR_{p}']:.3f}%</td>" for p in periods_sma])

            # AVGTOR
            avgtor_1_6_labels = "".join([f"<th>AVG{i}</th>" for i in range(1, 7)])
            avgtor_1_6_data = "".join([f"<td>{curr[f'AVGTOR_{i}']:.4f}</td>" for i in range(1, 7)])

            # ==================== C. 介面呈現 ====================
            
            # 日期控制與曲線
            c_ctrl, c_curve = st.columns([0.2, 0.8])
            with c_ctrl:
                st.write("#### 日期")
                if st.button("◀ -1", use_container_width=True):
                    st.session_state.ref_date -= timedelta(days=1)
                    st.rerun()
                st.markdown(f"<div style='text-align:center; font-size:16px; font-weight:bold; margin:10px 0;'>{actual_date}</div>", unsafe_allow_html=True)
                if st.button("▶ +1", use_container_width=True):
                    st.session_state.ref_date += timedelta(days=1)
                    st.rerun()
            
            with c_curve:
                curve_df = df.tail(30)
                fig_curve = go.Figure()
                for p in [7, 28, 106]:
                    fig_curve.add_trace(go.Scatter(x=curve_df.index, y=curve_df[f'SMA_{p}'], name=f"SMA{p}", mode='lines'))
                fig_curve.add_trace(go.Scatter(x=curve_df.index, y=curve_df['TOR'], name="TOR%", 
                                             line=dict(color='rgba(0,0,0,0.3)', width=1, dash='dot'), yaxis="y2"))
                fig_curve.update_layout(
                    height=300, 
                    margin=dict(l=10, r=10, t=10, b=10),
                    legend=dict(orientation="h", y=1.1),
                    yaxis2=dict(title="TOR%", overlaying="y", side="right", showgrid=False)
                )
                st.plotly_chart(fig_curve, use_container_width=True)

            st.divider()

            # Tabs (修復 ValueError: 變數數量必須等於 Tabs 數量)
            tab_data, tab_other = st.tabs(["📊 核心數據矩陣", "📉 其他圖表"])

            with tab_data:
                # 1. SMA Matrix
                st.markdown("### 1. SMA Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">Close Price (Day 2-7)</th></tr>
                        <tr class="highlight-row">{sma_hist_header}</tr>
                        <tr>{sma_hist_data}</tr>
                    </table>
                    
                    <table class="big-font-table">
                        <thead>
                            <tr class="highlight-row"><th>P</th><th>Max</th><th>Min</th><th>SMA</th></tr>
                        </thead>
                        <tbody>{sma_rows_html}</tbody>
                    </table>

                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">SMAC (%)</th></tr>
                        <tr class="highlight-row">{smac_labels}</tr>
                        <tr>{smac_data}</tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

                st.divider()

                # 2. Turnover Matrix
                st.markdown("### 2. Turnover Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="highlight-row">{tor_row1_labels}</tr>
                        <tr>{tor_row2_data}</tr>
                        <tr class="highlight-row">{tor_row3_labels}</tr>
                        <tr>{tor_row4_data}</tr>
                        
                        <tr class="section-header"><th colspan="6">Interval Stats</th></tr>
                        <tr class="highlight-row">{interval_labels}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;text-align:left;">Sum (TOR)</td></tr>
                        <tr>{sum_tor_data}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;text-align:left;">Max (TOR)</td></tr>
                        <tr>{max_tor_data}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;text-align:left;">Min (TOR)</td></tr>
                        <tr>{min_tor_data}</tr>
                        
                        <tr class="section-header"><th colspan="6">AVGTOR</th></tr>
                        <tr class="highlight-row">{avgtor_1_6_labels}</tr>
                        <tr>{avgtor_1_6_data}</tr>
                        <tr><th colspan="6">AVGTOR 7</th></tr>
                        <tr><td colspan="6">{curr['AVGTOR_7']:.4f}</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

            with tab_other:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
                st.plotly_chart(fig, use_container_width=True)
