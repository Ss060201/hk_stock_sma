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
    return opener, cj

def _do(url, method="GET", data=None, extra=None, to=30):
    req = urllib.request.Request(url, method=method)
    if extra:
        for k,v in extra.items(): req.add_header(k,v)
    if data is not None:
        if isinstance(data, dict):
            data_enc = urllib.parse.urlencode(data).encode()
        elif isinstance(data, str):
            data_enc = data.encode()
        else:
            data_enc = data
        req.data = data_enc
        if not req.has_header("Content-Type"):
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    try:
        with urllib.request.urlopen(req, timeout=to, context=ctx) as resp:
            body = resp.read()
            try: return 0, resp.status, body.decode("utf-8")
            except: return 0, resp.status, body.decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
            try: bdec = body.decode("utf-8")
            except: bdec = body.decode("utf-8", errors="ignore")
            return 1, e.code, bdec
        except Exception as e2:
            return 2, -1, str(e2)
    except Exception as e:
        return 3, -1, str(e)

if __name__ == "__main__":
    op, cj = build_opener()
    page = "https://www.aastocks.com/tc/stocks/quote/detail-quote.aspx?symbol=00700"

    print("STEP1 GET page ...", flush=True)
    _,st,_ = _do(page)
    print(f"  status={st}", flush=True)

    print("STEP2 GET API token ...", flush=True)
    api_url = "https://www.aastocks.com/tc/resources/datafeed/getapitoken.ashx?" + urllib.parse.urlencode({
        "PageURL": page, "HKT":"Y", "UST":"Y"
    })
    _,_,r = _do(api_url, extra={"X-Requested-With":"XMLHttpRequest", "Referer":page})
    try: api_token = json.loads(r)["token"]
    except:
        m = re.search(r'"token"\s*:\s*"([^"]+)"', r)
        api_token = m.group(1) if m else None
    print(f"  API token len={len(api_token) if api_token else 'NONE'}", flush=True)

    print("STEP3 GET CE token (Auth header!) ...", flush=True)
    ce_url = "https://www.aastocks.com/tc/resources/datafeed/getcetoken.ashx"
    _,_,ce_raw = _do(ce_url, extra={
        "Auth": f"Bearer {api_token}",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": page,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })
    ce_token = ce_raw.strip().strip('"').strip("'")
    print(f"  CE token len={len(ce_token)} | raw={repr(ce_token[:120])}", flush=True)

    grp_val = ",".join(AA_SYMBOLS) + "|" + GROUP_BASIC + "|F=Y"
    base_url = "https://fctdata.aastocks.com/g2ce/Quote/getQuote?format=json" + ce_token
    hdrs_base = {
        "Origin": "https://www.aastocks.com",
        "Referer": page,
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }

    tests = [
        ("POST w/ dict", "POST", {"grp0": grp_val}, None),
        ("POST w/ str",  "POST", "grp0=" + urllib.parse.quote(grp_val), None),
        ("POST w/ raw pipe", "POST", "grp0=" + grp_val.replace("|","%7C").replace(",","%2C"), None),
        ("GET  w/ query", "GET",  None, base_url + "&grp0=" + urllib.parse.quote(grp_val)),
        ("GET  w/ query noenc", "GET", None, base_url + "&grp0=" + grp_val),
    ]
    for name, method, data, url in tests:
        url_use = url or base_url
        print(f"\n=== TEST {name} ===", flush=True)
        err, st, body = _do(url_use, method=method, data=data, extra=hdrs_base, to=20)
        print(f"  err={err} status={st} body_len={len(body)}", flush=True)
        if body and len(body) > 0:
            head = body[:500]
            print(f"  HEAD: {head}", flush=True)
            if not err and len(body) > 50:
                out = os.path.join(os.path.dirname(__file__), f"tmp_fct_{name.replace(' ','_')}.json")
                with open(out, "w", encoding="utf-8") as f:
                    f.write(body)
                print(f"  SAVED: {out}", flush=True)
    print("\nALL DONE.", flush=True)
