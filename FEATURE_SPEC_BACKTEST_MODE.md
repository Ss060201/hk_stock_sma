# 新功能规格书：历史回测功能 (Backtest Mode)

## 🎯 功能概述

在单股详细页面（Stock Detail Page）新增 **【历史回测】** 功能，允许用户：
1. **选择历史时间段** - 指定回测周期（开始日期 + 结束日期）
2. **选择交易策略** - CDM / FZM / MR 三选一或组合
3. **查看回测结果** - 赢率、胜率、平均收益、最大回撤等关键指标
4. **优化参数** - 系统自动推荐最佳参数组合
5. **可视化展示** - 策略曲线、交易信号、盈利分析图表

---

## 📐 界面设计

### 1. 单股详情页面 - 新增【历史回测】选项卡

```
┌─ 📊 00700 ─────────────────────────────────────────────────────┐
│                                                                  │
│  [現價: 123.45] [變化: +2.3%] [開市: 122.50] [最高: 124.00]     │
│                                                                  │
│  ┌─ 標籤 ─────────────────────────────────────────────────────┐│
│  │ [📈 K線圖] [📊 SMA矩陣] [📋 數據列表] [🔙 互動模式] [🧪 歷史回測] ││
│  └────────────────────────────────────────────────────────────┘│
│                                                                  │
│  === 【🧪 歷史回測】頁籤內容 ===                                 │
│                                                                  │
│  ┌─ 回測參數設定區 ──────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  📅 時間段選擇:                                            │ │
│  │  ┌──────────────┐  ┌──────────────┐                       │ │
│  │  │ 開始日期     │  │ 結束日期     │  [⏪ 1Y] [⏪ 2Y] [⏪ ALL] ││ │
│  │  │ 2024-05-27   │  │ 2025-05-27   │                       │ │
│  │  └──────────────┘  └──────────────┘                       │ │
│  │                                                            │ │
│  │  🎲 策略選擇:                                              │ │
│  │  ☑️ CDM 策略                                               │ │
│  │  ☑️ FZM 策略 (超底)                                        │ │
│  │  ☑️ MR 策略 (偏離)                                         │ │
│  │  ☑️ 組合策略 (OR 邏輯)                                     │ │
│  │                                                            │ │
│  │  ⚙️ 進階參數:                                              │ │
│  │  CDM 偏差閾值: [___5%___] (調整範圍: 2%-10%)              │ │
│  │  MR 偏離閾值:  [___3%___] (調整範圍: 1%-8%)               │ │
│  │  FZM WR 閾值:  [__-80___] (調整範圍: -50 to -100)         │ │
│  │                                                            │ │
│  │  📈 交易邏輯:                                              │ │
│  │  ● 買入條件: 策略觸發時立即買入                           │ │
│  │  ● 賣出邏輯: ◉ 止盈 (+5% 目標)                            │ │
│  │              ○ 止損 (-3% 止損)                             │ │
│  │              ○ 時間 (5 交易日後賣出)                       │ │
│  │  交易本金: [_____10000_____] HKD                          │ │
│  │  手續費率: [______0.2______] %                            │ │
│  │                                                            │ │
│  │  [🔄 重新計算]  [📥 導入預設] [🎯 智能優化]                │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ 回測結果總覽 ─────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  總盈虧     月平均收益   年化收益    最大回撤   勝率      │ │
│  │  ┌─────┐  ┌─────────┐  ┌────────┐  ┌────────┐  ┌─────┐ │ │
│  │  │+18% │  │  +2.3%  │  │ +27.4% │  │ -8.5%  │  │ 65% │ │ │
│  │  └─────┘  └─────────┘  └────────┘  └────────┘  └─────┘ │ │
│  │   🟢      🟢 優秀      🟢 優秀      🟠 中等      🟠 中等  │ │
│  │                                                            │ │
│  │  ┌─────────────────────────────────────────────────────┐ │ │
│  │  │ 總交易次數: 24  |  勝利次數: 15  |  失敗次數: 9    │ │ │
│  │  │ 平均獲利: +2.1% | 平均虧損: -1.8% | 盈虧比: 1.17:1 │ │ │
│  │  │ 連勝紀錄: 5 次  | 連敗紀錄: 3 次  | 信心指數: ⭐⭐⭐⭐ │ │ │
│  │  └─────────────────────────────────────────────────────┘ │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ 策略曲線與交易信號 ──────────────────────────────────────┐ │
│  │                                                          │ │
│  │  📈 策略累積收益曲線 (vs 買入持有)                       │ │
│  │                                                          │ │
│  │   $12000 ┤                      ╱╲ ╱╲╱╲                │ │
│  │   $11000 ┤  ╱╲╱╲╱╲╱╲╱╲        ╱  ╲╱  ╲╱╲╱              │ │
│  │   $10000 ┤╱╲╱      ╲╱╲╱╲╱╲╱╲╱╲                       │ │
│  │   $9000  ┤                                              │ │
│  │          └────────────────────────────────────────────│ │
│  │          2024-05    2024-08    2024-11   2025-02     │ │
│  │                                                          │ │
│  │  ── CDM 策略  ── FZM 策略  ── MR 策略  ── 買入持有      │ │
│  │                                                          │ │
│  │  🔴 買入信號  ⬆️ 買入點  📊 交易詳情 (展開)             │ │
│  │                                                          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ 詳細交易列表 ─────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  序號 │ 日期      │ 操作 │ 買入價 │ 賣出價 │ 收益% │ 原因    │ │
│  │  ───┼──────────┼────┼────────┼────────┼────────┼──────  │ │
│  │   1 │2024-06-10│ 買 │ 120.50 │ 125.60 │ +4.2% │ CDM觸發 │ │
│  │   2 │2024-06-25│ 買 │ 118.30 │ 115.50 │ -2.4% │ FZM觸發 │ │
│  │   3 │2024-07-05│ 買 │ 122.00 │ 128.50 │ +5.3% │ MR觸發  │ │
│  │  ... │   ...    │ ... │  ...   │  ...   │  ...  │ ...    │ │
│  │                                                            │ │
│  │  [🔍 查看全部]  [📊 統計分析]  [📥 導出CSV]                │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ 參數優化分析 ─────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  🎯 智能推薦: 最佳參數組合                                 │ │
│  │                                                            │ │
│  │  ┌─ 參數組合1 (推薦) ───────────────────────────────────┐ │ │
│  │  │ CDM偏差: 4% | MR偏離: 2.5% | 勝率: 68% | 收益: +22% │ │ │
│  │  │ 評分: 9.2/10 🌟                                      │ │ │
│  │  └──────────────────────────────────────────────────────┘ │ │
│  │                                                            │ │
│  │  ┌─ 參數組合2 ───────────────────────────────────────────┐ │ │
│  │  │ CDM偏差: 5% | MR偏離: 3% | 勝率: 65% | 收益: +18%   │ │ │
│  │  │ 評分: 8.7/10                                         │ │ │
│  │  └──────────────────────────────────────────────────────┘ │ │
│  │                                                            │ │
│  │  ┌─ 參數組合3 ───────────────────────────────────────────┐ │ │
│  │  │ CDM偏差: 6% | MR偏離: 4% | 勝率: 62% | 收益: +15%   │ │ │
│  │  │ 評分: 8.1/10                                         │ │ │
│  │  └──────────────────────────────────────────────────────┘ │ │
│  │                                                            │ │
│  │  [📊 熱力圖分析]  [🔄 遍歷所有組合]  [💾 保存最佳組合]     │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ 風險分析面板 ─────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  最大回撤: -8.5%  |  回撤恢復天數: 12天                    │ │
│  │  最大連敗: 3 次   |  連敗最大虧損: -4.2%                   │ │
│  │  勝敗比:   1.17:1 |  夏普比率: 1.34                        │ │
│  │  信心指數: ⭐⭐⭐⭐ |  推薦度: 🟢 可交易                    │ │
│  │                                                            │ │
│  │  💡 風險提示:                                              │ │
│  │  • 回測數據基於歷史，不代表未來表現                       │ │
│  │  • 實際交易需考慮滑點和流動性                             │ │
│  │  • 建議先小額驗證策略                                     │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🔧 核心功能详细规格

### A. 回测参数设定区

#### 1. 时间段选择

```python
# UI 设计
col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 0.8, 0.8, 0.8])

