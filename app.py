import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣分析 v6.5", page_icon="📈", layout="wide")

# URL 狀態管理
query_params = st.query_params
url_watchlist = query_params.get("watchlist", "") 
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = url_watchlist.split(",") if url_watchlist else []
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# --- 初始化日期基準 (時光機) ---
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

def format_large_num(num):
    if pd.isna(num): return "-"
    if num >= 1_000_000_000: return f"{num/1_000_000_000:.2f}B"
    if num >= 1_000_000: return f"{num/1_000_000:.2f}M"
    if num >= 1_000: return f"{num/1_000:.2f}K"
    return f"{num:.0f}"

def filter_data_by_interval(df, interval):
    if df.empty: return df
    end_date = df.index[-1]
    start_date = end_date
    
    if interval == '1D': return df.iloc[-1:] 
    elif interval == '5D': start_date = end_date - timedelta(days=5)
    elif interval == '1M': start_date = end_date - relativedelta(months=1)
    elif interval == '3M': start_date = end_date - relativedelta(months=3)
    elif interval == '6M': start_date = end_date - relativedelta(months=6)
    elif interval == '1Y': start_date = end_date - relativedelta(years=1)
    elif interval == '3Y': start_date = end_date - relativedelta(years=3)
    else: return df 
        
    return df[df.index >= start_date]

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    # === 新增功能：日期基準控制 (時光機) ===
    st.subheader("📅 分析基準日")
    c_prev, c_date, c_next = st.columns([0.2, 0.6, 0.2])
    
    with c_prev:
        if st.button("➖", help="前一天"):
            st.session_state.ref_date -= timedelta(days=1)
            st.rerun()
    with c_date:
        # 日曆選擇器
        new_date = st.date_input("選擇日期", value=st.session_state.ref_date, label_visibility="collapsed")
        if new_date != st.session_state.ref_date:
            st.session_state.ref_date = new_date
            st.rerun()
    with c_next:
        if st.button("➕", help="後一天"):
            st.session_state.ref_date += timedelta(days=1)
            st.rerun()
    
    st.caption(f"數據鎖定至: {st.session_state.ref_date}")
    st.divider()

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
    else:
        st.caption("暫無收藏")

    st.divider()
    st.caption("SMA 參數 (主圖用)")
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

