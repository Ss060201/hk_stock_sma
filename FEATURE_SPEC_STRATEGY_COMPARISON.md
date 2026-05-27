# 新功能规格书：策略对标与推荐功能 (Strategy Comparison & Recommendation)

## 🎯 功能概述

在单股详情页面的【历史回测】选项卡中新增 **【策略对标】** 子页面，允许用户：
1. **自动对标三大策略** - CDM / FZM / MR 在同一时间段的表现对比
2. **可视化对比分析** - 并排展示所有策略的关键指标和收益曲线
3. **智能推荐最优策略** - 基于回测数据推荐最适合该股票的策略
4. **策略特性分析** - 展示每个策略的优缺点和适用场景
5. **切换默认策略** - 一键应用推荐的策略到实盘

---

## 📐 界面设计

### 1. 【历史回测】选项卡 - 新增【策略对标】子页面

```
┌─ 📊 00700 - 歷史回測 ────────────────────────────────────────────┐
│                                                                      │
│  [⚙️ 回測設定] [📊 單策略回測] [🆚 策略對標] [🎯 策略推薦]        │
│                                                                      │
│  === 【🆚 策略對標】子頁面 ===                                       │
│                                                                      │
│  ┌─ 對標時間段 ──────────────────────────────────────────────────┐ │
│  │ 📅 開始: 2024-05-27  📅 結束: 2025-05-27  [⏪ 1Y] [⏪ 2Y] [⏪ ALL]  ││
│  │ 時間段概況: 共 252 個交易日，時間跨度: 1 年                    ││
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ 三大策略核心指標對比 ──────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌──────────────┬──────────────┬──────────────┐            │ │
│  │  │   CDM 策略   │   FZM 策略   │   MR 策略    │            │ │
│  │  │ (價格目標型) │ (超底反轉)   │ (偏離套利)   │            │ │
│  │  ├──────────────┼──────────────┼──────────────┤            │ │
│  │  │ 📈 年化收益: │ 📈 年化收益: │ 📈 年化收益: │            │ │
│  │  │ +18.5%       │ +22.3%       │ +15.2%       │            │ │
│  │  │ 🥇 排名第2   │ 🥇 排名第1   │ 🥇 排名第3   │            │ │
│  │  │              │              │              │            │ │
│  │  │ 勝率: 68%    │ 勝率: 72%    │ 勝率: 61%    │            │ │
│  │  │ 回撤: -7.2%  │ 回撤: -9.5%  │ 回撤: -5.8%  │            │ │
│  │  │ 交易數: 24   │ 交易數: 18   │ 交易數: 31   │            │ │
│  │  │ 夏普比: 1.45 │ 夏普比: 1.32 │ 夏普比: 1.18 │            │ │
│  │  │              │              │              │            │ │
│  │  │ ⭐ 評級:     │ ⭐ 評級:     │ ⭐ 評級:     │            │ │
│  │  │ 🟡 中等推薦  │ 🟢 強烈推薦  │ 🔴 不推薦    │            │ │
│  │  │              │              │              │            │ │
│  │  │ [📊 詳情]    │ [📊 詳情]    │ [📊 詳情]    │            │ │
│  │  │ [✅ 採用]    │ [✅ 採用]    │ [✅ 採用]    │            │ │
│  │  └──────────────┴──────────────┴──────────────┘            │ │
│  │                                                            │ │
│  │  💡 對標說明:                                              │ │
│  │  • 所有策略基於相同時間段 (2024-05-27 ~ 2025-05-27)      │ │
│  │  • 所有策略共同參數 (本金: 10000 HKD, 手續費: 0.2%)       │ │
│  │  • 所有策略使用默認優化參數                               │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ 策略收益曲線對比 ─────────────────────────────────────────┐ │
│  │                                                              │ │
│  │  📈 累積收益對比圖 (% 收益)                                 │ │
│  │                                                              │ │
│  │   +30% ┤                        ╱╱╱╱╱                     │ │
│  │   +25% ┤                    ╱╱╱╱ (FZM)                   │ │
│  │   +20% ┤                ╱╱╱╱╱                             │ │
│  │   +15% ┤            ╱╱╱╱ (CDM)                            │ │
│  │   +10% ┤        ╱╱╱╱                                       │ │
│  │   +5%  ┤    ╱╱╱╱ (MR)                                      │ │
│  │    0%  ┤╱╱╱╱                                               │ │
│  │   -5%  ┤                                                    │ │
│  │        └─────────────────────────────────────────────────│ │
│  │        2024-05  2024-08  2024-11  2025-02  2025-05       │ │
│  │                                                              │ │
│  │  ── CDM (年化 +18.5%)  ── FZM (年化 +22.3%)              │ │
│  │  ── MR  (年化 +15.2%)  ── 基準線 (買入持有)               │ │
│  │                                                              │ │
│  │  📊 圖表說明:                                               │ │
│  │  • 陰影區域 = 最大回撤發生的時期                           │ │
│  │  • 虛線標記 = 策略信號發生點                              │ │
│  │  • 顏色代碼 = 對應每個策略的標誌色                        │ │
│  │                                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ 詳細對比表格 ────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌────────────────────┬────────┬────────┬────────┐        │ │
│  │  │ 指標               │ CDM    │ FZM    │ MR     │        │ │
│  │  ├────────────────────┼────────┼────────┼────────┤        │ │
│  │  │ 年化收益           │ +18.5% │ +22.3%✅│ +15.2%│        │ │
│  │  │ 月平均收益         │ +1.6%  │ +1.85% │ +1.3% │        │ │
│  │  │ 勝率               │ 68%    │ 72% ✅ │ 61%   │        │ │
│  │  │ 平均獲利           │ +2.8%  │ +3.2% ✅│ +2.5%│        │ │
│  │  │ 平均虧損           │ -1.8%  │ -2.1% │ -1.5%✅│        │ │
│  │  │ 盈虧比             │ 1.56:1 │ 1.52:1│ 1.67:1✅│        │ │
│  │  │ 最大回撤           │ -7.2%  │ -9.5% │ -5.8%✅│        │ │
│  │  │ 回撤恢復天數       │ 28 天✅ │ 35 天 │ 22 天✅│        │ │
│  │  │ 夏普比率           │ 1.45 ✅│ 1.32  │ 1.18  │        │ │
│  │  │ 信心指數           │ 72/100 │ 78/100✅│ 62/100│        │ │
│  │  │ 交易次數           │ 24     │ 18 ✅ │ 31    │        │ │
│  │  │ 連勝紀錄           │ 4 次   │ 5 次✅ │ 3 次  │        │ │
│  │  │ 連敗紀錄           │ 2 次✅ │ 3 次  │ 4 次  │        │ │
│  │  │ 適用場景           │ 中長線 │ 短線  │ 偏離  │        │ │
│  │  │ 參數調整難度       │ 簡單✅ │ 中等  │ 複雜  │        │ │
│  │  │ 信號頻率           │ 中等   │ 低✅  │ 高    │        │ │
│  │  │ 虛假信號比例       │ 中等   │ 低✅  │ 高    │        │ │
│  │  └────────────────────┴────────┴────────┴────────┘        │ │
│  │                                                            │ │
│  │  ✅ = 在該指標上表現最優的策略                           │ │
│  │                                                            │ │
│  └──────────────────────────────────────��─────────────────────┘ │
│                                                                      │
│  ┌─ 策略特性分析 ────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ╔═════════════════════════════════════════════════════╗  │ │
│  │  ║ 🥇 推薦策略: FZM (超底反轉策略) - 最高評分 9.2/10   ║  │ │
│  │  ║ 適合人群: 風險偏好 ◉ 高   對市場把握 ◉ 良好        ║  │ │
│  │  ║ 交易風格: 短線 ◉ 波段 ○ 中長線 ○                   ║  │ │
│  │  ╚═════════════════════════════════════════════════════╝  │ │
│  │                                                            │ │
│  │  📊 FZM 策略詳解:                                          │ │
│  │                                                            │ │
│  │  【策略原理】                                              │ │
│  │  基於威廉指標 (WR) 超賣信號 + SMA 雙線突破               │ │
│  │  當股價 > SMA7/14 且 WR < -80% 時買入                   │ │
│  │  當股價 < SMA14 或達止盈目標時賣出                       │ │
│  │                                                            │ │
│  │  【優點】                                                  │ │
│  │  ✅ 年化收益最高 (+22.3%)                                 │ │
│  │  ✅ 勝率最高 (72%)                                        │ │
│  │  ✅ 虛假信號最少                                          │ │
│  │  ✅ 交易次數適中 (不頻繁不緩慢)                          │ │
│  │  ✅ 適合在股價反彈時介入                                 │ │
│  │  ✅ 夏普比率最優 (1.45)                                   │ │
│  │                                                            │ │
│  │  【缺點】                                                  │ │
│  │  ❌ 最大回撤較大 (-9.5%)                                 │ │
│  │  ❌ 回撤恢復時間較長 (35 天)                             │ │
│  │  ❌ 需要准確把握超賣時機                                 │ │
│  │  ❌ 在震盪市中可能虧損                                    │ │
│  │                                                            │ │
│  │  【適用場景】                                              │ │
│  │  • 股價經歷下跌後觸及支撐位時 ◉ 推薦                     │ │
│  │  • 市場整體超賣時                ◉ 推薦                   │ │
│  │  • 股票基本面未變但技術面超賣    ◉ 推薦                   │ │
│  │  • 單邊下跌的熊市中              ❌ 不推薦               │ │
│  │  • 震盪行情中                    ❌ 不推薦               │ │
│  │                                                            │ │
│  │  【參數設置】                                              │ │
│  │  WR 閾值: -80%  |  止盈目標: +5%  |  止損點: -3%        │ │
│  │                                                            │ │
│  │  【最近表現】(最近 30 天)                                 │ │
│  │  勝率: 75% (6/8 筆交易獲利)                              │ │
│  │  月均收益: +2.1%                                          │ │
│  │  最大單筆虧損: -2.8%                                      │ │
│  │                                                            │ │
│  │  ───────────────────────────────────────────────────────  │ │
│  │                                                            │ │
│  │  🥈 備選策略: CDM (價格目標策略) - 評分 8.1/10           │ │
│  │  • 穩定性好，適合保守交易者                              │ │
│  │  • 年化收益 +18.5%，勝率 68%                            │ │
│  │  • 最大回撤最小 (-7.2%)，風險可控                       │ │
│  │  • 參數調整簡單，新手友好                               │ │
│  │                                                            │ │
│  │  🥉 不推薦: MR (偏離套利策略) - 評分 5.2/10             │ │
│  │  • 年化收益 +15.2%，低於其他策略                        │ │
│  │  • 勝率 61%，低於市場平均                               │ │
│  │  • 虛假信號多，交易太頻繁 (31 次)                       │ │
│  │  • 不適合該股票特性                                      │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ 操作建議 ────────────────────────────────────────────────┐ │
│  │                                                              │ │
│  │  💡 基於回測分析，我們的建議:                              │ │
│  │                                                              │ │
│  │  1️⃣ 【首選】                                                │ │
│  │     採用 FZM 策略進行實盤交易                              │ │
│  │     [✅ 採用 FZM] [🔄 交叉驗證] [📊 查看詳細回測]        │ │
│  │                                                              │ │
│  │  2️⃣ 【備選】                                                │ │
│  │     在 CDM 信號触发時作為補充                              │ │
│  │     [✅ 採用 CDM] [🔄 組合使用]                           │ │
│  │                                                              │ │
│  │  3️⃣ 【風險管理】                                            │ │
│  │     設置止損 -3% 保護資金                                  │ │
│  │     監控最大回撤警告線 (設定在 -8%)                       │ │
│  │     建議單次倉位 2-3% 分批進場                            │ │
│  │                                                              │ │
│  │  4️⃣【持續監控】                                             │ │
│  │     每月回測一次參數優化                                  │ │
│  │     如果勝率下降到 60% 以下，重新評估策略                │ │
│  │                                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ 風險警告 ────────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ⚠️ 重要提示:                                              │ │
│  │  • 回測數據基於歷史，無法保證未來表現                     │ │
│  │  • 市場環境改變時，最優策略可能會改變                     │ │
│  │  • 建議先用模擬賬戶測試 2-4 週後再實盤交易              │ │
│  │  • 請務必設置止損單保護資金                               │ │
│  │  • 不要過度槓桿，控制單次虧損在總資金 2% 以內           │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  📌 最後更新: 2025-05-27 15:30                                      │
│  🔄 下次自動評估: 2025-06-27 (每月評估一次)                        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 核心功能详细规格

### A. 策略对比参数设置

#### 1. 时间段与共同条件

```python
st.markdown("**📅 對標時間段:**")

