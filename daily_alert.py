import pandas as pd
import yfinance as yf
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time
import os
import json

# --- 配置區域 (請修改這裡或設置環境變量) ---
# 如果在 GitHub Actions 運行，建議使用 os.environ.get('TG_TOKEN')
TG_BOT_TOKEN = "你的_TOKEN_貼在這裡" 
TG_CHAT_ID = "你的_CHAT_ID_貼在這裡"

# 策略參數
CDM_COEF1 = 0.7
CDM_COEF2 = 0.5
CDM_THRESHOLD = 0.05
FZM_SMA_SHORT = 7
FZM_SMA_MED = 14
FZM_WILLR_PERIOD = 35
FZM_LOOKBACK = 5

# --- 輔助功能 ---
def init_firebase():
    if not firebase_admin._apps:
        # 本地運行讀取文件
        if os.path.exists("service_account.json"):
            cred = credentials.Certificate("service_account.json")
            firebase_admin.initialize_app(cred)
        # 如果是雲端 (如 GitHub Actions)，可以將 JSON 內容存在環境變數中
        elif "FIREBASE_KEY" in os.environ:
            key_dict = json.loads(os.environ["FIREBASE_KEY"])
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        else:
            print("Error: No Firebase credentials found.")
            return None
    return firestore.client()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
        print("Telegram sent.")
    except Exception as e:
        print(f"Telegram failed: {e}")

def calculate_willr(high, low, close, period):
    hh = high.rolling(window=period).max()
    ll = low.rolling(window=period).min()
    return -100 * ((hh - close) / (hh - ll))

# --- 主程序 ---
def run_scanner():
    print("Starting Daily Scanner...")
    db = init_firebase()
    if not db: return

    # 讀取 Watchlist
    doc = db.collection('stock_app').document('watchlist').get()
    if not doc.exists:
        print("No watchlist found in DB.")
        return
    
    watchlist_dict = doc.to_dict() # { "700": {params}, ... }
    
    for symbol, params in watchlist_dict.items():
        ticker = f"{symbol.zfill(4)}.HK" if symbol.isdigit() else symbol
        print(f"Checking {ticker}...")
        
        try:
            df = yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            if len(df) < 50: continue

            curr_p = df['Close'].iloc[-1]
            last_date = df.index[-1].strftime('%Y-%m-%d')
            today = datetime.now().date()
            
            cdm_triggered = False
            fzm_triggered = False
            report = f"<b>[{ticker}] 訊號報告 ({last_date})</b>\n\n"
            
            # === CDM ===
            b1_s = params.get('box1_start')
            b1_e = params.get('box1_end')
            b2_s = params.get('box2_start')
            b2_e = params.get('box2_end')
            
            if b1_s and b1_e and b2_s and b2_e:
                try:
                    s1 = pd.to_datetime(b1_s)
                    e1 = pd.to_datetime(b1_e)
                    s2 = pd.to_datetime(b2_s)
                    e2 = pd.to_datetime(b2_e)
                    
                    sma1 = df[(df.index >= s1) & (df.index <= e1)]['Close'].mean()
                    sma2 = df[(df.index >= s2) & (df.index <= e2)]['Close'].mean()
                    
                    t1_d = (e1 - s1).days
                    n_d = (pd.to_datetime(today) - s1).days
                    
                    if n_d > 0:
                        target = (sma1 * CDM_COEF1 * (t1_d/n_d)) + (sma2 * CDM_COEF2 * ((n_d - t1_d)/n_d))
                        diff = abs(curr_p - target) / target
                        
                        report += f"🔹 <b>CDM 抄底模式</b>\n"
                        report += f"目標價: {target:.2f} (偏差 {diff*100:.1f}%)\n"
                        if diff < CDM_THRESHOLD: cdm_triggered = True
                except: pass
            
            # === FZM ===
            df['SMA_S'] = df['Close'].rolling(FZM_SMA_SHORT).mean()
            df['SMA_M'] = df['Close'].rolling(FZM_SMA_MED).mean()
            df['WR'] = calculate_willr(df['High'], df['Low'], df['Close'], FZM_WILLR_PERIOD)
            
            s_val = df['SMA_S'].iloc[-1]
            m_val = df['SMA_M'].iloc[-1]
            wr_val = df['WR'].iloc[-1]
            prev_wr = df['WR'].iloc[-2]
            
            cond_a = (curr_p > s_val) and (curr_p > m_val)
            cond_b = (wr_val < -80) or (wr_val > -80 and prev_wr < -80)
            
            report += f"\n🔹 <b>FZM 反轉模式</b>\n"
            report += f"SMA{FZM_SMA_SHORT}: {s_val:.2f} | WR: {wr_val:.1f}\n"
            if cond_a and cond_b: fzm_triggered = True
            
            # === 發送 ===
            if cdm_triggered or fzm_triggered:
                final_msg = f"🚨 <b>交易警示觸發！</b>\n\n{report}\nCDM: {'✅' if cdm_triggered else '❌'}\nFZM: {'✅' if fzm_triggered else '❌'}"
                send_telegram(final_msg)
                time.sleep(1)

        except Exception as e:
            print(f"Error {symbol}: {e}")

if __name__ == "__main__":
    run_scanner()
