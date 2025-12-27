import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 Volume Ratio 分析", page_icon="📊", layout="wide")

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

def filter_data_by_interval(df, interval):
    """根據選擇的時間區間篩選數據"""
    if df.empty: return df
    
    end_date = df.index[-1]
    start_date = end_date # Default
    
    if interval == '1D':
        # 1D 對於日線圖來說就是最後一行，但為了畫圖通常至少回傳 2 筆，或只顯示當天
        return df.iloc[-1:] 
    elif interval == '5D':
        start_date = end_date - timedelta(days=5)
    elif interval == '1M':
        start_date = end_date - relativedelta(months=1)
    elif interval == '3M':
        start_date = end_date - relativedelta(months=3)
    elif interval == '6M':
        start_date = end_date - relativedelta(months=6)
    elif interval == '1Y':
        start_date = end_date - relativedelta(years=1)
    elif interval == '3Y':
        start_date = end_date - relativedelta(years=3)
    else:
        return df # Max
        
    return df[df.index >= start_date]

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
    if search_input:
        cleaned_search = clean_ticker_input(search_input)
        if cleaned_search:
            st.session_state.current_view = cleaned_search

    st.divider()
    
    st.subheader(f"我的收藏 ({len(st.session_state.watchlist)})")
    if st.session_state.watchlist:
        for ticker in st.session_state.watchlist:
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                st.session_state.current_view = ticker
    else:
        st.caption("暫無收藏")

    st.divider()
    st.caption("基礎 SMA 設定 (用於主圖)")
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view

if not current_code:
    st.title("港股 Volume Ratio 分析系統")
    st.info("👈 請輸入代號開始分析")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    # 標題與收藏
    col_t, col_b = st.columns([0.85, 0.15])
    with col_t:
        st.title(f"📊 {display_ticker}")
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

    # 獲取數據 (抓 4 年以確保 3Y 顯示正常)
    @st.cache_data(ttl=900)
    def get_data(symbol):
        try:
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except: return None

    with st.spinner("計算成交量比率模型中..."):
        df = get_data(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"無法獲取 {display_ticker} 數據")
    else:
        # --- A. 基礎計算 ---
        # 1. 計算所需的 Rolling Sum
        # 需要的週期: 7, 14, 28, 57
        periods = [7, 14, 28, 57]
        for p in periods:
            df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()

        # 2. 計算使用者指定的 5 個 Ratio 公式
        # R1: Sum(7)/sum(28)
        df['R1'] = df['Sum_7'] / df['Sum_28']
        
        # R2: sum(7)/(sum(14)+sum(28))
        df['R2'] = df['Sum_7'] / (df['Sum_14'] + df['Sum_28'])
        
        # R3: Sum(14)/sum(28)
        df['R3'] = df['Sum_14'] / df['Sum_28']
        
        # R4: Sum(14)/(sum(14)+sum(28))
        df['R4'] = df['Sum_14'] / (df['Sum_14'] + df['Sum_28'])
        
        # R5: Sum(14)/(sum(14)+sum(28)+sum(57))
        df['R5'] = df['Sum_14'] / (df['Sum_14'] + df['Sum_28'] + df['Sum_57'])

        # 基礎 SMA (給 Tab1 用)
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        # --- B. 介面呈現 ---
        
        # 時間區間選擇器 (放在最上面，控制所有圖表)
        st.write("⏱️ **選擇觀察區間 (Time Interval):**")
        interval_options = ['1D', '5D', '1M', '3M', '6M', '1Y', '3Y']
        selected_interval = st.select_slider("滑動選擇時間跨度", options=interval_options, value='6M', label_visibility="collapsed")

        # 根據選擇篩選數據
        display_df = filter_data_by_interval(df, selected_interval)

        tab1, tab2 = st.tabs(["📉 Price & SMA (主圖)", "📊 Volume Ratio Curves (比率分析)"])

        # === Tab 1: 價格主圖 (保留基本功能) ===
        with tab1:
            if display_df.empty:
                st.warning("選定區間無數據")
            else:
                fig_price = go.Figure()
                fig_price.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                             low=display_df['Low'], close=display_df['Close'], name='K線'))
                fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], 
                                         line=dict(color='orange', width=1), name=f'SMA {sma1}'))
                fig_price.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], 
                                         line=dict(color='blue', width=1), name=f'SMA {sma2}'))
                
                fig_price.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white",
                                        title=f"股價走勢 ({selected_interval})")
                st.plotly_chart(fig_price, use_container_width=True)

        # === Tab 2: 成交量比率分析 (核心需求) ===
        with tab2:
            last_row = df.iloc[-1]
            
            # 1. 列表顯示 (List Display)
            st.subheader("📋 最新比率數值 (Latest Ratios)")
            
            # 定義公式名稱與顏色
            ratio_configs = [
                {"id": "R1", "label": "Sum(7) / Sum(28)", "color": "#FF6B6B"},
                {"id": "R2", "label": "Sum(7) / (Sum(14)+Sum(28))", "color": "#FFA500"},
                {"id": "R3", "label": "Sum(14) / Sum(28)", "color": "#FFD700"},
                {"id": "R4", "label": "Sum(14) / (Sum(14)+Sum(28))", "color": "#4CAF50"},
                {"id": "R5", "label": "Sum(14) / (S(14)+S(28)+S(57))", "color": "#2196F3"},
            ]

            # 顯示 Metrics
            cols = st.columns(5)
            for i, conf in enumerate(ratio_configs):
                val = last_row[conf['id']]
                with cols[i]:
                    st.metric(label=conf['id'], value=f"{val:.4f}")
                    st.caption(conf['label'])
                    st.markdown(f'<div style="background-color:{conf["color"]};height:4px;border-radius:2px;"></div>', unsafe_allow_html=True)
            
            st.divider()

            # 2. 曲線圖 (Curve Graph)
            st.subheader(f"📈 比率收斂趨勢圖 ({selected_interval})")
            
            if display_df.empty:
                st.warning("選定區間無數據，請切換至更長的時間範圍 (例如 3M 或 1Y)。")
            elif selected_interval == '1D':
                st.info("⚠️ '1D' 模式下僅顯示單點數據，無法繪製曲線，請選擇 5D 以上區間。")
            else:
                fig_ratio = go.Figure()
                
                # 繪製 5 條曲線
                for conf in ratio_configs:
                    fig_ratio.add_trace(go.Scatter(
                        x=display_df.index, 
                        y=display_df[conf['id']],
                        mode='lines',
                        name=conf['id'], # Legend 顯示簡稱
                        line=dict(color=conf['color'], width=2),
                        hovertemplate=f"<b>{conf['label']}</b><br>Value: %{{y:.4f}}<extra></extra>"
                    ))

                fig_ratio.update_layout(
                    height=600,
                    xaxis_title="Date",
                    yaxis_title="Ratio Value",
                    hovermode="x unified", # 統一顯示 tooltip，方便比較收斂
                    template="plotly_white",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    )
                )
                
                st.plotly_chart(fig_ratio, use_container_width=True)
                
                st.caption("ℹ️ **操作提示**：\n"
                           "- 上方滑桿可切換時間區間 (1D - 3Y)。\n"
                           "- 點擊圖例 (Legend) 可隱藏/顯示特定曲線。\n"
                           "- 當多條曲線數值接近時，即為「收斂」現象。")