col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 0.7, 0.7, 0.7])

with col1:
    compare_start_date = st.date_input(
        "開始日期",
        value=df.index.min().date(),
        min_value=df.index.min().date()
    )

with col2:
    compare_end_date = st.date_input(
        "結束日期",
        value=df.index.max().date(),
        min_value=compare_start_date
    )

with col3:
    if st.button("⏪ 1Y", use_container_width=True):
        compare_end_date = df.index.max().date()
        compare_start_date = (pd.to_datetime(compare_end_date) - timedelta(days=365)).date()

with col4:
    if st.button("⏪ 2Y", use_container_width=True):
        compare_end_date = df.index.max().date()
        compare_start_date = (pd.to_datetime(compare_end_date) - timedelta(days=730)).date()

with col5:
    if st.button("⏪ ALL", use_container_width=True):
        compare_start_date = df.index.min().date()
        compare_end_date = df.index.max().date()

# 显示时间段概况
trading_days = len(df[(df.index >= pd.to_datetime(compare_start_date)) & 
                      (df.index <= pd.to_datetime(compare_end_date))])
time_span_years = (pd.to_datetime(compare_end_date) - pd.to_datetime(compare_start_date)).days / 365

st.caption(f"⏱️ 時間段概況: 共 {trading_days} 個交易日，時間跨度: {time_span_years:.1f} 年")
```

#### 2. 共同参数设置

```python
st.markdown("**⚙️ 共同參數 (所有策略適用):**")

