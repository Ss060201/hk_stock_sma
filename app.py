import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os

# --- 1. 系統初始化 ---
st.set_page_config(page_title="港股 SMA 矩陣 v9.5", page_icon="📈", layout="wide")

# --- CSS 樣式 (針對新表格優化) ---
st.markdown("""
<style>
    .big-font-table { 
        font-size: 14px !important; 
        width: 100%; 
        border-collapse: collapse; 
        text-align: center; 
        font-family: 'Arial', sans-serif;
        margin-bottom: 20px;
    }
    .big-font-table th, .big-font-table td { 
        padding: 8px; 
        border: 1px solid #dee2e6; 
    }
    /* 第一欄 (描述欄) */
    .big-font-table td:first-child {
        font-weight: bold;
        text-align: left;
        background-color: #fff;
        width: 120px;
    }
    .section-header {
        background-color: #f1f3f5;
        font-weight: bold;
        color: #000;
    }
    .header-row td {
        background-color: #ffffff !important; /* 白色背景 */
        font-weight: bold;
        color: #000;
    }
    .data-row td {
        background-color: #d4edda !important; /* 綠色背景 */
        color: #000;
        font-weight: normal;
    }
    .pos-val { color: #d9534f; font-weight: bold; } /* 紅色 */
    .neg-val { color: #28a745; font-weight: bold; } /* 綠色 */
    .stButton>button { width: 100%; height: 3em; font-size: 18px; }
</style>
""", unsafe_allow_html=True)

# --- 數據庫連接 (Firebase) ---
@st.cache_resource
def get_db():
    try:
        if not firebase_admin._apps:
            if "firebase" in st.secrets:
                if "json_content" in st.secrets["firebase"]:
                    try:
                        key_dict = json.loads(st.secrets["firebase"]["json_content"])
                        cred = credentials.Certificate(key_dict)
                        firebase_admin.initialize_app(cred)
                    except json.JSONDecodeError:
                        st.error("Secrets JSON 格式錯誤。")
                        return None
                elif "private_key" in st.secrets["firebase"]:
                    try:
                        key_dict = dict(st.secrets["firebase"])
                        if "\\n" in key_dict["private_key"]:
                            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                        cred = credentials.Certificate(key_dict)
                        firebase_admin.initialize_app(cred)
                    except Exception as e:
                        st.error(f"TOML 格式讀取失敗: {e}")
                        return None
                else:
                    return None
            elif os.path.exists("service_account.json"):
                cred = credentials.Certificate("service_account.json")
                firebase_admin.initialize_app(cred)
            else:
                return None
        db = firestore.client()
        return db
    except Exception as e:
        st.error(f"Firebase 連接失敗: {e}")
        return None

def get_watchlist_from_db():
    db = get_db()
    if not db: return {}
    try:
        doc_ref = db.collection('stock_app').document('watchlist')
        doc = doc_ref.get()
        if doc.exists: return doc.to_dict()
        else: return {}
    except: return {}

def update_stock_in_db(symbol, params=None):
    db = get_db()
    if not db: 
        st.error("無法連接數據庫")
        return
    doc_ref = db.collection('stock_app').document('watchlist')
    data = {symbol: params if params else {
        "box1_start": "", "box1_end": "",
        "box2_start": "", "box2_end": ""
    }}
    doc_ref.set(data, merge=True)
    st.toast(f"已同步 {symbol}", icon="☁️")

def remove_stock_from_db(symbol):
    db = get_db()
    if not db: return
    doc_ref = db.collection('stock_app').document('watchlist')
    doc_ref.update({symbol: firestore.DELETE_FIELD})
    st.toast(f"已移除 {symbol}", icon="🗑️")

# --- Telegram 發送功能 ---
def send_telegram_msg(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload)
        if not resp.ok:
            return False, f"Error {resp.status_code}: {resp.text}"
        return True, "OK"
    except Exception as e:
        return False, str(e)

# --- 核心運算邏輯 (CDM & FZM) ---
def calculate_willr(high, low, close, period):
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    wr = -100 * ((highest_high - close) / (highest_high - lowest_low))
    return wr