with col1:
    start_date = st.date_input(
        "開始日期",
        value=df.index.min().date() if len(df) else datetime.now().date(),
        min_value=df.index.min().date() if len(df) else None
    )

with col2:
    end_date = st.date_input(
        "結束日期",
        value=df.index.max().date() if len(df) else datetime.now().date(),
        min_value=start_date
    )

with col3:
    if st.button("⏪ 1Y", use_container_width=True):
        end_date = df.index.max().date()
        start_date = (pd.to_datetime(end_date) - timedelta(days=365)).date()

with col4:
    if st.button("⏪ 2Y", use_container_width=True):
        end_date = df.index.max().date()
        start_date = (pd.to_datetime(end_date) - timedelta(days=730)).date()

with col5:
    if st.button("⏪ ALL", use_container_width=True):
        start_date = df.index.min().date()
        end_date = df.index.max().date()
```

**时间段要求**：
- 最少数据点: 50 个交易日 (约3个月)
- 最多回测周期: 5 年 (建议)
- 支持任意时间范围

#### 2. 策略选择

```python
st.markdown("**🎲 策略選擇:**")
col1, col2, col3, col4 = st.columns(4)

with col1:
    use_cdm = st.checkbox("CDM 策略", value=True)
with col2:
    use_fzm = st.checkbox("FZM 策略", value=True)
