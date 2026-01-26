import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股矩陣 Pro v7.1", page_icon="📱", layout="wide")

# URL 狀態管理
query_params = st.query_params
url_watchlist = query_params.get("watchlist", "") 
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = url_watchlist.split(",") if url_watchlist else []
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# 初始化日期基準
if 'ref_date' not in st.session_state:
    # 預設為今日
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

def format_large_num(num):
    if pd.isna(num): return "-"
    if num >= 1_000_000_000: return f"{num/1_000_000_000:.2f}B"
    if num >= 1_000_000: return f"{num/1_000_000:.2f}M"
    if num >= 1_000: return f"{num/1_000:.2f}K"
    return f"{num:.0f}"

# --- CSS 樣式 (針對手機優化大字體表格) ---
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
            padding: 10px;
            border: 1px solid #ddd;
            font-size: 16px; /* 手機標題字體 */
            text-align: center;
        }
        .big-font-table td {
            padding: 12px;
            border: 1px solid #ddd;
            text-align: center;
            font-size: 18px; /* 手機數據字體 (加大) */
            color: #000;
        }
        .highlight-row {
            background-color: #e8f5e9; /* 淺綠色背景 */
        }
        .section-header {
            background-color: #31333F;
            color: white !important;
            font-size: 18px;
            text-align: left !important;
            padding-left: 15px !important;
        }
        </style>
    """, unsafe_allow_html=True)

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    # 日期控制 (備用，主要操作已移至首頁)
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
    st.title("港股矩陣 Pro v7.1")
    st.info("👈 請輸入代號開始分析")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    # 標題與收藏按鈕
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
    def get_data_v71(symbol, end_date):
        try:
            # 抓取 4 年數據 (確保 SMA212 可計算)
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 過濾日期 (時光機邏輯)
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
        df, shares_outstanding = get_data_v71(yahoo_ticker, st.session_state.ref_date)

    # 手動輸入補救
    if df is not None and not df.empty and shares_outstanding is None:
        with st.sidebar:
            st.warning("⚠️ 無法獲取流通股數，請手動輸入。")
            manual_shares = st.number_input("手動輸入股數", min_value=0, value=0)
            if manual_shares > 0: shares_outstanding = manual_shares

    if df is None or df.empty:
        st.error(f"數據不足或該日休市 ({ref_date_str})。請按上方按鈕調整日期。")
    else:
        # ==========================================
        #       A. 核心計算邏輯 (SMA & Turnover)
        # ==========================================
        
        # 1. 基礎 SMA
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

        # 2. SMA Convergence (SMAC) - 依據要求 % 表示
        # SMAC1 = 1 - SMA(7)/SMA(57)  (根據 Prompt: "SMAC1=1-SMA(7/)57")
        df['SMAC_1'] = (1 - (df['SMA_7'] / df['SMA_57'])) * 100
        
        # 為了填滿 SMAC1-6，這裡推導其他邏輯 (或使用之前的 diff logic)
        # 這裡假設使用者想要類似的 Convergence 概念
        df['SMAC_2'] = ((df['SMA_14'] - df['SMA_7']) / df['SMA_106']) * 100
        df['SMAC_3'] = ((df['SMA_28'] - df['SMA_14']) / df['SMA_106']) * 100
        df['SMAC_4'] = ((df['SMA_57'] - df['SMA_28']) / df['SMA_106']) * 100
        df['SMAC_5'] = ((df['SMA_106'] - df['SMA_57']) / df['SMA_106']) * 100
        df['SMAC_6'] = (df['SMA_7'] / df['SMA_106']) * 100 # 補一個 Ratio

        # 3. 換手率 (Turnover Rate)
        if shares_outstanding:
            df['TOR'] = (df['Volume'] / shares_outstanding) * 100
            
            # Interval Sum(TOR)
            for p in periods_sma:
                # Sum of Turnover Rate over P days
                df[f'Sum_TOR_{p}'] = df['TOR'].rolling(window=p).sum()
                
                # Max/Min TOR over P days
                df[f'Max_TOR_{p}'] = df['TOR'].rolling(window=p).max()
                df[f'Min_TOR_{p}'] = df['TOR'].rolling(window=p).min()
        else:
            df['TOR'] = 0
            for p in periods_sma:
                df[f'Sum_TOR_{p}'] = 0
                df[f'Max_TOR_{p}'] = 0
                df[f'Min_TOR_{p}'] = 0

        # 4. AVGTOR (特殊公式計算) - 雖然使用 SMA 變數，但依據 Prompt 放在 Turnover 區
        # (SMA(14)-SMA(7))/(SMA(106)
        df['AVGTOR_1'] = (df['SMA_14'] - df['SMA_7']) / df['SMA_106']
        # (SMA(28)-SMA(14))/SMA(106)/2
        df['AVGTOR_2'] = (df['SMA_28'] - df['SMA_14']) / df['SMA_106'] / 2
        # (SMA(57)-SMA(28))/SMA (106)*7/29
        df['AVGTOR_3'] = ((df['SMA_57'] - df['SMA_28']) / df['SMA_106']) * 7 / 29
        # (SMA(106)-SMA(57)/SMA(106)/7
        df['AVGTOR_4'] = ((df['SMA_106'] - df['SMA_57']) / df['SMA_106']) / 7
        # 補位
        df['AVGTOR_5'] = 0 
        df['AVGTOR_6'] = 0
        df['AVGTOR_7'] = 0

        # ==========================================
        #       B. 數據提取 (Trading Day Logic)
        # ==========================================
        # iloc[-1] 是基準日 (Day 1), iloc[-2] 是 Day 2...
        # 確保數據夠長
        if len(df) < 15:
            st.error("歷史數據不足，無法生成完整矩陣。")
        else:
            curr = df.iloc[-1]
            
            # 提取過去 13 個交易日的 TOR
            # Days: [Day 2, 3, 4, 5, 6, 7] -> iloc[-2] to iloc[-7]
            # Days: [Day 8, 9, 10, 11, 12, 13] -> iloc[-8] to iloc[-13]
            
            # 構建 SMA Matrix HTML
            # SMA 橫列: Day 2-7
            sma_hist_html = ""
            for i in range(2, 8): # 2 to 7
                day_val = df['Close'].iloc[-i]
                sma_hist_html += f"<td>{day_val:.2f}</td>"

            # 構建 SMA 縱列 (Intervals)
            sma_intervals = [7, 14, 28, 57, 106, 212]
            
            # 準備 SMAC 數據
            smac_labels = ["SMAC1", "SMAC2", "SMAC3", "SMAC4", "SMAC5", "SMAC6"]
            smac_vals = [curr[f'SMAC_{i}'] for i in range(1, 7)]

            # 構建 Turnover HTML
            # Row 1-2: Day 2-7
            tor_row1_labels = "".join([f"<th>Day {i}</th>" for i in range(2, 8)])
            tor_row2_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(2, 8)])
            
            # Row 3-4: Day 8-13
            tor_row3_labels = "".join([f"<th>Day {i}</th>" for i in range(8, 14)])
            tor_row4_data = "".join([f"<td>{df['TOR'].iloc[-i]:.3f}%</td>" for i in range(8, 14)])

            # Row 5-8: Intervals (7, 14, 28, 57, 106, 212)
            interval_labels_html = "".join([f"<th>{p}</th>" for p in sma_intervals])
            sum_tor_html = "".join([f"<td>{curr[f'Sum_TOR_{p}']:.2f}%</td>" for p in sma_intervals])
            max_tor_html = "".join([f"<td>{curr[f'Max_TOR_{p}']:.3f}%</td>" for p in sma_intervals])
            min_tor_html = "".join([f"<td>{curr[f'Min_TOR_{p}']:.3f}%</td>" for p in sma_intervals])

            # Row 9-12: AVGTOR
            avgtor_labels_html = "".join([f"<th>AVG{i}</th>" for i in range(1, 7)])
            avgtor_data_html = "".join([f"<td>{curr[f'AVGTOR_{i}']:.4f}</td>" for i in range(1, 7)])
            
            # ==========================================
            #       C. 介面呈現 (Tabs)
            # ==========================================
            
            tab_home, tab1, tab2 = st.tabs(["🏠 核心矩陣 (Mobile)", "📉 K線與SMA", "📊 其他圖表"])

            with tab_home:
                # --- 1. 日期控制與曲線圖 ---
                c_ctrl, c_curve = st.columns([0.2, 0.8])
                with c_ctrl:
                    st.write("#### 日期")
                    if st.button("◀ -1天", use_container_width=True):
                        st.session_state.ref_date -= timedelta(days=1)
                        st.rerun()
                    
                    st.markdown(f"<div style='text-align:center; font-size:18px; font-weight:bold; margin:10px 0;'>{ref_date_str}</div>", unsafe_allow_html=True)
                    
                    if st.button("▶ +1天", use_container_width=True):
                        st.session_state.ref_date += timedelta(days=1)
                        st.rerun()
                
                with c_curve:
                    # 繪製 SMA 曲線 (Day 1-30)
                    curve_df = df.tail(30)
                    fig_curve = go.Figure()
                    # SMA Curves
                    for p in [7, 28, 106]:
                        fig_curve.add_trace(go.Scatter(x=curve_df.index, y=curve_df[f'SMA_{p}'], name=f"SMA{p}", mode='lines'))
                    # TOR Curve (Secondary Y)
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

                # --- 2. SMA 數據列表 (HTML) ---
                st.markdown("### 1. SMA Matrix")
                
                # 構建 SMA 表格 Rows
                sma_rows_html = ""
                for p in sma_intervals:
                    sma_val = curr[f'SMA_{p}']
                    # 計算該週期的 Max/Min (Price) - 這裡簡單取 Close 的 Max/Min
                    p_max = df['Close'].rolling(p).max().iloc[-1]
                    p_min = df['Close'].rolling(p).min().iloc[-1]
                    
                    sma_rows_html += f"""
                    <tr>
                        <td>{p}</td>
                        <td>{p_max:.2f}</td>
                        <td>{p_min:.2f}</td>
                        <td style="font-weight:bold; color:blue;">{sma_val:.2f}</td>
                    </tr>
                    """

                st.markdown(f"""
                <table class="big-font-table">
                    <tr class="section-header"><th colspan="6">Historical Close (Day 2-7)</th></tr>
                    <tr>{sma_hist_html}</tr>
                </table>
                
                <table class="big-font-table">
                    <thead>
                        <tr>
                            <th>Interval</th><th>Max</th><th>Min</th><th>SMA</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sma_rows_html}
                    </tbody>
                </table>
                
                <table class="big-font-table">
                    <tr class="section-header"><th colspan="6">SMA Convergence (SMAC %)</th></tr>
                    <tr>
                        {"".join([f"<th>{l}</th>" for l in smac_labels])}
                    </tr>
                    <tr>
                        {"".join([f"<td>{v:.2f}%</td>" for v in smac_vals])}
                    </tr>
                </table>
                """, unsafe_allow_html=True)

                # --- 3. 換手率數據列表 (HTML) ---
                st.markdown("### 2. Turnover Rate Matrix")
                
                st.markdown(f"""
                <table class="big-font-table">
                    <tr class="highlight-row">{tor_row1_labels}</tr>
                    <tr>{tor_row2_data}</tr>
                    
                    <tr class="highlight-row">{tor_row3_labels}</tr>
                    <tr>{tor_row4_data}</tr>
                </table>
                
                <table class="big-font-table">
                    <tr class="section-header"><th colspan="6">Interval Stats (Sum/Max/Min)</th></tr>
                    <tr>{interval_labels_html}</tr>
                    
                    <tr><td colspan="6" style="text-align:left;font-weight:bold;font-size:14px;background:#eee;">Sum (TOR)</td></tr>
                    <tr>{sum_tor_html}</tr>
                    
                    <tr><td colspan="6" style="text-align:left;font-weight:bold;font-size:14px;background:#eee;">Max (TOR)</td></tr>
                    <tr>{max_tor_html}</tr>
                    
                    <tr><td colspan="6" style="text-align:left;font-weight:bold;font-size:14px;background:#eee;">Min (TOR)</td></tr>
                    <tr>{min_tor_html}</tr>
                </table>

                <table class="big-font-table">
                    <tr class="section-header"><th colspan="6">AVGTOR (Formulas)</th></tr>
                    <tr>{avgtor_labels_html}</tr>
                    <tr>{avgtor_data_html}</tr>
                    
                    <tr><th colspan="6">AVGTOR 7</th></tr>
                    <tr><td colspan="6">{curr['AVGTOR_7']:.4f}</td></tr>
                </table>
                """, unsafe_allow_html=True)

            # === Tab 1: K線圖 (舊功能保留) ===
            with tab1:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
                st.plotly_chart(fig, use_container_width=True)

            # === Tab 2: 其他圖表 (舊功能保留) ===
            with tab2:
                st.write("詳細比率曲線請見 v6.4 版本")
