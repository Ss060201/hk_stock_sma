import os
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. 環境變數讀取 (GitHub Secrets) ---
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
FIREBASE_KEY_JSON = os.environ.get("FIREBASE_KEY")

# --- 2. 初始化 Firebase ---
if not firebase_admin._apps:
    try:
        if FIREBASE_KEY_JSON:
            # 解析 JSON 字串
            cred_dict = json.loads(FIREBASE_KEY_JSON)
            # 確保私鑰格式正確 (處理換行符號)
            if "\\n" in cred_dict["private_key"]:
                cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase 連接成功")
        else:
            print("❌ 錯誤: 找不到 FIREBASE_KEY 環境變數")
            exit(1)
    except Exception as e:
        print(f"❌ Firebase 初始化失敗: {e}")
        exit(1)

db = firestore.client()

# --- 3. 輔助函數 ---
def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("⚠️ 缺少 Telegram 設定，跳過發送")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"發送失敗: {e}")

def calculate_willr(high, low, close, period):
    hh = high.rolling(window=period).max()
    ll = low.rolling(window=period).min()
    return -100 * ((hh - close) / (hh - ll))

def get_yahoo_ticker(symbol):
    if symbol.isdigit(): return f"{symbol.zfill(4)}.HK"
    return symbol

# --- 4. 核心分析邏輯 ---
def run_analysis():
    print("🚀 開始每日掃描...")
    
    # 從 Firebase 讀取收藏清單
    try:
        doc = db.collection('stock_app').document('watchlist').get()
        if not doc.exists:
            print("📭 收藏清單為空")
            return
        watchlist = doc.to_dict()
    except Exception as e:
        print(f"讀取 Watchlist 失敗: {e}")
        return

    # 參數設定
    CDM_COEF1 = 0.7
    CDM_COEF2 = 0.5
    CDM_THRESHOLD = 0.05
    FZM_SMA_S = 7
    FZM_SMA_M = 14
    FZM_WILLR_P = 35
    today = datetime.now().date()

    # 遍歷股票
    for symbol, params in watchlist.items():
        ticker = get_yahoo_ticker(symbol)
        print(f"正在檢查: {ticker}...")
        
        try:
            # 獲取數據
            df = yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            
            if len(df) < 50:
                print(f"  -> 數據不足，跳過")
                continue

            curr_p = df['Close'].iloc[-1]
            
            # --- CDM 運算 ---
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
                        target = (sma1 * CDM_COEF1 * (t1_d/n_d)) + (sma2 * CDM_COEF2 * ((n_d - t1_d)/n_d))
                        diff = abs(curr_p - target) / target
                        if diff < CDM_THRESHOLD:
                            cdm_trigger = True
                            cdm_info = f"🎯 目標價: {target:.2f} (偏差 {diff*100:.1f}%)"
                except: pass

            # --- FZM 運算 ---
            fzm_trigger = False
            
            df['S7'] = df['Close'].rolling(FZM_SMA_S).mean()
            df['S14'] = df['Close'].rolling(FZM_SMA_M).mean()
            df['WR'] = calculate_willr(df['High'], df['Low'], df['Close'], FZM_WILLR_P)
            
            s7 = df['S7'].iloc[-1]
            s14 = df['S14'].iloc[-1]
            wr = df['WR'].iloc[-1]
            
            # 條件: 站上雙均線 + 處於低位(-80以下)
            if (curr_p > s7 and curr_p > s14) and (wr < -80):
                fzm_trigger = True

            # --- 發送警示 ---
            if cdm_trigger or fzm_trigger:
                msg = f"<b>🚨 [自動警示] {symbol} 觸發訊號</b>\n\n"
                msg += f"現價: {curr_p:.2f}\n"
                if cdm_trigger: msg += f"✅ <b>CDM 抄底</b>: 觸發\n{cdm_info}\n"
                if fzm_trigger: msg += f"✅ <b>FZM 反轉</b>: 觸發 (WillR: {wr:.1f})\n"
                
                print(f"  -> 觸發訊號！正在發送 Telegram...")
                send_telegram(msg)
            else:
                print(f"  -> 無訊號")

        except Exception as e:
            print(f"  -> 錯誤: {e}")

if __name__ == "__main__":
    run_analysis()
