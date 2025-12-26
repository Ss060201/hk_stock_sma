import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 分析", page_icon="📈", layout="wide")

# 讀取 URL 中的 watchlist
query_params = st.query_params
url_watchlist = query_params.get("watchlist", "") 

# 初始化 Session State
if 'watchlist' not in st.session_state:
    if url_watchlist:
        st.session_state.watchlist = url_watchlist.split(",")
    else:
        st.session_state.watchlist = []

if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

# --- 2. 核心邏輯函數 ---
def clean_ticker_input(symbol):
    """
    處理使用者輸入：
    1. 移除空白
    2. 確保只有數字
    3. 補齊為港股常見格式 (雖然 Yahoo 接受 0700, 但我們保持輸入純淨)
    """
    symbol = str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")
    return symbol

def get_yahoo_ticker(symbol):
    """將純數字代號轉換為 Yahoo Finance 格式"""
    # Yahoo Finance 港股格式必須是 4位數 + .HK (例如 0700.HK)
    # 如果使用者輸入 700 -> 0700.HK
    if symbol.isdigit():
        return f"{symbol.zfill(4)}.HK"
    return symbol

def update_url():
    watchlist_str = ",".join(st.session_state.watchlist)
    st.query_params["watchlist"] = watchlist_str

def toggle_watchlist(ticker):
    # 確保儲存的是純數字代號，不是 Yahoo 格式
    clean_code = clean_ticker_input(ticker)
    if clean_code in st.session_state.watchlist:
        st.session_state.watchlist.remove(clean_code)
        st.toast(f'已移除 {clean_code}', icon="🗑️")
    else:
        st.session_state.watchlist.append(clean_code)
        st.toast(f'已收藏 {clean_code}', icon="⭐")
    update_url()

# (已移除 get_market_index 函數)

# --- 3. 側邊欄設計 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    # 1. 純淨的搜尋框
    search_input = st.text_input("輸入股票代號", placeholder="例如: 700 或 00005", key="search_bar")
    
    # 邏輯：有輸入則優先顯示輸入的股票
    if search_input:
        cleaned_search = clean_ticker_input(search_input)
        if cleaned_search:
            st.session_state.current_view = cleaned_search

    st.divider()
    
    # 2. 收藏夾列表
    st.subheader(f"我的收藏 ({len(st.session_state.watchlist)})")
    
    if not st.session_state.watchlist:
        st.caption("暫無收藏")
    else:
        for ticker in st.session_state.watchlist:
            # 按鈕顯示純代號
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                st.session_state.current_view = ticker

    st.divider()
    st.caption("SMA 參數設定")
    sma1 = st.number_input("SMA 短線", value=20)
    sma2 = st.number_input("SMA 長線", value=50)

# --- 4. 主畫面內容 ---

# (已移除大市看板顯示區域)

# 4.1 判斷是否需要顯示分析圖表
current_code = st.session_state.current_view

if not current_code:
    # 這裡稍微調整版面，因為沒有上面的指數了，顯示一個歡迎標題比較好看
    st.title("歡迎使用港股 SMA 分析")
    st.info("👈 請在左側輸入代號 (例如 700) 或選擇收藏股以開始分析。")
else:
    # 準備數據
    yahoo_ticker = get_yahoo_ticker(current_code) # 轉成後台用的 0700.HK
    display_ticker = current_code.zfill(5) # 前台顯示漂亮的 00700 格式

    # 標題與收藏按鈕區域
    col_title, col_star = st.columns([0.85, 0.15])

    with col_title:
        st.title(f"📊 {display_ticker}")

    with col_star:
        st.write("") 
        is_fav = current_code in st.session_state.watchlist
        if is_fav:
            if st.button("★ 已收藏", type="primary", use_container_width=True):
                toggle_watchlist(current_code)
                st.rerun()
        else:
            if st.button("☆ 加入", use_container_width=True):
                toggle_watchlist(current_code)
                st.rerun()

    # 抓取數據與繪圖
    @st.cache_data(ttl=900)
    def get_stock_data(symbol):
        try:
            data = yf.download(symbol, period="2y", auto_adjust=False)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return data
        except:
            return None

    with st.spinner(f"正在分析 {display_ticker}..."):
        df = get_stock_data(yahoo_ticker)

    if df is None or df.empty:
        st.error(f"⚠️ 找不到代號 **{current_code}** 的數據，請確認輸入正確。")
    else:
        # SMA & RSI 計算
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 繪圖 (Plotly)
        display_df = df.iloc[-250:]
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                            subplot_titles=("價格 & SMA", "成交量", "RSI (14)"))

        fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                     low=display_df['Low'], close=display_df['Close'], name='K線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], 
                                 line=dict(color='orange'), name=f'SMA {sma1}'), row=1, col=1)
        fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], 
                                 line=dict(color='blue'), name=f'SMA {sma2}'), row=1, col=1)
        
        colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in display_df.iterrows()]
        fig.add_trace(go.Bar(x=display_df.index, y=display_df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
        
        fig.add_trace(go.Scatter(x=display_df.index, y=display_df['RSI'], line=dict(color='purple'), name='RSI'), row=3, col=1)
        
        # RSI 輔助線
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, template="plotly_white", margin=dict(t=30))
        st.plotly_chart(fig, use_container_width=True)