if not current_code:
    st.title("港股 SMA 矩陣分析 v6.5")
    st.info("👈 請輸入代號開始分析。您可以透過左側按鈕調整日期基準。")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    col_t, col_b = st.columns([0.85, 0.15])
    with col_t: st.title(f"📊 {display_ticker} (Base: {ref_date_str})")
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
    def get_data_v65(symbol, end_date):
        try:
            # 抓取足夠長的數據 (4年)
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # **關鍵：根據基準日切分數據**
            # 我們需要切分數據，使得 index <= ref_date
            # 這樣所有的 SMA 和 Max/Min 計算都是基於那個時間點
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

    with st.spinner(f"回溯數據至 {ref_date_str} 並計算矩陣..."):
        df, shares_outstanding = get_data_v65(yahoo_ticker, st.session_state.ref_date)

    # 手動輸入補救
    if df is not None and not df.empty and shares_outstanding is None:
        with st.sidebar:
            st.warning("⚠️ 無法獲取流通股數，請手動輸入。")
            manual_shares = st.number_input("手動輸入流通股數 (Shares)", min_value=0, value=0)
            if manual_shares > 0: shares_outstanding = manual_shares

    if df is None or df.empty:
        st.error(f"數據不足或當日休市 (Date: {ref_date_str})。請嘗試調整日期。")
    else:
        # --- A. 核心計算 ---
        # 1. 基礎 SMA 計算
        periods_sma = [7, 14, 28, 57, 106]
        for p in periods_sma:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

        # 2. SMA Convergence (基本收斂)
        # S(7)/S(106)
        df['C_7_106'] = df['SMA_7'] / df['SMA_106']
        # (S(14)-S(7))/S(106)
        df['C_14_7'] = (df['SMA_14'] - df['SMA_7']) / df['SMA_106']
        # (S(28)-S(14))/S(106)
        df['C_28_14'] = (df['SMA_28'] - df['SMA_14']) / df['SMA_106']
        # (S(57)-S(28))/S(106)
        df['C_57_28'] = (df['SMA_57'] - df['SMA_28']) / df['SMA_106']
        # (S(106)-S(57))/S(106)
        df['C_106_57'] = (df['SMA_106'] - df['SMA_57']) / df['SMA_106']

        # 3. Weighted Formulas (依據圖片邏輯的特殊加權公式)
        # (SMA(14)-SMA(7))/(SMA(106) -> Same as C_14_7
        df['W_1'] = df['C_14_7']
        # (SMA(28)-SMA(14))/SMA(106)/2
        df['W_2'] = df['C_28_14'] / 2
        # (SMA(57)-SMA(28))/SMA (106)*7/29
        df['W_3'] = df['C_57_28'] * 7 / 29
        # (SMA(106)-SMA(57)/SMA(106)/7
        df['W_4'] = df['C_106_57'] / 7

        # 4. 換手率與 Max/Min 計算
        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
            
            # Max/Min over periods (106, 57, 28, 14)
            for p in [14, 28, 57, 106]:
                df[f'TO_Max_{p}'] = df['Turnover_Rate'].rolling(window=p).max()
                df[f'TO_Min_{p}'] = df['Turnover_Rate'].rolling(window=p).min()

        # 5. 原有功能計算 (保留 v6.4 兼容性)
        periods_sum = [7, 14, 28, 57, 106, 212]
        for p in periods_sum:
            df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()
        # 簡易主圖 SMA
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        # Ratios (v6.4)
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']
        df['R3'] = df['Sum_14'] / df['Sum_28']
        df['R4'] = df['Sum_14'] / df['Sum_57']
        df['R5'] = df['Sum_28'] / df['Sum_57']
        df['R6'] = df['Sum_28'] / df['Sum_106']

        # --- B. 介面呈現 ---
        
        # 定義 5 個 Tabs (首頁為新功能，後續為舊功能)
        tab_home, tab1, tab2, tab3, tab4 = st.tabs(
            ["🏠 首頁數據矩陣", "📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume (Abs)", "💹 Turnover Analysis"]
        )

        # === Tab Home: 數據矩陣 (新功能) ===
        with tab_home:
            last_row = df.iloc[-1]
            
            st.markdown("### 1. SMA Convergence Matrix (收斂矩陣)")
            
            # 建立類似 Excel 截圖的數據結構
            # 我們需要建立一個 DataFrame 來展示
            matrix_data = {
                "Metric": ["Formula", "Value"],
                "SMA(7)/SMA(106)": ["S7/S106", f"{last_row['C_7_106']:.5f}"],
                "(S14-S7)/S106": ["Diff/S106", f"{last_row['C_14_7']:.5f}"],
                "(S28-S14)/S106": ["Diff/S106", f"{last_row['C_28_14']:.5f}"],
                "(S57-S28)/S106": ["Diff/S106", f"{last_row['C_57_28']:.5f}"],
                "(S106-S57)/S106": ["Diff/S106", f"{last_row['C_106_57']:.5f}"],
            }
            st.dataframe(pd.DataFrame(matrix_data).set_index("Metric"), use_container_width=True)

            st.markdown("### 2. Weighted Matrix (加權矩陣)")
            weight_data = {
                "Metric": ["Formula", "Value"],
                "W1 (S14-S7)": ["Base", f"{last_row['W_1']:.5f}"],
                "W2 (S28-S14)": ["/ 2", f"{last_row['W_2']:.5f}"],
                "W3 (S57-S28)": ["* 7/29", f"{last_row['W_3']:.5f}"],
                "W4 (S106-S57)": ["/ 7", f"{last_row['W_4']:.5f}"],
            }
            st.dataframe(pd.DataFrame(weight_data).set_index("Metric"), use_container_width=True)

            if has_turnover:
                st.markdown("### 3. Turnover Rate Extremes (換手率極值)")
                to_stats_data = {
                    "Period": ["14 Days", "28 Days", "57 Days", "106 Days"],
                    "Max (%)": [f"{last_row['TO_Max_14']:.3f}%", f"{last_row['TO_Max_28']:.3f}%", f"{last_row['TO_Max_57']:.3f}%", f"{last_row['TO_Max_106']:.3f}%"],
                    "Min (%)": [f"{last_row['TO_Min_14']:.3f}%", f"{last_row['TO_Min_28']:.3f}%", f"{last_row['TO_Min_57']:.3f}%", f"{last_row['TO_Min_106']:.3f}%"],
                }
                st.table(pd.DataFrame(to_stats_data))
            else:
                st.warning("無流通股數數據，無法顯示換手率極值。")

            st.divider()
            
            # --- Curve & List for SMA Days 1-7 ---
            st.subheader("📈 SMA Trend (Day 1-7)")
            
            # 準備 Day 1-7 數據 (SMA 7, 14, 28, 57, 106)
            # 這裡我們取最近 7 天的數據
            recent_df = df.tail(7)
            
            # 繪製曲線
            fig_sma_trend = go.Figure()
            colors = ['#FF6B6B', '#FFA500', '#FFD700', '#4CAF50', '#2196F3']
            sma_labels = [7, 14, 28, 57, 106]
            
            for i, p in enumerate(sma_labels):
                col_name = f'SMA_{p}'
                fig_sma_trend.add_trace(go.Scatter(
                    x=recent_df.index, y=recent_df[col_name],
                    mode='lines+markers',
                    name=f"SMA({p})",
                    line=dict(color=colors[i], width=2)
                ))
            
            fig_sma_trend.update_layout(
                height=450, 
                title="SMA Values (Last 7 Days)", 
                template="plotly_white", 
                hovermode="x unified"
            )
            st.plotly_chart(fig_sma_trend, use_container_width=True)

            # 列表顯示 (Day 1-7)
            st.caption("詳細數據 (Day 1 = Latest)")
            # 轉置 DataFrame 以符合列表需求
            list_cols = [f'SMA_{p}' for p in sma_labels]
            list_df = recent_df[list_cols].sort_index(ascending=False).reset_index()
            # 重命名 index 為 Day 1, 2...
            list_df.index = [f"Day({i+1})" for i in range(len(list_df))]
            list_df = list_df.drop(columns=['Date']) # 移除日期欄位，只留數值
            st.dataframe(list_df.style.format("{:.3f}"), use_container_width=True)


        # === 以下為 v6.4 原有功能 (保持不變，僅數據源受 Ref Date 影響) ===
        
        # 區間選擇 (影響圖表顯示範圍)
        st.write("---")
        interval_options = ['1D', '5D', '1M', '3M', '6M', '1Y', '3Y']
        selected_interval = st.select_slider("圖表顯示區間", options=interval_options, value='6M', label_visibility="collapsed")
        display_df = filter_data_by_interval(df, selected_interval)

        # Tab 1: Price
        with tab1:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                         low=display_df['Low'], close=display_df['Close'], name='K線'))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], line=dict(color='orange'), name=f'SMA {sma1}'))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], line=dict(color='blue'), name=f'SMA {sma2}'))
            fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

        # Tab 2: Ratio Curves
        with tab2:
            st.subheader(f"📋 Volume Sum Ratios")
            ratio_cols = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6']
            # Map simplified names to v6.4 logic
            display_map = {
                'R1': 'Sum(7)/Sum(14)', 'R2': 'Sum(7)/Sum(28)', 'R3': 'Sum(14)/Sum(28)',
                'R4': 'Sum(14)/Sum(57)', 'R5': 'Sum(28)/Sum(57)', 'R6': 'Sum(28)/Sum(106)'
            }
            colors = ['#FF6B6B', '#FFA500', '#FFD700', '#4CAF50', '#2196F3', '#9C27B0']
            
            fig_r = go.Figure()
            for i, col in enumerate(ratio_cols):
                latest = last_row[col]
                label = display_map[col]
                fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df[col], mode='lines',
                    name=f"{label}: {latest:.3f}", line=dict(color=colors[i], width=2)))
            fig_r.update_layout(height=600, hovermode="x unified", template="plotly_white", legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig_r, use_container_width=True)

        # Tab 3: Abs Volume
        with tab3:
            curr = df.iloc[-1]
            last_7 = df['Volume'].tail(7)
            c1, c2 = st.columns(2)
            with c1:
                st.caption("最近 7 日成交量")
                fig_d = go.Figure(go.Bar(x=last_7.index, y=last_7.values, marker_color='#636EFA', 
                                         text=[format_large_num(v) for v in last_7.values]))
                st.plotly_chart(fig_d, use_container_width=True)
            with c2:
                st.caption("累積成交量")
                abs_data = {f"S({p})": curr[f'Sum_{p}'] for p in periods_sum}
                fig_s = go.Figure(go.Bar(x=list(abs_data.keys()), y=list(abs_data.values()), marker_color='#EF553B',
                                         text=[format_large_num(v) for v in abs_data.values()]))
                st.plotly_chart(fig_s, use_container_width=True)

        # Tab 4: Turnover Analysis
        with tab4:
            if not has_turnover:
                st.warning("⚠️ 請手動輸入流通股數以啟用此功能。")
            else:
                st.subheader(f"💹 換手率結構分析")
                
                st.markdown("#### 1. Daily Sequence")
                last_7_to = df['Turnover_Rate'].tail(7).sort_index(ascending=False)
                cols_d = st.columns(7)
                for i in range(7):
                    if i < len(last_7_to):
                        with cols_d[i]:
                            st.metric(f"D({i+1})", f"{last_7_to.iloc[i]:.2f}%", last_7_to.index[i].strftime('%m-%d'), delta_color="off")
                
                # Curve
                fig_to_day = go.Figure()
                fig_to_day.add_trace(go.Scatter(x=display_df.index, y=display_df['Turnover_Rate'], mode='lines',
                    name=f"Daily: {last_row['Turnover_Rate']:.2f}%", line=dict(color='#00CC96', width=1), fill='tozeroy'))
                fig_to_day.update_layout(height=300, margin=dict(t=10, b=10), template="plotly_white", hovermode="x unified")
                st.plotly_chart(fig_to_day, use_container_width=True)

                st.divider()
                st.markdown("#### 2. Cumulative Sums & Differences")
                
                # Difference Metrics (v6.4 logic)
                diffs = {
                    "Sum(14)-Sum(7)": (df['Sum_14'] - df['Sum_7']) / shares_outstanding * 100,
                    "Sum(28)-Sum(14)": (df['Sum_28'] - df['Sum_14']) / shares_outstanding * 100,
                    "Sum(57)-Sum(28)": (df['Sum_57'] - df['Sum_28']) / shares_outstanding * 100,
                    "Sum(106)-Sum(57)": (df['Sum_106'] - df['Sum_57']) / shares_outstanding * 100,
                    "Sum(212)-Sum(106)": (df['Sum_212'] - df['Sum_106']) / shares_outstanding * 100
                }
                
                cols_diff = st.columns(5)
                for i, (label, series) in enumerate(diffs.items()):
                    val = series.iloc[-1]
                    with cols_diff[i]: st.metric(label.replace("Sum", "S"), f"{val:.2f}%")
