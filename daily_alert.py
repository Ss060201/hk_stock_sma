import firebase_admin
from firebase_admin import credentials, firestore
import yfinance as yf
import pandas as pd
import requests
import os
import json
from datetime import datetime

# --- 設定區域 ---
# 從 GitHub Secrets 讀取環境變數
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# --- 1. 連接 Firebase ---
def get_db():
    if not firebase_admin._apps:
        # GitHub Actions 會幫我們把 Secrets 寫入這個臨時檔案
        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
        else:
            print("❌ 找不到 service_account.json")
            return None
    return firestore.client()

# --- 2. Telegram 發送 ---
def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 缺少 Telegram 設定")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
        print("✅ Telegram 發送成功")
    except Exception as e:
        print(f"❌ 發送失敗: {e}")

# --- 3. 核心運算邏輯 (CDM & FZM) ---
def calculate_willr(high, low, close, period):
    hh = high.rolling(window=period).max()
    ll = low.rolling(window=period).min()
    return -100 * ((hh - close) / (hh - ll))

def run_analysis(df, symbol, params):
    # 策略參數
    curr_price = df['Close'].iloc[-1]
    today = datetime.now().date()
    
    # CDM 參數
    cdm_trigger = False
    cdm_info = ""
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
            t1_d = (e1 - s1).days
            n_d = (pd.to_datetime(today) - s1).days
            
            if n_d > 0:
                target = (sma1 * 0.7 * (t1_d/n_d)) + (sma2 * 0.5 * ((n_d - t1_d)/n_d))
                diff = abs(curr_price - target) / target
                if diff < 0.05: cdm_trigger = True
                cdm_info = f"目標價: {target:.2f} (偏差 {diff*100:.2f}%)"
        except: pass

    # FZM 參數
    df['SMA7'] = df['Close'].rolling(7).mean()
    df['SMA14'] = df['Close'].rolling(14).mean()
    df['WR'] = calculate_willr(df['High'], df['Low'], df['Close'], 35)
    
    cond_a = (curr_price > df['SMA7'].iloc[-1]) and (curr_price > df['SMA14'].iloc[-1])
    cond_b = (df['WR'].iloc[-1] < -80)
    fzm_trigger = True if (cond_a and cond_b) else False
    
    # --- 判斷發送 ---
    if cdm_trigger or fzm_trigger:
        msg = f"""<b>[自動警示] {symbol}</b>
股價: {curr_price:.2f}
日期: {today}

<b>CDM 狀態:</b> {'🔴 觸發' if cdm_trigger else '未觸發'}
{cdm_info}

<b>FZM 狀態:</b> {'🔴 觸發' if fzm_trigger else '未觸發'}
SMA7/14: {df['SMA7'].iloc[-1]:.2f} / {df['SMA14'].iloc[-1]:.2f}
WillR: {df['WR'].iloc[-1]:.2f}

<i>GitHub Actions 自動發送</i>"""
        return msg
    return None

# --- 主程序 ---
if __name__ == "__main__":
    print("🚀 開始執行每日掃描...")
    db = get_db()
    if db:
        docs = db.collection('stock_app').document('watchlist').get()
        if docs.exists:
            watchlist = docs.to_dict()
            for symbol, params in watchlist.items():
                print(f"正在檢查: {symbol}...")
                ticker = f"{symbol.zfill(4)}.HK" if symbol.isdigit() else symbol
                try:
                    df = yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
                    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                    
                    if len(df) > 50:
                        report = run_analysis(df, symbol, params)
                        if report:
                            send_telegram(report)
                except Exception as e:
                    print(f"錯誤 {symbol}: {e}")
        else:
            print("雲端無收藏清單")
    print("✅ 掃描完成")
