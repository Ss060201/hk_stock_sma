import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣分析 v7.2", page_icon="📈", layout="wide")

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

# --- CSS 樣式 ---
st.markdown("""
<style>
    /* 強制放大表格字體 */
    .big-font-table {
        font-size: 16px !important;
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-family: sans-serif;
    }
    .big-font-table th {
        background-color: #f0f2f6;
        color: #31333F;
        padding: 10px;
        border: 1px solid #ddd;
        font-weight: bold;
    }
    .big-font-table td {
        padding: 10px;
        border: 1px solid #ddd;
        color: #31333F;
    }
    /* 針對手機的響應式調整 */
    @media (max-width: 600px) {
        .big-font-table { font-size: 14px !important; }
        .big-font-table th, .big-font-table td { padding: 6px; }
    }
    /* 數值顏色 */
    .pos-val { color: #d9534f; font-weight: bold; } /* 紅色 (漲/正) */
    .neg-val { color: #5cb85c; font-weight: bold; } /* 綠色 (跌/負) */
    
    /* 按鈕樣式 */
    .stButton>button {
        width: 100%;
        height: 3em;
        font-size: 18px;
    }
</style>
""", unsafe_allow_html=True)

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
    
    st.subheader("📅 日期設置")
    st.caption(f"Ref: {st.session_state.ref_date}")
    new_date = st.date_input("選擇日期", value=st.session_state.ref_date, label_visibility="collapsed")
    if new_date != st.session_state.ref_date:
        st.session_state.ref_date = new_date
        st.rerun()

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
    # 將 SMA 參數放入 session_state 以便全局調用
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 4. 主程式邏輯 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

