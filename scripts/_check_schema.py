import sqlite3, os
db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ohlcv_cache.sqlite")
print("DB path:", db, "exists:", os.path.exists(db))
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", cur.fetchall())
for t in ["ohlcv_cache", "fetcher_stats"]:
    try:
        cur.execute(f"PRAGMA table_info({t})")
        cols = cur.fetchall()
        print(f"\nColumns of {t}:")
        for c in cols:
            print(" ", c)
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  Rows: {cur.fetchone()[0]}")
    except Exception as e:
        print(f"  Err {t}: {e}")
try:
    cur.execute("SELECT * FROM ohlcv_cache LIMIT 2")
    rs = cur.fetchall()
    for r in rs:
        print("\nSample row:", r)
except Exception as e:
    print("sample err:", e)
try:
    cur.execute("SELECT DISTINCT symbol FROM ohlcv_cache LIMIT 10")
    print("\nDistinct symbols:", cur.fetchall())
except Exception as e:
    print("symbols err:", e)
conn.close()
