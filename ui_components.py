"""
UI组件模块
包含可复用的UI组件函数
"""

import streamlit as st

def render_header(title="📊 资金盘推演", subtitle="Crypto Trading Simulator • Risk Management & Strategy Analysis"):
    """渲染应用头部"""
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem 0 2rem 0;">
        <h1 style="margin-bottom: 0.5rem; font-size: 2.8rem;">{title}</h1>
        <p style="color: #64748b; font-size: 1rem; margin: 0;">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)


def render_metric_card(label, value, delta=None, help_text=None):
    """
    渲染增强的指标卡片
    
    Args:
        label: 标签文本
        value: 显示值
        delta: 变化值（可选）
        help_text: 帮助提示（可选）
    """
    st.metric(label=label, value=value, delta=delta, help=help_text)


def render_section_header(title, icon=""):
    """
    渲染带图标的章节标题
    
    Args:
        title: 标题文本
        icon: emoji图标（可选）
    """
    full_title = f"{icon} {title}" if icon else title
    st.header(full_title)


def render_info_box(message, type="info"):
    """
    渲染信息提示框
    
    Args:
        message: 提示信息
        type: 类型 ("info", "success", "warning", "error")
    """
    if type == "success":
        st.success(message)
    elif type == "warning":
        st.warning(message)
    elif type == "error":
        st.error(message)
    else:
        st.info(message)


def render_operation_table(operations, current_price):
    """
    渲染操作序列表格
    
    Args:
        operations: 操作列表
        current_price: 当前价格
    """
    if not operations:
        st.info("暂无操作。点击上方「+ 添加」按钮添加操作。", icon="ℹ️")
        return
    
    # 构建表格数据
    table_data = []
    for op in operations:
        # 计算USDT等值
        if op['amount_type'] == '百分比':
            usdt_equiv = f"{op['amount']}%"
        else:
            usdt_equiv = f"${op['amount']:,.0f}"
        
        # 计算其他字段（需要传入更多上下文）
        table_data.append({
            '操作': op['action'],
            '触发价': f"${op['price']:,.0f}",
            '金额': usdt_equiv,
            '权益': '-',  # 需要计算
            '持仓': '-',  # 需要计算
            '强平价': '-',  # 需要计算
        })
    
    # 显示表格
    if table_data:
        import pandas as pd
        df = pd.DataFrame(table_data)
        st.dataframe(df, hide_index=True)


def render_price_badge(price, label="Current Price"):
    """
    渲染价格徽章
    
    Args:
        price: 价格值
        label: 标签
    """
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 8px 16px;
        border-radius: 20px;
        display: inline-block;
        font-weight: 600;
        font-size: 0.9rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    ">
        {label}: ${price:,.2f}
    </div>
    """, unsafe_allow_html=True)


def render_divider():
    """渲染分隔线"""
    st.markdown("<hr>", unsafe_allow_html=True)


def render_container_header(title, description=None):
    """
    渲染容器标题（用于 st.container）
    
    Args:
        title: 标题
        description: 描述文本（可选）
    """
    st.markdown(f"### {title}")
    if description:
        st.caption(description)
