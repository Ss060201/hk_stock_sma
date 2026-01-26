import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股矩陣 Pro v7.2", page_icon="📱", layout="wide")

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
            font-size: 14px;
            text-align: center;
        }
        .big-font-table td {
            padding: 10px;
            border: 1px solid #ddd;
            text-align: center;
            font-size: 16px; /* 數據字體加大 */
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
        /* 按鈕樣式微調 */
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
    st.caption("SMA 參數 (主圖用)")
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')
render_custom_css()

if not current_code:
    st.title("港股矩陣 Pro v7.2")
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

    # --- 數據獲取 ---
    @st.cache_data(ttl=900)
    def get_data_v72(symbol, end_date):
        try:
            # 抓取 4 年數據
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 過濾日期 (小於等於基準日)
            end_dt = pd.to_datetime(end_date)
            df = df[df.index <= end_dt]
            
            # 獲取流通股數
            shares = None
            ticker = yf.Ticker(symbol)
            try: shares = ticker.fast_info.get('shares', None)
            except: pass
            if shares is None:
                try: shares = ticker.info.get('sharesOutstanding', None)
                except: pass
            
            return df, shares
        except Exception as e:
            return None, None

    with st.spinner(f"正在計算 {ref_date_str} 的矩陣數據..."):
        df, shares_outstanding = get_data_v72(yahoo_ticker, st.session_state.ref_date)

    if df is not None and not df.empty and shares_outstanding is None:
        with st.sidebar:
            st.warning("⚠️ 無法獲取流通股數，請手動輸入。")
            manual_shares = st.number_input("手動輸入股數", min_value=0, value=0)
            if manual_shares > 0: shares_outstanding = manual_shares

    if df is None or df.empty:
        st.error(f"數據不足或該日休市 ({ref_date_str})。請按上方按鈕調整日期。")
    else:
        # ==================== A. 計算邏輯 ====================
        periods_sma = [7, 14, 28, 57, 106, 212]
        
        # 1. SMA & Price
        for p in periods_sma:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

        # 2. SMAC (Convergence) %
        # SMAC1 = 1 - SMA(7)/SMA(57)
        df['SMAC_1'] = (1 - (df['SMA_7'] / df['SMA_57'])) * 100
        # SMAC2 = (SMA(14)-SMA(7))/SMA(106)
        df['SMAC_2'] = ((df['SMA_14'] - df['SMA_7']) / df['SMA_106']) * 100
        # SMAC3 = (SMA(28)-SMA(14))/SMA(106)
        df['SMAC_3'] = ((df['SMA_28'] - df['SMA_14']) / df['SMA_106']) * 100
        # SMAC4 = (SMA(57)-SMA(28))/SMA(106)
        df['SMAC_4'] = ((df['SMA_57'] - df['SMA_28']) / df['SMA_106']) * 100
        # SMAC5 = (SMA(106)-SMA(57))/SMA(106)
        df['SMAC_5'] = ((df['SMA_106'] - df['SMA_57']) / df['SMA_106']) * 100
        # SMAC6 = SMA(7)/SMA(106)
        df['SMAC_6'] = (df['SMA_7'] / df['SMA_106']) * 100

        # 3. Turnover (TOR) %
        if shares_outstanding:
            df['TOR'] = (df['Volume'] / shares_outstanding) * 100
        else:
            df['TOR'] = 0
            
        # Interval Sum, Max, Min for TOR
        for p in periods_sma:
            df[f'Sum_TOR_{p}'] = df['TOR'].rolling(window=p).sum()
            df[f'Max_TOR_{p}'] = df['TOR'].rolling(window=p).max()
            df[f'Min_TOR_{p}'] = df['TOR'].rolling(window=p).min()

        # 4. AVGTOR (特殊公式)
        # 這些公式使用 SMA 計算，但放在 Turnover 區塊顯示
        df['AVGTOR_1'] = (df['SMA_14'] - df['SMA_7']) / df['SMA_106']
        df['AVGTOR_2'] = (df['SMA_28'] - df['SMA_14']) / df['SMA_106'] / 2
        df['AVGTOR_3'] = ((df['SMA_57'] - df['SMA_28']) / df['SMA_106']) * 7 / 29
        df['AVGTOR_4'] = ((df['SMA_106'] - df['SMA_57']) / df['SMA_106']) / 7
        df['AVGTOR_5'] = 0 # Placeholder
        df['AVGTOR_6'] = 0 # Placeholder
        df['AVGTOR_7'] = 0 # Placeholder

        # ==================== B. 數據提取 ====================
        if len(df) < 15:
            st.error("歷史數據不足，無法生成完整矩陣。")
        else:
            curr = df.iloc[-1]
            
            # --- SMA Matrix Components ---
            # Horizontal: Day 2-7 (Price History)
            sma_hist_html = ""
            for i in range(2, 8):
                val = df['Close'].iloc[-i]
                sma_hist_html += f"<td>{val:.2f}</td>"

            # Vertical: Intervals (Max/Min Price, Current SMA)
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

            # SMAC Rows (SMAC1-6)
            smac_labels = "".join([f"<th>SMAC{i}</th>" for i in range(1, 7)])
            smac_data = "".join([f"<td>{curr[f'SMAC_{i}']:.2f}%</td>" for i in range(1, 7)])

            # --- Turnover Matrix Components ---
            # Day 2-7 TOR
            tor_row1_labels = "".join([f"<th>D{i}</th>" for i in range(2, 8)])
            tor_row2_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(2, 8)])
            
            # Day 8-13 TOR
            tor_row3_labels = "".join([f"<th>D{i}</th>" for i in range(8, 14)])
            tor_row4_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(8, 14)])

            # Interval Stats (Sum, Max, Min)
            interval_labels = "".join([f"<th>{p}</th>" for p in periods_sma])
            sum_tor_data = "".join([f"<td>{curr[f'Sum_TOR_{p}']:.2f}%</td>" for p in periods_sma])
            max_tor_data = "".join([f"<td>{curr[f'Max_TOR_{p}']:.3f}%</td>" for p in periods_sma])
            min_tor_data = "".join([f"<td>{curr[f'Min_TOR_{p}']:.3f}%</td>" for p in periods_sma])

            # AVGTOR Rows
            avgtor_1_6_labels = "".join([f"<th>AVG{i}</th>" for i in range(1, 7)])
            avgtor_1_6_data = "".join([f"<td>{curr[f'AVGTOR_{i}']:.4f}</td>" for i in range(1, 7)])

            # ==================== C. 介面呈現 (修復 Bug) ====================
            # 這裡只宣告 3 個變數，對應 3 個 Tabs
            tab_home, tab_chart, tab_other = st.tabs(["🏠 核心矩陣 (Mobile)", "📉 K線與SMA", "📊 其他圖表"])

            with tab_home:
                # 1. 日期控制與曲線圖 (Top Section)
                c_ctrl, c_curve = st.columns([0.2, 0.8])
                with c_ctrl:
                    st.write("#### 日期")
                    if st.button("◀ -1", use_container_width=True):
                        st.session_state.ref_date -= timedelta(days=1)
                        st.rerun()
                    
                    st.markdown(f"<div style='text-align:center; font-size:16px; font-weight:bold; margin:10px 0;'>{ref_date_str}</div>", unsafe_allow_html=True)
                    
                    if st.button("▶ +1", use_container_width=True):
                        st.session_state.ref_date += timedelta(days=1)
                        st.rerun()
                
                with c_curve:
                    # 繪製曲線 (SMA + TOR)
                    curve_df = df.tail(30)
                    fig_curve = go.Figure()
                    # SMA Lines
                    for p in [7, 28, 106]:
                        fig_curve.add_trace(go.Scatter(x=curve_df.index, y=curve_df[f'SMA_{p}'], name=f"SMA{p}", mode='lines'))
                    # TOR Line (Secondary Y)
                    fig_curve.add_trace(go.Scatter(x=curve_df.index, y=curve_df['TOR'], name="TOR%", 
                                                 line=dict(color='rgba(0,0,0,0.3)', width=1, dash='dot'), yaxis="y2"))
                    
                    fig_curve.update_layout(
                        height=350, 
                        margin=dict(l=10, r=10, t=10, b=10),
                        legend=dict(orientation="h", y=1.1),
                        yaxis2=dict(title="TOR%", overlaying="y", side="right", showgrid=False)
                    )
                    st.plotly_chart(fig_curve, use_container_width=True)

                st.divider()

                # 2. SMA Matrix (Bottom Section)
                st.markdown("### 1. SMA Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">History (Day 2-7)</th></tr>
                        <tr>{sma_hist_html}</tr>
                    </table>
                    
                    <table class="big-font-table">
                        <thead>
                            <tr class="highlight-row"><th>P</th><th>Max</th><th>Min</th><th>SMA</th></tr>
                        </thead>
                        <tbody>{sma_rows_html}</tbody>
                    </table>
                    
                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">SMAC (%)</th></tr>
                        <tr>{smac_labels}</tr>
                        <tr>{smac_data}</tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

                # 3. Turnover Matrix (Bottom Section)
                st.markdown("### 2. Turnover Matrix")
                st.markdown(f"""
                <div class="table-container">
                    <table class="big-font-table">
                        <tr class="highlight-row">{tor_row1_labels}</tr>
                        <tr>{tor_row2_data}</tr>
                        <tr class="highlight-row">{tor_row3_labels}</tr>
                        <tr>{tor_row4_data}</tr>
                    </table>

                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">Interval Stats (Sum/Max/Min)</th></tr>
                        <tr class="highlight-row">{interval_labels}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;font-size:14px;">Sum (TOR)</td></tr>
                        <tr>{sum_tor_data}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;font-size:14px;">Max (TOR)</td></tr>
                        <tr>{max_tor_data}</tr>
                        
                        <tr><td colspan="6" style="background:#eee;font-weight:bold;font-size:14px;">Min (TOR)</td></tr>
                        <tr>{min_tor_data}</tr>
                    </table>

                    <table class="big-font-table">
                        <tr class="section-header"><th colspan="6">AVGTOR</th></tr>
                        <tr>{avgtor_1_6_labels}</tr>
                        <tr>{avgtor_1_6_data}</tr>
                        <tr><th colspan="6">AVGTOR 7</th></tr>
                        <tr><td colspan="6">{curr['AVGTOR_7']:.4f}</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)

            # Tab 2 & 3: 保留圖表
            with tab_chart:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
                st.plotly_chart(fig, use_container_width=True)

            with tab_other:
                st.info("更多圖表功能請見 v6.4 版本")