col1, col2, col3 = st.columns(3)

with col1:
    compare_capital = st.number_input(
        "交易本金 (HKD)",
        min_value=1000,
        max_value=1000000,
        value=10000,
        step=1000,
        help="每筆交易的本金（所有策略統一使用）"
    )

with col2:
    compare_commission = st.number_input(
        "手續費率 (%)",
        min_value=0.0,
        max_value=1.0,
        value=0.2,
        step=0.05,
        help="每筆交易的手續費百分比（所有策略統一使用）"
    )

with col3:
    compare_sell_logic = st.radio(
        "賣出邏輯",
        ["🎯 止盈 (+5%)", "🛑 止損 (-3%)", "⏱️ 時間 (5日)"],
        help="所有策略採用相同賣出邏輯"
    )

st.caption("💡 說明: 為了公平對比，所有策略使用相同的交易本金、手續費率和賣出邏輯")
```

#### 3. 一键对标按钮

```python
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🆚 開始對標 (全部策略)", type="primary", use_container_width=True):
        st.session_state.run_strategy_comparison = True

with col2:
    if st.button("🔄 清空結果", use_container_width=True):
        st.session_state.comparison_results = None

with col3:
    if st.button("📥 導出對比報告", use_container_width=True):
        export_comparison_report()
```

---

### B. 三大策略核心指标对比卡片

#### 1. 卡片数据结构

```python
class StrategyComparisonResult:
    """策略对比结果数据类"""
    
    def __init__(self, strategy_name, backtest_results):
        self.strategy_name = strategy_name  # "CDM", "FZM", "MR"
        self.results = backtest_results
        
        # 从回测结果继承所有指标
        self.annual_return = backtest_results.annualized_return
        self.monthly_return = backtest_results.monthly_avg_return
        self.win_rate = backtest_results.win_rate
        self.max_drawdown = backtest_results.max_drawdown
        self.trades_count = len(backtest_results.trades)
        self.sharpe_ratio = backtest_results.sharpe_ratio
        self.profit_factor = backtest_results.profit_factor
        self.avg_winning = backtest_results.avg_winning_trade
        self.avg_losing = backtest_results.avg_losing_trade
        self.win_streak = backtest_results.win_streak
        self.loss_streak = backtest_results.loss_streak
    
    @property
    def rank_score(self):
        """计算综合排名得分"""
        score = (
            min(self.win_rate, 100) * 0.25 +           # 胜率 25%
            min(self.annual_return / 2, 100) * 0.30 +  # 收益 30%
            (100 - min(self.max_drawdown * 5, 100)) * 0.25 +  # 回撤 25%
            min(self.sharpe_ratio * 10, 100) * 0.20    # 夏普比 20%
        )
        return min(max(score, 0), 100)
    
    @property
    def rating(self):
        """策略评级"""
        score = self.rank_score
        if score >= 8.5:
            return ("🟢 強烈推薦", 0)  # 排名序号
        elif score >= 7.5:
            return ("🟡 中等推薦", 1)
        elif score >= 6.5:
            return ("🔵 可考慮", 2)
        else:
            return ("🔴 不推薦", 3)
