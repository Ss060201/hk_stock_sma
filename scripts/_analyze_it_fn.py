import urllib.request, ssl, re

url = 'https://www.aastocks.com/tc/resources/script/js_us_stream?v=E1wUq87iBZ7HYHFt0OieKyGu3KoZhMlepQktP8r74SM1'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
    js = resp.read().decode('utf-8', errors='ignore')

idx = js.find('function it(t,i){')
if idx >= 0:
    print('=== FUNCTION it(t,i) FULL SNIPPET ===')
    print(js[idx:idx+6000])

print('\n\n=== r.d / request option build around it() ===')
seg = js[idx:idx+15000]
for pat in ['r.d={','.d = {','symbol:','group:','action:','$.ajax({','data:r.d']:
    i2 = seg.find(pat)
    if i2 >= 0:
        print(f'\n--- PAT: {pat} at {i2} ---')
        print(seg[max(0,i2-100):i2+600])
