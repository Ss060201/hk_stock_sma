import urllib.request, ssl, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

url = 'https://www.aastocks.com/tc/resources/script/js_us_stream?v=E1wUq87iBZ7HYHFt0OieKyGu3KoZhMlepQktP8r74SM1'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

print("Downloading js_us_stream...", flush=True)
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
try:
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        js = resp.read().decode('utf-8', errors='ignore')
except Exception as e:
    print(f"FAILED: {e}")
    sys.exit(1)

print(f"JS_LEN: {len(js)}", flush=True)

for pat in ['fctdata','GetData_URL','function it(','symbol=','.ashx?','Token','getapitoken','getcetoken']:
    idx = js.find(pat)
    if idx >= 0:
        snippet = js[max(0,idx-150):idx+600]
        print(f"\n==== PATTERN: {pat} at idx {idx} ====")
        print(snippet[:700])

print("\n\n==== URL CONSTRUCTION PATTERNS ====", flush=True)
for m in re.finditer(r"url\s*[:=+]\s*[\"']([^\"']+)[\"']", js):
    u = m.group(1)
    if any(k in u.lower() for k in ['data','quote','symbol','ashx','stream','get','token','chart']):
        print('URL-CAND:', u[:250])

print("\n\n==== symbol param concat patterns ====", flush=True)
for m in re.finditer(r"symbol\s*[+=]\s*['\"]?([^\"';&\n]{0,100})", js):
    raw = m.group(0)
    if len(raw) > 20:
        print('SYM-PAT:', raw[:200])
