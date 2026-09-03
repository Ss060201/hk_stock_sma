import os, re, json
ROOT = r"c:\Users\one\sma\hk_stock_sma"
TARGETS = [
    ('tmp_aastocks_00700.html', (400, 470), "0700.HK local≈438.2"),
    ('tmp_aastocks_02318.html', (50, 65), "2318.HK local≈55.5"),
    ('tmp_aastocks_01299.html', (70, 82), "1299.HK local≈76"),
    ('tmp_aastocks_00005.html', (150, 175), "0005.HK local≈162"),
]
for fname, rng, tag in TARGETS:
    p = os.path.join(ROOT, fname)
    if not os.path.exists(p): continue
    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
        txt = f.read()
    lo, hi = rng
    print("=" * 72)
    print(f"{fname}  [{tag}]")
    nums = sorted(set(float(x) for x in re.findall(r'(\d{1,5}\.\d{2})', txt) if lo <= float(x) <= hi))
    print(f"  AAStocks 價位候選 ({lo}~{hi}): {nums[:15]}")
    print()
    for w in ['前收市','開市','最高','最低','現價','成交金額','Volume','Nominal','Turnover','Net','HIGH','LOW','PREV']:
        for m in re.finditer(re.escape(w) + r'.{0,120}', txt):
            s = m.group(0).replace('\t',' ').replace('\r',' ').replace('\n',' ')
            print(f"  [{w:>8s}]  {s[:120]!r}")
            break
    # 找 JSON 內含 0700 / 2318 / 1299 / 0005
    code = fname.split("_")[-1].split(".")[0]
    for pat in [rf'["\']{code}["\'][^,]*,\s*["\']([^"\']{{2,20}})["\'],\s*(-?\d[\d\.]*)[^,]*,\s*(-?\d[\d\.]*)[^,]*,\s*(-?\d[\d\.]*)[^,]*,\s*(-?\d[\d\.]*)[^,]*,\s*(-?\d[\d\.]*)']:
        found = list(re.finditer(pat, txt))[:3]
        if found:
            print(f"\n  JS array matches for {code}:")
            for f1 in found:
                print(f"    {f1.group(0)[:200]!r}")
    print()