```

#### 2. 卡片渲染函数

```python
def render_strategy_comparison_cards(comparison_results):
    """渲染三大策略对比卡片"""
    
    # 按得分排序
    sorted_results = sorted(
        comparison_results,
        key=lambda x: x.rank_score,
        reverse=True
    )
    
    st.markdown("### 🆚 三大策略核心指標對比")
    
    # 创建三列布局
    col1, col2, col3 = st.columns(3)
    
    for idx, (col, result) in enumerate(zip([col1, col2, col3], sorted_results)):
        with col:
            # 获取排名
            rank_emoji = ["🥇", "🥈", "🥉"][idx]
            rank_text = ["排名第1", "排名第2", "排名第3"][idx]
            rating_text, _ = result.rating
            
            # 确定背景颜色
            if idx == 0:
                bg_color = "#d4edda"  # 绿色
                border_color = "#28a745"
            elif idx == 1:
                bg_color = "#fff3cd"  # 黄色
                border_color = "#ffc107"
            else:
                bg_color = "#f8d7da"  # 红色
                border_color = "#dc3545"
            
            # 渲染卡片
            card_html = f"""
            <div style="
                border: 3px solid {border_color};
                border-radius: 10px;
                padding: 20px;
                background-color: {bg_color};
                text-align: center;
                margin-bottom: 15px;
            ">
                <h3 style="margin-top: 0; color: {border_color};">
                    {rank_emoji} {result.strategy_name} 策略 {rank_emoji}
                </h3>
                <p style="color: #666; margin: 5px 0; font-size: 12px;">
                    ({result.strategy_name} 简称: {result.strategy_name})
                </p>
                
                <hr style="border: none; border-top: 1px solid {border_color}; margin: 10px 0;">
                
                <div style="text-align: left;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0;">
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>📈 年化收益:</b></p>
                            <p style="margin: 5px 0; font-size: 18px; color: #28a745;"><b>{result.annual_return:+.1f}%</b></p>
                        </div>
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>勝率:</b></p>
                            <p style="margin: 5px 0; font-size: 18px; color: #007bff;"><b>{result.win_rate:.1f}%</b></p>
                        </div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0;">
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>回撤:</b></p>
                            <p style="margin: 5px 0; font-size: 16px; color: #dc3545;"><b>{result.max_drawdown:.1f}%</b></p>
                        </div>
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>交易數:</b></p>
                            <p style="margin: 5px 0; font-size: 16px;"><b>{result.trades_count}</b></p>
                        </div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0;">
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>夏普比:</b></p>
                            <p style="margin: 5px 0; font-size: 16px;"><b>{result.sharpe_ratio:.2f}</b></p>
                        </div>
                        <div>
                            <p style="margin: 5px 0; font-size: 12px; color: #666;"><b>盈虧比:</b></p>
                            <p style="margin: 5px 0; font-size: 16px;"><b>{result.profit_factor:.2f}:1</b></p>
                        </div>
                    </div>
                </div>
                
                <hr style="border: none; border-top: 1px solid {border_color}; margin: 10px 0;">
                
                <p style="margin: 10px 0;">
                    <b>⭐ 評級: {rating_text}</b><br>
                    <span style="color: #666; font-size: 12px;">綜合評分: {result.rank_score:.1f}/100</span>
                </p>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px;">
                    <button style="
                        padding: 8px;
                        background-color: {border_color};
                        color: white;
                        border: none;
                        border-radius: 5px;
                        cursor: pointer;
                        font-size: 12px;
                    ">📊 詳情</button>
                    <button style="
                        padding: 8px;
                        background-color: {border_color};
                        color: white;
                        border: none;
                        border-radius: 5px;
                        cursor: pointer;
                        font-size: 12px;
                    ">✅ 採用</button>
                </div>
            </div>
            """
            
            st.markdown(card_html, unsafe_allow_html=True)
