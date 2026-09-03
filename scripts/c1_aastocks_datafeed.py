import urllib.request
import urllib.parse
import http.cookiejar
import ssl
import json
import re
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AA_CODE_TO_YAHOO = {
    "00700": "0700.HK",
    "02318": "2318.HK",
    "01299": "1299.HK",
    "00005": "0005.HK",
}
AA_SYMBOLS = list(AA_CODE_TO_YAHOO.keys())
GROUP_BASIC = "127,76,40,6"
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ohlcv_cache.sqlite")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

def build_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx)
    )
    opener.addheaders = [
        ("User-Agent", UA),
        ("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.8"),
    ]
    return opener, cj

def http_get(opener, url, headers_extra=None, timeout=20):
    req = urllib.request.Request(url)
    if headers_extra:
        for k, v in headers_extra.items():
            req.add_header(k, v)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read()
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("utf-8", errors="ignore")

def http_post(opener, url, data, headers_extra=None, timeout=20):
    if isinstance(data, dict):
        data_enc = urllib.parse.urlencode(data).encode("utf-8")
    else:
        data_enc = data.encode("utf-8") if isinstance(data, str) else data
    req = urllib.request.Request(url, data=data_enc, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    if headers_extra:
        for k, v in headers_extra.items():
            req.add_header(k, v)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read()
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("utf-8", errors="ignore")

def run_aastocks():
    opener, cj = build_opener()
    page_url = "https://www.aastocks.com/tc/stocks/quote/detail-quote.aspx?symbol=00700"
    print("STEP 1: GET detail-quote.aspx to get cookies ...", flush=True)
    html = http_get(opener, page_url)
    print(f"  HTML len = {len(html)}", flush=True)

    print("\nSTEP 2: GET API token ...", flush=True)
    api_url = "https://www.aastocks.com/tc/resources/datafeed/getapitoken.ashx?" + urllib.parse.urlencode({
        "PageURL": page_url,
        "HKT": "Y",
        "UST": "Y",
    })
    api_resp = http_get(opener, api_url, headers_extra={
        "X-Requested-With": "XMLHttpRequest",
        "Referer": page_url,
    })
    print(f"  RAW API response: {api_resp[:200]}", flush=True)
    api_token = None
    try:
        api_obj = json.loads(api_resp)
        api_token = api_obj.get("token")
    except Exception as e:
        m = re.search(r'"token"\s*:\s*"([^"]+)"', api_resp)
        if m:
            api_token = m.group(1)
    if not api_token:
        print("  ❌ FAILED to get API token")
        return None
    print(f"  ✅ API token len={len(api_token)}", flush=True)

    print("\nSTEP 3: GET CE token (Bearer) ...", flush=True)
    ce_url = "https://www.aastocks.com/tc/resources/datafeed/getcetoken.ashx"
    ce_resp = http_get(opener, ce_url, headers_extra={
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": page_url,
    })
    ce_token = ce_resp.strip().strip('"').strip("'")
    if not ce_token or len(ce_token) < 10:
        print(f"  ❌ FAILED CE token. Raw: {repr(ce_resp[:200])}")
        return None
    print(f"  ✅ CE token len={len(ce_token)}", flush=True)

    print("\nSTEP 4: POST fctdata getQuote ...", flush=True)
    sym_list = ",".join(AA_SYMBOLS)
    post_data_str = f"grp0={sym_list}|{GROUP_BASIC}|F=Y"
    datafeed_url = f"https://fctdata.aastocks.com/g2ce/Quote/getQuote?format=json{ce_token}"
    print(f"  URL: {datafeed_url[:100]}...")
    print(f"  POST data: {post_data_str}", flush=True)
    try:
        quote_resp = http_post(opener, datafeed_url, post_data_str, headers_extra={
            "Origin": "https://www.aastocks.com",
            "Referer": page_url,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }, timeout=30)
    except Exception as e:
        print(f"  ❌ POST exception: {e}")
        return None
    print(f"  Response len = {len(quote_resp)}", flush=True)
    print(f"  Response head (500): {quote_resp[:500]}", flush=True)

    try:
        data = json.loads(quote_resp)
        print("\n✅ PARSED JSON. Top-level type:", type(data).__name__)
        if isinstance(data, dict):
            print("  Keys:", list(data.keys())[:30])
        elif isinstance(data, list):
            print("  List len:", len(data))
            if data:
                print("  Item 0 type:", type(data[0]).__name__)
                if isinstance(data[0], (dict, list)):
                    print("  Item 0 preview:", json.dumps(data[0], ensure_ascii=False)[:600])
        return data
    except Exception as e:
        print(f"  ❌ JSON parse error: {e}")
        print("  Trying to find JSON in response...")
        m = re.search(r'\{.*\}', quote_resp, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                print("  ✅ Extracted JSON via regex")
                return data
            except Exception as e2:
                print(f"  Still failed: {e2}")
        print("  Saving raw response to tmp_aastocks_raw.txt")
        with open("tmp_aastocks_raw.txt", "w", encoding="utf-8") as f:
            f.write(quote_resp)
        return None

def parse_aastocks_response(data, aa_symbols):
    result = {s: {} for s in aa_symbols}
    if data is None:
        return result
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
    flat = []
    def _flatten(obj):
        if isinstance(obj, list):
            for x in obj: _flatten(x)
        elif isinstance(obj, dict):
            flat.append(obj)
            for v in obj.values():
                if isinstance(v, (dict, list)): _flatten(v)
    _flatten(items)
    print(f"\nparse_aastocks: flat dicts = {len(flat)}")
    for i, d in enumerate(flat[:10]):
        print(f"  flat[{i}] keys: {list(d.keys())[:15]}")
    return result

def get_local_cache(symbols_yahoo):
    result = {}
    if not os.path.exists(DB_PATH):
        print(f"\n⚠️ SQLite DB not found at {DB_PATH}")
        return result
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for yh in symbols_yahoo:
        cur.execute("""
            SELECT date, open, high, low, close, adj_close, volume
            FROM ohlcv_cache
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT 2
        """, (yh,))
        rows = cur.fetchall()
        if rows:
            last = rows[0]
            prev = rows[1] if len(rows) > 1 else None
            result[yh] = {"last": last, "prev": prev}
            print(f"\nSQLite {yh}: last date={last[0]} O={last[1]} H={last[2]} L={last[3]} C={last[4]} Vol={last[6]}")
            if prev:
                print(f"  prev date={prev[0]} C={prev[4]}")
    conn.close()
    return result

def cmp(label, aa_v, local_v):
    if aa_v is None or local_v is None:
        print(f"  {label:>10s}: AA={aa_v} local={local_v} (缺資料)")
        return None
    try:
        aa_f = float(aa_v)
        lc_f = float(local_v)
    except (ValueError, TypeError):
        print(f"  {label:>10s}: parse fail AA={aa_v} local={local_v}")
        return None
    if abs(lc_f) < 1e-9:
        print(f"  {label:>10s}: local zero, skip")
        return None
    diff = aa_f - lc_f
    reld = abs(diff) / abs(lc_f) * 100.0
    mark = "✅" if reld < 0.5 else "⚠️" if reld < 2.0 else "❌"
    print(f"  {label:>10s}: AA={aa_f:>10.3f} local={lc_f:>10.3f} Δ={diff:+.3f} ({reld:+.2f}%) {mark}")
    return reld

if __name__ == "__main__":
    aa_data = run_aastocks()
    parsed = parse_aastocks_response(aa_data, AA_SYMBOLS)

    print("\n" + "=" * 80)
    print("LOCAL SQLITE:")
    local = get_local_cache(list(AA_CODE_TO_YAHOO.values()))

    print("\n" + "=" * 80)
    print("CROSS-VALIDATION REPORT (AAStocks vs Local SQLite Cache):")
    print("=" * 80)
    for aa, yh in AA_CODE_TO_YAHOO.items():
        print(f"\n【{aa} → {yh}】")
        if yh not in local:
            print("  ⚠️ local cache 無此股，跳過")
            continue
        row = local[yh]["last"]
        prev_row = local[yh]["prev"]
        l_date, l_open, l_high, l_low, l_close, _, l_vol = row
        p_close = prev_row[4] if prev_row else None
        for col, lv in [("Open", l_open), ("High", l_high), ("Low", l_low), ("Close", l_close)]:
            cmp(col, None, lv)
        if p_close:
            cmp("PrevClose", None, p_close)
        chg_calc = ((l_close - p_close) / p_close * 100) if p_close else None
        if chg_calc is not None:
            print(f"  計算漲跌: ({l_close}-{p_close})/{p_close}*100 = {chg_calc:+.2f}%")
    print("\nDONE.")
