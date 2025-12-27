import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣分析", page_icon="📈", layout="wide")

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
    """將大數字格式化為易讀格式 (K, M, B)"""
    if pd.isna(num): return "-"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.2f}K"
    else:
        return f"{num:.0f}"

# --- 3. 側邊欄設定 ---
with st.sidebar:
    st.header("HK Stock Matrix")
    
    # 搜尋框
    search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
    if search_input:
        cleaned_search = clean_ticker_input(search_input)
        if cleaned_search:
            st.session_state.current_view = cleaned_search

    st.divider()
    
    # 收藏夾
    st.subheader(f"我的收藏 ({len(st.session_state.watchlist)})")
    if st.session_state.watchlist:
        for ticker in st.session_state.watchlist:
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                st.session_state.current_view = ticker
    else:
        st.caption("暫無收藏")

    st.divider()
    st.header("⚙️ 矩陣參數設定")
    
    # 6條 SMA 設定
    st.caption("SMA 週期 (Days)")
    c1, c2 = st.columns(2)
    with c1:
        p1 = st.number_input("SMA 1", value=7)
        p3 = st.number_input("SMA 3", value=28)
        p5 = st.number_input("SMA 5", value=106)
    with c2:
        p2 = st.number_input("SMA 2", value=14)
        p4 = st.number_input("SMA 4", value=57)
        p6 = st.number_input("SMA 6", value=212)
    
    periods = [p1, p2, p3, p4, p5, p6]
    
    st.divider()
    st.caption("收斂偵測設定")
    y_scale = st.slider("收斂圖 Y 軸範圍 (%)", 1.0, 20.0, 5.0, 0.5) / 100
    convergence_threshold = st.slider("收斂判定閾值 (%)", 0.1, 2.0, 0.5, 0.1) / 100

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view

if not current_code:
    st.title("均線矩陣分析系統")
    st.info("👈 請輸入代號開始分析")