```

---

### C. 策略收益曲线对比

#### 1. 多策略累积收益曲线

```python
def plot_multi_strategy_curves(comparison_results, df):
    """绘制多个策略的累积收益曲线"""
    
    fig = go.Figure()
    
    # 定义颜色
    colors = {
        'CDM': '#1f77b4',
        'FZM': '#ff7f0e',
        'MR': '#2ca02c'
    }
    
    # 为每个策略添加曲线
    for result in comparison_results:
        trades = result.results.trades
        
        # 计算累积收益
        cumulative_pnl = []
        cumulative_sum = 0
        trade_dates = []
        
        for trade in trades:
            cumulative_sum += trade['pnl']
            cumulative_pnl.append(cumulative_sum)
            trade_dates.append(trade['exit_date'])
        
        # 添加轨迹
        fig.add_trace(go.Scatter(
            x=trade_dates,
            y=cumulative_pnl,
            mode='lines+markers',
            name=f"{result.strategy_name} (年化 {result.annual_return:+.1f}%)",
            line=dict(color=colors.get(result.strategy_name, '#666'), width=2.5),
            marker=dict(size=5),
            hovertemplate=f"<b>{result.strategy_name}</b><br>日期: %{{x|%Y-%m-%d}}<br>累積收益: %{{y:.2f}}%<extra></extra>"
        ))
    
    # 添加零线
    fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
    
    # 更新布局
    fig.update_layout(
        title="📈 三大策略累積收益曲線對比",
        xaxis_title="日期",
        yaxis_title="累積收益 (%)",
        height=450,
        template="plotly_white",
        hovermode='x unified',
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        )
    )
    
    return fig