with col3:
    use_mr = st.checkbox("MR 策略", value=True)
with col4:
    use_combined = st.checkbox("組合策略", value=False)

# 当使用组合策略时，设置逻辑
if use_combined:
    combine_logic = st.radio(
        "組合邏輯",
        ["任意一個觸發 (OR)", "同時觸發 (AND)", "加權評分"]
    )
```

**策略说明**：

| 策略 | 触发条件 | 信号性质 |
|------|--------|--------|
| **CDM** | 目标价偏差 < 5% AND TOR 条件 AND SMA 接近 | 中长线 |
| **FZM** | 价格 > SMA7/14 AND Williams %R < -80% | 短线超底 |
| **MR** | \|AvgP MR%\| > 3% (可调) | 均线偏离 |
| **组合** | 至少一个策略触发 (可选加权) | 综合 |

#### 3. 进阶参数设置

```python
st.markdown("**⚙️ 進階參數:**")

col1, col2, col3 = st.columns(3)

with col1:
    cdm_threshold = st.slider(
        "CDM 偏差閾值 (%)",
        min_value=2,
        max_value=10,
        value=5,
        step=0.5,
        help="CDM 觸發的最大偏差百分比"
    )

with col2:
    mr_threshold = st.slider(
        "MR 偏離閾值 (%)",
        min_value=1,
        max_value=8,
        value=3,
        step=0.5,
        help="MR 策略的觸發偏離閾值"
    )

with col3:
    wr_threshold = st.slider(
        "FZM WR 閾值",
        min_value=-100,
        max_value=-50,
        value=-80,
        step=5,
        help="Williams %R 觸發的閾值 (負數)"
    )
```

#### 4. 交易逻辑配置

```python
st.markdown("**📈 交易邏輯:**")

col1, col2 = st.columns(2)

with col1:
    st.write("**買入條件:**")
    st.caption("✅ 當策略觸發時立即買入")
    
    st.write("**賣出邏輯:**")
    sell_logic = st.radio(
        "選擇賣出條件",
        [
            "🎯 止盈 (+5% 目標)",
            "🛑 止損 (-3% 止損)",
            "⏱️ 時間 (5 交易日)",
            "🔄 策略反轉信號"
        ]
    )

with col2:
    capital = st.number_input(
        "交易本金 (HKD)",
        min_value=1000,
        max_value=1000000,
        value=10000,
        step=1000,
        help="每筆交易的本金"
    )
    
    commission_rate = st.number_input(
        "手續費率 (%)",
        min_value=0.0,
        max_value=1.0,
        value=0.2,
        step=0.05,
        help="每筆交易的手續費百分比"
    )

# 解析卖出逻辑
sell_config = {
    "🎯 止盈 (+5% 目標)": {"type": "profit_target", "value": 5},
    "🛑 止損 (-3% 止損)": {"type": "stop_loss", "value": -3},
    "⏱️ 時間 (5 交易日)": {"type": "time_based", "value": 5},
    "🔄 策略反轉信號": {"type": "signal_reverse", "value": None}
}[sell_logic]
```

#### 5. 操作按钮

```python
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🔄 重新計算", type="primary", use_container_width=True):
        run_backtest = True

with col2:
    if st.button("📥 導入預設", use_container_width=True):
        # 导入预设参数
        st.session_state.backtest_params = load_preset_params(current_code)

with col3:
    if st.button("🎯 智能優化", use_container_width=True):
        # 启动参数优化
        st.session_state.run_optimization = True