def run_analysis_logic(df, symbol, params):
    # 參數設定
    CDM_COEF1 = 0.7
    CDM_COEF2 = 0.5
    CDM_THRESHOLD = 0.05
    FZM_SMA_S = 7
    FZM_SMA_M = 14
    FZM_WILLR_P = 35
    FZM_LOOKBACK = 5

    curr_price = df['Close'].iloc[-1]
    today = datetime.now().date()
    
    # --- 1. CDM 運算 ---
    cdm_status = "未設定參數"
    target_price_str = "N/A"
    diff_str = "N/A"
    
    b1_s = params.get('box1_start')
    b1_e = params.get('box1_end')
    b2_s = params.get('box2_start')
    b2_e = params.get('box2_end')

    if b1_s and b1_e and b2_s and b2_e:
        try:
            s1, e1 = pd.to_datetime(b1_s), pd.to_datetime(b1_e)
            s2, e2 = pd.to_datetime(b2_s), pd.to_datetime(b2_e)
            
            sma1 = df[(df.index >= s1) & (df.index <= e1)]['Close'].mean()
            sma2 = df[(df.index >= s2) & (df.index <= e2)]['Close'].mean()
            
            t1_days = (e1 - s1).days
            n_days = (pd.to_datetime(today) - s1).days
            
            if n_days > 0:
                p_target = (sma1 * CDM_COEF1 * (t1_days/n_days)) + (sma2 * CDM_COEF2 * ((n_days - t1_days)/n_days))
                diff = abs(curr_price - p_target) / p_target
                
                target_price_str = f"{p_target:.2f}"
                diff_str = f"{diff*100:.2f}"
                cdm_status = "🔴 <b>觸發</b>" if diff < CDM_THRESHOLD else "未觸發"
            else:
                cdm_status = "時間參數錯誤 (N<=0)"
        except Exception as e:
            cdm_status = f"計算錯誤: {str(e)}"
    
    # --- 2. FZM 運算 ---
    df['SMA7'] = df['Close'].rolling(FZM_SMA_S).mean()
    df['SMA14'] = df['Close'].rolling(FZM_SMA_M).mean()
    df['WillR'] = calculate_willr(df['High'], df['Low'], df['Close'], FZM_WILLR_P)
    
    val_sma7 = df['SMA7'].iloc[-1]
    val_sma14 = df['SMA14'].iloc[-1]
    val_willr = df['WillR'].iloc[-1]
    lowest_low = df['Low'].tail(FZM_LOOKBACK).min()
    
    cond_a = (curr_price > val_sma7) and (curr_price > val_sma14)
    cond_b = (val_willr < -80) 
    
    fzm_status = "🔴 <b>觸發</b>" if (cond_a and cond_b) else "未觸發"
    trend_str = "站上雙均線" if cond_a else "均線下方"

    report = f"""<b>[股票警示] {symbol} 分析報告</b>

<b>1. CDM (抄底模式) 狀態： {cdm_status}</b>
目前股價：{curr_price:.2f}
計算目標價：{target_price_str}
偏差率：{diff_str}%

<b>2. FZM (反轉模式) 狀態： {fzm_status}</b>
SMA(7)：{val_sma7:.2f} | SMA(14)：{val_sma14:.2f}
WillR(35)：{val_willr:.2f}
趨勢判斷：{trend_str}
建議止損位 (5日低點)：{lowest_low:.2f}

<i>本訊息由 Streamlit 手動測試觸發。</i>
"""
    return report

# --- 初始化 State ---
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""

def clean_ticker_input(symbol):
    return str(symbol).strip().replace(" ", "").replace(".HK", "").replace(".hk", "")

def get_yahoo_ticker(symbol):
    if symbol.isdigit(): return f"{symbol.zfill(4)}.HK"
    return symbol

# --- 側邊欄 ---
with st.sidebar:
    st.header("HK Stock Analysis")
    
    with st.expander("✈️ Telegram 分析與發送", expanded=True):
        def_token = st.secrets["telegram"]["token"] if "telegram" in st.secrets else ""
        def_chat_id = st.secrets["telegram"]["chat_id"] if "telegram" in st.secrets else ""
        
        tg_token = st.text_input("Bot Token", value=def_token, type="password")
        tg_chat_id = st.text_input("Chat ID", value=def_chat_id)
        
        if st.button("🚀 分析並發送報告", type="primary"):
            if not st.session_state.current_view:
                st.toast("請先選擇一支股票！", icon="⚠️")
            elif not tg_token or not tg_chat_id:
                st.toast("請填寫 Token 和 ID", icon="⚠️")
            else:
                curr_sym = st.session_state.current_view
                yt = get_yahoo_ticker(curr_sym)
                with st.spinner(f"正在分析 {curr_sym}..."):
                    try:
                        df_test = yf.download(yt, period="6mo", progress=False, auto_adjust=False)
                        if isinstance(df_test.columns, pd.MultiIndex): 
                            df_test.columns = df_test.columns.get_level_values(0)
                        
                        if len(df_test) > 50:
                            wl_data = get_watchlist_from_db()
                            stock_params = wl_data.get(curr_sym, {})
                            msg_body = run_analysis_logic(df_test, curr_sym, stock_params)
                            ok, res = send_telegram_msg(tg_token, tg_chat_id, msg_body)
                            if ok: st.toast("報告已發送！", icon="✅")
                            else: st.error(f"Telegram 錯誤: {res}")
                        else:
                            st.error("數據不足，無法分析。")
                    except Exception as e:
                        st.error(f"分析失敗: {e}")
    
    st.divider()

    st.subheader("📅 日期設置")
    new_date = st.date_input("選擇日期", value=st.session_state.ref_date, label_visibility="collapsed")
    if new_date != st.session_state.ref_date:
        st.session_state.ref_date = new_date
        st.rerun()

    search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
    if search_input:
        cleaned_search = clean_ticker_input(search_input)
        if cleaned_search: st.session_state.current_view = cleaned_search

    st.divider()
    watchlist_data = get_watchlist_from_db()
    watchlist_list = list(watchlist_data.keys()) if watchlist_data else []
    
    st.subheader(f"我的收藏 (雲端: {len(watchlist_list)})")
    
    # 刪除了原有的「載入收藏行情」按鈕與數據表格 (Action 1)

    if watchlist_list:
        for ticker in watchlist_list:
            if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                st.session_state.current_view = ticker
    else:
        st.caption("暫無收藏")

    st.divider()
    sma1 = st.number_input("SMA 1", value=20)
    sma2 = st.number_input("SMA 2", value=50)