```

---

### D. 详细对比表格

#### 1. 多策略指标表格

```python
def render_comparison_table(comparison_results):
    """渲染详细对比表格"""
    
    # 准备数据
    table_data = []
    
    for result in comparison_results:
        # 获取每个指标的最优值（用于标记）
        table_data.append({
            '指標': '年化收益',
            'CDM': f"{comparison_results[0].annual_return:+.1f}%",
            'FZM': f"{comparison_results[1].annual_return:+.1f}%",
            'MR': f"{comparison_results[2].annual_return:+.1f}%",
        })
    
    # 简化版：使用 pandas dataframe
    metrics = [
        ('年化收益', [f"{r.annual_return:+.1f}%" for r in comparison_results]),
        ('月平均收益', [f"{r.monthly_return:+.2f}%" for r in comparison_results]),
        ('勝率', [f"{r.win_rate:.1f}%" for r in comparison_results]),
        ('平均獲利', [f"{r.avg_winning:+.2f}%" for r in comparison_results]),
        ('平均虧損', [f"{r.avg_losing:+.2f}%" for r in comparison_results]),
        ('盈虧比', [f"{r.profit_factor:.2f}:1" for r in comparison_results]),
        ('最大回撤', [f"{r.max_drawdown:.1f}%" for r in comparison_results]),
        ('回撤恢復天數', [f"{compute_recovery_days(r)} 天" for r in comparison_results]),
        ('夏普比率', [f"{r.sharpe_ratio:.2f}" for r in comparison_results]),
        ('信心指數', [f"{r.rank_score:.0f}/100" for r in comparison_results]),
        ('交易次數', [str(r.trades_count) for r in comparison_results]),
        ('連勝紀錄', [f"{r.win_streak} 次" for r in comparison_results]),
        ('連敗紀錄', [f"{r.loss_streak} 次" for r in comparison_results]),
        ('適用場景', ['中長線', '短線', '偏離']),
        ('參數調整難度', ['簡單', '中等', '複雜']),
        ('信號頻率', ['中等', '低', '高']),
        ('虛假信號比例', ['中等', '低', '高']),
    ]
    
    # 创建对比表格
    df_comparison = pd.DataFrame(
        [[metric[0]] + metric[1] for metric in metrics],
        columns=['指標', 'CDM', 'FZM', 'MR']
    )
    
    st.markdown("### 📊 詳細對比表格")
    
    # 使用 HTML 表格以支持更好的格式化
    html_table = create_comparison_html_table(df_comparison, comparison_results)
    st.markdown(html_table, unsafe_allow_html=True)
```

---

### E. 策略特性分析与推荐

#### 1. 最优策略分析

```python
def render_best_strategy_analysis(comparison_results):
    """渲染最优策略分析"""
    
    # 按得分排序
    sorted_results = sorted(
        comparison_results,
        key=lambda x: x.rank_score,
        reverse=True
    )
    
    best = sorted_results[0]
    second = sorted_results[1]
    worst = sorted_results[2]
    
    st.markdown("### 🎯 策略特性分析")
    
    # 最优策略详解
    st.markdown(f"""
    #### 🥇 推薦策略: {best.strategy_name} ({best.rating[0]}) - 最高評分 {best.rank_score:.1f}/100
    
    **適合人群:**
    - 風險偏好: {"◉ 高" if best.annual_return > 20 else "◉ 中" if best.annual_return > 15 else "◉ 低"}   
    - 對市場把握: {"◉ 良好" if best.win_rate > 65 else "◉ 一般"}
    
    **交易風格:**
    - {"◉ 短線" if best.trades_count > 20 else "◉ 波段" if best.trades_count > 15 else "◉ 中長線"}
    
    ---
    
    **【策略原理】**
    
    {get_strategy_description(best.strategy_name)['principle']}
    
    **【優點】**
    
    """)
    
    # 动态生成优点列表
    for advantage in get_strategy_advantages(best, comparison_results):
        st.markdown(f"✅ {advantage}")
    
    st.markdown("**【缺點】**\n")
    
    for disadvantage in get_strategy_disadvantages(best, comparison_results):
        st.markdown(f"❌ {disadvantage}")
    
    st.markdown(f"""
    **【適用場景】**
    
    """)
    
    for scenario, recommended in get_strategy_scenarios(best.strategy_name):
        status = "◉ 推薦" if recommended else "❌ 不推薦"
        st.markdown(f"• {scenario}  {status}")
    
    st.markdown(f"""
    **【參數設置】**
    
    {get_strategy_parameters(best.strategy_name)}
    
    **【最近表現】(最近 30 天)**
    
    """)
    
    recent_performance = calculate_recent_performance(best, days=30)
    st.markdown(f"""
    - 勝率: {recent_performance['win_rate']:.0f}% ({recent_performance['winning_trades']}/{recent_performance['total_trades']} 筆交易獲利)
    - 月均收益: {recent_performance['monthly_return']:+.1f}%
    - 最大單筆虧損: {recent_performance['max_loss']:+.1f}%
    """)
    
    # 备选策略
    st.markdown(f"""
    ---
    
    #### 🥈 備選策略: {second.strategy_name} - 評分 {second.rank_score:.1f}/100
    
    • 年化收益 {second.annual_return:+.1f}%，勝率 {second.win_rate:.1f}%
    • 最大回撤 {second.max_drawdown:.1f}%，風險可控
    • 適合作為補充策略使用
    
    ---
    
    #### 🥉 不推薦: {worst.strategy_name} - 評分 {worst.rank_score:.1f}/100
    
    • 年化收益 {worst.annual_return:+.1f}%，低於其他策略
    • 勝率 {worst.win_rate:.1f}%，表現不理想
    • 虛假信號多，不適合該股票特性
    """)