```

---

### B. 回测结果总览

#### 1. 关键指标计算

```python
class BacktestResults:
    """回测结果数据类"""
    
    def __init__(self, trades):
        self.trades = trades  # List of trade records
        
    @property
    def total_return(self):
        """总收益率"""
        if not self.trades:
            return 0.0
        final_pnl = sum(t['pnl'] for t in self.trades)
        return (final_pnl / (len(self.trades) * capital)) * 100
    
    @property
    def win_rate(self):
        """赢率（百分比）"""
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        return (len(winning_trades) / len(self.trades) * 100) if self.trades else 0.0
    
    @property
    def monthly_avg_return(self):
        """月平均收益"""
        if not self.trades:
            return 0.0
        months = (trades[-1]['date'] - trades[0]['date']).days / 30
        return self.total_return / months if months > 0 else 0.0
    
    @property
    def annualized_return(self):
        """年化收益"""
        if not self.trades:
            return 0.0
        days = (trades[-1]['date'] - trades[0]['date']).days
        years = days / 365.25
        return (self.total_return * (365.25 / days)) if days > 0 else 0.0
    
    @property
    def max_drawdown(self):
        """最大回撤"""
        if not self.trades:
            return 0.0
        cumulative_pnl = [sum(t['pnl'] for t in self.trades[:i+1]) for i in range(len(self.trades))]
        running_max = [max(cumulative_pnl[:i+1]) for i in range(len(cumulative_pnl))]
        drawdowns = [(running_max[i] - cumulative_pnl[i]) / running_max[i] * 100 for i in range(len(cumulative_pnl))]
        return max(drawdowns) if drawdowns else 0.0
    
    @property
    def profit_factor(self):
        """盈亏比"""
        winning_sum = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        losing_sum = abs(sum(t['pnl'] for t in self.trades if t['pnl'] < 0))
        return (winning_sum / losing_sum) if losing_sum > 0 else float('inf')
    
    @property
    def avg_winning_trade(self):
        """平均获利"""
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        return (sum(t['pnl'] for t in winning_trades) / len(winning_trades)) if winning_trades else 0.0
    
    @property
    def avg_losing_trade(self):
        """平均亏损"""
        losing_trades = [t for t in self.trades if t['pnl'] < 0]
        return (sum(t['pnl'] for t in losing_trades) / len(losing_trades)) if losing_trades else 0.0
    
    @property
    def win_streak(self):
        """连胜纪录"""
        max_streak = 0
        current_streak = 0
        for trade in self.trades:
            if trade['pnl'] > 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak
    
    @property
    def loss_streak(self):
        """连败纪录"""
        max_streak = 0
        current_streak = 0
        for trade in self.trades:
            if trade['pnl'] < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak
    
    @property
    def sharpe_ratio(self):
        """夏普比率"""
        daily_returns = []
        for i in range(1, len(self.trades)):
            daily_pnl = sum(t['pnl'] for t in self.trades[:i+1]) - sum(t['pnl'] for t in self.trades[:i])
            daily_returns.append(daily_pnl)
        
        if len(daily_returns) < 2:
            return 0.0
        
        mean_return = np.mean(daily_returns)
        std_return = np.std(daily_returns)
        return (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0
    
    def confidence_score(self):
        """信心指数 (0-100)"""
        score = (
            min(self.win_rate, 100) * 0.3 +          # 赢率权重 30%
            min(self.annualized_return / 2, 100) * 0.3 +  # 收益权重 30%
            (100 - min(self.max_drawdown * 5, 100)) * 0.2 +  # 回撤权重 20%
            min(self.sharpe_ratio * 10, 100) * 0.2    # 夏普比率权重 20%
        )
        return min(max(score, 0), 100)
```

#### 2. 结果展示卡片

```python
def render_backtest_results(results):
    """渲染回测结果总览卡片"""
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    # 总盈虧
    with col1:
        total_ret = results.total_return
        color = "🟢" if total_ret > 0 else "🔴"
        st.metric(
            "總盈虧",
            f"{total_ret:+.1f}%",
            delta=color,
            delta_color="normal"
        )
    
    # 月平均收益
    with col2:
        monthly = results.monthly_avg_return
        color = "🟢" if monthly > 0 else "🔴"
        st.metric(
            "月平均收益",
            f"{monthly:+.2f}%",
            delta=color,
            delta_color="normal"
        )
    
    # 年化收益
    with col3:
        annual = results.annualized_return
        color = "🟢" if annual > 10 else "🟠" if annual > 0 else "🔴"
        st.metric(
            "年化收益",
            f"{annual:+.1f}%",
            delta=color,
            delta_color="normal"
        )
    
    # 最大回撤
    with col4:
        mdd = results.max_drawdown
        color = "🟢" if mdd < 5 else "🟠" if mdd < 10 else "🔴"
        st.metric(
            "最大回撤",
            f"{mdd:.1f}%",
            delta=color,
            delta_color="inverse"
        )
    
    # 勝率
    with col5:
        wr = results.win_rate
        color = "🟢" if wr > 60 else "🟠" if wr > 50 else "🔴"
        st.metric(
            "勝率",
            f"{wr:.1f}%",
            delta=color,
            delta_color="normal"
        )
    
    # 详细统计
    st.divider()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        **交易統計**
        - 總交易次數: {len(results.trades)}
        - 勝利次數: {sum(1 for t in results.trades if t['pnl'] > 0)}
        - 失敗次數: {sum(1 for t in results.trades if t['pnl'] < 0)}
        """)
    
    with col2:
        st.markdown(f"""
        **收益分析**
        - 平均獲利: {results.avg_winning_trade:+.2f}%
        - 平均虧損: {results.avg_losing_trade:+.2f}%
        - 盈虧比: {results.profit_factor:.2f}:1
        """)
    
    with col3:
        confidence = results.confidence_score()
        stars = "⭐" * int(confidence / 25)
        st.markdown(f"""
        **風險評估**
        - 連勝紀錄: {results.win_streak} 次
        - 連敗紀錄: {results.loss_streak} 次
        - 信心指數: {stars} ({confidence:.0f}/100)
        """)
```

---

### C. 策略曲线与交易信号

#### 1. 累积收益曲线

```python
def plot_strategy_curve(df, trades, sell_config):
    """绘制策略累积收益曲线"""
    
    fig = go.Figure()
    
    # 计算累积收益
    cumulative_pnl = []
    cumulative_sum = 0
    for trade in trades:
        cumulative_sum += trade['pnl']
        cumulative_pnl.append(cumulative_sum)
    
    trade_dates = [trade['exit_date'] for trade in trades]
    
    # 策略收益曲线
    fig.add_trace(go.Scatter(
        x=trade_dates,
        y=cumulative_pnl,
        mode='lines+markers',
        name='策略收益',
        line=dict(color='#1f77b4', width=2),
        marker=dict(size=6)
    ))
    
    # 买入持有基准线
    buy_hold_pnl = [(df.loc[trade['entry_date'], 'Close'] - df.loc[trade['entry_date'], 'Close']) 
                    + (df.loc[trade['exit_date'], 'Close'] - df.loc[trade['entry_date'], 'Close']) 
                    for trade in trades]
    cumulative_buy_hold = np.cumsum(buy_hold_pnl)
    
    fig.add_trace(go.Scatter(
        x=trade_dates,
        y=cumulative_buy_hold,
        mode='lines',
        name='買入持有',
        line=dict(color='#ff7f0e', width=1, dash='dash')
    ))
    
    # 标记买入点
    entry_dates = [trade['entry_date'] for trade in trades]
    entry_prices = [df.loc[trade['entry_date'], 'Close'] for trade in trades]
    
    fig.add_trace(go.Scatter(
        x=entry_dates,
        y=[0] * len(entry_dates),
        mode='markers',
        name='買入點',
        marker=dict(symbol='triangle-up', color='green', size=10)
    ))
    
    fig.update_layout(
        title=f"策略累積收益曲線 (vs 買入持有)",
        xaxis_title="日期",
        yaxis_title="累積收益 (%)",
        height=400,
        template="plotly_white",
        hovermode='x unified'
    )
    
    return fig
```

#### 2. 交易信号可视化

```python
def plot_trading_signals(df, trades):
    """绘制 K 线 + 交易信号"""
    
    fig = go.Figure()
    
    # K 线图
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        name='K線'
    ))
    
    # 买入信号
    for trade in trades:
        entry_date = trade['entry_date']
        entry_price = trade['entry_price']
        
        fig.add_trace(go.Scatter(
            x=[entry_date],
            y=[entry_price],
            mode='markers',
            marker=dict(
                symbol='triangle-up',
                color='green',
                size=15,
                line=dict(width=2)
            ),
            name='買入信號',
            showlegend=False
        ))
        
        # 买入原因注释
        fig.add_annotation(
            x=entry_date,
            y=entry_price,
            text=f"買 ({trade['signal_type']})",
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=2,
            arrowcolor="green",
            ax=0,
            ay=-30,
            bgcolor="rgba(0,255,0,0.3)",
            font=dict(color="darkgreen")
        )
    
    # 卖出信号
    for trade in trades:
        exit_date = trade['exit_date']
        exit_price = trade['exit_price']
        
        fig.add_trace(go.Scatter(
            x=[exit_date],
            y=[exit_price],
            mode='markers',
            marker=dict(
                symbol='triangle-down',
                color='red',
                size=15,
                line=dict(width=2)
            ),
            name='賣出信號',
            showlegend=False
        ))
    
    fig.update_layout(
        title="K線圖 + 交易信號",
        yaxis_title="股價",
        height=500,
        template="plotly_white",
        xaxis_rangeslider_visible=False
    )
    
    return fig
```

---

### D. 详细交易列表

#### 1. 交易记录表格

```python
def render_trade_details(trades):
    """渲染详细交易列表"""
    
    trade_data = []
    for i, trade in enumerate(trades, 1):
        pnl_pct = ((trade['exit_price'] - trade['entry_price']) / trade['entry_price'] * 100)
        
        trade_data.append({
            '序號': i,
            '日期': trade['entry_date'].strftime('%Y-%m-%d'),
            '操作': '買',
            '買入價': f"{trade['entry_price']:.2f}",
            '賣出價': f"{trade['exit_price']:.2f}",
            '收益%': f"{pnl_pct:+.2f}%",
            '原因': trade['signal_type'],
            '交易時長': f"{(trade['exit_date'] - trade['entry_date']).days}天",
            '盈虧': '✅ 獲利' if pnl_pct > 0 else '❌ 虧損'
        })
    
    df_trades = pd.DataFrame(trade_data)
    
    st.dataframe(
        df_trades,
        use_container_width=True,
        hide_index=True,
        column_config={
            '收益%': st.column_config.TextColumn(
                help="交易收益百分比"
            ),
            '盈虧': st.column_config.TextColumn(
                help="交易結果"
            )
        }
    )
    
    # 导出选项
    col1, col2, col3 = st.columns(3)
    
    with col1:
        csv = df_trades.to_csv(index=False)
        st.download_button(
            label="📥 導出 CSV",
            data=csv,
            file_name=f"交易明細_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    
    with col2:
        st.button("🔍 查看全部")
    
    with col3:
        st.button("📊 統計分析")
```

---

### E. 参数优化分析

#### 1. 智能推荐参数

```python
def recommend_optimal_params(df, backtest_func):
    """智能推荐最佳参数组合"""
    
    # 定义参数搜索空间
    cdm_thresholds = [3, 4, 5, 6, 7]
    mr_thresholds = [1.5, 2, 2.5, 3, 3.5, 4]
    wr_thresholds = [-70, -75, -80, -85, -90]
    
    best_results = []
    
    # 网格搜索
    for cdm in cdm_thresholds:
        for mr in mr_thresholds:
            for wr in wr_thresholds:
                params = {
                    'cdm_threshold': cdm,
                    'mr_threshold': mr,
                    'wr_threshold': wr
                }
                
                results = backtest_func(df, params)
                
                # 计算综合评分
                score = (
                    results.win_rate * 0.3 +
                    min(results.annualized_return / 2, 100) * 0.3 +
                    (100 - min(results.max_drawdown * 5, 100)) * 0.2 +
                    min(results.sharpe_ratio * 10, 100) * 0.2
                )
                
                best_results.append({
                    'params': params,
                    'results': results,
                    'score': score
                })
    
    # 排序并返回前3个
    best_results.sort(key=lambda x: x['score'], reverse=True)
    return best_results[:3]


def render_parameter_optimization(best_params):
    """渲染参数优化结果"""
    
    st.markdown("### 🎯 智能推薦: 最佳參數組合")
    
    for rank, item in enumerate(best_params, 1):
        params = item['params']
        results = item['results']
        score = item['score']
        
        # 推荐标签
        if rank == 1:
            badge = "🌟 推薦 (最優)"
            color = "#28a745"
        elif rank == 2:
            badge = "⭐ 推薦"
            color = "#ffc107"
        else:
            badge = "可選"
            color = "#6c757d"
        
        with st.container():
            col1, col2 = st.columns([0.7, 0.3])
            
            with col1:
                st.markdown(f"""
                <div style="border: 2px solid {color}; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <h4 style="color: {color}; margin-top: 0;">參數組合{rank} {badge}</h4>
                
                **CDM偏差**: {params['cdm_threshold']}% | 
                **MR偏離**: {params['mr_threshold']}% | 
                **WR閾值**: {params['wr_threshold']}
                
                **回測結果:**
                - 勝率: {results.win_rate:.1f}%
                - 收益: {results.annualized_return:+.1f}%
                - 回撤: {results.max_drawdown:.1f}%
                - 夏普比: {results.sharpe_ratio:.2f}
                
                **評分: {score:.1f}/100** {'⭐' * int(score / 25)}
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                if rank == 1:
                    if st.button("✅ 採用最優", key=f"use_param_{rank}"):
                        st.session_state.selected_params = params
                        st.success("已采用最优参数！")
```

#### 2. 热力图分析

```python
def plot_heatmap_analysis(optimization_results):
    """绘制参数组合热力图"""
    
    # 准备数据
    cdm_vals = sorted(set(r['params']['cdm_threshold'] for r in optimization_results))
    mr_vals = sorted(set(r['params']['mr_threshold'] for r in optimization_results))
    
    # 创建矩阵
    heatmap_data = np.zeros((len(mr_vals), len(cdm_vals)))
    
    for result in optimization_results:
        cdm_idx = cdm_vals.index(result['params']['cdm_threshold'])
        mr_idx = mr_vals.index(result['params']['mr_threshold'])
        heatmap_data[mr_idx][cdm_idx] = result['results'].win_rate
    
    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data,
        x=cdm_vals,
        y=mr_vals,
        colorscale='RdYlGn',
        colorbar=dict(title="勝率 (%)")
    ))
    
    fig.update_layout(
        title="參數組合勝率熱力圖",
        xaxis_title="CDM 偏差閾值 (%)",
        yaxis_title="MR 偏離閾值 (%)",
        height=400
    )
    
    return fig
