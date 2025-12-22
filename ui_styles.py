"""
UI样式配置模块
包含所有CSS样式和主题配置
"""

# 颜色主题配置
COLORS = {
    # 主色调
    'primary': '#667eea',
    'primary_dark': '#764ba2',
    
    # 背景色
    'bg_gradient_start': '#f5f7fa',
    'bg_gradient_end': '#c3cfe2',
    'card_bg': '#ffffff',
    'card_bg_gradient_end': '#f8f9fa',
    
    # 文字颜色
    'text_primary': '#2c3e50',
    'text_secondary': '#64748b',
    'text_dark': '#1e293b',
    'text_muted': '#546e7a',
    
    # 边框和分隔线
    'border': '#e0e6ed',
    'border_light': 'rgba(255, 255, 255, 0.3)',
    
    # 状态颜色
    'success': '#10b981',
    'warning': '#f59e0b',
    'danger': '#ef4444',
    
    # Hover效果
    'hover_bg': '#f8f9fa',
}

# 字体配置
TYPOGRAPHY = {
    'title_size': '2.8rem',
    'h2_size': '1.4rem',
    'h3_size': '1.1rem',
    'h4_size': '1rem',
    'metric_label_size': '0.8rem',
    'metric_value_size': '1.5rem',
}

# 间距配置
SPACING = {
    'container_padding': '24px',
    'metric_padding': '16px',
    'button_padding': '0.5rem 1.5rem',
    'border_radius': '12px',
    'border_radius_sm': '8px',
}

# CSS样式模板
CSS_STYLES = f"""
<style>
    /* ===== 全局样式 ===== */
    .stApp {{ 
        background: linear-gradient(135deg, {COLORS['bg_gradient_start']} 0%, {COLORS['bg_gradient_end']} 100%);
        color: {COLORS['text_primary']};
    }}
    
    /* 主容器 */
    .main .block-container {{
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }}
    
    /* ===== 标题样式 ===== */
    h1 {{ 
        font-size: 2.5rem !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_dark']} 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem !important;
        text-align: center;
    }}
    
    h2 {{ 
        font-size: {TYPOGRAPHY['h2_size']} !important;
        font-weight: 600 !important;
        color: {COLORS['text_primary']} !important;
        margin-top: 1.5rem !important;
        margin-bottom: 1rem !important;
        border-left: 4px solid {COLORS['primary']};
        padding-left: 12px;
    }}
    
    h3 {{ 
        font-size: {TYPOGRAPHY['h3_size']} !important;
        font-weight: 600 !important;
        color: #34495e !important;
    }}
    
    h4 {{ 
        font-size: {TYPOGRAPHY['h4_size']} !important;
        font-weight: 500 !important;
        color: {COLORS['text_muted']} !important;
        margin-bottom: 0.5rem !important;
    }}
    
    /* ===== 容器样式 ===== */
    div[data-testid="stVerticalBlock"] > div[style*="background"] {{
        background: {COLORS['card_bg']} !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.07), 0 1px 3px rgba(0, 0, 0, 0.06) !important;
        padding: {SPACING['container_padding']} !important;
        border: 1px solid {COLORS['border_light']} !important;
    }}
    
    /* Streamlit 容器边框 */
    [data-testid="stHorizontalBlock"] {{
        gap: 1rem !important;
    }}
    
    /* ===== Metrics 卡片 ===== */
    .stMetric {{ 
        background: linear-gradient(135deg, {COLORS['card_bg']} 0%, {COLORS['card_bg_gradient_end']} 100%);
        border: 1px solid {COLORS['border']};
        padding: {SPACING['metric_padding']} !important;
        border-radius: {SPACING['border_radius']};
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
        transition: all 0.3s ease;
    }}
    
    .stMetric:hover {{
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.08);
    }}
    
    .stMetric label {{ 
        font-size: {TYPOGRAPHY['metric_label_size']} !important;
        font-weight: 500 !important;
        color: {COLORS['text_secondary']} !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    
    .stMetric [data-testid="stMetricValue"] {{ 
        font-size: {TYPOGRAPHY['metric_value_size']} !important;
        font-weight: 700 !important;
        color: {COLORS['text_dark']} !important;
    }}
    
    .stMetric [data-testid="stMetricDelta"] {{
        font-size: 0.85rem !important;
    }}
    
    /* ===== 按钮样式 ===== */
    .stButton > button {{
        background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_dark']} 100%);
        color: white;
        border: none;
        border-radius: {SPACING['border_radius_sm']};
        padding: {SPACING['button_padding']};
        font-weight: 600;
        box-shadow: 0 2px 4px rgba(102, 126, 234, 0.3);
        transition: all 0.3s ease;
    }}
    
    .stButton > button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
    }}
    
    /* 删除按钮样式 */
    button[kind="secondary"] {{
        background: linear-gradient(135deg, {COLORS['danger']} 0%, #dc2626 100%) !important;
        color: white !important;
    }}
    
    /* ===== 输入框样式 ===== */
    .stNumberInput > div > div > input,
    .stTextInput > div > div > input {{
        border-radius: {SPACING['border_radius_sm']};
        border: 1.5px solid {COLORS['border']};
        padding: 0.5rem 0.75rem;
        transition: all 0.3s ease;
    }}
    
    .stNumberInput > div > div > input:focus,
    .stTextInput > div > div > input:focus {{
        border-color: {COLORS['primary']};
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }}
    
    /* ===== 选择框样式 ===== */
    .stSelectbox > div > div,
    .stRadio > div {{
        border-radius: {SPACING['border_radius_sm']};
    }}
    
    /* ===== 表格样式 ===== */
    .dataframe {{
        border-radius: {SPACING['border_radius_sm']};
        overflow: hidden;
        border: 1px solid {COLORS['border']} !important;
    }}
    
    .dataframe thead tr {{
        background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_dark']} 100%);
        color: white !important;
    }}
    
    .dataframe thead th {{
        color: white !important;
        font-weight: 600 !important;
        padding: 12px !important;
    }}
    
    .dataframe tbody tr:hover {{
        background-color: {COLORS['hover_bg']};
    }}
    
    /* ===== 提示框样式 ===== */
    .stAlert {{
        border-radius: {SPACING['border_radius']};
        border-left-width: 4px;
        padding: 1rem 1.25rem;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }}
    
    /* 成功提示 */
    div[data-baseweb="notification"][kind="success"] {{
        background-color: #d1fae5;
        border-left-color: {COLORS['success']};
    }}
    
    /* 警告提示 */
    div[data-baseweb="notification"][kind="warning"] {{
        background-color: #fef3c7;
        border-left-color: {COLORS['warning']};
    }}
    
    /* ===== 滑块样式 ===== */
    .stSlider > div > div > div {{
        background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_dark']} 100%);
    }}
    
    /* ===== 高亮颜色 ===== */
    .highlight {{ 
        color: {COLORS['success']}; 
        font-weight: 600; 
    }}
    
    .danger {{ 
        color: {COLORS['danger']}; 
        font-weight: 600; 
    }}
    
    /* ===== 分隔线 ===== */
    hr {{
        margin: 2rem 0;
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, {COLORS['border']}, transparent);
    }}
    
    /* ===== 图表容器 ===== */
    .js-plotly-plot {{
        border-radius: {SPACING['border_radius']};
        overflow: hidden;
    }}
</style>
"""