```

#### 2. 策略描述函数

```python
def get_strategy_description(strategy_name):
    """获取策略描述"""
    descriptions = {
        'CDM': {
            'principle': '''基於價格目標預測模型 (CDM)
            • 根據波段高低點計算目標價
            • 結合成交量變化判斷機會
            • 當偏差 < 5% 且成交量下降時買入
            • 適合中長線持倉''',
            'best_for': '保守型交易者、新手'
        },
        'FZM': {
            'principle': '''基於威廉指標 (Williams %R) 超賣反彈
            • 使用 WR 指標捕捉超賣信號
            • 結合 SMA7/14 突破判斷進場
            • 當 WR < -80% 且價格 > SMA 時買入
            • 適合短線波段交易''',
            'best_for': '激進型交易者、經驗豐富'
        },
        'MR': {
            'principle': '''基於平均線偏離率 (MR) 套利
            • 計算股價與多條均線的乖離
            • 當乖離 > 3% 時認為有套利機會
            • 當乖離恢復到正常水位時賣出
            • 適合高頻交易''',
            'best_for': '高頻交易者、量化愛好者'
        }
    }
    return descriptions.get(strategy_name, {})


def get_strategy_advantages(result, all_results):
    """获取策略优点"""
    advantages = []
    
    # 年化收益最好
    if result.annual_return == max(r.annual_return for r in all_results):
        advantages.append(f"年化收益最高 ({result.annual_return:+.1f}%)")
    
    # 胜率最高
    if result.win_rate == max(r.win_rate for r in all_results):
        advantages.append(f"勝率最高 ({result.win_rate:.1f}%)")
    
    # 回撤最小
    if result.max_drawdown == min(r.max_drawdown for r in all_results):
        advantages.append(f"最大回撤最小 ({result.max_drawdown:.1f}%)")
    
    # 交易频率适中
    if result.trades_count == min(r.trades_count for r in all_results):
        advantages.append("交易次數最少，減少手續費")
    
    # 夏普比率最优
    if result.sharpe_ratio == max(r.sharpe_ratio for r in all_results):
        advantages.append(f"風險調整收益最優 (夏普比 {result.sharpe_ratio:.2f})")
    
    return advantages


def get_strategy_disadvantages(result, all_results):
    """获取策略缺点"""
    disadvantages = []
    
    # 如果回撤较大
    if result.max_drawdown < max(r.max_drawdown for r in all_results) * 0.5:
        disadvantages.append(f"最大回撤較大 ({result.max_drawdown:.1f}%)")
    
    # 如果交易频率过高
    if result.trades_count > max(r.trades_count for r in all_results) * 0.8:
        disadvantages.append("交易次數過多，手續費負擔重")
    
    # 如果胜率不够高
    if result.win_rate < 65:
        disadvantages.append(f"勝率相對較低 ({result.win_rate:.1f}%)")
    
    return disadvantages
