import urllib.request
import urllib.parse
import http.cookiejar
import ssl
import json
import re
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AA_SYMBOLS = ["00700","02318","01299","00005"]
GROUP_BASIC = "127,76,40,6"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def build_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx)
    )
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.8")]
    return opener

def _do(url, method="GET", data=None, extra=None):
    req = urllib.request.Request(url, method=method)
    if extra:
        for k,v in extra.items(): req.add_header(k,v)
    if data is not None:
        if isinstance(data, dict): data = urllib.parse.urlencode(data).encode()
        elif isinstance(data, str): data = data.encode()
        req.data = data
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
        body = resp.read()
        try: return body.decode("utf-8")
        except: return body.decode("utf-8", errors="ignore")

if __name__ == "__main__":
    op = build_opener()
    page = "https://www.aastocks.com/tc/stocks/quote/detail-quote.aspx?symbol=00700"
    print("STEP1 GET page ...", flush=True)
    _do(page)

    print("STEP2 GET API token ...", flush=True)
    api_url = "https://www.aastocks.com/tc/resources/datafeed/getapitoken.ashx?" + urllib.parse.urlencode({
        "PageURL": page, "HKT":"Y", "UST":"Y"
    })
    r = _do(api_url, extra={"X-Requested-With":"XMLHttpRequest", "Referer":page})
    try: api_token = json.loads(r)["token"]
    except:
        m = re.search(r'"token"\s*:\s*"([^"]+)"', r)
        api_token = m.group(1) if m else None
    print(f"  API token len={len(api_token) if api_token else 'NONE'}", flush=True)

    print("STEP3 GET CE token (Auth header!) ...", flush=True)
    ce_url = "https://www.aastocks.com/tc/resources/datafeed/getcetoken.ashx"
    ce_raw = _do(ce_url, extra={
        "Auth": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": page,
    })
    ce_token = ce_raw.strip().strip('"').strip("'")
    print(f"  CE token len={len(ce_token)} | head={ce_token[:60] if len(ce_token)>60 else ce_token}", flush=True)

    print("STEP4 POST getQuote ...", flush=True)
    post = f"grp0={','.join(AA_SYMBOLS)}|{GROUP_BASIC}|F=Y"
    fct_url = f"https://fctdata.aastocks.com/g2ce/Quote/getQuote?format=json{ce_token}"
    try:
        qr = _do(fct_url, method="POST", data=post, extra={
            "Origin": "https://www.aastocks.com",
            "Referer": page,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
    except Exception as e:
        print(f"  POST ERR: {e}", flush=True)
        sys.exit(1)
    print(f"  Response len = {len(qr)}", flush=True)
    with open(os.path.join(os.path.dirname(__file__), "tmp_fctdata_raw.json"),"w",encoding="utf-8") as f:
        f.write(qr)
    print("  Saved to scripts/tmp_fctdata_raw.json", flush=True)

    try:
        data = json.loads(qr)
    except Exception as e:
        print(f"  JSON parse fail: {e} | find embedded ...", flush=True)
        m = re.search(r'\{.*\}', qr, re.DOTALL)
        if m:
            try: data = json.loads(m.group(0)); print("  Extracted via regex", flush=True)
            except Exception as e2: print("  Still fail:", e2); data = None
        else: data = None

    if data is not None:
        print("  JSON TYPE:", type(data).__name__, flush=True)
        if isinstance(data, dict):
            print("  TOP KEYS:", list(data.keys())[:20], flush=True)
            for k, v in list(data.items())[:5]:
                print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:300]}", flush=True)
        elif isinstance(data, list):
            print(f"  LIST len={len(data)}", flush=True)
            if data:
                print("  ITEM[0]:", json.dumps(data[0], ensure_ascii=False)[:600], flush=True)

    print("\nDONE.", flush=True)