else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    # 標題區
    c_title, c_btn = st.columns([0.85, 0.15])
    with c_title:
        st.title(f"📊 {display_ticker}")
    with c_btn:
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
            # 抓取足夠長的數據以計算 SMA 212
            df = yf.download(symbol, period="2y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except: return None

    with st.spinner("正在進行矩陣運算..."):
        df = get_data(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"無法獲取 {display_ticker} 數據")
    else:
        # --- A. SMA & Volume Sum 計算 ---
        sma_cols = []
        vol_cols = []
        
        for p in periods:
            # SMA
            col_name = f'SMA_{p}'
            df[col_name] = df['Close'].rolling(window=p).mean()
            sma_cols.append(col_name)
            
            # Volume Sum (成交量累計)
            v_name = f'Vol_Sum_{p}'
            df[v_name] = df['Volume'].rolling(window=p).sum()
            vol_cols.append(v_name)

        # --- B. 平均值計算 (只計算前 5 條: 7, 14, 28, 57, 106) ---
        avg_cols = sma_cols[:5] 
        df['SMA_Avg_5'] = df[avg_cols].mean(axis=1)

        # --- C. 收斂度計算 (Convergence) ---
        conv_cols = []
        for i, col in enumerate(avg_cols): 
            p = periods[i]
            c_name = f'Conv_{p}'
            df[c_name] = (df[col] - df['SMA_Avg_5']) / df['SMA_Avg_5']
            conv_cols.append(c_name)

        # --- D. 偵測收斂訊號 ---
        def check_convergence(row):
            count = 0
            for c in conv_cols:
                if abs(row[c]) <= convergence_threshold:
                    count += 1
            return count

        df['Conv_Count'] = df.apply(check_convergence, axis=1)
        signal_mask = df['Conv_Count'] > 2 

        # --- E. 介面分頁 (Tabs) ---
        tab1, tab2 = st.tabs(["📈 SMA & Convergence (圖表)", "📊 Turnover Sum (成交量列表)"])
        
        last_row = df.iloc[-1]
        colors = ['#FF6B6B', '#FFA500', '#FFD700', '#4CAF50', '#2196F3', '#9C27B0']

        # === Tab 1: 圖表介面 ===
        with tab1:
            # 顯示簡單的 SMA 數值卡片
            cols_sma = st.columns(6)
            for i, p in enumerate(periods):
                val = last_row[f'SMA_{p}']
                with cols_sma[i]:
                    st.metric(f"SMA ({p})", f"{val:.2f}")
                    st.markdown(f'<div style="background-color:{colors[i]};height:4px;border-radius:2px;"></div>', unsafe_allow_html=True)
            
            # 繪圖
            display_df = df.iloc[-250:] 
            display_signal = signal_mask.iloc[-250:]

            fig = make_subplots(
                rows=4, cols=1, 
                shared_xaxes=True,
                vertical_spacing=0.02,
                row_heights=[0.5, 0.25, 0.15, 0.1],
                subplot_titles=(f"價格與 6 均線", "均線收斂度 (Convergence)", "成交量", "RSI")
            )

            # 1. 主圖
            fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                         low=display_df['Low'], close=display_df['Close'], name='K線'), row=1, col=1)
            for i, p in enumerate(periods):
                fig.add_trace(go.Scatter(
                    x=display_df.index, y=display_df[f'SMA_{p}'], 
                    line=dict(color=colors[i], width=1), name=f'SMA {p}'
                ), row=1, col=1)

            # 2. 收斂圖
            fig.add_hline(y=0, line_dash="solid", line_color="gray", row=2, col=1)
            fig.add_hline(y=convergence_threshold, line_dash="dot", line_color="gray", opacity=0.5, row=2, col=1)
            fig.add_hline(y=-convergence_threshold, line_dash="dot", line_color="gray", opacity=0.5, row=2, col=1)

            for i, c_name in enumerate(conv_cols):
                p = periods[i]
                fig.add_trace(go.Scatter(
                    x=display_df.index, y=display_df[c_name],
                    line=dict(color=colors[i], width=1.5), name=f'Conv {p}'
                ), row=2, col=1)

            converge_dates = display_df[display_signal].index
            if not converge_dates.empty:
                fig.add_trace(go.Scatter(
                    x=converge_dates, y=[0] * len(converge_dates),
                    mode='markers', marker=dict(symbol='diamond', size=10, color='red'),
                    name='收斂訊號'
                ), row=2, col=1)

            # 3. 成交量
            vol_colors = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for _, r in display_df.iterrows()]
            fig.add_trace(go.Bar(x=display_df.index, y=display_df['Volume'], marker_color=vol_colors, name='Volume'), row=3, col=1)

            # 4. RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            display_rsi = rsi.iloc[-250:]
            
            fig.add_trace(go.Scatter(x=display_df.index, y=display_rsi, line=dict(color='purple'), name='RSI'), row=4, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", row=4, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", row=4, col=1)

            fig.update_layout(
                height=900, xaxis_rangeslider_visible=False, showlegend=True,
                margin=dict(t=30, l=10, r=10, b=10), template="plotly_white"
            )
            fig.update_yaxes(range=[-y_scale, y_scale], tickformat=".1%", title="偏離度", row=2, col=1)
            fig.update_yaxes(title="價格", row=1, col=1)

            st.plotly_chart(fig, use_container_width=True)

        # === Tab 2: 列表介面 (成交量累計) ===
        with tab2:
            st.subheader("📊 Turnover (Volume) Sum 列表")
            st.caption("以下顯示各週期內的成交量總和 (Sum of Volume)：")
            
            # 使用列表呈現 (卡片式)
            cols_vol = st.columns(3) # 分3列顯示
            for i, p in enumerate(periods):
                val_vol = last_row[f'Vol_Sum_{p}']
                # 計算行數來分配 (0,1,2 -> row 1; 3,4,5 -> row 2)
                with cols_vol[i % 3]:
                    st.container(border=True).metric(
                        label=f"Sum ({p} Days)", 
                        value=format_large_num(val_vol),
                        help=f"精確數值: {val_vol:,.0f} 股"
                    )
            
            st.divider()
            
            # 詳細表格數據
            st.caption("詳細數據表 (最近 5 日):")
            recent_data = df[[f'Vol_Sum_{p}' for p in periods]].tail(5).sort_index(ascending=False)
            # 格式化 Dataframe 顯示
            formatted_df = recent_data.applymap(lambda x: f"{x:,.0f}")
            st.dataframe(formatted_df, use_container_width=True)