```

---

### F. 风险分析面板

```python
def render_risk_analysis(results):
    """渲染风险分析面板"""
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("最大回撤", f"{results.max_drawdown:.1f}%", 
                 help="从历史高点跌到最低的百分比")
    
    with col2:
        # 计算回撤恢复天数
        recovery_days = 0  # 简化版，实际需要计算
        st.metric("回撤恢復天數", f"{recovery_days} 天",
                 help="从最大回撤恢复到前高所需交易日数")
    
    with col3:
        st.metric("連敗最大虧損", f"{results.avg_losing_trade * results.loss_streak:.1f}%",
                 help="连续失败交易的最大累计亏损")
    
    with col4:
        st.metric("夏普比率", f"{results.sharpe_ratio:.2f}",
                 help="风险调整后的收益指标")
    
    st.divider()
    
    # 风险警告
    confidence = results.confidence_score()
    if confidence < 50:
        st.warning("""
        ⚠️ **風險提示:**
        - 此策略的回測表現欠佳，建議不交易
        - 歷史數據無法保證未來表現
        """)
    elif confidence < 70:
        st.info("""
        ℹ️ **風險提示:**
        - 回測表現一般，建議先小額驗證
        - 實際交易需考慮滑點和流動性
        - 監控最大回撤警告線
        """)
    else:
        st.success("""
        ✅ **可交易提示:**
        - 回測表現較好，可考慮交易
        - 建議從小額開始驗證策略
        - 設置止損單保護資金
        """)
