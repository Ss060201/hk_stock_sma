# 新功能规格书：比较模式 (Comparison Mode)

## 🎯 功能概述

在港股 SMA 矩阵收藏总览页面添加 **【比较模式】** 按钮，用户点击后进入新页面，快速对比收藏夹中所有港股的关键指标，帮助用户：
- 快速识别上升趋势的股票
- 找出偏离最大的机会
- 检视 CDM 触发状态
- 对比振幅大小

---

## 📐 界面设计

### 1. 主页面（收藏总览）- 添加按钮位置

```
┌─ 港股 SMA 矩阵 - 收藏總覽 ────────────────────────────┐
│                                                          │
│  [🔄 刷新所有數據] [📊 比較模式] ← 新增按钮              │
│                                                          │
│  ────────────────────────────────────────────────────  │
│                                                          │
│  ◆ 700 Tencent  Price: 123.45  (+2.3%)                 │
│  ├─ SMA Matrix 表格...                                  │
│  ├─ BS Analysis 表格...                                 │
│  │                                                      │
│  ◆ 1810 Xiaomi  Price: 45.67   (-0.5%)                 │
│  ├─ SMA Matrix 表格...                                  │
│  └─ BS Analysis 表格...                                 │
│                                                          │
└──────────────────────────────────────────────────────┘
```

**按钮位置**：与「🔄 刷新所有数据」按钮并排
**按钮样式**：同宽度布局，使用 `st.columns([1, 1])` 分割

---

### 2. 比较模式页面 - 完整布局

```
┌─ 📊 港股收藏夾對比面板 ───────────────────────────────┐
│                                                        │
│  [🏠 回到主頁面] [🔄 刷新數據] [⬇️ 下載報告] [🔧 篩選設定]│
│                                                        │
│  ════════════════════════════════════════════════   │
│                                                        │
│  📈 【SMA 上升趨勢排序】                               │
│  ┌─────────────────────────────────────────────────┐│
│  │ 股票  │ 現價 │ 變化% │ SMA7 │ SMA14│ SMA28│ 趨勢  ││
│  ├─────────────────────────────────────────────────┤│
│  │ 700   │ 123 │ +2.3% │ 121 │ 120 │ 119 │ ⬆️⬆️⬆️ ││
│  │ 1810  │ 45  │ -0.5% │ 46  │ 47  │ 48  │ ⬇️⬇️⬇️ ││
│  │ 2318  │ 89  │ +1.2% │ 88  │ 87  │ 86  │ ⬆️⬆️⬆️ ││
│  └─────────────────────────────────────────────────┘│
│                                                        │
│  💰 【MR 偏差排序 - 機會大小】                        │
│  ┌─────────────────────────────────────────────────┐│
│  │ 排名 │ 股票 │ 現價 │ AvgP MR% │ 評級 │ 上升勢 │ 推薦 ││
│  ├─────────────────────────────────────────────────┤│
│  │  1   │ 700  │ 123  │ +5.2%    │ 中度 │ ⬆️   │ ⭐⭐  ││
│  │  2   │ 2318 │ 89   │ +3.8%    │ 輕度 │ ⬆️⬆️  │ ⭐⭐⭐││
│  │  3   │ 1810 │ 45   │ -2.1%    │ 無   │ ⬇️   │ 謹慎  ││
│  └─────────────────────────────────────────────────┘│
│                                                        │
│  🔴 【CDM 觸發狀態 - 即時機會】                       │
│  ┌─────────────────────────────────────────────────┐│
│  │ 股票 │ CDM狀態│ 目標價 │ 偏差% │ TOR信號│ 信心度 ││
│  ├─────────────────────────────────────────────────┤│
│  │ 700  │ ❌未觸發│ 120.5 │ -2.1% │   ✅  │ 75%   ││
│  │ 1810 │ 🔴觸發 │ 44.2  │ +3.5% │   ✅  │ 92%   ││
│  │ 2318 │ ⏳待觀察│ 87.8  │ -1.2% │   ❌  │ 45%   ││
│  └─────────────────────────────────────────────────┘│
│                                                        │
│  📊 【振幅對比 - 交易機會大小】                       │
│  ┌─────────────────────────────────────────────────┐│
│  │ 股票 │ AMP(%)│ AMP MR%│ 級別  │ 預測振幅│ 風險等級 ││
│  ├─────────────────────────────────────────────────┤│
│  │ 700  │ 2.3% │ +45% │ 中等 │ 2.5-3.2%│   🟡   ││
│  │ 1810 │ 3.1% │ +78% │ 高   │ 3.0-4.5%│   🔴   ││
│  │ 2318 │ 1.8% │ +12% │ 低   │ 1.9-2.4%│   🟢   ││
│  └─────────────────────────────────────────────────┘│
│                                                        │
│  ⭐ 【綜合評分排序 - 當日最佳機會】                   │
│  ┌─────────────────────────────────────────────────┐│
│  │排名│ 股票 │ 評分 │ 趨勢 │ 偏差 │ 振幅 │ 推薦操作  ││
│  ├─────────────────────────────────────────────────┤│
│  │ 🥇 │ 1810 │ 9.2  │ ⬆️  │ 高  │ 高  │ 買入重點  ││
│  │ 🥈 │ 2318 │ 7.8  │ ⬆️  │ 中  │ 低  │ 可考慮    ││
│  │ 🥉 │ 700  │ 6.5  │ ⬆️  │ 低  │ 中  │ 觀望      ││
│  └─────────────────────────────────────────────────┘│
│                                                        │
│  📌 最後更新: 2026-05-27 15:30 (已同步)              │
│  💡 提示: 點擊股票代號可查看詳細圖表                  │
│                                                        │
└──────────────────────────────────────────────────────┘
```

