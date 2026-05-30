"""
Streamlit 移动端优化模块
提供完整的响应式 UI 组件和布局系统
"""

import streamlit as st
import pandas as pd
from typing import Dict, List, Any, Callable, Optional, Tuple
import plotly.graph_objects as go


class MobileOptimizer:
    """移动端优化管理器 - 主类"""
    
    def __init__(self):
        """初始化移动端优化器"""
        self._init_session_state()
        self.is_mobile = st.session_state.get('is_mobile', False)
        self.breakpoint_sm = 576
        self.breakpoint_md = 768
        self.breakpoint_lg = 1024
    
    def _init_session_state(self):
        """初始化 session state"""
        if 'is_mobile' not in st.session_state:
            st.session_state.is_mobile = self._detect_mobile()
        if 'force_mobile_mode' not in st.session_state:
            st.session_state.force_mobile_mode = None
    
    def _detect_mobile(self) -> bool:
        """
        检测是否为移动设备
        优先级: 查询参数 > User-Agent > 默认 False
        """
        # 检查查询参数 (用于测试)
        query_params = st.query_params
        if 'mobile_mode' in query_params:
            return query_params['mobile_mode'].lower() == 'true'
        
        # 检查强制设置
        if st.session_state.get('force_mobile_mode') is not None:
            return st.session_state.force_mobile_mode
        
        # 默认通过 User-Agent 检测 (不完全准确，但够用)
        return False
    
    def setup_responsive_page(self, 
                            title: str,
                            icon: str = "📊",
                            layout: str = "auto",
                            initial_sidebar_state: str = "auto"):
        """
        设置响应式页面配置
        
        Args:
            title: 页面标题
            icon: 页面图标
            layout: 布局模式 ("auto" / "wide" / "centered")
            initial_sidebar_state: 侧边栏初始状态 ("auto" / "expanded" / "collapsed")
        """
        self.is_mobile = st.session_state.get('is_mobile', False)
        
        # 根据设备类型选择布局
        if layout == "auto":
            layout = "centered" if self.is_mobile else "wide"
        
        if initial_sidebar_state == "auto":
            initial_sidebar_state = "collapsed" if self.is_mobile else "expanded"
        
        st.set_page_config(
            page_title=title,
            page_icon=icon,
            layout=layout,
            initial_sidebar_state=initial_sidebar_state,
            menu_items={
                'About': "港股 SMA 技术分析工具 v1.0"
            }
        )
        
        # 注入移动端 CSS
        self._inject_mobile_css()
    
    def _inject_mobile_css(self):
        """注入移动端优化 CSS"""
        css = """
        <style>
        /* ===== 全局移动端优化 ===== */
        @media (max-width: 768px) {
            /* 容器 */
            .reportview-container {
                padding: 8px !important;
            }
            .main .block-container {
                padding: 8px !important;
                max-width: 100% !important;
            }
            
            /* 列布局 */
            div[data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
            }
            div[data-testid="stHorizontalBlock"] > div {
                width: 100% !important;
                margin-bottom: 10px !important;
            }
            
            /* 按钮最小触摸区 (iOS 标准) */
            button {
                min-height: 44px !important;
                min-width: 44px !important;
                width: 100% !important;
                font-size: 14px !important;
                margin: 4px 0 !important;
                padding: 12px 16px !important;
            }
            
            /* 输入框 */
            input, textarea, select {
                min-height: 44px !important;
                font-size: 16px !important;
                padding: 12px !important;
            }
            
            /* 选择框 */
            select {
                width: 100% !important;
            }
            
            /* 标题 */
            h1, h2, h3 {
                margin-top: 12px !important;
                margin-bottom: 8px !important;
            }
            
            /* 间距 */
            .element-container {
                margin: 8px 0 !important;
            }
        }
        
        /* ===== 卡片样式 ===== */
        .metric-card {
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            border-radius: 6px;
            padding: 12px;
            margin: 8px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        
        .metric-card-header {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #212529;
        }
        
        .metric-card-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #dee2e6;
        }
        
        .metric-card-row:last-child {
            border-bottom: none;
        }
        
        .metric-card-label {
            font-size: 12px;
            color: #6c757d;
            font-weight: 500;
        }
        
        .metric-card-value {
            font-size: 14px;
            color: #212529;
            font-weight: 600;
        }
        
        /* ===== 表格优化 ===== */
        @media (max-width: 768px) {
            table {
                font-size: 12px !important;
            }
            th, td {
                padding: 8px !important;
                word-break: break-word;
            }
            thead {
                display: none;
            }
        }
        
        /* ===== 图表优化 ===== */
        .plotly-container {
            margin: 8px 0;
        }
        
        /* ===== 标签页优化 ===== */
        @media (max-width: 768px) {
            [data-testid="stTabs"] {
                overflow-x: auto;
            }
        }
        
        /* ===== 展开器优化 ===== */
        @media (max-width: 768px) {
            [data-testid="stExpander"] {
                margin: 8px 0;
            }
        }
        
        /* ===== 信息框优化 ===== */
        .element-container .stAlert {
            padding: 12px !important;
            margin: 8px 0 !important;
        }
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    
    def get_responsive_cols(self, 
                          num_cols: int,
                          weights: Optional[List[int]] = None) -> List:
        """
        获取响应式列
        
        手机: 最多 2 列
        桌面: 支持任意列数
        
        Args:
            num_cols: 请求的列数
            weights: 列的权重 (如 [1, 2, 1])
        
        Returns:
            列对象列表
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if is_mobile:
            # 手机端: 最多 2 列
            if num_cols <= 1:
                return [st.container()]
            elif num_cols <= 2:
                return st.columns(num_cols)
            else:
                # 超过 2 列在手机上使用标签页替代
                return [st.container()]  # 调用者需要自己处理
        else:
            # 桌面端: 返回正常列数
            if weights:
                return st.columns(weights)
            else:
                return st.columns(num_cols)
    
    def render_responsive_table(self,
                               df: pd.DataFrame,
                               title: str = "",
                               max_rows: int = 10,
                               height: Optional[int] = None):
        """
        渲染响应式表格
        
        手机: 卡片模式 (主要信息 + 可折叠详情)
        桌面: 普通数据表格
        
        Args:
            df: 数据框
            title: 表格标题
            max_rows: 最多显示的行数
            height: 表格高度 (仅桌面端)
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if title:
            st.subheader(title)
        
        if df.empty:
            st.info("📭 无数据")
            return
        
        if is_mobile:
            # 手机端: 卡片模式
            self._render_table_as_cards(df, max_rows)
        else:
            # 桌面端: 表格模式
            if height is None:
                height = min(400, len(df.head(max_rows)) * 35 + 100)
            
            st.dataframe(
                df.head(max_rows),
                use_container_width=True,
                height=height,
                hide_index=False
            )
    
    def _render_table_as_cards(self, df: pd.DataFrame, max_rows: int = 10):
        """
        将表格渲染为卡片 (移动端)
        
        Args:
            df: 数据框
            max_rows: 最多显示的行数
        """
        for idx, row in df.head(max_rows).iterrows():
            with st.container():
                # 卡片头部 (主要信息)
                cols = st.columns([2, 1])
                
                # 第一列: 主要标识 (第一列数据)
                main_col = df.columns[0]
                with cols[0]:
                    st.markdown(f"""
                    <div class="metric-card-header">
                        {row[main_col]}
                    </div>
                    """, unsafe_allow_html=True)
                
                # 第二列: 关键指标 (第二列数据)
                if len(df.columns) > 1:
                    key_col = df.columns[1]
                    with cols[1]:
                        st.markdown(f"""
                        <div style="text-align: right;">
                            <div class="metric-card-label">{key_col}</div>
                            <div class="metric-card-value">{row[key_col]}</div>
                        </div>
                        """, unsafe_allow_html=True)
                
                # 卡片主体 (前 3 列的详细信息)
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                
                for col in df.columns[:3]:
                    st.markdown(f"""
                    <div class="metric-card-row">
                        <span class="metric-card-label">{col}</span>
                        <span class="metric-card-value">{row[col]}</span>
                    </div>
                    """, unsafe_allow_html=True)
                
                # 更多信息 (其他列可折叠)
                if len(df.columns) > 3:
                    with st.expander("📊 更多信息", expanded=False):
                        for col in df.columns[3:]:
                            st.markdown(f"**{col}**: {row[col]}")
                
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()
    
    def render_action_buttons(self,
                             buttons: List[Dict[str, Any]],
                             layout: str = "auto") -> Optional[str]:
        """
        渲染响应式按钮组
        
        手机: 竖排堆叠 (100% 宽度)
        桌面: 横排 (自动分列)
        
        Args:
            buttons: 按钮配置列表
                [
                    {"label": "🏠 主页", "key": "home", "callback": func, "type": "primary"},
                    {"label": "🔄 刷新", "key": "refresh", "callback": func},
                ]
            layout: 布局模式 ("auto" / "horizontal" / "vertical")
        
        Returns:
            被点击的按钮 key，如果没有则返回 None
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if layout == "auto":
            # 手机或按钮过多时: 竖排
            layout = "vertical" if (is_mobile or len(buttons) > 3) else "horizontal"
        
        clicked_key = None
        
        if layout == "vertical":
            # 竖排堆叠
            for btn in buttons:
                if st.button(
                    btn['label'],
                    key=btn.get('key', btn['label']),
                    use_container_width=True,
                    type=btn.get('type', 'secondary'),
                    help=btn.get('help', '')
                ):
                    clicked_key = btn.get('key', btn['label'])
                    if 'callback' in btn:
                        btn['callback']()
        else:
            # 横排
            cols = st.columns(len(buttons))
            for col, btn in zip(cols, buttons):
                with col:
                    if st.button(
                        btn['label'],
                        key=btn.get('key', btn['label']),
                        use_container_width=True,
                        type=btn.get('type', 'secondary'),
                        help=btn.get('help', '')
                    ):
                        clicked_key = btn.get('key', btn['label'])
                        if 'callback' in btn:
                            btn['callback']()
        
        return clicked_key
    
    def render_responsive_chart(self,
                               fig: go.Figure,
                               title: str = "",
                               height: str = "auto",
                               use_container_width: bool = True):
        """
        渲染响应式图表
        
        手机: 350px 高、隐藏工具栏
        桌面: 500px 高、显示工具栏
        
        Args:
            fig: Plotly 图表对象
            title: 图表标题
            height: 图表高度 ("auto" / 像素数)
            use_container_width: 是否使用容器宽度
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if title:
            st.subheader(title)
        
        # 根据设备调整高度
        if height == "auto":
            chart_height = 350 if is_mobile else 500
        else:
            chart_height = height if isinstance(height, int) else 500
        
        # 根据设备调整配置
        config = {
            'responsive': True,
            'displayModeBar': not is_mobile,  # 手机隐藏工具栏
            'displaylogo': False,
            'toImageButtonOptions': {
                'format': 'png',
                'filename': 'chart',
                'height': chart_height,
                'width': 400 if is_mobile else 800,
                'scale': 1
            }
        }
        
        # 更新图表高度
        fig.update_layout(height=chart_height)
        
        st.plotly_chart(
            fig,
            use_container_width=use_container_width,
            config=config
        )
    
    def render_responsive_navigation(self,
                                    pages: Dict[str, Callable],
                                    default_page: Optional[str] = None) -> str:
        """
        渲染响应式导航
        
        手机: selectbox 下拉菜单
        桌面: st.tabs() 标签页
        
        Args:
            pages: 页面字典 {"页面名": 页面函数}
            default_page: 默认页面
        
        Returns:
            当前选中的页面名
        
        Example:
            pages = {
                "📊 概览": page_overview,
                "💼 对比": page_comparison,
                "⚙️ 设置": page_settings,
            }
            current = optimizer.render_responsive_navigation(pages)
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if 'current_page' not in st.session_state:
            st.session_state.current_page = default_page or list(pages.keys())[0]
        
        if is_mobile:
            # 手机: selectbox 下拉菜单
            selected = st.selectbox(
                "导航",
                list(pages.keys()),
                index=list(pages.keys()).index(st.session_state.current_page),
                key="nav_select"
            )
            st.session_state.current_page = selected
            pages[selected]()
            return selected
        else:
            # 桌面: 标签页
            tabs = st.tabs(list(pages.keys()))
            for tab, (page_name, page_func) in zip(tabs, pages.items()):
                with tab:
                    st.session_state.current_page = page_name
                    page_func()
            return st.session_state.current_page
    
    def render_metric_row(self,
                         metrics: List[Tuple[str, str]],
                         cols_count: int = 2):
        """
        渲染响应式指标行
        
        Args:
            metrics: 指标列表 [("标签", "值"), ...]
            cols_count: 列数 (手机自动调整为最多2列)
        
        Example:
            optimizer.render_metric_row([
                ("胜率", "65%"),
                ("收益", "+12.5%"),
                ("回撤", "-8.2%"),
            ])
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if is_mobile:
            cols_count = min(cols_count, 2)
        
        cols = st.columns(cols_count)
        
        for idx, (label, value) in enumerate(metrics):
            col_idx = idx % cols_count
            with cols[col_idx]:
                st.metric(label=label, value=value)
    
    def render_section(self,
                      title: str,
                      icon: str = "📊",
                      content_func: Optional[Callable] = None):
        """
        渲染响应式分区
        
        Args:
            title: 分区标题
            icon: 图标
            content_func: 内容渲染函数
        
        Example:
            def render_content():
                st.write("Section content here")
            
            optimizer.render_section("市场概览", "📊", render_content)
        """
        with st.container():
            st.markdown(f"### {icon} {title}")
            st.divider()
            
            if content_func:
                content_func()
    
    def get_responsive_grid(self,
                           items: List[Dict[str, Any]],
                           cols_count: int = 3) -> None:
        """
        渲染响应式网格布局
        
        手机: 1 列
        平板: 2 列
        桌面: 3+ 列
        
        Args:
            items: 网格项目列表 [{"title": "", "value": "", "icon": ""}, ...]
            cols_count: 桌面端列数
        
        Example:
            items = [
                {"title": "总收益", "value": "+15%", "icon": "📈"},
                {"title": "胜率", "value": "65%", "icon": "✅"},
                {"title": "回撤", "value": "-8%", "icon": "📉"},
            ]
            optimizer.get_responsive_grid(items)
        """
        is_mobile = st.session_state.get('is_mobile', False)
        
        if is_mobile:
            cols_count = 1
        
        for i, item in enumerate(items):
            if i % cols_count == 0:
                cols = st.columns(cols_count)
            
            col_idx = i % cols_count
            with cols[col_idx]:
                st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 24px; margin-bottom: 8px;">{item.get('icon', '📊')}</div>
                    <div class="metric-card-label">{item.get('title', '')}</div>
                    <div class="metric-card-value">{item.get('value', '')}</div>
                </div>
                """, unsafe_allow_html=True)
    
    def toggle_mobile_mode(self):
        """
        切换移动端模式 (用于测试)
        在侧边栏显示切换按钮
        """
        with st.sidebar:
            st.divider()
            st.markdown("### 🔧 开发工具")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📱 移动端模式"):
                    st.session_state.is_mobile = True
                    st.rerun()
            
            with col2:
                if st.button("🖥️ 桌面模式"):
                    st.session_state.is_mobile = False
                    st.rerun()
            
            is_mobile = st.session_state.get('is_mobile', False)
            st.info(f"当前模式: {'📱 移动端' if is_mobile else '🖥️ 桌面端'}")
            st.caption(f"或使用 URL 参数: ?mobile_mode=true/false")


