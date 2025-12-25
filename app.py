import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(
    page_title="港股 SMA 分析工具",
    page_icon="📈",
    layout="wide"
)

st.title("🇭🇰 港股 SMA 技術分析工具 (No API)")
st.markdown("數據來源：Yahoo Finance | 架構：Streamlit + GitHub")

# --- 2. 側邊欄：使用者輸入 ---
with st.sidebar:
    st.header("⚙️ 參數設定")
    
    # 股票代碼輸入
    ticker_input = st.text_input("輸入港股代號", value="0700", help="輸入數字即可，例如 700 或 0005")
    
    # 日期選擇
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("開始日期", datetime.now() - timedelta(days=365))
    with col2:
        end_date = st.date_input("結束日期", datetime.now())
        
    # SMA 參數
    st.subheader("均線設定 (SMA)")
    sma1 = st.number_input("短期均線 (SMA 1)", min_value=1, value=20)
    sma2 = st.number_input("長期均線 (SMA 2)", min_value=1, value=50)
    
    run_button = st.button("開始分析", type="primary")

# --- 3. 核心函數：處理代碼與獲取數據 ---
def format_ticker(symbol):
    """將輸入的數字轉為 Yahoo Finance 格式 (例如 700 -> 0700.HK)"""
    symbol = symbol.strip()
    # 如果是數字，補齊 4 位數並加上 .HK
    if symbol.isdigit():
        symbol = symbol.zfill(4) + ".HK"
    # 如果使用者已經打了 .HK，則轉換為大寫
    elif not symbol.endswith(".HK"):
        symbol = symbol.upper()
        if not symbol.endswith(".HK"):
             symbol += ".HK"
    return symbol

@st.cache_data(ttl=3600) # 緩存數據 1 小時，避免頻繁請求被 Yahoo 封鎖
def get_stock_data(symbol, start, end):
    try:
        # 下載數據，auto_adjust=True 會自動處理除權息，讓技術分析更準確
        df = yf.download(symbol, start=start, end=end, auto_adjust=False)
        return df
    except Exception as e:
        return None

# --- 4. 主程式邏輯 ---
if run_button:
    target_ticker = format_ticker(ticker_input)
    
    with st.spinner(f'正在從 Yahoo Finance 獲取 {target_ticker} 數據...'):
        df = get_stock_data(target_ticker, start_date, end_date)

    # 檢查數據是否為空
    if df is None or df.empty:
        st.error(f"❌ 找不到代碼 **{target_ticker}** 的數據。請確認代碼是否正確，或該股票是否已除牌。")
    else:
        # 處理 yfinance 可能返回的 MultiIndex Columns 問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # --- 計算 SMA ---
        df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        # --- 顯示摘要數據 ---
        last_close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        change = last_close - prev_close
        pct_change = (change / prev_close) * 100
        
        # 顏色邏輯：港股通常 綠漲 紅跌 (Yahoo 預設)，這裡我們用國際慣例：綠漲(Green) 紅跌(Red)
        color = "green" if change >= 0 else "red"
        
        st.markdown(f"### {target_ticker} 最新收盤價")
        st.metric(label="Close Price", 
                  value=f"{last_close:.2f}", 
                  delta=f"{change:.2f} ({pct_change:.2f}%)")

        # --- 繪圖 (使用 Plotly) ---
        fig = go.Figure()

        # 1. K線圖
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df['Open'], high=df['High'],
            low=df['Low'], close=df['Close'],
            name='K線'
        ))

        # 2. 短期均線
        fig.add_trace(go.Scatter(
            x=df.index, y=df[f'SMA_{sma1}'],
            line=dict(color='orange', width=1.5),
            name=f'SMA {sma1}'
        ))

        # 3. 長期均線
        fig.add_trace(go.Scatter(
            x=df.index, y=df[f'SMA_{sma2}'],
            line=dict(color='blue', width=1.5),
            name=f'SMA {sma2}'
        ))

        # 圖表版面設定
        fig.update_layout(
            title=f'{target_ticker} 股價走勢圖',
            yaxis_title='價格 (HKD)',
            xaxis_rangeslider_visible=False, # 隱藏下方的滑動條以節省空間
            height=600,
            template="plotly_white" # 白色背景更乾淨
        )

        st.plotly_chart(fig, use_container_width=True)

        # --- 顯示原始數據表格 (可選展開) ---
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False).style.format("{:.2f}"))

else:
    st.info("👈 請在左側輸入股票代碼並點擊「開始分析」")