if not current_code:
    st.title("港股 SMA 矩陣分析 v7.2")
    st.info("👈 請輸入代號開始分析。")
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

    # --- 數據獲取 ---
    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        try:
            # 抓取長數據以確保計算準確 (至少 212 + buffer)
            df = yf.download(symbol, period="3y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 切分數據：只取 end_date 之前的交易日
            end_dt = pd.to_datetime(end_date)
            df = df[df.index <= end_dt]
            
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

    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)

    if df is not None and not df.empty and shares_outstanding is None:
        st.warning("⚠️ 無法自動獲取流通股數，請輸入以啟用換手率計算。")
        manual_shares = st.number_input("流通股數 (Shares)", min_value=0, value=0)
        if manual_shares > 0: shares_outstanding = manual_shares

    if df is None or df.empty or len(df) < 5:
        st.error(f"數據不足或當日休市 (Date: {ref_date_str})。請嘗試調整日期。")
    else:
        # ==========================================
        # --- A. 核心計算 (修復版: 統一計算所有指標) ---
        # ==========================================
        
        # 1. 矩陣需要的固定 SMA
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

        # 2. 用戶自定義 SMA (Tab 1 圖表需要)
        if f'SMA_{sma1}' not in df.columns:
            df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        if f'SMA_{sma2}' not in df.columns:
            df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        # 3. 計算 Turnover Rate (TOR)
        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
        else:
            df['Turnover_Rate'] = 0.0

        # 4. 計算 Volume Sum 和 Ratios (Tab 2 需要)
        for p in [7, 14, 28, 57, 106, 212]:
             df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()
        
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']
        
        # ==========================================

        # --- B. 界面控制按鈕 ---
        c_nav_prev, c_nav_mid, c_nav_next = st.columns([1, 4, 1])
        
        with c_nav_prev:
            if st.button("◀ 前一交易日", use_container_width=True):
                if len(df) >= 2:
                    st.session_state.ref_date = df.index[-2].date()
                    st.rerun()
        
        with c_nav_mid:
            st.markdown(f"<h3 style='text-align: center; margin: 0;'>基準日: {df.index[-1].strftime('%Y-%m-%d')}</h3>", unsafe_allow_html=True)

        with c_nav_next:
            if st.button("後一交易日 ▶", use_container_width=True):
                st.session_state.ref_date += timedelta(days=1)
                st.rerun()

        st.divider()

        # --- C. 首頁核心數據 ---
        req_len = 13
        if len(df) < req_len:
            st.warning("數據長度不足以生成完整矩陣 (需至少 13 個交易日)。")
        else:
            data_slice = df.iloc[-req_len:][::-1] 
            
            # --- 1. SMA Trend Curve ---
            curve_data = df.iloc[-7:]
            fig_sma_trend = go.Figure()
            colors_map = {7: '#FF6B6B', 14: '#FFA500', 28: '#FFD700', 57: '#4CAF50', 106: '#2196F3', 212: '#9C27B0'}
            
            for p in periods_sma:
                col_name = f'SMA_{p}'
                if col_name in curve_data.columns:
                    fig_sma_trend.add_trace(go.Scatter(
                        x=curve_data.index, y=curve_data[col_name],
                        mode='lines', name=f"SMA({p})",
                        line=dict(color=colors_map.get(p, 'grey'), width=2)
                    ))
            
            fig_sma_trend.update_layout(
                height=350, 
                margin=dict(l=10, r=10, t=30, b=10),
                title="SMA 曲線 (近7個交易日)",
                template="plotly_white",
                legend=dict(orientation="h", y=1.1)
            )
            st.plotly_chart(fig_sma_trend, use_container_width=True)

            # --- 2. SMA Matrix (修復縮進導致的 HTML 顯示錯誤) ---
            st.subheader("📋 SMA Matrix")
            
            # 使用單行或去除縮進的方式構建 HTML 頭部，避免被視為 Markdown Code Block
            sma_html = '<table class="big-font-table"><thead><tr>'
            sma_html += '<th>Interval</th><th>Max</th><th>Min</th><th>SMA (Day1)</th><th>SMAC (%)</th>'
            sma_html += '<th>Day 2</th><th>Day 3</th><th>Day 4</th><th>Day 5</th><th>Day 6</th><th>Day 7</th>'
            sma_html += '</tr></thead><tbody>'
            
            for p in periods_sma:
                col_sma = f'SMA_{p}'
                sma_series_recent = df[col_sma].tail(14) 
                val_max = sma_series_recent.max()
                val_min = sma_series_recent.min()
                val_curr = df[col_sma].iloc[-1]
                
                base_sma = df[f'SMA_57'].iloc[-1]
                if base_sma and base_sma != 0:
                    smac_val = (1 - (val_curr / base_sma)) * 100
                else:
                    smac_val = 0
                
                smac_class = 'pos-val' if smac_val > 0 else 'neg-val'
                smac_str = f"{smac_val:.2f}%"
                
                day_vals = []
                for i in range(1, 7):
                    val = data_slice[col_sma].iloc[i]
                    day_vals.append(f"{val:.2f}")

                # 構建每一行，確保沒有會觸發 Code Block 的縮進
                row_html = f'<tr><td><b>{p}</b></td><td>{val_max:.2f}</td><td>{val_min:.2f}</td><td><b>{val_curr:.2f}</b></td>'
                row_html += f'<td class="{smac_class}">{smac_str}</td>'
                row_html += f'<td>{day_vals[0]}</td><td>{day_vals[1]}</td><td>{day_vals[2]}</td><td>{day_vals[3]}</td><td>{day_vals[4]}</td><td>{day_vals[5]}</td></tr>'
                sma_html += row_html
                
            sma_html += "</tbody></table>"
            st.markdown(sma_html, unsafe_allow_html=True)
            st.caption("註: SMAC = (1 - SMA_n / SMA_57) * 100%; Day 2-7 為歷史交易日數值")
            
            st.divider()

            # --- 3. Turnover Rate Matrix (修復縮進導致的 HTML 顯示錯誤) ---
            st.subheader("📋 Turnover Rate Matrix")
            
            if not has_turnover:
                st.error("無流通股數數據，無法顯示換手率矩陣。")
            else:
                dates_d2_d7 = [data_slice.index[i].strftime('%m-%d') for i in range(1, 7)]
                vals_d2_d7 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(1, 7)]
                
                dates_d8_d13 = [data_slice.index[i].strftime('%m-%d') for i in range(7, 13)]
                vals_d8_d13 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(7, 13)]
                
                intervals_tor = [7, 14, 28, 57, 106, 212]
                sums = []
                maxs = []
                mins = []
                avgs = []
                
                for p in intervals_tor:
                    subset = df['Turnover_Rate'].tail(p)
                    sums.append(f"{subset.sum():.2f}%")
                    maxs.append(f"{subset.max():.2f}%")
                    mins.append(f"{subset.min():.2f}%")
                    avgs.append(f"{subset.mean():.2f}%")
                
                avg_tor_7 = df['Turnover_Rate'].mean()
                val_avg_7 = f"{avg_tor_7:.2f}%"

                # 同樣避免使用多行字符串縮進
                tor_html = '<table class="big-font-table">'
                
                # Row 1 & 2
                tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 2<br><small>{dates_d2_d7[0]}</small></th><th>Day 3<br><small>{dates_d2_d7[1]}</small></th><th>Day 4<br><small>{dates_d2_d7[2]}</small></th><th>Day 5<br><small>{dates_d2_d7[3]}</small></th><th>Day 6<br><small>{dates_d2_d7[4]}</small></th><th>Day 7<br><small>{dates_d2_d7[5]}</small></th></tr>'
                tor_html += f'<tr><td>{vals_d2_d7[0]}</td><td>{vals_d2_d7[1]}</td><td>{vals_d2_d7[2]}</td><td>{vals_d2_d7[3]}</td><td>{vals_d2_d7[4]}</td><td>{vals_d2_d7[5]}</td></tr>'
                
                # Row 3 & 4
                tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 8<br><small>{dates_d8_d13[0]}</small></th><th>Day 9<br><small>{dates_d8_d13[1]}</small></th><th>Day 10<br><small>{dates_d8_d13[2]}</small></th><th>Day 11<br><small>{dates_d8_d13[3]}</small></th><th>Day 12<br><small>{dates_d8_d13[4]}</small></th><th>Day 13<br><small>{dates_d8_d13[5]}</small></th></tr>'
                tor_html += f'<tr><td>{vals_d8_d13[0]}</td><td>{vals_d8_d13[1]}</td><td>{vals_d8_d13[2]}</td><td>{vals_d8_d13[3]}</td><td>{vals_d8_d13[4]}</td><td>{vals_d8_d13[5]}</td></tr></table><br>'
                
                # Metrics Table
                tor_html += '<table class="big-font-table"><tr style="background-color: #ffe0b2;">'
                tor_html += f'<th style="width:16%">Metrics</th><th style="width:14%">Int: {intervals_tor[0]}</th><th style="width:14%">Int: {intervals_tor[1]}</th><th style="width:14%">Int: {intervals_tor[2]}</th><th style="width:14%">Int: {intervals_tor[3]}</th><th style="width:14%">Int: {intervals_tor[4]}</th><th style="width:14%">Int: {intervals_tor[5]}</th></tr>'
                
                tor_html += f'<tr><td><b>Sum(TOR)</b></td><td>{sums[0]}</td><td>{sums[1]}</td><td>{sums[2]}</td><td>{sums[3]}</td><td>{sums[4]}</td><td>{sums[5]}</td></tr>'
                tor_html += f'<tr><td><b>Max</b></td><td>{maxs[0]}</td><td>{maxs[1]}</td><td>{maxs[2]}</td><td>{maxs[3]}</td><td>{maxs[4]}</td><td>{maxs[5]}</td></tr>'
                tor_html += f'<tr><td><b>Min</b></td><td>{mins[0]}</td><td>{mins[1]}</td><td>{mins[2]}</td><td>{mins[3]}</td><td>{mins[4]}</td><td>{mins[5]}</td></tr>'
                
                tor_html += '<tr style="background-color: #c8e6c9;"><td><b>AVG Label</b></td><td>AVGTOR 1</td><td>AVGTOR 2</td><td>AVGTOR 3</td><td>AVGTOR 4</td><td>AVGTOR 5</td><td>AVGTOR 6</td></tr>'
                tor_html += f'<tr><td><b>AVGTOR</b></td><td>{avgs[0]}</td><td>{avgs[1]}</td><td>{avgs[2]}</td><td>{avgs[3]}</td><td>{avgs[4]}</td><td>{avgs[5]}</td></tr></table>'
                
                # Extra Table
                tor_html += f'<table class="big-font-table" style="margin-top: 10px;"><tr style="background-color: #c8e6c9;"><th style="width:50%">AVGTOR 7 (Total Average)</th><th style="width:50%">Data</th></tr><tr><td>{avg_tor_7:.2f}%</td><td>{val_avg_7}</td></tr></table>'

                st.markdown(tor_html, unsafe_allow_html=True)
                st.caption("註: Interval 單位為交易日; Day 數據為對應歷史交易日之換手率。")

    st.markdown("---")
    st.markdown("### 📚 歷史功能與圖表")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume (Abs)", "💹 Turnover Analysis (Old)"])

    display_df = filter_data_by_interval(df, '6M')

    # Tab 1: Price
    with tab1:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'],
                                     low=display_df['Low'], close=display_df['Close'], name='K線'))
        fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], line=dict(color='orange'), name=f'SMA {sma1}'))
        fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], line=dict(color='blue'), name=f'SMA {sma2}'))
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

    # Tab 2: Ratio Curves
    with tab2:
        fig_r = go.Figure()
        fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R1'], name="R1 (S7/S14)"))
        fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R2'], name="R2 (S7/S28)"))
        st.plotly_chart(fig_r, use_container_width=True)

    # Tab 3: Abs Volume
    with tab3:
        st.bar_chart(display_df['Volume'])

    # Tab 4: Turnover Analysis (Old)
    with tab4:
        if has_turnover:
             st.line_chart(display_df['Turnover_Rate'])