---

## 🔧 详细功能说明

### A. 表格 1：SMA 上升趋势排序

**显示字段**：
- 股票代号 (可点击进入详情)
- 现价 + 变化 %
- SMA 7日 / 14日 / 28日 (最新值)
- 趋势图标 (⬆️ = 价格 > SMA, ⬇️ = 价格 < SMA)
- **排序规则**：按 `(SMA7 > SMA14 > SMA28) + (价格 > SMA7)` 的条数排序
  - 3个条件都满足 = ⬆️⬆️⬆️ (强势)
  - 2个条件满足 = ⬆️⬆️ (上升)
  - 1个条件满足 = ⬆️ (弱势)
  - 0个条件 = ⬇️⬇️⬇️ (下跌)

**颜色编码**：
- ⬆️⬆️⬆️ 绿色背景 (最强)
- ⬆️⬆️ 浅绿色
- ⬆️ 灰色
- ⬇️ 浅红色
- ⬇️⬇️⬇️ 红色背景 (最弱)

---

### B. 表格 2：MR 偏差排序 - 机会大小

**显示字段**：
- 排名 (1-N)
- 股票代号
- 现价
- AvgP MR% (偏离率：+为高估，-为低估)
- 评级 (根据偏离幅度)：
  - |MR| > 5% = 🔴 极度偏离 (大机会或大风险)
  - 3% < |MR| ≤ 5% = 🟠 中度偏离 (中机会)
  - 1% < |MR| ≤ 3% = 🟡 轻度偏离 (小机会)
  - |MR| ≤ 1% = 🟢 正常范围 (无特殊机会)
- 上升势 (来自表1的⬆️⬆️⬆️ 判断)
- 推荐度 (结合 MR 和上升势)

**排序规则**：
1. 优先按 `|MR%|` 降序 (偏离最大的优先)
2. 其次按上升势的⬆️数量 (在偏离相同时，优先向上的)

**推荐度计算**：
```python
if 上升势 == '⬆️⬆️⬆️' and 1% < |MR| ≤ 5%:
    推荐度 = ⭐⭐⭐ (最推荐买入)
elif 上升势 == '⬆️⬆️' and 2% < |MR| ≤ 6%:
    推荐度 = ⭐⭐ (可以考虑)
elif 上升势 == '⬇️⬇️⬇️' and |MR| > 3%:
    推荐度 = ⚠️ 谨慎 (需要技术确认)
else:
    推荐度 = ⭐ (观望)
```

