"""
app.py 移动端优化 - 修改方案
===================================
参考 AAStocks iPhone 设计 + mobile_optimizer.py
完全重新设计手机端用户体验
"""

# ========== 关键改动列表 ==========

# [改动1] 第 1-14 行: 导入和页面初始化
"""
原代码:
    import streamlit as st
    ...
    st.set_page_config(page_title="港股 SMA 矩陣 v9.7 (整合版)", page_icon="📈", layout="wide")

改为:
"""
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os

# 导入移动端优化工具
from mobile_optimizer import (
    setup_page, 
    action_buttons, 
    responsive_cols, 
    responsive_table,
    responsive_chart,
    init_mobile_optimizer
)

# 页面初始化 (替代 st.set_page_config)
setup_page(
    title="港股 SMA 矩陣 v9.7",
    icon="📈",
    layout="auto",  # 自动根据设备选择
    initial_sidebar_state="auto"  # 手机自动折叠侧边栏
)

optimizer = init_mobile_optimizer()
is_mobile = st.session_state.get('is_mobile', False)


# ========== [改动2] CSS 样式 + 移动端优化 ==========
"""
保留原来的 CSS，但补充移动端卡片样式
第 16-76 行的 st.markdown(""" ... """) 保持不变,
只补充底部导航栏的 CSS
"""

