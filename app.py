import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 Volume Structure 分析", page_icon="📊", layout="wide")

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
    st.title("港股 Volume Structure 分析系統")
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
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except: return None

    with st.spinner("計算成交量矩陣數據中..."):
        df = get_data(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"無法獲取 {display_ticker} 數據")
    else:
        # --- A. 核心計算 ---
        # 1. 滾動加總 (Volume Sums)
        periods = [7, 14, 28, 57, 106]
        for p in periods:
            df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()

        # 2. 六組換手率比值 (Ratios) - Target: Turnover Structure
        df['R1 (7/14)'] = df['Sum_7'] / df['Sum_14']
        df['R2 (7/28)'] = df['Sum_7'] / df['Sum_28']
        df['R3 (14/28)'] = df['Sum_14'] / df['Sum_28']
        df['R4 (14/57)'] = df['Sum_14'] / df['Sum_57']
        df['R5 (28/57)'] = df['Sum_28'] / df['Sum_57']
        df['R6 (28/106)'] = df['Sum_28'] / df['Sum_106']

        # 3. 基礎 SMA
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()
        
        # --- B. 介面呈現 ---
        
        # 區間選擇
        st.write("⏱️ **時間區間 (Time Interval):**")
        interval_options = ['1D', '5D', '1M', '3M', '6M', '1Y', '3Y']
        selected_interval = st.select_slider("Select", options=interval_options, value='6M', label_visibility="collapsed")
        
        display_df = filter_data_by_interval(df, selected_interval)

        tab1, tab2, tab3 = st.tabs(["📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume Structure"])

        # === Tab 1: 主圖 ===
        with tab1:
            fig_price = go.Figure()
            fig_price.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                         low=display_df['Low'], close=display_df['Close'], name='K線'))
            fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], 
                                     line=dict(color='orange', width=1), name=f'SMA {sma1}'))
            fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], 
                                     line=dict(color='blue', width=1), name=f'SMA {sma2}'))
            fig_price.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white", title="股價走勢")
            st.plotly_chart(fig_price, use_container_width=True)

        # === Tab 2: 比率曲線 (含數值標註) ===
        with tab2:
            last_row = df.iloc[-1]
            st.subheader("📋 換手率結構比值 (Ratio Curves)")
            
            ratio_cols = ['R1 (7/14)', 'R2 (7/28)', 'R3 (14/28)', 'R4 (14/57)', 'R5 (28/57)', 'R6 (28/106)']
            colors = ['#FF6B6B', '#FFA500', '#FFD700', '#4CAF50', '#2196F3', '#9C27B0']

            fig_ratio = go.Figure()
            
            for i, col in enumerate(ratio_cols):
                latest_val = last_row[col]
                # 這裡實現 "直接嵌入對應周期的數值標註"
                # 在 Legend 中顯示數值，格式如: "Sum(7)/Sum(14): 0.512"
                label_with_val = f"{col}: {latest_val:.3f}"
                
                fig_ratio.add_trace(go.Scatter(
                    x=display_df.index, 
                    y=display_df[col],
                    mode='lines',
                    name=label_with_val, # 將數值嵌入圖例
                    line=dict(color=colors[i], width=2),
                    hovertemplate=f"<b>{col}</b><br>Value: %{{y:.3f}}<extra></extra>"
                ))

            fig_ratio.update_layout(
                height=650,
                xaxis_title="Date",
                yaxis_title="Ratio Value",
                hovermode="x unified",
                template="plotly_white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_ratio, use_container_width=True)
            
            # 列表顯示
            st.write("---")
            c_list = st.columns(6)
            for i, col in enumerate(ratio_cols):
                with c_list[i]:
                    st.metric(label=col.split(" ")[0], value=f"{last_row[col]:.3f}", delta=None)
                    st.caption(col.split(" ")[1]) # 顯示 (7/14) 這種細節

        # === Tab 3: 成交量結構分析 (新增功能) ===
        with tab3:
            st.subheader("🧱 成交量分佈與差值序列")
            
            # 準備數據 (取最新的一天)
            curr = df.iloc[-1]
            
            # 1. Day(1) - Day(7) 序列
            # 獲取最近 7 天的成交量
            last_7_days = df['Volume'].tail(7)
            # 為了顯示為 Day(1)...Day(7)，我們需要生成標籤
            # Day(1) 通常指最新的一天 (Today)，Day(7) 是 7 天前
            # 這裡我們用實際日期做 X 軸，標籤輔助顯示
            days_x = [d.strftime('%m-%d') for d in last_7_days.index][::-1] # 倒序，讓最新的在左邊? 或者按時間順序
            # 習慣上時間序列圖是左舊右新
            days_y = last_7_days.values
            days_labels = [f"Day({i+1})" for i in range(7)][::-1] # Day(1) 是最新
            
            # 2. 差值序列 (Incremental Sums)
            # Sum(7), Sum(14)-Sum(7), Sum(28)-Sum(14), Sum(57)-Sum(28)
            inc_data = {
                "Sum(7)": curr['Sum_7'],
                "Sum(14)-Sum(7)": curr['Sum_14'] - curr['Sum_7'],
                "Sum(28)-Sum(14)": curr['Sum_28'] - curr['Sum_14'],
                "Sum(57)-Sum(28)": curr['Sum_57'] - curr['Sum_28']
            }
            
            # 繪圖區域
            c_chart1, c_chart2 = st.columns(2)
            
            with c_chart1:
                st.caption("📅 最近 7 日成交量序列 (Day 1-7)")
                fig_days = go.Figure()
                fig_days.add_trace(go.Bar(
                    x=last_7_days.index,
                    y=last_7_days.values,
                    text=[format_large_num(v) for v in last_7_days.values],
                    textposition='auto',
                    marker_color='#636EFA',
                    name="Volume"
                ))
                fig_days.update_layout(height=400, template="plotly_white", showlegend=False)
                st.plotly_chart(fig_days, use_container_width=True)
                
            with c_chart2:
                st.caption("📈 區間增量分佈 (Incremental Sums)")
                st.info("此圖顯示成交量在不同時間跨度的「淨增量」，幫助判斷籌碼是集中在近期還是遠期。")
                
                fig_inc = go.Figure()
                fig_inc.add_trace(go.Bar(
                    x=list(inc_data.keys()),
                    y=list(inc_data.values()),
                    text=[format_large_num(v) for v in inc_data.values()],
                    textposition='auto',
                    marker_color=['#EF553B', '#FFA15A', '#AB63FA', '#19D3F3'],
                ))
                fig_inc.update_layout(height=400, template="plotly_white", showlegend=False)
                st.plotly_chart(fig_inc, use_container_width=True)

            # 數據列表展示
            st.write("---")
            st.write("詳細數據列表：")
            c_d1, c_d2 = st.columns(2)
            
            with c_d1:
                st.markdown("**Day Sequence (Latest 7 Days)**")
                # 倒序顯示，Day(1) 為最新
                for i in range(7):
                    day_idx = 7 - i - 1 # 6, 5...0
                    date_str = last_7_days.index[day_idx].strftime('%Y-%m-%d')
                    vol_val = last_7_days.iloc[day_idx]
                    st.text(f"Day({i+1}) [{date_str}]: {format_large_num(vol_val)}")

            with c_d2:
                st.markdown("**Difference Sequence (Incremental)**")
                for k, v in inc_data.items():
                    st.text(f"{k}: {format_large_num(v)}")
