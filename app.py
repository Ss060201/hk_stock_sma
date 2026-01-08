import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 Turnover Pro 分析", page_icon="📊", layout="wide")

# URL 狀態管理
query_params = st.query_params
url_watchlist = query_params.get("watchlist", "") 
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = url_watchlist.split(",") if url_watchlist else []
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

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

if not current_code:
    st.title("港股 Turnover Pro 分析系統")
    st.info("👈 請輸入代號開始分析")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    col_t, col_b = st.columns([0.85, 0.15])
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

    # 獲取數據
    @st.cache_data(ttl=900)
    def get_data(symbol):
        try:
            # 抓取 4 年數據
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 獲取流通股數 (Shares Outstanding)
            try:
                info = yf.Ticker(symbol).info
                shares = info.get('sharesOutstanding', None)
            except:
                shares = None
                
            return df, shares
        except: return None, None

    with st.spinner("計算成交量與換手率矩陣中..."):
        df, shares_outstanding = get_data(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"無法獲取 {display_ticker} 數據")
    else:
        # --- A. 核心計算 ---
        # 1. 滾動加總 (Volume Sums)
        periods = [7, 14, 28, 57, 106]
        for p in periods:
            df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()

        # 2. 比值 (Ratios)
        df['R1 (7/14)'] = df['Sum_7'] / df['Sum_14']
        df['R2 (7/28)'] = df['Sum_7'] / df['Sum_28']
        df['R3 (14/28)'] = df['Sum_14'] / df['Sum_28']
        df['R4 (14/57)'] = df['Sum_14'] / df['Sum_57']
        df['R5 (28/57)'] = df['Sum_28'] / df['Sum_57']
        df['R6 (28/106)'] = df['Sum_28'] / df['Sum_106']

        # 3. 基礎 SMA
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        # 4. === 新增功能：換手率特定序列計算 ===
        # 只有當獲取到流通股數時才計算
        has_turnover_data = False
        if shares_outstanding:
            has_turnover_data = True
            # (1) 單日換手率
            df['Turnover_Day'] = (df['Volume'] / shares_outstanding) * 100
            
            # (2) 區間加總換手率 (Sum of Turnover)
            # Sum(7)
            df['TO_Sum_7'] = (df['Sum_7'] / shares_outstanding) * 100
            
            # (3) 差值序列 (Incremental Turnover)
            # Sum(14) - Sum(7)
            df['TO_Diff_14_7'] = ((df['Sum_14'] - df['Sum_7']) / shares_outstanding) * 100
            # Sum(28) - Sum(14)
            df['TO_Diff_28_14'] = ((df['Sum_28'] - df['Sum_14']) / shares_outstanding) * 100
            # Sum(57) - Sum(28)
            df['TO_Diff_57_28'] = ((df['Sum_57'] - df['Sum_28']) / shares_outstanding) * 100
        
        # --- B. 介面呈現 ---
        
        # 區間選擇
        st.write("⏱️ **時間區間 (Time Interval):**")
        interval_options = ['1D', '5D', '1M', '3M', '6M', '1Y', '3Y']
        selected_interval = st.select_slider("Select", options=interval_options, value='6M', label_visibility="collapsed")
        
        display_df = filter_data_by_interval(df, selected_interval)

        # 增加 Tab 4
        tab1, tab2, tab3, tab4 = st.tabs(["📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume (Abs)", "💹 Turnover Rate % (NEW)"])

        # === Tab 1: 主圖 ===
        with tab1:
            fig_price = go.Figure()
            fig_price.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                         low=display_df['Low'], close=display_df['Close'], name='K線'))
            fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], 
                                     line=dict(color='orange', width=1), name=f'SMA {sma1}'))
            fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], 
                                     line=dict(color='blue', width=1), name=f'SMA {sma2}'))
            fig_price.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white")
            st.plotly_chart(fig_price, use_container_width=True)

        # === Tab 2: 比率曲線 ===
        with tab2:
            last_row = df.iloc[-1]
            st.subheader("📋 換手率結構比值 (Ratio Curves)")
            ratio_cols = ['R1 (7/14)', 'R2 (7/28)', 'R3 (14/28)', 'R4 (14/57)', 'R5 (28/57)', 'R6 (28/106)']
            colors = ['#FF6B6B', '#FFA500', '#FFD700', '#4CAF50', '#2196F3', '#9C27B0']

            fig_ratio = go.Figure()
            for i, col in enumerate(ratio_cols):
                latest_val = last_row[col]
                label_with_val = f"{col}: {latest_val:.3f}"
                fig_ratio.add_trace(go.Scatter(x=display_df.index, y=display_df[col], mode='lines',
                    name=label_with_val, line=dict(color=colors[i], width=2),
                    hovertemplate=f"<b>{col}</b><br>Value: %{{y:.3f}}<extra></extra>"))
            fig_ratio.update_layout(height=600, xaxis_title="Date", yaxis_title="Ratio", hovermode="x unified", template="plotly_white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_ratio, use_container_width=True)

        # === Tab 3: 成交量結構 (絕對值) ===
        with tab3:
            st.subheader("🧱 成交量分佈 (Volume in Shares)")
            curr = df.iloc[-1]
            last_7_days = df['Volume'].tail(7)
            inc_data = {
                "Sum(7)": curr['Sum_7'],
                "Sum(14)-Sum(7)": curr['Sum_14'] - curr['Sum_7'],
                "Sum(28)-Sum(14)": curr['Sum_28'] - curr['Sum_14'],
                "Sum(57)-Sum(28)": curr['Sum_57'] - curr['Sum_28']
            }
            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                st.caption("📅 最近 7 日成交量序列 (Day 1-7)")
                fig_days = go.Figure()
                fig_days.add_trace(go.Bar(x=last_7_days.index, y=last_7_days.values,
                    text=[format_large_num(v) for v in last_7_days.values], textposition='auto', marker_color='#636EFA'))
                fig_days.update_layout(height=400, template="plotly_white", showlegend=False)
                st.plotly_chart(fig_days, use_container_width=True)
            with c_chart2:
                st.caption("📈 區間增量分佈 (Incremental Sums)")
                fig_inc = go.Figure()
                fig_inc.add_trace(go.Bar(x=list(inc_data.keys()), y=list(inc_data.values()),
                    text=[format_large_num(v) for v in inc_data.values()], textposition='auto', marker_color='#EF553B'))
                fig_inc.update_layout(height=400, template="plotly_white", showlegend=False)
                st.plotly_chart(fig_inc, use_container_width=True)

        # === Tab 4: 換手率結構 (NEW) ===
        with tab4:
            if not has_turnover_data:
                st.warning("⚠️ 無法獲取流通股數 (Shares Outstanding)，無法計算換手率百分比。")
            else:
                last_row = df.iloc[-1]
                st.subheader("💹 換手率結構分析 (Target: Turnover Rate %)")
                
                # --- Part 1: Day(1)-Day(7) ---
                st.markdown("#### 1. Daily Turnover Sequence (Day 1-7)")
                
                # 準備列表數據 (最近 7 天)
                last_7_to = df['Turnover_Day'].tail(7).sort_index(ascending=False) # 倒序: Day 1 (最新) -> Day 7
                
                # 列表顯示
                cols_d = st.columns(7)
                for i in range(7):
                    # 安全檢查，避免數據不足 7 天報錯
                    if i < len(last_7_to):
                        date_str = last_7_to.index[i].strftime('%m-%d')
                        val = last_7_to.iloc[i]
                        with cols_d[i]:
                            st.metric(label=f"Day({i+1})", value=f"{val:.2f}%", delta=date_str, delta_color="off")
                
                # 曲線顯示 (Daily Turnover Curve)
                fig_to_day = go.Figure()
                fig_to_day.add_trace(go.Scatter(
                    x=display_df.index, 
                    y=display_df['Turnover_Day'],
                    mode='lines',
                    name=f"Daily Turnover: {last_row['Turnover_Day']:.2f}%",
                    line=dict(color='#00CC96', width=1.5),
                    fill='tozeroy', # 填充背景讓每日換手率更清楚
                    hovertemplate="Date: %{x}<br>Turnover: %{y:.2f}%<extra></extra>"
                ))
                fig_to_day.update_layout(height=350, title="Daily Turnover Trend", template="plotly_white", hovermode="x unified")
                st.plotly_chart(fig_to_day, use_container_width=True)

                st.divider()

                # --- Part 2: Incremental Turnover Sums ---
                st.markdown("#### 2. Incremental Turnover Sums (Difference Sequence)")
                
                # 定義 4 個指標
                to_metrics = [
                    {"col": "TO_Sum_7", "label": "Sum(7)", "color": "#AB63FA"},
                    {"col": "TO_Diff_14_7", "label": "Sum(14)-Sum(7)", "color": "#FFA15A"},
                    {"col": "TO_Diff_28_14", "label": "Sum(28)-Sum(14)", "color": "#19D3F3"},
                    {"col": "TO_Diff_57_28", "label": "Sum(57)-Sum(28)", "color": "#FF6692"},
                ]

                # 列表顯示
                cols_inc = st.columns(4)
                for i, item in enumerate(to_metrics):
                    val = last_row[item['col']]
                    with cols_inc[i]:
                        st.metric(label=item['label'], value=f"{val:.2f}%")
                        st.markdown(f'<div style="background-color:{item["color"]};height:4px;border-radius:2px;"></div>', unsafe_allow_html=True)

                # 曲線顯示 (Incremental Curves)
                fig_to_inc = go.Figure()
                for item in to_metrics:
                    latest_val = last_row[item['col']]
                    label_val = f"{item['label']}: {latest_val:.2f}%"
                    
                    fig_to_inc.add_trace(go.Scatter(
                        x=display_df.index,
                        y=display_df[item['col']],
                        mode='lines',
                        name=label_val,
                        line=dict(color=item['color'], width=2),
                        hovertemplate=f"<b>{item['label']}</b>: %{{y:.2f}}%<extra></extra>"
                    ))
                
                fig_to_inc.update_layout(
                    height=500, 
                    title="Incremental Turnover Sums Trend", 
                    yaxis_title="Turnover Rate (%)",
                    template="plotly_white", 
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_to_inc, use_container_width=True)