# 补充移动端导航栏 CSS
if is_mobile:
    st.markdown("""
    <style>
    /* 底部导航栏样式 */
    .bottom-nav {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        height: 60px;
        background-color: #f8f9fa;
        border-top: 1px solid #dee2e6;
        display: flex;
        justify-content: space-around;
        align-items: center;
        z-index: 1000;
        padding-bottom: 10px;
    }
    
    .bottom-nav-item {
        flex: 1;
        text-align: center;
        cursor: pointer;
        padding: 8px 0;
    }
    
    /* 给 main content 加下边距，为底部导航留空 */
    .main {
        padding-bottom: 80px !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ========== [改动3] Firebase 和辅助函数保持不变 ==========
# 第 78-210 行的所有函数保持不变


# ========== [改动4] Session State 初始化 ==========
"""
第 305-309 行, 添加移动端相关 state
"""
if 'ref_date' not in st.session_state:
    st.session_state.ref_date = datetime.now().date()
if 'current_view' not in st.session_state:
    st.session_state.current_view = ""
if 'mobile_current_tab' not in st.session_state:  # 新增: 手机版当前 tab
    st.session_state.mobile_current_tab = "home"
if 'is_mobile' not in st.session_state:  # 新增: 移动端模式
    st.session_state.is_mobile = False


# ========== [改动5] 侧边栏重构 (第 311-387 行) ==========
"""
新逻辑:
- 手机: 完全隐藏侧边栏，功能移到主页面顶部
- 桌面: 保持原来的侧边栏
"""

# 仅在桌面端显示侧边栏
if not is_mobile:
    # ===== 原来的侧边栏代码 (保持不变) =====
    with st.sidebar:
        st.header("HK Stock Analysis")
        
        # Telegram 设定 (保持原代码)
        with st.expander("✈️ Telegram 設定", expanded=False):
            def_token = st.secrets["telegram"]["token"] if "telegram" in st.secrets else ""
            def_chat_id = st.secrets["telegram"]["chat_id"] if "telegram" in st.secrets else ""
            tg_token = st.text_input("Bot Token", value=def_token, type="password")
            tg_chat_id = st.text_input("Chat ID", value=def_chat_id)
            
            if st.button("🚀 發送單股報告", type="primary"):
                # ... 原来的逻辑保持不变
                pass
        
        st.divider()
        
        # 日期选择
        new_date = st.date_input("基準日期", value=st.session_state.ref_date)
        if new_date != st.session_state.ref_date:
            st.session_state.ref_date = new_date
            st.rerun()
        
        # 搜索栏
        search_input = st.text_input("輸入股票代號", placeholder="例如: 700", key="search_bar")
        if search_input:
            cleaned = clean_ticker_input(search_input)
            if cleaned: st.session_state.current_view = cleaned
        
        st.divider()
        
        # 收藏夹导航
        watchlist_data = get_watchlist_from_db()
        watchlist_list = list(watchlist_data.keys()) if watchlist_data else []
        
        st.subheader(f"我的收藏 ({len(watchlist_list)})")
        if watchlist_list:
            for ticker in watchlist_list:
                if st.button(ticker, key=f"nav_{ticker}", use_container_width=True):
                    st.session_state.current_view = ticker
        else:
            st.caption("暫無收藏")
        
        st.divider()
        if st.button("🏠 回到總覽 (Overview)", use_container_width=True):
            st.session_state.current_view = ""
            st.rerun()
        
        st.divider()
        sma1 = st.number_input("SMA 1", value=20)
        sma2 = st.number_input("SMA 2", value=50)
else:
    # ===== 手机端: 顶部快捷栏 =====
    st.markdown("### 📊 港股 SMA 矩陣 - 收藏總覽")
    
    # 日期选择器 (紧凑)
    col1, col2 = st.columns([3, 1])
    with col1:
        new_date = st.date_input("基準日期", value=st.session_state.ref_date, label_visibility="collapsed")
    with col2:
        st.caption(f"📅 {new_date.strftime('%m-%d')}")
    
    if new_date != st.session_state.ref_date:
        st.session_state.ref_date = new_date
        st.rerun()
    
    # 搜索栏
    search_input = st.text_input("🔍 股票代號", placeholder="例: 700", key="search_bar_mobile")
    if search_input:
        cleaned = clean_ticker_input(search_input)
        if cleaned: 
            st.session_state.current_view = cleaned
            st.rerun()
    
    # SMA 参数 (简洁显示)
    col1, col2 = st.columns(2)
    with col1:
        sma1 = st.number_input("SMA 1", value=20, label_visibility="collapsed")
    with col2:
        sma2 = st.number_input("SMA 2", value=50, label_visibility="collapsed")


# 获取收藏夹数据
watchlist_data = get_watchlist_from_db()
watchlist_list = list(watchlist_data.keys()) if watchlist_data else []


# ========== [改动6] 主程序逻辑 (第 388-515 行) ==========
"""
总体结构保持不变，但修改表格/按钮渲染方式
"""

current_code = st.session_state.current_view
ref_date_str = st.session_state.ref_date.strftime('%Y-%m-%d')


# === 模式 A: 总覽模式 (第 392-499 行) ===
if not current_code:
    st.title("📊 港股 SMA 矩陣 - 收藏總覽")
    
    if not watchlist_list:
        st.info("👈 您的收藏清單為空，請從左側加入股票。")
    else:
        # ===== [改动6.1] 顶部按钮栏 - 使用响应式按钮 =====
        buttons = [
            {"label": "🔄 刷新", "key": "refresh"},
            {"label": "📊 比較", "key": "compare", "type": "primary"},
        ]
        
        clicked = action_buttons(buttons, layout="auto")
        
        if clicked == "refresh":
            st.cache_clear()
            st.rerun()
        elif clicked == "compare":
            st.session_state.comparison_mode = True
            st.rerun()
        
        st.divider()
        
        # ===== [改动6.2] 卡片式显示收藏股票 (手机优化) =====
        for ticker in watchlist_list:
            yt = get_yahoo_ticker(ticker)
            with st.spinner(f"正在分析 {ticker}..."):
                try:
                    df_w = yf.download(yt, period="1y", progress=False, auto_adjust=False)
                    if isinstance(df_w.columns, pd.MultiIndex): 
                        df_w.columns = df_w.columns.get_level_values(0)
                    
                    # 切割日期
                    end_dt = pd.to_datetime(st.session_state.ref_date)
                    df_w = df_w[df_w.index <= end_dt]
                    
                    # 获取 TSI
                    t_obj = yf.Ticker(yt)
                    try: tsi = t_obj.fast_info.get('shares', None)
                    except: tsi = None
                    if tsi is None: 
                        try: tsi = t_obj.info.get('sharesOutstanding', 100000000)
                        except: tsi = 100000000
                    
                    if len(df_w) > 20:
                        curr_p = df_w['Close'].iloc[-1]
                        prev_close_w = df_w['Close'].shift(1).replace(0, np.nan)
                        prev_close_last = prev_close_w.iloc[-1]
                        prev_close_last = float(prev_close_last) if pd.notna(prev_close_last) else 0.0
                        chg = (curr_p - prev_close_last) if prev_close_last else 0.0
                        pct = (chg / prev_close_last * 100) if prev_close_last else 0.0
                        
                        # ===== 新增: 手机卡片式UI =====
                        if is_mobile:
                            # 手机端: 卡片 + 可展开详情
                            with st.container():
                                # 卡片头部 (大字体, 关键信息)
                                col1, col2 = st.columns([2, 1])
                                with col1:
                                    st.markdown(f"""
                                    <div style="font-size: 18px; font-weight: bold;">
                                        {ticker.upper()}
                                    </div>
                                    """, unsafe_html=True)
                                    st.caption(f"Price: {curr_p:.2f}")
                                
                                with col2:
                                    chg_color = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                                    st.markdown(f"""
                                    <div style="text-align: right; font-weight: bold; color: {'green' if chg > 0 else 'red' if chg < 0 else 'gray'};">
                                        {chg_color}<br/>{pct:+.2f}%
                                    </div>
                                    """, unsafe_html=True)
                                
                                # 可展开详情
                                with st.expander(f"📊 詳細數據", expanded=False):
                                    # 计算 SMA 和指标 (原来的逻辑保持)
                                    intervals = [7, 14, 28, 57, 106, 212]
                                    avgp_vals = [curr_p]
                                    for p in intervals:
                                        avgp_vals.append(df_w['Close'].rolling(p).mean().iloc[-1] if len(df_w)>=p else 0)
                                    
                                    valid_avgp = [v for v in avgp_vals if v > 0]
                                    avg_avgp = sum(valid_avgp) / len(valid_avgp) if valid_avgp else 0
                                    avgp_mr_vals = [((v / avg_avgp) - 1)*100 if avg_avgp else 0 for v in avgp_vals]
                                    
                                    # 显示关键指标 (紧凑行)
                                    st.write("**SMA 價格**")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("SMA7", f"{avgp_vals[1]:.2f}")
                                    with col2:
                                        st.metric("SMA14", f"{avgp_vals[2]:.2f}")
                                    with col3:
                                        st.metric("SMA28", f"{avgp_vals[3]:.2f}")
                                    
                                    st.write("**MR 偏差%**")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("MR7", f"{avgp_mr_vals[1]:.2f}%")
                                    with col2:
                                        st.metric("MR14", f"{avgp_mr_vals[2]:.2f}%")
                                    with col3:
                                        st.metric("MR28", f"{avgp_mr_vals[3]:.2f}%")
                                
                                st.divider()
                        
                        else:
                            # 桌面端: 原来的 HTML 表格 (保持不变)
                            # ... 这里保留原来的 html 渲染逻辑
                            pass
                
                except Exception as e: 
                    st.error(f"Error {ticker}: {e}")


# === 模式 B: 单股詳細模式 (第 501-1339 行) ===
# 这部分代码保持 90% 不变，只改进以下几处:

else:
    yahoo_ticker = get_yahoo_ticker(current_code)
    display_ticker = current_code.zfill(5)
    
    # ===== [改动7] 头部栏 - 手机优化 =====
    if is_mobile:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("◀", use_container_width=True):
                st.session_state.current_view = ""
                st.rerun()
        with col2:
            st.markdown(f"<h3 style='text-align: center; margin: 0;'>{display_ticker}</h3>", unsafe_html=True)
        with col3:
            is_in_watchlist = current_code in watchlist_list
            btn_label = "★" if is_in_watchlist else "☆"
            if st.button(btn_label, use_container_width=True):
                if is_in_watchlist:
                    remove_stock_from_db(current_code)
                else:
                    update_stock_in_db(current_code)
                st.rerun()
    else:
        # 桌面端: 原来的两列布局
        col_t, col_b = st.columns([0.85, 0.15])
        with col_t: st.title(f"📊 {display_ticker}")
        with col_b:
            st.write("")
            is_in_watchlist = current_code in watchlist_list
            if is_in_watchlist:
                if st.button("★ 已收藏", type="primary", use_container_width=True):
                    remove_stock_from_db(current_code)
                    st.rerun()
            else:
                if st.button("☆ 加入", use_container_width=True):
                    update_stock_in_db(current_code)
                    st.rerun()
    
    # ===== 后续的数据获取和计算保持不变 =====
    @st.cache_data(ttl=900)
    def get_data_v7(symbol, end_date):
        try:
            df = yf.download(symbol, period="3y", auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex): 
                df.columns = df.columns.get_level_values(0)
            df = df[df.index <= pd.to_datetime(end_date)]
            t = yf.Ticker(symbol)
            try: s = t.fast_info.get('shares', None)
            except: s = t.info.get('sharesOutstanding', None)
            return df, s
        except: return None, None
    
    df, shares_outstanding = get_data_v7(yahoo_ticker, st.session_state.ref_date)
    
    if df is not None and len(df) > 5:
        # ===== [改动8] 图表改为响应式 =====
        
        # 原来的计算逻辑保持不变 (第 536-556 行)
        periods_sma = [7, 14, 28, 57, 106, 212]
        for p in periods_sma: 
            df[f'SMA_{p}'] = df['Close'].rolling(p).mean()
        if f'SMA_{sma1}' not in df.columns: 
            df[f'SMA_{sma1}'] = df['Close'].rolling(sma1).mean()
        if f'SMA_{sma2}' not in df.columns: 
            df[f'SMA_{sma2}'] = df['Close'].rolling(sma2).mean()
        
        has_turnover = False
        if shares_outstanding:
            has_turnover = True
            df['Turnover_Rate'] = (df['Volume'] / shares_outstanding) * 100
            df = simulate_bs_data(df, shares_outstanding)
        else:
            df['Turnover_Rate'] = 0.0
        
        prev_close_series = df['Close'].shift(1).replace(0, np.nan)
        df['AMP'] = (df['High'] - df['Low']) / prev_close_series * 100
        
        for p in periods_sma: 
            df[f'Sum_{p}'] = df['Volume'].rolling(p).sum()
        df['R1'] = df['Sum_7'] / df['Sum_14']
        df['R2'] = df['Sum_7'] / df['Sum_28']
        
        # ===== [改动9] 导航按钮 (手机改为竖排) =====
        if is_mobile:
            if st.button("◀ 返回", use_container_width=True):
                st.session_state.current_view = ""
                st.rerun()
            st.caption(f"📅 {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            c_nav_prev, c_nav_mid, c_nav_next = st.columns([1, 4, 1])
            with c_nav_prev:
                if st.button("◀ 前一交易日", use_container_width=True):
                    if len(df) >= 2:
                        st.session_state.ref_date = df.index[-2].date()
                        st.rerun()
            with c_nav_mid:
                st.markdown(f"<h3 style='text-align: center; margin: 0;'>基準日: {df.index[-1].strftime('%Y-%m-%d')}</h3>", unsafe_html=True)
            with c_nav_next:
                if st.button("後一交易日 ▶", use_container_width=True):
                    st.session_state.ref_date += timedelta(days=1)
                    st.rerun()
        
        st.divider()
        
        # ===== [改动10] 关键指标卡 (手机响应式) =====
        curr_close = float(df['Close'].iloc[-1])
        prev_close = df['Close'].shift(1).iloc[-1]
        prev_close = float(prev_close) if pd.notna(prev_close) else 0.0
        curr_open = float(df['Open'].iloc[-1])
        curr_high = float(df['High'].iloc[-1])
        curr_low = float(df['Low'].iloc[-1])
        chg = (curr_close - prev_close) if prev_close else 0.0
        pct = (chg / prev_close * 100) if prev_close else 0.0
        amp = ((curr_high - curr_low) / prev_close * 100) if prev_close else 0.0
        
        if is_mobile:
            # 手机: 竖排显示
            st.metric("現價", f"{curr_close:.3f}", f"{chg:+.3f} ({pct:+.2f}%)")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("開市", f"{curr_open:.3f}")
            with col2:
                st.metric("最高", f"{curr_high:.3f}")
            with col3:
                st.metric("最低", f"{curr_low:.3f}")
        else:
            # 桌面: 两行显示
            c_sum_1, c_sum_2 = st.columns(2)
            with c_sum_1:
                st.metric("現價", f"{curr_close:.3f}", f"{chg:+.3f} ({pct:+.2f}%)")
                st.metric("前收市", f"{prev_close:.3f}" if prev_close else "-")
                st.metric("波幅(AA)", f"{amp:.2f}%" if prev_close else "-")
            with c_sum_2:
                st.metric("開市", f"{curr_open:.3f}")
                st.metric("最高", f"{curr_high:.3f}")
                st.metric("最低", f"{curr_low:.3f}")
        
        # ===== [改动11] 图表 - 使用响应式渲染 =====
        end_date_dt = pd.to_datetime(st.session_state.ref_date)
        start_date_6m = end_date_dt - timedelta(days=180)
        display_df = df[df.index >= start_date_6m]
        
        fig_main = go.Figure()
        fig_main.add_trace(
            go.Candlestick(
                x=display_df.index,
                open=display_df["Open"],
                high=display_df["High"],
                low=display_df["Low"],
                close=display_df["Close"],
                name="K線",
            )
        )
        if "SMA_7" in display_df.columns:
            fig_main.add_trace(go.Scatter(x=display_df.index, y=display_df["SMA_7"], line=dict(color="orange"), name="SMA 7"))
        if "SMA_14" in display_df.columns:
            fig_main.add_trace(go.Scatter(x=display_df.index, y=display_df["SMA_14"], line=dict(color="blue"), name="SMA 14"))
        fig_main.update_layout(height=520 if not is_mobile else 350, xaxis_rangeslider_visible=True, template="plotly_white", dragmode="pan", uirevision=f"main_price_{current_code}")
        
        # 使用响应式图表渲染
        responsive_chart(fig_main, title="K線圖", height="auto")
        
        # ===== 后续的表格渲染 (第 616-1337 行) 改为响应式 =====
        # 这里简化示意，实际改动是把所有的 st.dataframe() 改为 responsive_table()
        
        st.markdown("**快速信號**")
        df_sig = df.tail(260).copy()
        df_sig["WR35"] = calculate_willr(df_sig["High"], df_sig["Low"], df_sig["Close"], 35)
        last_sig = df_sig.iloc[-1]
        
        val_sma7 = last_sig.get("SMA_7", np.nan)
        val_sma14 = last_sig.get("SMA_14", np.nan)
        val_wr35 = last_sig.get("WR35", np.nan)
        
        cond_above = (pd.notna(val_sma7) and pd.notna(val_sma14) and (curr_close > float(val_sma7)) and (curr_close > float(val_sma14)))
        cond_wr = (pd.notna(val_wr35) and (float(val_wr35) < -80))
        fzm_trigger = bool(cond_above and cond_wr)
        
        # 手机: 竖排, 桌面: 两列
        if is_mobile:
            st.write(f"超底(FZM)：{'🔴 觸發' if fzm_trigger else '未觸發'}")
            st.write(f"WR35: {'-' if pd.isna(val_wr35) else f'{float(val_wr35):.2f}'}")
            st.write(f"SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}")
        else:
            c_sig_1, c_sig_2 = st.columns(2)
            with c_sig_1:
                st.markdown(f"超底(FZM)：{'🔴 觸發' if fzm_trigger else '未觸發'}")
                st.write(f"WR35: {'-' if pd.isna(val_wr35) else f'{float(val_wr35):.2f}'}")
                st.write(f"SMA7/14: {'-' if pd.isna(val_sma7) else f'{float(val_sma7):.3f}'} / {'-' if pd.isna(val_sma14) else f'{float(val_sma14):.3f}'}")
            with c_sig_2:
                st.markdown(f"振蕩(MR)：暂不计算")
        
        # 后续所有表格改为响应式:
        # responsive_table(df, title="SMA Matrix", max_rows=10)
        
        # ========== 底部导航 (手机端新增) ==========
        if is_mobile:
            st.markdown("---")
            nav_cols = st.columns(4)
            nav_items = [
                {"label": "🏠Home", "key": "home"},
                {"label": "📊Detail", "key": "detail"},
                {"label": "💼Alert", "key": "alert"},
                {"label": "⚙️More", "key": "more"},
            ]
            
            for col, item in zip(nav_cols, nav_items):
                with col:
                    if st.button(item["label"], use_container_width=True):
                        if item["key"] == "home":
                            st.session_state.current_view = ""
                            st.rerun()


# ========== 底部固定导航栏 (手机端) ==========
if is_mobile and not current_code:
    st.markdown("---")
    st.markdown("### 📱 快速导航")
    nav_cols = st.columns(4)
    nav_items = [
        {"label": "🏠Home", "key": "home"},
        {"label": "📊Markets", "key": "markets"},
        {"label": "📈Portfolio", "key": "portfolio"},
        {"label": "⚙️More", "key": "more"},
    ]
    
    for col, item in zip(nav_cols, nav_items):
        with col:
            if st.button(item["label"], use_container_width=True):
                if item["key"] == "home":
                    pass  # 已在首页
                elif item["key"] == "markets":
                    st.info("Markets 页面开发中...")
                elif item["key"] == "portfolio":
                    st.info("Portfolio 页面开发中...")
                elif item["key"] == "more":
                    st.info("More 页面开发中...")


# ========== 开发者工具 (调试) ==========
optimizer.toggle_mobile_mode()