```

---

## 🛠️ 技术实现细节

### 1. 回测引擎

```python
class BacktestEngine:
    """完整的回测引擎"""
    
    def __init__(self, df, params, capital=10000, commission_rate=0.2):
        self.df = df
        self.params = params
        self.capital = capital
        self.commission_rate = commission_rate
        self.trades = []
        self.position = None
    
    def run(self):
        """执行回测"""
        
        for date_idx in range(len(self.df)):
            current_date = self.df.index[date_idx]
            current_row = self.df.iloc[date_idx]
            
            # 检查买入信号
            if not self.position:
                if self._check_buy_signal(date_idx):
                    self._open_position(date_idx)
            
            # 检查卖出信号
            else:
                if self._check_sell_signal(date_idx):
                    self._close_position(date_idx)
        
        return BacktestResults(self.trades)
    
    def _check_buy_signal(self, date_idx):
        """检查是否触发买入信号"""
        
        current_row = self.df.iloc[date_idx]
        
        cdm_signal = self._check_cdm_signal(date_idx)
        fzm_signal = self._check_fzm_signal(date_idx)
        mr_signal = self._check_mr_signal(date_idx)
        
        # 根据组合逻辑判断
        if self.params.get('use_combined'):
            return cdm_signal or fzm_signal or mr_signal
        else:
            signals = []
            if self.params.get('use_cdm'):
                signals.append(cdm_signal)
            if self.params.get('use_fzm'):
                signals.append(fzm_signal)
            if self.params.get('use_mr'):
                signals.append(mr_signal)
            return any(signals)
    
    def _open_position(self, date_idx):
        """开仓"""
        entry_price = self.df['Close'].iloc[date_idx]
        self.position = {
            'entry_date': self.df.index[date_idx],
            'entry_price': entry_price,
            'signal_type': self._get_signal_type(date_idx),
            'date_idx': date_idx
        }
    
    def _close_position(self, date_idx):
        """平仓"""
        exit_price = self.df['Close'].iloc[date_idx]
        pnl = (exit_price - self.position['entry_price']) / self.position['entry_price'] * 100
        
        self.position['exit_date'] = self.df.index[date_idx]
        self.position['exit_price'] = exit_price
        self.position['pnl'] = pnl
        
        self.trades.append(self.position)
        self.position = None
    
    def _check_cdm_signal(self, date_idx):
        """检查 CDM 信号"""
        # 简化版实现
        return False
    
    def _check_fzm_signal(self, date_idx):
        """检查 FZM 信号"""
        # 简化版实现
        return False
    
    def _check_mr_signal(self, date_idx):
        """检查 MR 信号"""
        # 简化版实现
        return False
