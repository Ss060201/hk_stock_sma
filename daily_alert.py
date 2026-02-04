import os
import json
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# --- 環境變數讀取 (從 GitHub Secrets) ---
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
FIREBASE_KEY_JSON = os.environ.get("FIREBASE_KEY")

# --- 策略參數 ---
CDM_COEF1 = 0.7
CDM_COEF2 = 0.5
CDM_THRESHOLD = 0.05
FZM_SMA_S = 7
FZM_SMA_M = 14
FZM_WILLR_P = 35
FZM_LOOKBACK = 5

# --- 1. 初始化 Firebase ---
def init_firebase():
    if not firebase_admin._apps:
        if FIREBASE_KEY_JSON:
            try:
                cred_dict = json.loads(FIREBASE_KEY_JSON)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase 連接成功")
            except Exception as e:
                print(f"❌ Firebase Key 解析失敗: {e}")
                return None
        else:
            print("❌ 找不到 FIREBASE_KEY 環境變數")
            return None
    return firestore.client()

# --- 2. Telegram 發送 ---
def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 缺少 Telegram Token 或 Chat ID")
        return
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload)
        if resp.ok:
            print("✅ Telegram 發送成功")
        else:
            print(f"❌ Telegram 發送失敗: {resp.text}")
    except Exception as e:
        print(f"❌ 連接錯誤: {e}")

# --- 3. 指標計算 ---
def calculate_willr(high, low, close, period):
    hh = high.rolling(window=period).max()
    ll = low.rolling(window=period).min()
    # 避免分母為 0
    denom = hh - ll
    denom = denom.replace(0, np.nan) 
    wr = -100 * ((hh - close) / denom)
    return wr

# --- 4. 核心邏輯 ---
def run_scanner():
    db = init_firebase()
    if not db: return

    # 讀取 Watchlist
    try:
        doc = db.collection('stock_app').document('watchlist').get()
        if not doc.exists:
            print("⚠️ Watchlist 為空")
            return
        watchlist = doc.to_dict()
    except Exception as e:
        print(f"❌ 讀取資料庫失敗: {e}")
        return

    print(f"🔍 開始掃描 {len(watchlist)} 支股票...")
    
    for symbol, params in watchlist.items():
        # 處理股票代碼 (加 .HK)
        ticker = f"{symbol.zfill(4)}.HK" if symbol.isdigit() else symbol
        print(f"Checking {ticker}...")

        try:
            # 下載數據
            df = yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            if len(df) < 50:
                print(f"  -> {ticker} 數據不足，跳過")
                continue

            # 準備變數
            curr_price = df['Close'].iloc[-1]
            last_date = df.index[-1].strftime('%Y-%m-%d')
            today = datetime.now().date()
            
            cdm_msg = ""
            fzm_msg = ""
            is_triggered = False

            # === CDM 策略 ===
            b1s, b1e = params.get('box1_start'), params.get('box1_end')
            b2s, b2e = params.get('box2_start'), params.get('box2_end')

            if b1s and b1e and b2s and b2e:
                try:
                    s1, e1 = pd.to_datetime(b1s), pd.to_datetime(b1e)
                    s2, e2 = pd.to_datetime(b2s), pd.to_datetime(b2e)
                    
                    # 檢查日期有效性
                    if pd.to_datetime(today) > s1:
                        sma1 = df[(df.index >= s1) & (df.index <= e1)]['Close'].mean()
                        sma2 = df[(df.index >= s2) & (df.index <= e2)]['Close'].mean()
                        
                        t1_days = (e1 - s1).days
                        n_days = (pd.to_datetime(today) - s1).days
                        
                        if n_days > 0:
                            p_target = (sma1 * CDM_COEF1 * (t1_days/n_days)) + (sma2 * CDM_COEF2 * ((n_days - t1_days)/n_days))
                            diff = abs(curr_price - p_target) / p_target
                            
                            if diff < CDM_THRESHOLD:
                                cdm_msg = f"🎯 <b>CDM 觸發</b>\n目標: {p_target:.2f} (偏差 {diff*100:.1f}%)"
                                is_triggered = True
                except Exception as e:
                    print(f"  -> CDM 計算錯誤: {e}")

            # === FZM 策略 ===
            df['SMA_S'] = df['Close'].rolling(FZM_SMA_S).mean()
            df['SMA_M'] = df['Close'].rolling(FZM_SMA_M).mean()
            df['WillR'] = calculate_willr(df['High'], df['Low'], df['Close'], FZM_WILLR_P)
            
            s_val = df['SMA_S'].iloc[-1]
            m_val = df['SMA_M'].iloc[-1]
            w_val = df['WillR'].iloc[-1]
            low5 = df['Low'].tail(FZM_LOOKBACK).min()
            
            cond_a = (curr_price > s_val) and (curr_price > m_val)
            cond_b = (w_val < -80) # 簡化版條件：處於超賣區
            
            if cond_a and cond_b:
                fzm_msg = f"🌊 <b>FZM 觸發</b>\nSMA({FZM_SMA_S}): {s_val:.2f} | WillR: {w_val:.1f}"
                is_triggered = True

            # === 發送通知 ===
            if is_triggered:
                final_msg = f"🚨 <b>{ticker} 訊號警示</b> ({last_date})\n現價: {curr_price:.2f}\n"
                if cdm_msg: final_msg += f"\n{cdm_msg}"
                if fzm_msg: final_msg += f"\n{fzm_msg}"
                final_msg += f"\n\n止損參考 (5日低): {low5:.2f}"
                
                send_telegram(final_msg)

        except Exception as e:
            print(f"❌ 處理 {ticker} 時發生錯誤: {e}")

if __name__ == "__main__":
    run_scanner()