```

---

### F. 操作建议与一键采用

```python
def render_action_recommendations(comparison_results):
    """渲染操作建议"""
    
    best = sorted(comparison_results, key=lambda x: x.rank_score, reverse=True)[0]
    
    st.markdown("### 💡 操作建議")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        **1️⃣ 【首選】**
        
        採用 {best.strategy_name} 策略進行實盤交易
        
        年化收益: {best.annual_return:+.1f}%
        勝率: {best.win_rate:.1f}%
        """)
        
        if st.button(f"✅ 採用 {best.strategy_name}", key="adopt_best", use_container_width=True):
            st.session_state.selected_strategy = best.strategy_name
            st.session_state.selected_strategy_params = get_default_params(best.strategy_name)
            st.success(f"已採用 {best.strategy_name} 策略！")
            st.balloons()
    
    with col2:
        st.markdown("""
        **2️⃣ 【備選】**
        
        在其他信號觸發時作為補充
        
        [🔄 組合使用]
        """)
    
    with col3:
        st.markdown("""
        **3️⃣ 【風險管理】**
        
        設置止損 -3% 保護資金
        
        [🛡️ 配置止損]
        """)


def get_default_params(strategy_name):
    """获取默认参数"""
    params = {
        'CDM': {
            'threshold': 5.0,
            'tor_enabled': True,
            'sma_enabled': True
        },
        'FZM': {
            'wr_threshold': -80,
            'sma7_enabled': True,
            'sma14_enabled': True
        },
        'MR': {
            'threshold': 3.0,
            'period': 7,
            'recovery_threshold': 1.0
        }
    }
    return params.get(strategy_name, {})
```

---

## 🛠️ 技术实现细节

### 1. 策略对比引擎

```python
class StrategyComparisonEngine:
    """策略对比引擎"""
    
    def __init__(self, df, start_date, end_date, capital, commission_rate):
        self.df = df
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        self.capital = capital
        self.commission_rate = commission_rate
        
        # 过滤时间段
        self.df_period = df[(df.index >= self.start_date) & (df.index <= self.end_date)]
    
    def compare_all_strategies(self):
        """对比所有策略"""
        results = []
        
        # 对标 CDM 策略
        cdm_backtest = self._backtest_cdm()
        results.append(StrategyComparisonResult('CDM', cdm_backtest))
        
        # 对标 FZM 策略
        fzm_backtest = self._backtest_fzm()
        results.append(StrategyComparisonResult('FZM', fzm_backtest))
        
        # 对标 MR 策略
        mr_backtest = self._backtest_mr()
        results.append(StrategyComparisonResult('MR', mr_backtest))
        
        return results
    
    def _backtest_cdm(self):
        """CDM 策略回测"""
        # 使用默认优化参数
        params = {
            'cdm_threshold': 5.0,
            'tor_enabled': True,
            'sma_enabled': True,
            'sell_logic': 'profit_target',
            'profit_target': 5
        }
        engine = BacktestEngine(self.df_period, params, self.capital, self.commission_rate)
        return engine.run()
    
    def _backtest_fzm(self):
        """FZM 策略回测"""
        params = {
            'wr_threshold': -80,
            'sma7_enabled': True,
            'sma14_enabled': True,
            'sell_logic': 'profit_target',
            'profit_target': 5
        }
        engine = BacktestEngine(self.df_period, params, self.capital, self.commission_rate)
        return engine.run()
    
    def _backtest_mr(self):
        """MR 策略回测"""
        params = {
            'mr_threshold': 3.0,
            'period': 7,
            'recovery_threshold': 1.0,
            'sell_logic': 'profit_target',
            'profit_target': 5
        }
        engine = BacktestEngine(self.df_period, params, self.capital, self.commission_rate)
        return engine.run()
```

### 2. 缓存优化

```python
@st.cache_data(ttl=600)
def run_strategy_comparison_cached(symbol, start_date, end_date, capital, commission_rate):
    """缓存策略对比结果"""
    df = get_stock_data(symbol, "3y")  # 获取3年数据
    engine = StrategyComparisonEngine(df, start_date, end_date, capital, commission_rate)
    return engine.compare_all_strategies()
```

---

## 📝 主要代码改动位置

### 1. `app.py` - 单股详情页面的【历史回测】选项卡

**新增子选项卡**：
```python
with tab5:  # 历史回测选项卡
    # 创建子选项卡
    subtab1, subtab2, subtab3 = st.tabs([
        "⚙️ 回測設定",
        "📊 單策略回測",
        "🆚 策略對標"  # ← 新增
    ])
    
    with subtab3:
        render_strategy_comparison_page(df, current_code, yahoo_ticker)
```

### 2. 新增文件：`strategy_comparison.py`

包含：
- `StrategyComparisonEngine` 类
- `StrategyComparisonResult` 类
- `render_strategy_comparison_page()`
- `render_strategy_comparison_cards()`
- `plot_multi_strategy_curves()`
- `render_comparison_table()`
- `render_best_strategy_analysis()`
- 所有辅助函数

---

## ✅ 验收标准

- [ ] 【策略对标】子选项卡在【历史回测】中可见
- [ ] 时间段选择功能正常 (1Y/2Y/ALL 快捷按钮)
- [ ] 共同参数设置有效（本金、手续费、卖出逻辑统一）
- [ ] 三大策略自动对标，结果准确
- [ ] 卡片展示清晰，排名正确
- [ ] 策略收益曲线图表正常显示
- [ ] 对比表格数据完整准确
- [ ] 推荐策略分析详细有价值
- [ ] 一键采用功能正常
- [ ] 性能要求 < 15 秒 (3 个策略回测)
- [ ] 响应式设计，在各屏幕尺寸正常显示
- [ ] 风险警告信息清晰

---

## 🚀 后续优化方向

1. **动态参数调优** - 为每个策略自动找到最优参数，而不是使用默认值
2. **时间段策略切换** - 根据不同市场环境自动推荐不同策略
3. **多周期组合** - 测试日线 + 周线 + 月线的多周期组合策略
4. **市场状态识别** - 自动识别当前是牛市/熊市/震荡市，推荐对应策略
5. **策略收益稳定性** - 添加策略在不同时间段的稳定性评分
6. **实盘跟踪** - 对比策略推荐与实际收益的偏差
7. **策略融合** - 建议用户如何组合多个策略以降低风险