# ===== 快捷函数 (无需创建类实例) =====

def init_mobile_optimizer() -> MobileOptimizer:
    """初始化移动端优化器（推荐用法）"""
    if 'optimizer' not in st.session_state:
        st.session_state.optimizer = MobileOptimizer()
    return st.session_state.optimizer


def setup_page(title: str,
              icon: str = "📊",
              layout: str = "auto",
              initial_sidebar_state: str = "auto"):
    """快捷函数: 设置响应式页面"""
    optimizer = init_mobile_optimizer()
    optimizer.setup_responsive_page(title, icon, layout, initial_sidebar_state)


def responsive_cols(num_cols: int,
                   weights: Optional[List[int]] = None) -> List:
    """快捷函数: 获取响应式列"""
    optimizer = init_mobile_optimizer()
    return optimizer.get_responsive_cols(num_cols, weights)


def responsive_table(df: pd.DataFrame,
                    title: str = "",
                    max_rows: int = 10):
    """快捷函数: 渲染响应式表格"""
    optimizer = init_mobile_optimizer()
    optimizer.render_responsive_table(df, title, max_rows)


def action_buttons(buttons: List[Dict[str, Any]],
                  layout: str = "auto") -> Optional[str]:
    """快捷函数: 渲染响应式按钮组"""
    optimizer = init_mobile_optimizer()
    return optimizer.render_action_buttons(buttons, layout)


def responsive_chart(fig: go.Figure,
                    title: str = "",
                    height: str = "auto"):
    """快捷函数: 渲染响应式图表"""
    optimizer = init_mobile_optimizer()
    optimizer.render_responsive_chart(fig, title, height)


# ===== 使用示例 =====
"""
在 app.py 中使用:

    from mobile_optimizer import setup_page, responsive_cols, responsive_table, action_buttons

    # 1. 页面初始化
    setup_page("港股 SMA 分析", icon="📊")
    
    # 2. 响应式按钮
    clicked = action_buttons([
        {"label": "🏠 主页", "key": "home", "callback": lambda: print("Home")},
        {"label": "🔄 刷新", "key": "refresh", "callback": lambda: print("Refresh")},
        {"label": "⚙️ 设置", "key": "settings", "callback": lambda: print("Settings")},
    ])
    
    # 3. 响应式表格
    df = pd.DataFrame({
        "股票": ["0001", "0002", "0003"],
        "价格": ["1.5", "2.3", "3.1"],
        "涨幅": ["+2.5%", "-1.2%", "+3.8%"],
    })
    responsive_table(df, title="港股行情", max_rows=10)
    
    # 4. 响应式图表
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
    responsive_chart(fig, title="走势图")
"""