---

### C. 表格 3：CDM 触发状态 - 即时机会

**显示字段**：
- 股票代号
- CDM 状态：
  - 🔴 **触发** (满足：偏差 < 5% AND TOR 条件 AND SMA 条件)
  - ❌ **未触发** (不满足上述条件)
  - ⏳ **待观察** (接近触发但尚未完全满足，如偏差 5-8%)
- 目标价 (基于 CDM 算法计算的价格)
- 偏差% (目标价 vs 现价 的百分比)
- TOR 信号 (✅ = 成交量下降正常, ❌ = 成交量异常)
- 信心度% (基于满足条件的百分比)

**CDM 状态判断逻辑**：
```python
if 已设置 CDM 参数:
    if abs(偏差%) < 5% AND TOR_满足 AND SMA57_SMA106_接近:
        状态 = '🔴 触发'
    elif 5% <= abs(偏差%) < 8%:
        状态 = '⏳ 待观察'
    else:
        状态 = '❌ 未触发'
else:
    状态 = '⚙️ 未配置'  # 引导用户点击进去配置
```

**信心度计算**：
```python
信心度 = (
    (1 - min(abs(偏差%), 10) / 10) * 40 +  # 偏差小加分
    TOR_条件_满足 * 30 +                    # TOR满足加分
    SMA_条件_满足 * 30                      # SMA满足加分
)
```

---

### D. 表格 4：振幅对比 - 交易机会大小

**显示字段**：
- 股票代号
- AMP(%) = 当日 (High - Low) / Prev Close * 100
- AMP MR% = (AMP0 / Avg AMP) - 1 (振幅相对历史平均的偏离)
- 级别：
  - AMP > 平均 * 1.5 = 🔴 **高** (波动大，适合短线)
  - 平均 * 1.2 < AMP ≤ 平均 * 1.5 = 🟠 **中等** (正常波动)
  - AMP ≤ 平均 * 1.2 = 🟢 **低** (波动小，适合长线)
- 预测振幅 (基于历史数据预测明天可能的振幅范围)
- 风险等级 (基于波动性)：
  - 🔴 高风险 (AMP MR > 50%)
  - 🟠 中风险 (20% < AMP MR ≤ 50%)
  - 🟡 低风险 (AMP MR ≤ 20%)
  - 🟢 超低风险 (AMP MR 为负，且 < -20%)

**排序规则**：优先按 AMP MR% 降序 (振幅异常大的优先)

**预测振幅公式**：
```python
预测振幅_下界 = Avg AMP * 0.8
预测振幅_上界 = Avg AMP * 1.2
预测范围 = f"{预测振幅_下界:.2f}% - {预测振幅_上界:.2f}%"
```

---

### E. 表格 5：综合评分排序 - 当日最佳机会

**综合评分算法**：
```python
综合评分 = (
    趋势评分 * 0.25 +      # ⬆️⬆️⬆️ = 10, ⬆️⬆️ = 7, ⬆️ = 5, ⬇️ = 2
    偏差评分 * 0.30 +      # 中度偏离向上 = 10, 轻度 = 7, 无偏离 = 4
    CDM评分 * 0.25 +       # 触发 = 10, 待观察 = 6, 未触发 = 2
    振幅评分 * 0.20        # 中等-高振幅向上 = 10, 低振幅 = 3
)
# 最终评分 0-10 分
```

**推荐操作**：
- 评分 ≥ 8.5: 🟢 **买入重点** (强烈建议)
- 7.0 ≤ 评分 < 8.5: 🟡 **可考虑** (中等推荐)
- 5.5 ≤ 评分 < 7.0: 🔵 **观望** (可关注)
- 评分 < 5.5: 🔴 **谨慎** (暂不考虑)

**排名显示**：
- 🥇 第1名 (最高评分)
- 🥈 第2名
- 🥉 第3名
- 4+ (序号显示)

---

## 📊 页面交互功能

### 1. 顶部操作栏

