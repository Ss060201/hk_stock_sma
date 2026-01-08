import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 Turnover Rate 分析", page_icon="📊", layout="wide")

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

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view

if not current_code:
    st.title("港股 Turnover Rate (換手率) 分析系統")
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
    def get_data_with_shares(symbol):
        try:
            # 1. 獲取歷史價格
            df = yf.download(symbol, period="4y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 2. 獲取流通股數 (Shares Outstanding)
            ticker_obj = yf.Ticker(symbol)
            shares = ticker_obj.info.get('sharesOutstanding', None)
            
            return df, shares
        except: return None, None

    with st.spinner("正在下載並計算換手率數據..."):
        df, shares_outstanding = get_data_with_shares(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"無法獲取 {display_ticker} 數據")
    elif not shares_outstanding:
        st.error(f"⚠️ 無法獲取 {display_ticker} 的流通股數 (Shares Outstanding)，無法計算換手率百分比。")
        st.caption("建議：請嘗試其他大型股，或稍後再試。")
    else:
        # --- A. 核心計算 (全部基於換手率 %) ---
        
        # 1. 計算單日換手率 (Daily Turnover %)
        # 公式: (成交量 / 流通股數) * 100
        df['Turnover_Pct'] = (df['Volume'] / shares_outstanding) * 100

        # 2. 計算滾動換手率加總 (Rolling Sum of Turnover)
        # 用於計算區間總換手
        periods = [7, 14, 28, 57]
        for p in periods:
            df[f'T_Sum_{p}'] = df['Turnover_Pct'].rolling(window=p).sum()

        # 3. 計算增量序列 (Incremental Series)
        # Sum(7)
        df['Inc_Sum_7'] = df['T_Sum_7']
        # Sum(14) - Sum(7)
        df['Inc_Sum_14_7'] = df['T_Sum_14'] - df['T_Sum_7']
        # Sum(28) - Sum(14)
        df['Inc_Sum_28_14'] = df['T_Sum_28'] - df['T_Sum_14']
        # Sum(57) - Sum(28)
        df['Inc_Sum_57_28'] = df['T_Sum_57'] - df['T_Sum_28']

        # --- B. 介面呈現 ---
        
        # 區間選擇
        st.write("⏱️ **圖表觀察區間:**")
        interval_options = ['1D', '5D', '1M', '3M', '6M', '1Y', '3Y']
        selected_interval = st.select_slider("Select", options=interval_options, value='6M', label_visibility="collapsed")
        
        display_df = filter_data_by_interval(df, selected_interval)
        last_row = df.iloc[-1]

        # 分頁設計
        tab1, tab2 = st.tabs(["📅 Day(1)-Day(7) (單日序列)", "📈 Period Incremental (區間增量)"])

        # === Tab 1: Day(1)-Day(7) 單日換手率 ===
        with tab1:
            st.subheader("📋 單日換手率列表 (Latest 7 Days)")
            
            # 準備數據: 取最後 7 天並倒序 (Day 1 = Latest)
            last_7_days = df['Turnover_Pct'].tail(7).iloc[::-1]
            
            # 列表顯示
            cols = st.columns(7)
            for i, (date, val) in enumerate(last_7_days.items()):
                with cols[i]:
                    st.metric(
                        label=f"Day({i+1})", 
                        value=f"{val:.3f}%",
                        help=date.strftime('%Y-%m-%d')
                    )
            
            st.divider()
            
            # 曲線圖
            st.subheader(f"📈 日換手率走勢圖 ({selected_interval})")
            fig_day = go.Figure()
            
            # 嵌入數值標註到 Legend
            latest_val = df['Turnover_Pct'].iloc[-1]
            label_day = f"Daily Turnover: {latest_val:.3f}%"
            
            fig_day.add_trace(go.Scatter(
                x=display_df.index, 
                y=display_df['Turnover_Pct'],
                mode='lines',
                name=label_day,
                line=dict(color='#2962FF', width=1.5),
                hovertemplate="<b>Date</b>: %{x}<br><b>Turnover</b>: %{y:.3f}%<extra></extra>"
            ))
            
            fig_day.update_layout(
                height=500, xaxis_title="Date", yaxis_title="Turnover Rate (%)",
                hovermode="x unified", template="plotly_white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_day, use_container_width=True)

        # === Tab 2: Sum(7) & Incremental Sums ===
        with tab2:
            st.subheader("📋 區間換手率增量列表")
            
            # 定義顯示項目
            inc_items = [
                {"id": "Inc_Sum_7", "label": "Sum(7)", "color": "#FF6B6B"},
                {"id": "Inc_Sum_14_7", "label": "Sum(14) - Sum(7)", "color": "#FFA500"},
                {"id": "Inc_Sum_28_14", "label": "Sum(28) - Sum(14)", "color": "#00E676"},
                {"id": "Inc_Sum_57_28", "label": "Sum(57) - Sum(28)", "color": "#651FFF"},
            ]
            
            # 列表顯示
            c1, c2, c3, c4 = st.columns(4)
            cols_ref = [c1, c2, c3, c4]
            
            for i, item in enumerate(inc_items):
                val = last_row[item['id']]
                with cols_ref[i]:
                    st.metric(label=item['label'], value=f"{val:.3f}%")
                    st.markdown(f'<div style="background-color:{item["color"]};height:4px;border-radius:2px;"></div>', unsafe_allow_html=True)

            st.divider()

            # 曲線圖
            st.subheader(f"📈 區間增量走勢圖 ({selected_interval})")
            
            if display_df.empty:
                st.warning("數據不足")
            else:
                fig_inc = go.Figure()
                
                for item in inc_items:
                    col_name = item['id']
                    val = last_row[col_name]
                    # 嵌入數值到 Legend
                    label_with_val = f"{item['label']}: {val:.3f}%"
                    
                    fig_inc.add_trace(go.Scatter(
                        x=display_df.index,
                        y=display_df[col_name],
                        mode='lines',
                        name=label_with_val,
                        line=dict(color=item['color'], width=2),
                        hovertemplate=f"<b>{item['label']}</b>: %{{y:.3f}}%<extra></extra>"
                    ))

                fig_inc.update_layout(
                    height=600,
                    xaxis_title="Date",
                    yaxis_title="Accumulated Turnover (%)",
                    hovermode="x unified",
                    template="plotly_white",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                
                st.plotly_chart(fig_inc, use_container_width=True)
                
                st.info("""
                **指標解讀**:
                * **Sum(7)**: 最近 7 個交易日的總換手率。
                * **Sum(14)-Sum(7)**: 過去第 8 天到第 14 天的總換手率 (上一週的活躍度)。
                * 此圖表用於觀察籌碼交換的**時間分佈**。若 Sum(7) 曲線急劇上升並超過其他長週期曲線，代表近期資金介入極其明顯。
                """)