```

### 2. 缓存优化

```python
@st.cache_data(ttl=600)
def run_backtest_cached(symbol, start_date, end_date, params):
    """缓存回测结果"""
    df = get_stock_data(symbol, start_date, end_date)
    engine = BacktestEngine(df, params)
    return engine.run()
```

---

## 📝 主要代码改动位置

### 1. `app.py` - 单股详情页面 (第 500+ 行)

**新增选项卡**：
```python
# 在现有的 "K線圖", "SMA矩陣" 等选项卡之后添加
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 K線圖",
    "📊 SMA矩陣", 
    "📋 數據列表",
    "🔙 互動模式",
    "🧪 歷史回測"  # ← 新增
])

with tab5:
    render_backtest_page(df, current_code, yahoo_ticker)
```

### 2. 新增文件：`backtest_engine.py`

包含：
- `BacktestEngine` 类
- `BacktestResults` 类
- 所有回测相关函数

### 3. 新增文件：`backtest_ui.py`

包含：
- `render_backtest_page()`
- `render_parameter_settings()`
- `render_backtest_results()`
- `render_trade_details()`
- `render_risk_analysis()`
- 所有可视化函数

---

## ✅ 验收标准

- [ ] 【历史回测】选项卡在单股页面可见
- [ ] 时间段选择功能正常 (1Y/2Y/ALL 快捷按钮)
- [ ] 支持选择多个策略 (CDM/FZM/MR)
- [ ] 参数滑块能调整阈值
- [ ] 回测计算正确 (验证计算公式)
- [ ] 回测结果展示完整 (所有 KPI 都显示)
- [ ] 策略曲线图表正常
- [ ] 交易列表详情完整
- [ ] 参数优化推荐有效
- [ ] 热力图能正确展示参数组合效果
- [ ] 风险分析面板有意义
- [ ] 回测耗时 < 10 秒 (性能要求)
- [ ] 数据导出功能正常

---

## 🚀 后续优化方向

1. **实时监控** - 自动监控实时信号，与历史回测对比
2. **蒙特卡洛分析** - 模拟未来 1000 次可能的市场走势
3. **参数稳定性分析** - 测试参数在不同时间段的表现
4. **多周期合成** - 支持多个时间框架的组合策略
5. **机器学习优化** - 用 ML 算法找最优参数
6. **风险管理方案** - 自动生成仓位大小和止损建议
7. **策略对标** - 与基准指数进行统计显著性检验