```python
col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

with col1:
    if st.button("🏠 回到主頁面", use_container_width=True):
        st.session_state.current_view = ""
        st.rerun()

with col2:
    if st.button("🔄 刷新數據", use_container_width=True):
        st.cache_clear()
        st.rerun()

with col3:
    if st.button("⬇️ 下載報告", use_container_width=True):
        # 生成 Excel/CSV 报告
        download_comparison_report()

with col4:
    if st.button("🔧 篩選設定", use_container_width=True):
        st.session_state.show_filter = not st.session_state.show_filter
```

### 2. 可选的筛选面板 (expander)

```python
with st.expander("🔧 篩選設定", expanded=False):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        filter_trend = st.multiselect(
            "篩選趨勢",
            ["⬆️⬆️⬆️ 強勢", "⬆️⬆️ 上升", "⬆️ 弱勢", "⬇️ 下跌"],
            default=["⬆️⬆️⬆️ 強勢", "⬆️⬆️ 上升"]
        )
    
    with col2:
        filter_mr = st.multiselect(
            "篩選偏差",
            ["🔴 極度", "🟠 中度", "🟡 輕度", "🟢 正常"],
            default=["🔴 極度", "🟠 中度"]
        )
    
    with col3:
        filter_cdm = st.multiselect(
            "篩選 CDM 狀態",
            ["🔴 觸發", "⏳ 待觀察", "❌ 未觸發"],
            default=["🔴 觸發", "⏳ 待觀察"]
        )
    
    if st.button("✅ 應用篩選"):
        st.session_state.comparison_filters = {
            "trend": filter_trend,
            "mr": filter_mr,
            "cdm": filter_cdm
        }
```

### 3. 点击股票代号跳转

```python
# 在每个表格中，股票代号需要是可点击的
if st.button(ticker, key=f"compare_nav_{ticker}"):
    st.session_state.current_view = ticker
    st.rerun()
```

### 4. 下载报告功能

```python
def download_comparison_report():
    """生成 Excel 对比报告"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    
    wb = Workbook()
    
    # 工作表1: 趋势排序
    ws1 = wb.active
    ws1.title = "SMA趨勢"
    # ... 写入表1数据
    
    # 工作表2: MR偏差
    ws2 = wb.create_sheet("MR偏差")
    # ... 写入表2数据
    
    # 工作表3: CDM状态
    ws3 = wb.create_sheet("CDM狀態")
    # ... 写入表3数据
    
    # 工作表4: 振幅对比
    ws4 = wb.create_sheet("振幅對比")
    # ... 写入表4数据
    
    # 工作表5: 综合评分
    ws5 = wb.create_sheet("綜合評分")
    # ... 写入表5数据
    
    # 保存并下载
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    st.download_button(
        label="📥 下載 Excel 報告",
        data=buffer.getvalue(),
        file_name=f"港股對比報告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
```

### 5. 更新时间显示

```python
# 页面底部显示
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"📌 最後更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (已同步)")
with col2:
    st.caption("💡 點擊股票代號可查看詳細圖表")
```

---

## 🛠️ 实现技术细节

### 数据缓存策略

```python
@st.cache_data(ttl=300)  # 5分钟缓存
def get_comparison_data(watchlist_codes):
    """批量获取对比数据"""
    comparison_data = {}
    
    for ticker in watchlist_codes:
        yahoo_ticker = get_yahoo_ticker(ticker)
        try:
            df = yf.download(yahoo_ticker, period="3y", progress=False)
            # ... 计算所有指标
            comparison_data[ticker] = {
                'price': df['Close'].iloc[-1],
                'change_pct': ...,
                'sma7': ...,
                'sma14': ...,
                'sma28': ...,
                'mr': ...,
                'amp': ...,
                'cdm_status': ...,
                'cdm_target': ...,
                'cdm_diff': ...,
                'cdm_confidence': ...,
            }
        except Exception as e:
            st.warning(f"無法獲取 {ticker} 數據: {e}")
    
    return comparison_data
```

### 表格排序和渲染