# --- 主程式 ---
current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')

# --- 2. 主頁面：收藏股票數據概覽 (Action 2) ---
if not current_code:
    st.title("港股 SMA 矩陣分析 v9.5")
    st.subheader("📋 我的收藏概覽")

    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        if st.button("🔄 刷新所有數據"):
            st.rerun()
            
        st.write("---")
        
        # 遍歷每一個收藏股票並顯示詳細表格
        for ticker in watchlist_list:
            yt = get_yahoo_ticker(ticker)
            
            with st.spinner(f"正在分析 {ticker}..."):
                try:
                    # 獲取數據 (需要足夠長度以計算 SMA212)
                    df_w = yf.download(yt, period="1y", progress=False, auto_adjust=False)
                    if isinstance(df_w.columns, pd.MultiIndex): df_w.columns = df_w.columns.get_level_values(0)
                    
                    if len(df_w) > 20: # 確保至少有基本數據
                        # --- 計算邏輯 (AvgP & Amp) ---
                        curr_p = df_w['Close'].iloc[-1]
                        intervals = [7, 14, 28, 57, 106, 212]
                        
                        # 1. AvgP
                        avgp_vals = [curr_p] # Avg0
                        for p in intervals:
                            # 計算 SMA，如果數據不足則為 NaN
                            if len(df_w) >= p:
                                avgp_vals.append(df_w['Close'].rolling(p).mean().iloc[-1])
                            else:
                                avgp_vals.append(0)
                        
                        # Avg(AvgP)
                        valid_avgp = [v for v in avgp_vals if v > 0]
                        avg_avgp = sum(valid_avgp) / len(valid_avgp) if valid_avgp else 0
                        
                        # AvgP MR
                        avgp_mr_vals = []
                        for v in avgp_vals:
                            mr = (v / avg_avgp - 1) * 100 if avg_avgp else 0
                            avgp_mr_vals.append(mr)

                        # 2. Amp
                        df_w['AMP'] = (df_w['High'] - df_w['Low']) / df_w['Close'] * 100
                        val_amp0 = df_w['AMP'].iloc[-1]
                        amp_vals = [val_amp0] # Amp0 (雖然公式排除Avg計算，但顯示列表需要)
                        
                        # Amp1-6
                        amp_rolling_vals = []
                        for p in intervals:
                            if len(df_w) >= p:
                                val = df_w['AMP'].rolling(p).mean().iloc[-1]
                                amp_rolling_vals.append(val)
                            else:
                                amp_rolling_vals.append(0)
                        
                        # Avg Amp (排除 Amp0)
                        valid_amp_rolling = [v for v in amp_rolling_vals if v > 0]
                        avg_amp = sum(valid_amp_rolling) / len(valid_amp_rolling) if valid_amp_rolling else 0
                        
                        # Amp MR
                        # MR0 (Amp0 vs Avg)
                        mr0 = (val_amp0 / avg_amp - 1) * 100 if avg_amp else 0
                        amp_mr_vals = [mr0]
                        
                        # MR1-6
                        for v in amp_rolling_vals:
                            mr = (v / avg_amp - 1) * 100 if avg_amp else 0
                            amp_mr_vals.append(mr)

                        # --- HTML 構建 ---
                        html = f'<div style="margin-bottom: 30px; border: 1px solid #ddd; padding: 10px; border-radius: 5px;">'
                        html += '<table class="big-font-table">'
                        
                        # Group 1: AvgP
                        # Header: Stock Code | Avg(AvgP) | AvgP0 | ... | AvgP6
                        html += '<tr class="header-row">'
                        html += f'<td>{ticker}</td><td>Avg(AvgP)</td><td>AvgP0</td><td>AvgP1</td><td>AvgP2</td><td>AvgP3</td><td>AvgP4</td><td>AvgP5</td><td>AvgP6</td></tr>'
                        # Data (Green)
                        html += '<tr class="data-row">'
                        html += f'<td></td><td>{avg_avgp:.2f}</td>'
                        html += "".join([f"<td>{v:.2f}</td>" for v in avgp_vals])
                        html += '</tr>'
                        
                        # Group 2: AvgP MR
                        # Header: Empty | AvgP MR0 | ...
                        html += '<tr class="header-row">'
                        html += f'<td></td><td>AvgP MR</td><td>AvgP MR0</td><td>AvgP MR1</td><td>AvgP MR2</td><td>AvgP MR3</td><td>AvgP MR4</td><td>AvgP MR5</td><td>AvgP MR6</td></tr>'
                        # Data (Green)
                        avgp_mr_avg = sum(avgp_mr_vals)/len(avgp_mr_vals) if avgp_mr_vals else 0
                        html += '<tr class="data-row">'
                        html += f'<td></td><td>{avgp_mr_avg:.2f}%</td>'
                        html += "".join([f"<td>{v:.2f}%</td>" for v in avgp_mr_vals])
                        html += '</tr>'
                        
                        # Group 3: Amp
                        # Header: Empty | Avg Amp | Amp0 | ...
                        html += '<tr class="header-row">'
                        html += f'<td></td><td>Avg Amp</td><td>Amp0</td><td>Amp1</td><td>Amp2</td><td>Amp3</td><td>Amp4</td><td>Amp5</td><td>Amp6</td></tr>'
                        # Data (Green)
                        all_amps = [val_amp0] + amp_rolling_vals
                        html += '<tr class="data-row">'
                        html += f'<td></td><td>{avg_amp:.2f}</td>'
                        html += "".join([f"<td>{v:.2f}</td>" for v in all_amps])
                        html += '</tr>'

                        # Group 4: Amp MR
                        # Header: Empty | AmpMR0 | ...
                        html += '<tr class="header-row">'
                        html += f'<td></td><td>Amp MR</td><td>AmpMR0</td><td>AmpMR1</td><td>AmpMR2</td><td>AmpMR3</td><td>AmpMR4</td><td>AmpMR5</td><td>AmpMR6</td></tr>'
                        # Data (Green)
                        amp_mr_avg = sum(amp_mr_vals)/len(amp_mr_vals) if amp_mr_vals else 0
                        html += '<tr class="data-row">'
                        html += f'<td></td><td>{amp_mr_avg:.2f}%</td>'
                        html += "".join([f"<td>{v:.2f}%</td>" for v in amp_mr_vals])
                        html += '</tr>'
                        html += '</table>'

                        # --- 表格底部：時段統計 (MMB, MMS, RTB, RTS) ---
                        # 注意：因無具體公式，此處使用 0.00% 佔位，請後續填入邏輯
                        html += '<table class="big-font-table" style="margin-top: 10px;">'
                        
                        # Part 1: Day 0-6
                        days_header = ["Day", "0", "1", "2", "3", "4", "5", "6"]
                        html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in days_header]) + '</tr>'
                        
                        metrics_day = ["MMB (%)", "MMS (%)", "RTB (%)", "RTS (%)"]
                        for m in metrics_day:
                            html += '<tr class="data-row">'
                            html += f'<td style="background-color:#fff !important; font-weight:bold;">{m}</td>'
                            # 填充 7 個 0.00%
                            html += "".join([f"<td>0.00%</td>" for _ in range(7)])
                            html += '</tr>'
                        
                        # Separator Row (Optional or just continue)
                        html += '</table><table class="big-font-table" style="margin-top: 5px;">'

                        # Part 2: Interval 7-212
                        int_header = ["Interval", "7", "14", "28", "57", "106", "212"]
                        html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in int_header]) + '</tr>'
                        
                        metrics_sum = ["Sum(MMB)", "Sum(MMS)", "Sum(RTB)", "Sum(RTS)"]
                        for m in metrics_sum:
                            html += '<tr class="data-row">'
                            html += f'<td style="background-color:#fff !important; font-weight:bold;">{m}</td>'
                            # 填充 6 個 0.00%
                            html += "".join([f"<td>0.00%</td>" for _ in range(6)])
                            html += '</tr>'

                        html += '</table></div>'
                        st.markdown(html, unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Error analyzing {ticker}: {str(e)}")
    

else:
    # --- 單一股票詳細分析視圖 (保持原有功能) ---
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)

    col_t, col_b = st.columns([0.85, 0.15])
    with col_t: st.title(f"📊 {display_ticker}")
    with col_b:
        st.write("")
        is_in_watchlist = current_code in watchlist_list
        if is_in_watchlist:
            if st.button("★ 已收藏", type="primary", use_container_width=True):
                remove_stock_from_db(current_code)
                st.rerun()
        else:
            if st.button("☆ 加入", use_container_width=True):
                update_stock_in_db(current_code)
                st.rerun()

    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        try:
            df = yf.download(symbol, period="3y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
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
        except:
            return None, None

    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)

    if df is not None and not df.empty and shares_outstanding is None:
        st.warning("⚠️ 無法自動獲取流通股數，請輸入以啟用換手率計算。")
        manual_shares = st.number_input("流通股數 (Shares)", min_value=0, value=0)
        if manual_shares > 0: shares_outstanding = manual_shares

    if df is None or df.empty or len(df) < 5:
        st.error(f"數據不足或當日休市 (Date: {ref_date_str})。")
    else:
        # --- A. 核心計算 ---
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p).mean()

        if f'SMA_{sma1}' not in df.columns: 
            df[f'SMA_{sma1}'] = df['Close'].rolling(window=sma1).mean()
        if f'SMA_{sma2}' not in df.columns: 
            df[f'SMA_{sma2}'] = df['Close'].rolling(window=sma2).mean()

        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
        else:
            df['Turnover_Rate'] = 0.0

        for p in periods_sma:
            df[f'Sum_{p}'] = df['Volume'].rolling(window=p).sum()
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']

        # --- B. 界面控制 ---
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

        # --- C. CDM 參數 ---
        if is_in_watchlist:
            with st.expander("⚙️ 設定 CDM 自動監測參數", expanded=False):
                st.caption("設定將同步至雲端，供每日腳本使用。")
                curr_params = watchlist_data.get(current_code, {})
                c1, c2 = st.columns(2)
                with c1:
                    val_b1s = pd.to_datetime(curr_params.get('box1_start')).date() if curr_params.get('box1_start') else None
                    val_b1e = pd.to_datetime(curr_params.get('box1_end')).date() if curr_params.get('box1_end') else None
                    new_b1_s = st.date_input("Box 1 Start", value=val_b1s)
                    new_b1_e = st.date_input("Box 1 End", value=val_b1e)
                with c2:
                    val_b2s = pd.to_datetime(curr_params.get('box2_start')).date() if curr_params.get('box2_start') else None
                    val_b2e = pd.to_datetime(curr_params.get('box2_end')).date() if curr_params.get('box2_end') else None
                    new_b2_s = st.date_input("Box 2 Start", value=val_b2s)
                    new_b2_e = st.date_input("Box 2 End", value=val_b2e)
                
                if st.button("💾 儲存參數"):
                    new_params = {
                        "box1_start": str(new_b1_s) if new_b1_s else "",
                        "box1_end": str(new_b1_e) if new_b1_e else "",
                        "box2_start": str(new_b2_s) if new_b2_s else "",
                        "box2_end": str(new_b2_e) if new_b2_e else ""
                    }
                    update_stock_in_db(current_code, new_params)
                    st.rerun()

        # --- D. 數據呈現 ---
        req_len = 13
        if len(df) < req_len:
            st.warning("數據長度不足")
        else:
            data_slice = df.iloc[-req_len:][::-1]
            
            # 1. Curve
            curve_data = df.iloc[-7:]
            fig_sma_trend = go.Figure()
            colors_map = {7: '#FF6B6B', 14: '#FFA500', 28: '#FFD700', 57: '#4CAF50', 106: '#2196F3', 212: '#9C27B0'}
            for p in periods_sma:
                col_name = f'SMA_{p}'
                if col_name in curve_data.columns:
                    fig_sma_trend.add_trace(go.Scatter(x=curve_data.index, y=curve_data[col_name], mode='lines', name=f"SMA({p})", line=dict(color=colors_map.get(p, 'grey'), width=2)))
            fig_sma_trend.update_layout(height=350, margin=dict(l=10, r=10, t=30, b=10), title="SMA 曲線 (近7個交易日)", template="plotly_white", legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_sma_trend, use_container_width=True)

           # 2. SMA Matrix (New Format v10.0)
            st.subheader("📋 SMA Matrix")
            
            # 定義列與對應的 Interval
            matrix_intervals = [7, 14, 28, 57, 106, 212]
            headers = ["2", "3", "4", "5", "6", "7"] # 對應 Day 2 - Day 7
            
            # 預先計算需要的數據，存入字典以利後續提取
            matrix_data = {}
            current_close = df['Close'].iloc[-1]
            
            for p in matrix_intervals:
                col = f'SMA_{p}'
                if col in df.columns:
                    series = df[col].tail(14) # 取近14天算 Max/Min
                    val_curr = df[col].iloc[-1]
                    val_max = series.max()
                    val_min = series.min()
                    # SMAC (%) = (股價 - SMA) / SMA
                    smac_val = ((current_close - val_curr) / val_curr) * 100 if val_curr else 0
                else:
                    val_curr = val_max = val_min = smac_val = 0
                
                matrix_data[p] = {
                    "max": val_max,
                    "min": val_min,
                    "sma": val_curr,
                    "smac": smac_val
                }

            # 構建 HTML 表格
            sma_html = '<table class="big-font-table">'
            sma_html += '<thead><tr><th>Day</th>' + "".join([f"<th>{h}</th>" for h in headers]) + '</tr></thead><tbody>'
            sma_html += '<tr><td><b>P</b></td>' + "".join([f"<td>SMA {p}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Interval</b></td>' + "".join([f"<td>{p}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Max</b></td>' + "".join([f"<td>{matrix_data[p]['max']:.2f}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>Min</b></td>' + "".join([f"<td>{matrix_data[p]['min']:.2f}</td>" for p in matrix_intervals]) + '</tr>'
            sma_html += '<tr><td><b>SMA</b></td>' + "".join([f"<td><b>{matrix_data[p]['sma']:.2f}</b></td>" for p in matrix_intervals]) + '</tr>'
            
            # SMAC Rows
            sma_html += '<tr><td><b>SMAC (%)</b></td>'
            for p in matrix_intervals:
                val = matrix_data[p]['smac']
                color_class = 'pos-val' if val > 0 else 'neg-val'
                sma_html += f'<td class="{color_class}">{val:.2f}%</td>'
            sma_html += '</tr>'
            
            # SMAC Differences
            base_smas = {14: matrix_data[14]['sma'], 28: matrix_data[28]['sma'], 57: matrix_data[57]['sma']}
            for base_p, base_val in base_smas.items():
                sma_html += f'<tr><td><b>SMAC{base_p} (%)</b></td>'
                for p in matrix_intervals:
                    curr_sma = matrix_data[p]['sma']
                    if base_val and curr_sma:
                        val = ((curr_sma - base_val) / base_val) * 100
                        color_class = 'pos-val' if val > 0 else 'neg-val'
                        sma_html += f'<td class="{color_class}">{val:.2f}%</td>'
                    else:
                        sma_html += '<td>-</td>'
                sma_html += '</tr>'

            sma_html += "</tbody></table>"
            st.markdown(sma_html, unsafe_allow_html=True)
            
            # --- NEW: Price Interface Data List (修正版) ---
            st.write("") # Spacer
            
            # ==========================================
            # A. Price (AvgP) 計算
            # ==========================================
            # Avg0 = Close, Avg1-6 = SMA [7, 14, 28, 57, 106, 212]
            avgp_vals = [current_close] # Avg0
            for p in matrix_intervals:
                # 若 SMA 尚未產生 (NaN) 則補 0 或略過，這裡假設已有值
                val = matrix_data[p]['sma'] if matrix_data[p]['sma'] else 0
                avgp_vals.append(val)
            
            # 計算 Avg(AvgP) = (Avg0 + ... + Avg6) / 7
            if len(avgp_vals) > 0:
                avg_avg_p = sum(avgp_vals) / len(avgp_vals)
            else:
                avg_avg_p = 0
            
            # 計算 AvgP MR = (AvgP / Avg) - 1
            # 包含 AvgP MR0 到 AvgP MR6
            avgp_mr_vals = []
            for v in avgp_vals:
                if avg_avg_p != 0:
                    # 數學上 (v - avg) / avg 等同於 (v / avg) - 1
                    mr = (v / avg_avg_p) - 1
                else:
                    mr = 0
                avgp_mr_vals.append(mr * 100) # 轉百分比
            
            # AvgP MR (總) - 這裡取所有 MR 的平均
            avg_avgp_mr_total = sum(avgp_mr_vals) / len(avgp_mr_vals)

            # ==========================================
            # B. AMP (Amplitude) 計算 (修正公式)
            # ==========================================
            # 定義：AMP = (High - Low) / Close * 100
            df['AMP'] = (df['High'] - df['Low']) / df['Close'] * 100
            
            # 1. 準備 AMP0 (當日)
            val_amp0 = df['AMP'].iloc[-1]
            
            # 2. 準備 AMP1 ~ AMP6 (對應 SMA 週期的歷史平均振幅)
            amp_rolling_vals = [] 
            for p in matrix_intervals:
                # 計算過去 p 天的 AMP 平均值
                val = df['AMP'].rolling(p).mean().iloc[-1]
                amp_rolling_vals.append(val)
            
            # 3. 計算 AVG Amp (根據圖片公式)
            # 公式：AVG Amp = (Amp1 + Amp2 + Amp3 + Amp4 + Amp5 + Amp6) / 6
            # ⚠️ 關鍵修正：排除 AMP0
            if len(amp_rolling_vals) > 0:
                avg_amp = sum(amp_rolling_vals) / len(amp_rolling_vals)
            else:
                avg_amp = 0
            
            # 4. 計算 AMP MR
            # 公式：MR = (AMPn / AVG Amp) - 1
            amp_mr_vals = []
            
            # 4a. 計算 AMP MR0 (AMP0 / Avg - 1)
            if avg_amp != 0:
                mr0 = (val_amp0 / avg_amp) - 1
            else:
                mr0 = 0
            amp_mr_vals.append(mr0 * 100)
            
            # 4b. 計算 AMP MR1 ~ MR6
            for v in amp_rolling_vals:
                if avg_amp != 0:
                    mr = (v / avg_amp) - 1
                else:
                    mr = 0
                amp_mr_vals.append(mr * 100)

            # 5. 整合顯示數據
            # AvgP 部分
            row1_headers = ["Avg(AvgP)", "Avg0", "Avg1", "Avg2", "Avg3", "Avg4", "Avg5", "Avg6"]
            row1_data = [avg_avg_p] + avgp_vals
            
            row2_headers = ["AvgP MR", "AvgP MR0", "AvgP MR1", "AvgP MR2", "AvgP MR3", "AvgP MR4", "AvgP MR5", "AvgP MR6"]
            row2_data = [avg_avgp_mr_total] + avgp_mr_vals

            # AMP 部分
            # 注意：列表順序為 [平均值, AMP0, AMP1...AMP6]
            row3_headers = ["Avg(AMP)", "AMP0", "AMP1", "AMP2", "AMP3", "AMP4", "AMP5", "AMP6"]
            row3_data = [avg_amp] + [val_amp0] + amp_rolling_vals
            
            # MR 部分：列表順序為 [MR總平均(自訂), MR0, MR1...MR6]
            avg_amp_mr_total = sum(amp_mr_vals) / len(amp_mr_vals)
            row4_headers = ["AMP MR", "AMP MR0", "AMP MR1", "AMP MR2", "AMP MR3", "AMP MR4", "AMP MR5", "AMP MR6"]
            row4_data = [avg_amp_mr_total] + amp_mr_vals

            # ==========================================
            # C. 渲染 HTML 表格
            # ==========================================
            pi_html = '<table class="big-font-table" style="margin-top: 20px;">'
            
            # Title
            pi_html += '<tr><td colspan="8" class="section-title">Price 界面 數據列表</td></tr>'
            
            # Row 1: AvgP Data (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row1_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}</td>" for d in row1_data]) + '</tr>'
            
            # Row 2: AvgP MR (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row2_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}%</td>" for d in row2_data]) + '</tr>'
            
            # Row 3: AMP Data (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row3_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}</td>" for d in row3_data]) + '</tr>'

            # Row 4: AMP MR (White Header + Green Data)
            pi_html += '<tr class="header-row">' + "".join([f"<td>{h}</td>" for h in row4_headers]) + '</tr>'
            pi_html += '<tr class="data-row">' + "".join([f"<td>{d:.2f}%</td>" for d in row4_data]) + '</tr>'
            
            pi_html += '</table>'
            st.markdown(pi_html, unsafe_allow_html=True)


            # 3. Turnover Matrix
            st.subheader("📋 Turnover Rate Matrix")
            if not has_turnover:
                st.error("無流通股數數據。")
            else:
                dates_d2_d7 = [data_slice.index[i].strftime('%m-%d') for i in range(1, 7)]
                vals_d2_d7 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(1, 7)]
                dates_d8_d13 = [data_slice.index[i].strftime('%m-%d') for i in range(7, 13)]
                vals_d8_d13 = [f"{data_slice['Turnover_Rate'].iloc[i]:.2f}%" for i in range(7, 13)]
                
                intervals_tor = [7, 14, 28, 57, 106, 212]
                sums = [f"{df['Turnover_Rate'].tail(p).sum():.2f}%" for p in intervals_tor]
                maxs = [f"{df['Turnover_Rate'].tail(p).max():.2f}%" for p in intervals_tor]
                mins = [f"{df['Turnover_Rate'].tail(p).min():.2f}%" for p in intervals_tor]
                avgs = [f"{df['Turnover_Rate'].tail(p).mean():.2f}%" for p in intervals_tor]
                avg_tor_7 = f"{df['Turnover_Rate'].mean():.2f}%"

                tor_html = '<table class="big-font-table">'
                tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 2<br><small>{dates_d2_d7[0]}</small></th><th>Day 3<br><small>{dates_d2_d7[1]}</small></th><th>Day 4<br><small>{dates_d2_d7[2]}</small></th><th>Day 5<br><small>{dates_d2_d7[3]}</small></th><th>Day 6<br><small>{dates_d2_d7[4]}</small></th><th>Day 7<br><small>{dates_d2_d7[5]}</small></th></tr>'
                tor_html += f'<tr><td>{vals_d2_d7[0]}</td><td>{vals_d2_d7[1]}</td><td>{vals_d2_d7[2]}</td><td>{vals_d2_d7[3]}</td><td>{vals_d2_d7[4]}</td><td>{vals_d2_d7[5]}</td></tr>'
                tor_html += f'<tr style="background-color: #e8eaf6;"><th>Day 8<br><small>{dates_d8_d13[0]}</small></th><th>Day 9<br><small>{dates_d8_d13[1]}</small></th><th>Day 10<br><small>{dates_d8_d13[2]}</small></th><th>Day 11<br><small>{dates_d8_d13[3]}</small></th><th>Day 12<br><small>{dates_d8_d13[4]}</small></th><th>Day 13<br><small>{dates_d8_d13[5]}</small></th></tr>'
                tor_html += f'<tr><td>{vals_d8_d13[0]}</td><td>{vals_d8_d13[1]}</td><td>{vals_d8_d13[2]}</td><td>{vals_d8_d13[3]}</td><td>{vals_d8_d13[4]}</td><td>{vals_d8_d13[5]}</td></tr></table><br>'
                
                tor_html += '<table class="big-font-table"><tr style="background-color: #ffe0b2;"><th>Metrics</th>' + "".join([f"<th>Int: {p}</th>" for p in intervals_tor]) + '</tr>'
                tor_html += f'<tr><td><b>Sum(TOR)</b></td>' + "".join([f"<td>{v}</td>" for v in sums]) + '</tr>'
                tor_html += f'<tr><td><b>Max</b></td>' + "".join([f"<td>{v}</td>" for v in maxs]) + '</tr>'
                tor_html += f'<tr><td><b>Min</b></td>' + "".join([f"<td>{v}</td>" for v in mins]) + '</tr>'
                tor_html += f'<tr style="background-color: #c8e6c9;"><td><b>AVG Label</b></td><td>AVGTOR 1</td><td>AVGTOR 2</td><td>AVGTOR 3</td><td>AVGTOR 4</td><td>AVGTOR 5</td><td>AVGTOR 6</td></tr>'
                tor_html += f'<tr><td><b>AVGTOR</b></td>' + "".join([f"<td>{v}</td>" for v in avgs]) + '</tr></table>'
                tor_html += f'<table class="big-font-table" style="margin-top: 10px;"><tr style="background-color: #c8e6c9;"><th style="width:50%">AVGTOR 7 (Total Average)</th><th style="width:50%">Data</th></tr><tr><td>{avg_tor_7}</td><td>{avg_tor_7}</td></tr></table>'
                st.markdown(tor_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📚 歷史功能與圖表")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📉 Price & SMA", "🔄 Ratio Curves", "📊 Volume (Abs)", "💹 Turnover Analysis (Old)"])

    end_date_dt = pd.to_datetime(st.session_state.ref_date)
    start_date_6m = end_date_dt - timedelta(days=180)
    display_df = df[df.index >= start_date_6m]

    # Tab 1
    with tab1:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'], low=display_df['Low'], close=display_df['Close'], name='K線'))
        if f'SMA_{sma1}' in display_df.columns: fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma1}'], line=dict(color='orange'), name=f'SMA {sma1}'))
        if f'SMA_{sma2}' in display_df.columns: fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'SMA_{sma2}'], line=dict(color='blue'), name=f'SMA {sma2}'))
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

    # Tab 2
    with tab2:
        fig_r = go.Figure()
        if 'R1' in display_df.columns: fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R1'], name="R1 (S7/S14)"))
        if 'R2' in display_df.columns: fig_r.add_trace(go.Scatter(x=display_df.index, y=display_df['R2'], name="R2 (S7/S28)"))
        st.plotly_chart(fig_r, use_container_width=True)

    # Tab 3
    with tab3:
        st.bar_chart(display_df['Volume'])

    # Tab 4
    with tab4:
        if has_turnover: st.line_chart(display_df['Turnover_Rate'])