```python
import pandas as pd

def render_comparison_tables(comparison_data, filters=None):
    """渲染所有对比表格"""
    
    # 1. SMA 趋势表
    trend_data = []
    for ticker, data in comparison_data.items():
        trend_score = calculate_trend_score(data['sma7'], data['sma14'], data['sma28'], data['price'])
        trend_data.append({
            '股票': ticker,
            '現價': f"{data['price']:.2f}",
            '變化%': f"{data['change_pct']:+.2f}%",
            'SMA7': f"{data['sma7']:.2f}",
            'SMA14': f"{data['sma14']:.2f}",
            'SMA28': f"{data['sma28']:.2f}",
            '趨勢': get_trend_icon(trend_score),
            '_sort_key': trend_score  # 用于排序
        })
    
    df_trend = pd.DataFrame(trend_data).sort_values('_sort_key', ascending=False).drop('_sort_key', axis=1)
    st.subheader("📈 【SMA 上升趨勢排序】")
    st.dataframe(df_trend, use_container_width=True, hide_index=True)
    
    # 2. MR偏差表
    # ... 类似逻辑
    
    # 3. CDM状态表
    # ... 类似逻辑
    
    # 4. 振幅对比表
    # ... 类似逻辑
    
    # 5. 综合评分表
    # ... 类似逻辑
```

---

## 📝 主要代码改动位置

### 1. `app.py` 第 393-399 行（收藏总览页面）

**现有代码**：
```python
if not watchlist_list:
    st.info("👈 您的收藏清單為空，請從左側加入股票。")
else:
    if st.button("🔄 刷新所有數據"): st.rerun()
    st.write("---")
```

**改动后**：
```python
if not watchlist_list:
    st.info("👈 您的收藏清單為空，請從左側加入股票。")
else:
    col_refresh, col_compare = st.columns(2)
    with col_refresh:
        if st.button("🔄 刷新所有數據", use_container_width=True): 
            st.rerun()
    with col_compare:
        if st.button("📊 比較模式", use_container_width=True, type="primary"):
            st.session_state.comparison_mode = True
            st.rerun()
    
    st.write("---")
    
    # 进入比较模式
    if st.session_state.get('comparison_mode', False):
        render_comparison_page(watchlist_list, watchlist_data)
    else:
        # 原有的卡片显示逻辑...
        for ticker in watchlist_list:
            # ... 现有代码
```

### 2. 新增文件：`comparison_mode.py`

包含所有对比模式的函数：
- `render_comparison_page()`
- `get_comparison_data()`
- `calculate_trend_score()`
- `calculate_mr_score()`
- `calculate_cdm_score()`
- `calculate_amp_score()`
- `calculate_overall_score()`
- `render_trend_table()`
- `render_mr_table()`
- `render_cdm_table()`
- `render_amp_table()`
- `render_overall_table()`
- `download_comparison_report()`

---

## ✅ 验收标准

- [ ] 【比较模式】按钮在收藏总览页面可见
- [ ] 点击按钮能进入新的对比页面
- [ ] 5 个对比表格都能正确显示
- [ ] 表格排序符合逻辑说明
- [ ] 点击股票代号能跳转到详情页
- [ ] 【回到主页面】按钮能返回总览
- [ ] 【刷新数据】功能正常
- [ ] 【下载报告】生成有效的 Excel 文件
- [ ] 【筛选设定】能过滤表格数据
- [ ] 页面加载时间 < 5 秒（包含 API 调用）
- [ ] 在小屏幕设备上仍可读（响应式设计）
- [ ] 所有数据计算公式与规格书一致

---

## 📚 相关参考

- **对比表格参考**：TradingView 的 Stock Screener
- **评分算法参考**：Alpha Vantage 评分机制
- **报告下载参考**：Finviz Elite 报告功能
- **响应式设计参考**：Streamlit 官方最佳实践

---

## 🚀 后续优化方向

1. **缓存优化** - 使用 Redis 存储对比数据，加快加载速度
2. **实时更新** - 使用 WebSocket 实现实时数据推送
3. **AI 智能排序** - 根据用户历史操作学习最优排序
4. **对比历史** - 保存历史对比结果，查看趋势变化
5. **导出模板** - 支持导出为 PDF/Word/PPT
6. **对比预警** - 当股票排名变化时 Telegram 通知用户
7. **分组对比** - 按行业/板块分组对比

