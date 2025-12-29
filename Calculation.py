import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
from datetime import datetime

# 导入模块化UI组件
from ui_styles import CSS_STYLES
from ui_components import render_header

# 导入资金划转引擎
import transfer_engine as te

# ==========================================
# 0. 页面配置
# ==========================================

st.set_page_config(
    page_title="Trading Simulation | 资金盘推演", 
    layout="wide", 
    page_icon="📊",
    initial_sidebar_state="collapsed"
)

# ==================== 保持滚动位置 ====================
# 在按钮点击前保存滚动位置
import streamlit.components.v1 as components

def preserve_scroll_position():
    """保存当前滚动位置并在重新加载后恢复"""
    components.html("""
        <script>
        // 保存当前滚动位置
        const scrollY = window.parent.document.documentElement.scrollTop || window.parent.document.body.scrollTop;
        window.parent.sessionStorage.setItem('streamlit_scroll', scrollY);
        
        // 尝试恢复滚动位置（页面加载后）
        setTimeout(function() {
            const savedScroll = window.parent.sessionStorage.getItem('streamlit_scroll');
            if (savedScroll !== null) {
                window.parent.scrollTo(0, parseInt(savedScroll));
            }
        }, 100);
        </script>
    """, height=0)

# 在每次页面加载时尝试恢复滚动位置
preserve_scroll_position()

# 应用样式
st.markdown(CSS_STYLES, unsafe_allow_html=True)

# 渲染头部
render_header()

# ==========================================
# 0.5 CoinGecko API 集成（无地理限制）
# ==========================================

@st.cache_data(ttl=30, show_spinner=False)
def get_btc_price():
    """从 CoinGecko API 获取 BTC/USDT 实时价格（无地理限制）"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin",
            "vs_currencies": "usd"
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data['bitcoin']['usd'])
    except Exception as e:
        st.error(f"⚠️ 无法获取 BTC 价格: {str(e)}")
        return None

# ==========================================
# 1. 数据输入 - 替代侧边栏
# ==========================================

# 初始化 session state 保存最后有效价格
if 'last_valid_price' not in st.session_state:
    st.session_state.last_valid_price = None

# 获取实时价格（每30秒自动刷新）
live_price = get_btc_price()

if live_price and live_price > 0:
    # 成功获取有效价格
    current_price = live_price
    st.session_state.last_valid_price = live_price  # 保存为最后有效价格
elif st.session_state.last_valid_price:
    # API 失败或返回 0，使用上次保存的有效价格
    current_price = st.session_state.last_valid_price
else:
    # 完全没有历史数据，使用合理的默认值
    current_price = 90000.0  # 备用默认值（避免除零错误）
    st.warning("⚠️ 暂时无法获取实时价格，使用默认值 $90,000")
# 这些将在 Portfolio Overview 中作为可编辑字段显示
# ⚠️ 重要：不再创建局部变量，直接使用 session state
# 这样确保所有地方（包括划转、操作序列等）都使用同一份数据源
# binance_spot_value 和 binance_equity 将直接从 st.session_state 读取

# 初始持仓参数（会被数据编辑器覆盖）
long_size_usdt = 2500000.0
long_entry = 100000.0
short_size_usdt = 0.0
short_entry = 100000.0

# 计算持仓数量（初始值，会在数据编辑器中更新）
long_qty = 0.0
short_qty = 0.0

mm_rate = 0.005  # 0.5%

# ==========================================
# 1.5 操作序列 Session State 初始化
# ==========================================

if 'operations' not in st.session_state:
    st.session_state.operations = []

if 'new_op_price' not in st.session_state:
    st.session_state.new_op_price = 80000.0

if 'new_op_action' not in st.session_state:
    st.session_state.new_op_action = "买入"

if 'new_op_amount_type' not in st.session_state:
    st.session_state.new_op_amount_type = "USDT金额"

if 'new_op_amount' not in st.session_state:
    st.session_state.new_op_amount = 100000.0

if 'new_op_percent' not in st.session_state:
    st.session_state.new_op_percent = 10.0

# 目标价格 session state（保持用户设置不被刷新重置）
if 'target_price' not in st.session_state:
    st.session_state.target_price = 100000.0

# 资金划转 session state
if 'transfer_history' not in st.session_state:
    st.session_state.transfer_history = []

# 账户余额 session state（持久化存储，避免刷新重置）
if 'binance_spot_value' not in st.session_state:
    st.session_state.binance_spot_value = 1_000_000.0

if 'binance_equity' not in st.session_state:
    st.session_state.binance_equity = 2_000_000.0

# ==========================================
# 2. 后端计算引擎 (Engine)
# ==========================================

def calc_liq_price(equity, l_q, l_e, s_q, s_e, mm, curr_p):
    """ 
    计算 Binance 全仓强平价 (Cross Margin Liquidation Price)
    
    使用简化公式（不考虑维持保证金率）：
    Liq = 均价 - Equity / 持仓数量
    
    对于净多单：Liq = 做多均价 - Equity / 做多数量
    对于净空单：Liq = 做空均价 + Equity / 做空数量
    """
    
    net_qty = l_q - s_q
    
    if net_qty > 0:  # 净做多
        if l_q == 0:
            return 0.0
        liq_price = l_e - equity / l_q
    elif net_qty < 0:  # 净空单
        if s_q == 0:
            return 0.0
        liq_price = s_e + equity / s_q
    else:  # 无净持仓
        return 0.0
    
    return max(0.0, liq_price)


def calc_coin_liq_price(position_type, entry_price, leverage=10, mm_rate=0.005):
    """
    计算币本位合约强平价 (Coin-Margined Liquidation Price) - 反向合约
    
    重要：币本位合约的保证金随价格波动，使用非线性公式（除法）
    
    公式来源: Binance 币本位永续合约说明
    - 做多: Entry / (1 + 1/Lev - MMR)
    - 做空: Entry / (1 - 1/Lev + MMR)
    
    参数:
    - position_type: "做多" 或 "做空"
    - entry_price: 开仓均价
    - leverage: 杠杆倍数，默认10倍
    - mm_rate: 维持保证金率，默认0.5%
    
    返回:
    - 强平价格
    """
    if entry_price <= 0:
        return 0.0
    
    inv_leverage = 1 / leverage
    
    if position_type == "做多":
        # 做多强平价：价格下跌时保证金贬值，强平价更高
        denominator = 1 + inv_leverage - mm_rate
        if denominator == 0:
            return 0.0
        liq_price = entry_price / denominator
    else:  # 做空
        # 做空强平价：价格上涨时保证金升值，但合约亏损
        denominator = 1 - inv_leverage + mm_rate
        if denominator <= 0:
            return float('inf')  # 极端情况：无强平点
        liq_price = entry_price / denominator
    
    return max(0.0, liq_price)

def calc_coin_margined_pnl(position_type, entry_price, exit_price, qty_btc):
    """
    计算币本位盈亏 (BTC计价)
    
    币本位是反向合约，以BTC计价盈亏：
    - 做多盈亏: profit_btc = qty × (1/entry - 1/exit)
    - 做空盈亏: profit_btc = qty × (1/exit - 1/entry)
    
    参数:
    - position_type: "做多" 或 "做空"
    - entry_price: 开仓价格 (USD)
    - exit_price: 平仓/当前价格 (USD)
    - qty_btc: 持仓数量 (BTC)
    
    返回:
    - 盈亏 (BTC)
    """
    if entry_price <= 0 or exit_price <= 0:
        return 0.0
    
    if position_type == "做多":
        # 做多：价格上涨时，买回合约需要更少BTC，赚币
        pnl_btc = qty_btc * (1/entry_price - 1/exit_price)
    else:  # 做空
        # 做空：价格下跌时，买回合约需要更少BTC，赚币
        pnl_btc = qty_btc * (1/exit_price - 1/entry_price)
    
    return pnl_btc


# 强平价计算将在数据编辑器之后进行，使用更新后的持仓数据
# current_liq = calc_liq_price(st.session_state.binance_equity, long_qty, long_entry, short_qty, short_entry, mm_rate, current_price)
# current_buffer = (current_price - current_liq) / current_price * 100 if current_price > 0 else 0

# ==========================================
# 2.5 操作序列计算引擎
# ==========================================

def calculate_operation_sequence(operations, start_equity, start_qty, start_entry, current_p):
    """
    计算操作序列执行后的结果
    返回: (final_equity, final_qty, final_entry, operation_points)
    """
    equity = start_equity
    qty = start_qty
    avg_entry = start_entry
    
    # Excel formula tracking variables
    prev_price = start_entry
    net_position = start_qty * start_entry if start_qty > 0 else 0
    floating_position = net_position
    
    # operation_points 用于图表标记
    operation_points = []
    
    # 使用传入的操作顺序（不再强制按价格排序）
    # 调用方负责传入正确排序的操作列表
    for op in operations:
        op_price = op['price']
        op_action = op['action']
        op_amount_type = op['amount_type']
        op_amount = op['amount']
        
        
        # ⚠️ 修复：移除价格移动PnL累加
        # 原逻辑会累加未实现盈亏到equity，导致与目标价推演的重复计算
        # Excel设计中"资金"列保持不变，只有操作才改变equity
        # price_delta = op_price - current_p
        # pnl = price_delta * (qty - short_qty)
        # equity += pnl  # ❌ 删除此行
        
        current_p = op_price  # 只更新当前价格追踪
        
        if op_action == "卖出":
            # 计算卖出数量
            if op_amount_type == "百分比":
                sell_qty = qty * (op_amount / 100)
            else:  # USDT金额
                sell_qty = op_amount / op_price if op_price > 0 else 0
                sell_qty = min(sell_qty, qty)  # 不能卖出超过持仓
            
            # 执行卖出
            realized_pnl = (op_price - avg_entry) * sell_qty
            equity += realized_pnl
            qty -= sell_qty
            
            # ⚠️ 关键修复：卖出后更新 net_position 和 floating_position
            # 卖出比例
            sell_ratio = sell_qty / (qty + sell_qty) if (qty + sell_qty) > 0 else 0
            
            # 按比例减少净持仓和浮动持仓
            net_position = net_position * (1 - sell_ratio)
            floating_position = floating_position * (1 - sell_ratio)
            
            operation_points.append({
                'price': op_price,
                'equity': equity,
                'action': '卖出',
                'qty_change': -sell_qty
            })
            
        else:  # 买入
            # 计算买入数量
            if op_amount_type == "百分比":
                # 百分比基于当前持仓价值
                buy_value = (qty * op_price) * (op_amount / 100)
                buy_qty = buy_value / op_price if op_price > 0 else 0
                effective_usdt = buy_value
            else:  # USDT金额
                buy_qty = op_amount / op_price if op_price > 0 else 0
                effective_usdt = op_amount
            
            
            # ⚠️ 匹配Excel：不扣除保证金
            # Excel假设不占用保证金或全额买入
            # platform = op.get('platform', 'binance')
            # if platform == 'binance':
            #     margin_required = effective_usdt / 10
            #     equity -= margin_required
            
            # Excel formula: 保存前一个均价
            prev_avg = avg_entry
            
            # Excel formula: Net Position
            prev_net = net_position
            net_position += effective_usdt
            
            # Excel formula: Floating Position - 价格方向判断
            if prev_net > 0:
                if op_price < prev_price:  # 价格下跌
                    floating_position = effective_usdt + prev_net - (prev_avg - op_price) * prev_net / prev_avg
                else:  # 价格上涨
                    floating_position = effective_usdt + prev_net + (prev_avg - op_price) * prev_net / prev_avg
            else:
                floating_position = effective_usdt
            
            # Excel formula: Average Price
            if floating_position > 0:
                avg_entry = ((op_price * effective_usdt) + prev_avg * (floating_position - effective_usdt)) / floating_position
            
            # 更新持仓数量
            qty += buy_qty
            prev_price = op_price
            
            operation_points.append({
                'price': op_price,
                'equity': equity,
                'action': '买入',
                'qty_change': buy_qty
            })
    
    return equity, qty, avg_entry, net_position, operation_points

# ==========================================
# 3. 界面布局 (UI Layout)
# ==========================================

# Row 1: Portfolio Overview (全宽)
with st.container(border=True):
    st.header("1. 资产概览")
    
    # 添加数据编辑器
    with st.expander("📝 编辑数据", expanded=False):
        col_edit1, col_edit2 = st.columns(2)
        
        with col_edit1:
            st.subheader("市场与持仓")
            current_price = st.number_input("BTC 当前价格", value=current_price, step=100.0, key="edit_price")
            
            # 直接使用 session state 值，确保持久化
            binance_spot_value = st.number_input(
                "Binance 现货价值", 
                value=st.session_state.binance_spot_value, 
                step=10000.0, 
                key="edit_binance_spot"
            )
            binance_equity = st.number_input(
                "Binance 权益", 
                value=st.session_state.binance_equity, 
                step=10000.0, 
                key="edit_equity"
            )
            
            # 币本位账户 (BTC计价)
            if 'coin_margined_btc' not in st.session_state:
                st.session_state.coin_margined_btc = 0.0
            
            coin_margined_btc = st.number_input(
                "币本位账户 (BTC)",
                value=st.session_state.coin_margined_btc,
                min_value=0.0,
                step=0.5,
                key="edit_coin_margined",
                help="币本位合约账户的BTC保证金"
            )
            
            # 立即同步到 session state
            st.session_state.binance_spot_value = binance_spot_value
            st.session_state.binance_equity = binance_equity
            st.session_state.coin_margined_btc = coin_margined_btc

        
        with col_edit2:
            st.subheader("合约持仓")
            long_size_usdt = st.number_input("做多持仓价值", value=long_size_usdt, step=10000.0, key="edit_long_size")
            long_entry = st.number_input("做多均价", value=long_entry, step=100.0, key="edit_long_entry")
            short_size_usdt = st.number_input("做空持仓价值", value=short_size_usdt, step=10000.0, key="edit_short_size")
            if short_size_usdt > 0:
                short_entry = st.number_input("做空均价", value=short_entry, step=100.0, key="edit_short_entry")
        
        # 同步到 session state（当用户手动编辑时）
        st.session_state.binance_spot_value = binance_spot_value
        st.session_state.binance_equity = binance_equity
        st.session_state.coin_margined_btc = coin_margined_btc
        
        # 重新计算持仓数量
        long_qty = long_size_usdt / long_entry if long_entry else 0
        short_qty = short_size_usdt / short_entry if (short_entry and short_size_usdt > 0) else 0
    
    # ⚠️ 重要：从 session state 重新获取最新值，确保后续计算使用最新的余额
    # （这样在数据编辑或资金划转后，操作序列和目标价推演都会使用最新值）
    # 注意：直接使用 st.session_state，不创建局部变量
    
    # ===== 强平价计算（使用编辑器更新后的数据） =====
    current_liq = calc_liq_price(
        st.session_state.binance_equity, 
        long_qty, 
        long_entry, 
        short_qty, 
        short_entry, 
        mm_rate, 
        current_price
    )
    current_buffer = (current_price - current_liq) / current_price * 100 if current_price > 0 else 0
    
    # 计算总资产组合
    luno_btc_qty = st.session_state.binance_spot_value / current_price if current_price > 0 else 0
    total_portfolio = st.session_state.binance_equity + st.session_state.binance_spot_value
    
    # Row 1: 总资产
    st.markdown("#### 总资产组合")
    p1, p2 = st.columns(2)
    p1.metric("总资产", f"${total_portfolio:,.0f}", help="Binance合约 + Binance现货 总资产")
    total_position_value = (long_qty - short_qty) * current_price + st.session_state.binance_spot_value
    p2.metric("总持仓价值", f"${total_position_value:,.0f}", 
              help="全部持仓价值（含现货和合约净头寸）")
    
    st.markdown("---")
    
    # Row 2: Binance 合约
    st.markdown("#### Binance 合约")
    b1, b2 = st.columns(2)
    b1.metric("Binance 权益", f"${binance_equity:,.0f}", help="初始本金（不含未实现盈亏，参考Excel设计）")
    b2.metric("未实现盈亏", f"${(current_price-long_entry)*long_qty + (short_entry-current_price)*short_qty:,.0f}")
    
    st.markdown("---")
    
    # Row 3: Binance 现货
    st.markdown("#### Binance 现货")
    l1, l2 = st.columns(2)
    l1.metric("现货价值", f"${st.session_state.binance_spot_value:,.0f}", help="Binance现货资产价值")
    l2.metric("现货持仓", f"${st.session_state.binance_spot_value:,.0f}", help="Binance现货持仓价值")
    
    st.markdown("---")
    
    # Row 4: 风险指标
    st.markdown("#### 风险指标")
    r1, r2 = st.columns(2)
    r1.metric("强平价", f"${current_liq:,.2f}", 
              delta=f"安全垫: ${current_price - current_liq:,.0f}", 
              delta_color="normal")
    
    # 风险仪表盘
    gauge_color = "green" if current_buffer > 40 else ("orange" if current_buffer > 20 else "red")
    r2.markdown(f"""
        <div style="border:1px solid #ddd; border-radius:5px; padding:10px; text-align:center; background:#f8f9fa;">
            <span style="color:#666; font-size:12px;">风险缓冲</span><br>
            <span style="color:{gauge_color}; font-size:24px; font-weight:bold;">{current_buffer:.1f}%</span>
        </div>
    """, unsafe_allow_html=True)

# ==========================================
# Row 1.5: Fund Transfer Panel
# ==========================================
with st.container(border=True):
    st.header("💸 资金划转")

    # 显示可用余额
    col_bal1, col_bal2, col_bal3 = st.columns(3)
    col_bal1.metric("Binance 现货", f"${st.session_state.binance_spot_value:,.0f}")
    col_bal2.metric("Binance 权益", f"${st.session_state.binance_equity:,.0f}")
    col_bal3.metric("总资产", f"${st.session_state.binance_spot_value + st.session_state.binance_equity:,.0f}")

    st.markdown("---")

    # 划转控制面板
    transfer_col1, transfer_col2 = st.columns([1, 1])
    
    with transfer_col1:
        st.markdown("#### 划转设置")
        
        # 划转方向
        direction = st.radio(
            "划转方向",
            options=["现货 → 合约", "合约 → 现货"],
            key="transfer_direction",
            horizontal=True
        )
        
        direction_key = 'spot_to_contract' if direction == "现货 → 合约" else 'contract_to_spot'
        
        # 计算可用余额 - 使用 session state 值
        max_available = te.calculate_available_to_transfer(
            direction_key, 
            st.session_state.binance_spot_value,  # 使用 session state
            st.session_state.binance_equity,    # 使用 session state
            long_qty, long_entry, short_qty, short_entry,
            mm_rate, current_price
        )
        
        # 划转金额输入
        transfer_amount = st.number_input(
            "划转金额 (USDT)",
            min_value=0.0,
            max_value=max_available,
            value=min(100000.0, max_available),
            step=10000.0,
            key="transfer_amount_input",
            help=f"最大可划转: ${max_available:,.0f}"
        )
        
        st.caption(f"💡 安全可划转上限: ${max_available:,.0f}")
    
    with transfer_col2:
        st.markdown("#### 影响预览")
        
        # 验证划转 - 使用 session state 值
        is_valid, error_msg, warning_msg = te.validate_transfer(
            direction_key, transfer_amount, 
            st.session_state.binance_spot_value,  # 使用 session state
            st.session_state.binance_equity,    # 使用 session state
            long_qty, long_entry, short_qty, short_entry, mm_rate, current_price,
            calc_liq_price_func=calc_liq_price
        )
        
        if transfer_amount > 0:
            # 计算划转影响 - 使用 session state 值
            impact = te.calculate_transfer_impact(
                direction_key, transfer_amount, 
                st.session_state.binance_spot_value,  # 使用 session state
                st.session_state.binance_equity,    # 使用 session state
                long_qty, long_entry, short_qty, short_entry, mm_rate, current_price,
                calc_liq_price_func=calc_liq_price
            )
            
            # 显示划转后的状态
            st.markdown("**划转后账户余额:**")
            after_col1, after_col2 = st.columns(2)
            
            luno_delta = impact['luno_change']
            binance_delta = impact['binance_change']
            
            after_col1.metric(
                "Luno", 
                f"${impact['luno_after']:,.0f}",
                delta=f"{luno_delta:+,.0f}"
            )
            after_col2.metric(
                "Binance", 
                f"${impact['binance_after']:,.0f}",
                delta=f"{binance_delta:+,.0f}"
            )
            
            st.markdown("**风险指标变化:**")
            risk_col1, risk_col2 = st.columns(2)
            
            liq_delta = impact['liq_price_change']
            liq_delta_color = "inverse" if liq_delta > 0 else "normal"
            
            risk_col1.metric(
                "强平价",
                f"${impact['liq_price_after']:,.0f}",
                delta=f"{liq_delta:+,.0f}",
                delta_color=liq_delta_color
            )
            
            buffer_delta = impact['buffer_change']
            buffer_delta_color = "normal" if buffer_delta > 0 else "inverse"
            
            risk_col2.metric(
                "风险缓冲",
                f"{impact['buffer_after']:.1f}%",
                delta=f"{buffer_delta:+.1f}%",
                delta_color=buffer_delta_color
            )
            
            # 显示警告或错误
            if error_msg:
                st.error(f"❌ {error_msg}")
            elif warning_msg:
                st.warning(warning_msg)
            else:
                st.success("✅ 划转安全，可以执行")
        else:
            st.info("请输入划转金额查看影响预览")
    
    st.markdown("---")
    
    # 执行按钮
    button_col1, button_col2, button_col3 = st.columns([1, 1, 1])
    
    with button_col2:
        execute_disabled = not is_valid or transfer_amount <= 0
        
        if st.button(
            "🚀 执行划转",
            type="primary",
            use_container_width=True,
            disabled=execute_disabled,
            help="确认执行资金划转" if not execute_disabled else error_msg
        ):
            # 执行划转 - 使用 session state 的最新值而不是局部变量
            new_luno, new_binance = te.execute_transfer(
                direction_key, transfer_amount, 
                st.session_state.binance_spot_value,  # 使用 session state 值
                st.session_state.binance_equity     # 使用 session state 值
            )
            
            # 更新 session state
            st.session_state.binance_spot_value = new_luno
            st.session_state.binance_equity = new_binance
            
            # 记录历史
            transfer_record = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'direction': direction,
                'amount': transfer_amount,
                'luno_after': new_luno,
                'binance_after': new_binance
            }
            st.session_state.transfer_history.append(transfer_record)
            
            st.success(f"✅ 划转成功！已将 ${transfer_amount:,.0f} 从 {direction}")
            st.rerun()
    
    # 划转历史
    if len(st.session_state.transfer_history) > 0:
        st.markdown("---")
        st.markdown("#### 📜 划转历史")
        
        # 创建历史记录表格
        history_df = pd.DataFrame(st.session_state.transfer_history)
        
        # 格式化显示
        display_df = history_df.copy()
        display_df['金额'] = display_df['amount'].apply(lambda x: f"${x:,.0f}")
        display_df['时间'] = display_df['timestamp']
        display_df['方向'] = display_df['direction']
        
        # 只显示最近5条
        recent_history = display_df[['时间', '方向', '金额']].tail(5).iloc[::-1]
        
        st.dataframe(
            recent_history,
            use_container_width=True,
            hide_index=True
        )
        
        # 清空历史按钮
        if st.button("🗑️ 清空历史记录"):
            st.session_state.transfer_history = []
            st.rerun()

# ⚠️ 关键：从 session state 获取值用于后续计算
# 不创建局部变量，确保所有地方使用同一数据源
# 同时重新计算当前强平价和风险缓冲（基于最新资金量）
current_liq = calc_liq_price(st.session_state.binance_equity, long_qty, long_entry, short_qty, short_entry, mm_rate, current_price)
current_buffer = (current_price - current_liq) / current_price * 100 if current_price > 0 else 0

# Row 2: Operation Sequencer (左) + Target Price Calculator (右)
row2_col1, row2_col2 = st.columns(2)

# --- 2. Operation Sequencer (Left) ---
# 操作序列编辑器：定义多个买入/卖出操作
with row2_col1.container(border=True):
    st.header("2. 操作序列")
    
    # 创建 Binance 和 Luno 两个标签页
    tab1, tab2, tab3 = st.tabs([
        "🔶 Binance 合约 (U本位 10x)", 
        "🟦 Binance 现货",
        "🟡 币本位合约 (10x)"
    ])
    
    # === Binance Tab ===
    with tab1:
        
        # 显示可用资金
        available_binance = binance_equity
        st.caption(f"💰 当前 Binance 权益：${available_binance:,.0f} | 最大可开仓位：${available_binance * 10:,.0f}")
        
        st.markdown("#### ➕ 添加 Binance 合约操作")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            binance_price = st.number_input("触发价格", value=st.session_state.new_op_price, step=100.0, key="binance_input_price")
        
        with col2:
            binance_action = st.selectbox("动作", ["买入", "卖出"], key="binance_input_action")
        
        # 金额输入 - 优先使用 USDT 金额
        binance_amount_mode = st.radio("金额方式", ["USDT金额", "百分比"], horizontal=True, key="binance_input_amount_mode")
        
        if binance_amount_mode == "USDT金额":
            # 计算最大可开仓位（权益 * 10）
            max_position = available_binance * 10
            binance_amount_usdt = st.number_input("仓位金额 (USDT)", 
                                                   min_value=0.0,
                                                   max_value=max_position,
                                                   value=min(1000000.0, max_position), 
                                                   step=100000.0, 
                                                   key="binance_input_amount",
                                                   help=f"输入目标仓位金额，系统自动计算所需保证金（仓位÷10）\n最大可开：${max_position:,.0f}")
            binance_amount = binance_amount_usdt
        else:
            binance_percent = st.slider("百分比 (%)", 0.0, 100.0, 10.0, 1.0, key="binance_input_percent")
            binance_amount = binance_percent
        
        with col3:
            st.write("")  # spacing
            st.write("")  # spacing
            if st.button("➕ 添加", use_container_width=True, key="binance_add_btn"):
                new_op = {
                    'price': binance_price,
                    'action': binance_action,
                    'amount_type': binance_amount_mode,
                    'amount': binance_amount,
                    'platform': 'binance',
                    'leverage': 10
                }
                st.session_state.operations.append(new_op)
                st.session_state.new_op_price = binance_price  # 保存输入
                st.rerun()
    
    # === Luno Tab ===
    with tab2:        
        # 显示可用资金
        available_luno = st.session_state.binance_spot_value
        st.caption(f"💰 当前 Luno 余额：${available_luno:,.0f}")
        
        st.markdown("#### ➕ 添加 Binance 现货操作")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            luno_price = st.number_input("触发价格", value=st.session_state.new_op_price, step=100.0, key="luno_input_price")
        
        with col2:
            luno_action = st.selectbox("动作", ["买入", "卖出"], key="luno_input_action")
        
        # 金额输入 - 优先使用 USDT 金额
        luno_amount_mode = st.radio("金额方式", ["USDT金额", "百分比"], horizontal=True, key="luno_input_amount_mode")
        
        if luno_amount_mode == "USDT金额":
            luno_amount_usdt = st.number_input("现货金额 (USDT)", 
                                               min_value=0.0,
                                               max_value=available_luno,
                                               value=min(100000.0, available_luno), 
                                               step=10000.0, 
                                               key="luno_input_amount",
                                               help=f"输入购买现货的金额\n最大可用：${available_luno:,.0f}")
            luno_amount = luno_amount_usdt
        else:
            luno_percent = st.slider("百分比 (%)", 0.0, 100.0, 10.0, 1.0, key="luno_input_percent")
            luno_amount = luno_percent
        
        with col3:
            st.write("")  # spacing
            st.write("")  # spacing
            if st.button("➕ 添加", use_container_width=True, key="luno_add_btn"):
                new_op = {
                    'price': luno_price,
                    'action': luno_action,
                    'amount_type': luno_amount_mode,
                    'amount': luno_amount,
                    'platform': 'binance_spot',
                    'leverage': 1
                }
                st.session_state.operations.append(new_op)
                st.session_state.new_op_price = luno_price  # 保存输入
                st.rerun()
    
    # === 币本位 Tab ===
    with tab3:
        st.info("💡 币本位逻辑：赚币亏币。做多时由 (1+1/Lev) 决定强平，比U本位更容易触及强平线。")
        
        st.markdown("#### ➕ 添加币本位合约操作")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            coin_price = st.number_input(
                "开仓均价 (USD)", 
                value=st.session_state.new_op_price, 
                step=100.0, 
                key="coin_input_price"
            )
        
        with col2:
            coin_position_type = st.selectbox(
                "仓位方向", 
                ["做多", "做空"], 
                key="coin_position_type"
            )
        
        # 持仓数量（BTC）- 仅作记录用
        coin_amount = st.number_input(
            "持仓数量 (BTC)", 
            min_value=0.0,
            value=1.0, 
            step=0.1, 
            key="coin_input_amount",
            help="此处仅作记录。注意：Binance实际交易中 1张BTC合约=100USD。"
        )
        
        # 计算强平价（使用修正后的反向合约公式）
        coin_liq_price = calc_coin_liq_price(
            coin_position_type, 
            coin_price, 
            leverage=10, 
            mm_rate=mm_rate
        )
        
        # 根据方向显示强平预警
        if coin_position_type == "做多":
            st.write(f"📉 下跌至 **${coin_liq_price:,.2f}** 强平")
        else:
            st.write(f"📈 上涨至 **${coin_liq_price:,.2f}** 强平")
        
        with col3:
            st.write("")  # spacing
            st.write("")  # spacing
            if st.button("➕ 添加", use_container_width=True, key="coin_add_btn"):
                new_op = {
                    'price': coin_price,
                    'action': coin_position_type,  # "做多" 或 "做空"
                    'amount_type': 'BTC',  # 统一标记
                    'amount': coin_amount,
                    'platform': 'coin_margined',
                    'leverage': 10,
                    'liq_price': coin_liq_price  # 保存强平价
                }
                st.session_state.operations.append(new_op)
                st.session_state.new_op_price = coin_price  # 保持最后输入的价格
                st.rerun()
    
    st.markdown("---")
    
    # 显示操作列表
    st.markdown("#### 📋 操作列表与预览")
    
    if len(st.session_state.operations) == 0:
        st.info("暂无操作。点击上方「➕ 添加」按钮添加操作。")
    else:
        # 计算整个操作序列的执行结果（用于显示）
        sim_binance_equity = st.session_state.binance_equity
        sim_luno_value = st.session_state.binance_spot_value
        sim_coin_margined_btc = st.session_state.coin_margined_btc  # 新增：币本位BTC账户
        sim_qty = long_qty
        sim_entry = long_entry
        sim_price = current_price
        
        # ⚠️ 关键修复：保存初始权益用于强平价计算
        # 强平价应基于初始权益（买入前的总权益），而非操作过程中扣除保证金后的权益
        initial_equity_for_liq = st.session_state.binance_equity
        
        # Excel formula tracking variables
        prev_price = long_entry if long_qty > 0 else current_price  # 前一个操作价格
        net_position = long_qty * long_entry if long_qty > 0 else 0  # D列：净持仓（累积成本）
        floating_position = net_position  # E列：浮动持仓
        
        # 按时间顺序执行操作（匹配Excel）
        sorted_ops = st.session_state.operations  # 保持原始添加顺序
        
        # 表格表头 - 移除总权益列
        h0, h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([0.4, 0.7, 1.0, 1.0, 0.9, 0.9, 1.1, 1.0, 0.4])
        h0.markdown("**平台**")
        h1.markdown("**操作**")
        h2.markdown("**触发价**")
        h3.markdown("**金额**")
        h4.markdown("**持仓均价**")
        h5.markdown("**币本位 BTC**")
        h6.markdown("**Binance (U)**")
        h7.markdown("**强平价**")
        h8.write("") # 删除按钮列
        
        st.markdown("---")
        
        # 添加自定义滚动条样式
        st.markdown("""
            <style>
            /* 自定义滚动条样式 */
            div[data-testid="stVerticalBlock"] > div[style*="overflow"] {
                scrollbar-width: thin;
                scrollbar-color: #888 #f1f1f1;
            }
            
            div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar {
                width: 8px;
            }
            
            div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar-track {
                background: #f1f1f1;
                border-radius: 4px;
            }
            
            div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar-thumb {
                background: #888;
                border-radius: 4px;
            }
            
            div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar-thumb:hover {
                background: #555;
            }
            </style>
        """, unsafe_allow_html=True)
        
        # 使用带高度限制的容器包裹操作列表（Streamlit 原生支持）
        ops_container = st.container(height=400)
        
        with ops_container:
            for idx, op in enumerate(sorted_ops):
                # 向后兼容：旧操作没有 platform 字段，默认为 binance
                platform = op.get('platform', 'binance')
                leverage = op.get('leverage', 10)
                # 模拟执行到这个操作
                op_price = op['price']
                
                # 价格变动的PnL (仅对 Binance 合约)
                if platform == 'binance':
                    price_delta = op_price - sim_price
                    pnl = price_delta * (sim_qty - short_qty)
                    sim_binance_equity += pnl
                sim_price = op_price
                
                # --- 执行操作并计算实际金额 ---
                effective_usdt = 0.0
                
                if platform == 'binance':
                    # Binance 合约操作 (10x 杠杆)
                    if op['action'] == "卖出":
                        if op['amount_type'] == "百分比":
                            sell_qty = sim_qty * (op['amount'] / 100)
                            effective_usdt = sell_qty * op_price
                        else:
                            sell_qty = op['amount'] / op_price if op_price > 0 else 0
                            sell_qty = min(sell_qty, sim_qty)
                            effective_usdt = sell_qty * op_price
                        
                        realized_pnl = (op_price - sim_entry) * sell_qty
                        sim_binance_equity += realized_pnl
                        sim_qty -= sell_qty
                        
                        # ⚠️ 关键修复：卖出后更新 net_position 和 floating_position
                        # 卖出比例
                        sell_ratio = sell_qty / (sim_qty + sell_qty) if (sim_qty + sell_qty) > 0 else 0
                        
                        # 按比例减少净持仓和浮动持仓
                        net_position = net_position * (1 - sell_ratio)
                        floating_position = floating_position * (1 - sell_ratio)
                        
                    else:  # 买入 - 使用Excel公式
                        if op['amount_type'] == "百分比":
                            buy_value = (sim_qty * op_price) * (op['amount'] / 100)
                            buy_qty = buy_value / op_price if op_price > 0 else 0
                            margin_used = buy_value / 10  # 实际使用的保证金
                            effective_usdt = buy_value  # 显示仓位价值
                        else:
                            # USDT金额现在是仓位金额，不是保证金
                            position_value = op['amount']
                            buy_qty = position_value / op_price if op_price > 0 else 0
                            margin_used = position_value / 10  # 实际使用的保证金
                            effective_usdt = position_value  # 显示仓位价值
                        
                        # 扣除保证金
                        sim_binance_equity -= margin_used
                        
                        # Excel formula: 保存前一个均价（用于浮动持仓计算）
                        prev_avg = sim_entry
                        
                        # Excel formula: Net Position (D列)
                        prev_net_position = net_position
                        net_position += effective_usdt  # 累加仓位价值
                        
                        # Excel formula: Floating Position (E列) - 使用净持仓前值和均价前值
                        if prev_net_position > 0:  # 有前一次的净持仓
                            if op_price < prev_price:  # 价格下跌
                                floating_position = effective_usdt + prev_net_position - (prev_avg - op_price) * prev_net_position / prev_avg
                            else:  # 价格上涨或持平
                                floating_position = effective_usdt + prev_net_position + (prev_avg - op_price) * prev_net_position / prev_avg
                        else:  # 首次买入
                            floating_position = effective_usdt
                        
                        # Excel formula: Average Price (F列) - 基于浮动持仓
                        if floating_position > 0:
                            sim_entry = ((op_price * effective_usdt) + sim_entry * (floating_position - effective_usdt)) / floating_position
                        
                        # 更新持仓数量
                        sim_qty += buy_qty
                        
                        # 更新前一个价格用于下次比较
                        prev_price = op_price
                
                elif platform == 'binance_spot':
                    # Binance 现货操作 (1x, 无杠杆)
                    if op['action'] == "卖出":
                        # 卖出现货，获得 USDT
                        if op['amount_type'] == "百分比":
                            # 百分比基于当前 Binance 现货价值
                            sell_value = sim_luno_value * (op['amount'] / 100)
                            effective_usdt = sell_value
                        else:
                            effective_usdt = op['amount']
                        sim_luno_value += effective_usdt
                    else:  # 买入
                        # 买入现货，花费 USDT
                        if op['amount_type'] == "百分比":
                            buy_value = sim_luno_value * (op['amount'] / 100)
                            effective_usdt = buy_value
                        else:
                            effective_usdt = op['amount']
                        sim_luno_value -= effective_usdt
                
                elif platform == 'coin_margined':
                    # 币本位合约操作 - 以BTC计价盈亏
                    # 简化模型：假设每次操作都是开仓，价格变化即刻结算
                    # 注意：实际币本位需要追踪持仓，这里简化为即时P&L计算
                    
                    # 当前只记录操作的USD价值用于显示
                    effective_usdt = op['amount'] * op_price  # BTC数量 * 价格 = USD价值
                    
                    # TODO: 完整实现需要追踪币本位持仓并计算盈亏
                    # 当前版本：币本位账户余额保持不变（不参与模拟）
                    # 未来版本：需要实现持仓管理和盈亏结算

                
                # 计算强平价 - Excel formula: 基于净持仓（D列，不是浮动持仓E列）
                if platform == 'binance':
                    # 强平价 = 均价 - (初始权益 / 净持仓) * 均价
                    if net_position > 0:
                        sim_liq = sim_entry - (initial_equity_for_liq / net_position) * sim_entry
                        sim_liq = max(0.0, sim_liq)  # ⚠️ 强平价不能为负数
                    else:
                        sim_liq = 0
                elif platform == 'coin_margined':
                    # 币本位使用预先计算的强平价
                    sim_liq = op.get('liq_price', 0)
                    sim_liq = max(0.0, sim_liq)  # ⚠️ 强平价不能为负数
                else:
                    sim_liq = None  # Binance 现货无强平价
                
                # 格式化显示金额 (总是显示 USDT 估值)
                if op['amount_type'] == "百分比":
                    amount_str = f"{op['amount']:.0f}% (${effective_usdt:,.0f})"
                else:
                    amount_str = f"${effective_usdt:,.0f}"
                
                # 平台标识
                if platform == 'binance':
                    platform_icon = "🔶"
                    platform_text = "Binance"
                elif platform == 'binance_spot':
                    platform_icon = "🟦"
                    platform_text = "Luno"
                elif platform == 'coin_margined':
                    platform_icon = "🟡"
                    platform_text = "币本位"
                else:
                    platform_icon = "❓"
                    platform_text = "未知"
                
                # 显示行 - 移除总权益列
                c0, c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([0.4, 0.7, 1.0, 1.0, 0.9, 0.9, 1.1, 1.0, 0.4])
                
                # 平台标识
                c0.markdown(f"{platform_icon}")
                
                # 操作类型带颜色
                action_color = "green" if op['action'] == "买入" else "red"
                
                c1.markdown(f"**{op['action']}**")
                c2.markdown(f"${op_price:,.0f}")
                c3.markdown(amount_str)
                
                # 显示持仓均价（加权平均价）
                c4.markdown(f"${sim_entry:,.2f}")
                
                # 币本位 BTC
                c5.markdown(f"{sim_coin_margined_btc:.4f}")
                
                # Binance U本位 USDT
                c6.markdown(f"${sim_binance_equity:,.0f}")
                
                # 强平价显示（根据平台类型）
                if platform == 'binance' and sim_liq is not None:
                    liq_delta = sim_liq - current_liq
                    liq_color = "red" if liq_delta > 0 else "green"
                    c7.markdown(f":{liq_color}[${sim_liq:,.0f}]")
                elif platform == 'coin_margined' and sim_liq is not None:
                    # 币本位显示预设的强平价
                    c7.markdown(f"${sim_liq:,.0f}")
                else:
                    c7.markdown("N/A")  # 现货无强平
                
                # 删除按钮
                if c8.button("🗑️", key=f"del_{idx}_{op_price}", help="删除此操作"):
                     for j, original_op in enumerate(st.session_state.operations):
                        if original_op['price'] == op['price'] and original_op['action'] == op['action']:
                            st.session_state.operations.pop(j)
                            break
                     st.rerun()
                
                # 加一点行间距
                st.markdown("<div style='margin-top: -10px'></div>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 显示最终状态总结
        st.markdown("#### 📈 操作序列执行后")
        final_col1, final_col2, final_col3 = st.columns(3)
        
        # 计算最终价格（最后一个操作的价格）
        final_price = sorted_ops[-1]['price'] if len(sorted_ops) > 0 else current_price
        
        # Binance U本位权益
        equity_change = sim_binance_equity - st.session_state.binance_equity
        final_col1.metric("Binance (U)", f"${sim_binance_equity:,.0f}", 
                         delta=f"{equity_change:+,.0f}",
                         help="U本位合约账户USDT余额")
        
        # U本位合约净持仓（USDT计价）- 会随买入/卖出变动
        # net_position 代表虚拟的合约仓位价值
        initial_net_position = long_qty * long_entry if long_qty > 0 else 0
        net_position_change = net_position - initial_net_position
        
        # 计算对应的BTC数量（用于tooltip）
        position_btc = net_position / final_price if final_price > 0 else 0
        
        final_col2.metric("持仓总量", f"${net_position:,.0f}", 
                         delta=f"{net_position_change:+,.0f}",
                         help=f"U本位合约净持仓价值 (约 {position_btc:.4f} BTC)")
        
        
        # 强平价只在有 Binance 操作时显示
        if sim_liq is not None:
            liq_change = sim_liq - current_liq
            final_col3.metric("U本位强平价", f"${sim_liq:,.0f}", 
                             delta=f"{liq_change:+,.0f}",
                             delta_color="inverse" if liq_change > 0 else "normal",
                             help="U本位合约强平价")
        else:
            final_col3.metric("U本位强平价", "N/A", help="无U本位操作")

    
    # 快速清空
    if len(st.session_state.operations) > 0:
        if st.button("🗑️ 清空所有操作"):
            st.session_state.operations = []
            st.rerun()
    
    # 根据选中的 tab 决定后续使用哪个值 (减仓或加仓后的状态)
    # 这里我们默认使用减仓的逻辑，因为原代码后续步骤依赖 remain_qty
    # 如果用户选择了加仓，需要在 Scenario Simulation 中相应调整
    
    # 创建默认变量以保持向后兼容
    action_1_sell_pct = 0
    sell_qty = 0
    realized_pnl_step1 = 0
    remain_qty = long_qty
    enable_reentry = False
    reentry_price = None
    final_qty_after_reentry = long_qty

# --- 3. Target Price Calculator (Right) ---
# 目标价计算器：对比 Hold vs 操作序列执行后的结果
with row2_col2.container(border=True):
    st.header("3. 目标价推演")
    
    # 显示当前使用的策略
    if len(st.session_state.operations) > 0:
        st.success(f"✅ 已启用操作序列 ({len(st.session_state.operations)} 个操作)")
    else:
        st.info("ℹ️ 未设置操作序列，对比结果将相同")
    
    # 输入目标价 - 使用 session state 保持值不被重置
    target_price = st.number_input(
        "目标价格 (Target Price)", 
        min_value=0.0,
        value=st.session_state.target_price,
        step=1000.0,
        format="%.2f",
        help="设定BTC目标价格，计算到达时的盈亏"
    )
    
    # 更新 session state（用户修改后保存）
    st.session_state.target_price = target_price
    
    st.markdown("---")
    
    # === 情景对比 ===
    st.markdown("#### 📊 情景对比")
    
    # === 情景 A: Hold（不操作，保持当前状态到目标价） ===
    # 注意：情景 A 完全不考虑操作序列，只基于当前持仓和目标价
    # 盈亏 = (目标价 - 开仓均价) × 持仓数量
    hold_pnl = (target_price - long_entry) * (long_qty - short_qty)
    hold_equity_final = st.session_state.binance_equity + hold_pnl
    
    # === 情景 B: 执行操作序列（考虑第2板块的所有操作） ===
    op_points_for_chart = [] # 存储用于绘图的操作点
    
    if len(st.session_state.operations) > 0:
        # ⚠️ 核心修复：calculate_operation_sequence 返回执行操作后的实际权益
        # 包括所有卖出的实现盈亏（可能是亏损）
        seq_equity, seq_qty, seq_entry, seq_net_position, op_points = calculate_operation_sequence(
            st.session_state.operations,  # 直接使用时间顺序
            st.session_state.binance_equity,
            long_qty,
            long_entry,
            current_price
        )
        op_points_for_chart = op_points # 保存给图表使用
        
        # ⚠️ Excel逻辑（绝对值计算）：
        # 从当前价到目标价的浮盈
        # 有效持仓数量 = 净持仓 / 均价
        # 浮盈 = (目标价 - 当前价) × 有效持仓数量
        # 最终权益 = 操作后权益 + 浮盈
        effective_qty = seq_net_position / seq_entry if seq_entry > 0 else 0
        floating_pnl = (target_price - seq_entry) * effective_qty  # Excel: (H-F)*D/F
        adjusted_equity_final = seq_equity + floating_pnl  # ⚠️ 修复：使用操作后权益
        
        adjusted_qty_display = seq_qty
        strategy_label = f"操作序列 ({len(st.session_state.operations)}步)"
        
        # 计算执行操作序列后的最终强平价
        final_liq_after_ops = calc_liq_price(
            seq_equity,  # ⚠️ 修复：使用操作后的实际权益
            seq_qty,  # 使用操作后的持仓数量
            seq_entry,  # 使用操作后的均价
            short_qty, 
            short_entry, 
            mm_rate, 
            current_price
        )
    else:
        # 没有操作，等同于 Hold
        adjusted_equity_final = hold_equity_final
        adjusted_qty_display = long_qty
        strategy_label = "无操作 (= Hold)"
        final_liq_after_ops = current_liq  # 没有操作，强平价不变
    
    # 显示对比
    col_hold, col_adjusted = st.columns(2)
    
    with col_hold:
        st.markdown("**情景 A: Hold (死扛)**")
        st.info("💡 不考虑任何操作，保持当前持仓到目标价")
        st.metric("剩余资金(止盈)", f"${hold_equity_final:,.0f}")
        st.metric("浮盈", f"${hold_pnl:,.0f}", 
                  delta=f"vs 现在",
                  delta_color="normal")
    
    with col_adjusted:
        st.markdown(f"**情景 B: {strategy_label}**")
        # 始终显示info框以保持和情景A对齐
        if len(st.session_state.operations) > 0:
            st.info(f"⚙️ 考虑第2板块的 {len(st.session_state.operations)} 个操作")
        else:
            st.info("💡 未设置操作序列，结果与情景A相同")
        st.metric("剩余资金(止盈)", f"${adjusted_equity_final:,.0f}")
        total_pnl_adjusted = adjusted_equity_final - st.session_state.binance_equity
        st.metric("浮盈", f"${total_pnl_adjusted:,.0f}", 
                  delta=f"vs 现在",
                  delta_color="normal")
    
    st.markdown("---")
    
    # 对比结果 - 增强显示
    difference = adjusted_equity_final - hold_equity_final
    difference_pct = (difference / hold_equity_final * 100) if hold_equity_final != 0 else 0
    
    
    if difference > 0:
        st.success(f"✅ **操作优势**: {strategy_label}策略比死扛多赚 **${difference:,.0f}** (+{difference_pct:.2f}%)")
    elif difference < 0:
        st.error(f"⚠️ **操作劣势**: {strategy_label}策略比死扛少赚 **${abs(difference):,.0f}** ({difference_pct:.2f}%)")
    else:
        st.info("➡️ 两种策略结果相同")

# ==========================================
# 4. Strategy Outlook (可视化图表) - Row 3
# ==========================================
with st.container(border=True):
    st.header("4. 策略推演图 (Strategy Outlook)")
    
    # 准备数据 - 图表范围聚焦于当前价到目标价
    # 确定主要范围（当前价 <-> 目标价）
    price_min_main = min(current_price, target_price)
    price_max_main = max(current_price, target_price)
    
    # 如果有操作序列，确保包含所有操作点
    if len(st.session_state.operations) > 0:
        op_prices = [op['price'] for op in st.session_state.operations]
        price_min_main = min(price_min_main, min(op_prices))
        price_max_main = max(price_max_main, max(op_prices))
    
    # 添加少量缓冲（5%）使图表更美观
    price_range = price_max_main - price_min_main
    x_min = price_min_main - price_range * 0.05
    x_max = price_max_main + price_range * 0.05
    
    
    x_prices = np.linspace(x_min, x_max, 100)
    
    # 1. 计算 Hold 曲线 - 改为显示实时盈亏（PnL）
    pnl_hold_curve = []
    for p in x_prices:
        pnl = (p - current_price) * (long_qty - short_qty)
        pnl_hold_curve.append(pnl)  # 只显示盈亏，不加初始权益
    
    # 2. 计算 Adjusted 曲线 - 使用分段计算清晰展示斜率变化（勾状）
    pnl_adjusted_curve = []
    x_adjusted_prices = []  # 用于存储包含操作点的完整价格序列
    
    # 按时间顺序执行操作（匹配Excel）
    sorted_ops = st.session_state.operations  # 保持原始添加顺序
    
    # 构建关键价格点列表（当前价 → 操作点们 → 目标价）
    key_prices = [current_price]
    for op in sorted_ops:
        if current_price < op['price'] <= x_max:
            key_prices.append(op['price'])
    key_prices.append(x_max)
    key_prices = sorted(set(key_prices))  # 去重并排序
    
    # 在每两个关键点之间生成密集的价格点
    for i in range(len(key_prices) - 1):
        start_p = key_prices[i]
        end_p = key_prices[i + 1]
        # 在这个区间生成20个点
        segment_prices = np.linspace(start_p, end_p, 20, endpoint=False)
        x_adjusted_prices.extend(segment_prices)
    
    # 添加最后一个点
    x_adjusted_prices.append(key_prices[-1])
    x_adjusted_prices = np.array(x_adjusted_prices)
    
    # 计算每个价格点的PnL - 使用绝对值PnL公式（不追踪equity）
    sim_price = current_price
    sim_qty = long_qty
    sim_entry = long_entry
    
    # Excel formula tracking variables for chart
    prev_price_chart = long_entry if long_qty > 0 else current_price
    net_position_chart = long_qty * long_entry if long_qty > 0 else 0
    floating_position_chart = net_position_chart
    
    op_index = 0  # 当前要触发的操作索引
    
    for p in x_adjusted_prices:
        # 检查当前价格p之前是否有需要触发的操作
        while op_index < len(sorted_ops) and sorted_ops[op_index]['price'] <= p:
            op = sorted_ops[op_index]
            
            # 1. 价格移动到操作价 - 更新sim_price，不PnL不累计到equity
            sim_price = op['price']
            
            # 2. 执行操作 - 只更新持仓，不追踪equity
            if op['action'] == '卖出':
                if op['amount_type'] == '百分比':
                    sell_qty = sim_qty * (op['amount'] / 100)
                else:
                    sell_qty = min(op['amount'] / op['price'], sim_qty)
                
                # ⚠️ 关键修复：卖出后更新 net_position_chart 和 floating_position_chart
                # 卖出比例
                sell_ratio = sell_qty / sim_qty if sim_qty > 0 else 0
                
                # 按比例减少净持仓和浮动持仓
                net_position_chart = net_position_chart * (1 - sell_ratio)
                floating_position_chart = floating_position_chart * (1 - sell_ratio)
                
                sim_qty -= sell_qty
                
            else:  # 买入 - 使用Excel公式
                if op['amount_type'] == '百分比':
                    buy_value = (sim_qty * op['price']) * (op['amount'] / 100)
                    buy_qty = buy_value / op['price']
                    effective_usdt = buy_value
                else:
                    buy_qty = op['amount'] / op['price']
                    effective_usdt = op['amount']
                
                # Excel formula: 保存前一个均价
                prev_avg_chart = sim_entry
                
                # Excel formula: Net Position
                prev_net_chart = net_position_chart
                net_position_chart += effective_usdt
                
                # Excel formula: Floating Position - 价格方向判断
                if prev_net_chart > 0:
                    if op['price'] < prev_price_chart:  # 价格下跌
                        floating_position_chart = effective_usdt + prev_net_chart - (prev_avg_chart - op['price']) * prev_net_chart / prev_avg_chart
                    else:  # 价格上涨
                        floating_position_chart = effective_usdt + prev_net_chart + (prev_avg_chart - op['price']) * prev_net_chart / prev_avg_chart
                else:
                    floating_position_chart = effective_usdt
                
                # Excel formula: Average Price
                if floating_position_chart > 0:
                    sim_entry = ((op['price'] * effective_usdt) + prev_avg_chart * (floating_position_chart - effective_usdt)) / floating_position_chart
                
                sim_qty += buy_qty
                prev_price_chart = op['price']
            
            op_index += 1
        
        # 3. 计算当前价格p的PnL - 使用绝对值公式
        pnl_at_price = (p - sim_entry) * (sim_qty - short_qty)
        pnl_adjusted_curve.append(pnl_at_price)

    # 绘制图表
    fig = go.Figure()
    
    # 先添加填充区域（收益差异可视化）
    fig.add_trace(go.Scatter(
        x=x_adjusted_prices, 
        y=pnl_adjusted_curve,
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip',
        fillcolor='rgba(0,255,0,0.1)'
    ))
    
    fig.add_trace(go.Scatter(
        x=x_prices,
        y=pnl_hold_curve,
        fill='tonexty',
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip',
        name='Hold基准下界'
    ))
    
    # Hold曲线（蓝色虚线）- 始终是直线，斜率恒定
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_hold_curve,
        mode='lines',
        name='Hold (死扛)',
        line=dict(
            color='rgba(31, 119, 180, 0.8)',  # 蓝色
            width=3,
            dash='dash'
        ),
        hovertemplate='<b>Hold策略</b><br>BTC价格: $%{x:,.0f}<br>PnL: $%{y:,.0f}<extra></extra>'
    ))
    
    # Adjusted曲线（绿色实线）- 在操作点显示斜率变化（勾状）
    fig.add_trace(go.Scatter(
        x=x_adjusted_prices,  # 使用包含操作点的密集价格序列
        y=pnl_adjusted_curve,
        mode='lines',
        name=f'操作序列 ({len(st.session_state.operations)}步)',
        line=dict(
            color='rgba(0, 200, 83, 1)',  # 绿色
            width=3
        ),
        hovertemplate='<b>操作策略</b><br>BTC价格: $%{x:,.0f}<br>PnL: $%{y:,.0f}<extra></extra>'
    ))
    
    # 标记点：当前价（起点，PnL = 0）
    fig.add_trace(go.Scatter(
        x=[current_price], y=[0],
        mode='markers+text', 
        name='当前状态',
        text=['起点'],
        textposition='top center',
        marker=dict(color='#2962ff', size=14, symbol='circle', line=dict(color='white', width=2)),
        showlegend=False
    ))
    
    # 标记点：目标价 Hold 的 PnL
    hold_pnl_at_target = (target_price - current_price) * (long_qty - short_qty)
    fig.add_trace(go.Scatter(
        x=[target_price], y=[hold_pnl_at_target],
        mode='markers', 
        name='目标 (Hold)',
        marker=dict(color='#999', size=12, symbol='circle', line=dict(color='white', width=2)),
        showlegend=False
    ))
    
    # 标记点：目标价 Adjusted 的 PnL
    adjusted_pnl_at_target = adjusted_equity_final - binance_equity
    fig.add_trace(go.Scatter(
        x=[target_price], y=[adjusted_pnl_at_target],
        mode='markers+text', 
        name='目标 (调仓)',
        text=[f'盈亏: ${adjusted_pnl_at_target/1000:.0f}k'],
        textposition='top center',
        marker=dict(color='#00c853', size=16, symbol='star', line=dict(color='white', width=2)),
        showlegend=False
    ))
    
    # 在目标价位置画一条垂直虚线
    fig.add_vline(
        x=target_price, 
        line_dash="dot", 
        line_color="rgba(0,0,0,0.3)",
        annotation_text=f"目标价: ${target_price:,.0f}",
        annotation_position="top"
    )

    # 标记所有操作点 - 更明显的标记
    for idx, op in enumerate(op_points_for_chart):
        color = '#ff5252' if op['action'] == '卖出' else '#00c853'
        symbol = 'triangle-down' if op['action'] == '卖出' else 'triangle-up'
        
        # 计算该操作点的 PnL
        op_pnl = op['equity'] - binance_equity
        
        # 绘制操作点
        fig.add_trace(go.Scatter(
            x=[op['price']], y=[op_pnl],
            mode='markers+text',
            name=f"{op['action']}点",
            text=[op['action']],
            textposition='top center' if op['action'] == '买入' else 'bottom center',
            showlegend=False,
            marker=dict(
                color=color, 
                size=12, 
                symbol=symbol, 
                line=dict(width=2, color='white')
            ),
            hovertemplate=f"<b>{op['action']}</b><br>价格: ${op['price']:,.0f}<br>盈亏: ${op_pnl:,.0f}<extra></extra>"
        ))
        
        # 添加垂直虚线标记操作价格
        fig.add_vline(
            x=op['price'], 
            line_dash="dot", 
            line_color=color,
            opacity=0.3,
            annotation_text=f"{op['action']} @ ${op['price']:,.0f}",
            annotation_position="top" if idx % 2 == 0 else "bottom",
            annotation_font_size=9,
            annotation_font_color=color
        )

    # 盈亏平衡线（0线）
    fig.add_hline(y=0, line_dash="solid", line_color="rgba(0,0,0,0.3)", line_width=2,
                  annotation_text="盈亏平衡", annotation_position="right")

    # 布局美化
    fig.update_layout(
        title="实时盈亏走势图 (Profit & Loss Projection)",
        xaxis_title="BTC 价格 (USDT)",
        yaxis_title="实时盈亏 (USDT)",
        template="plotly_white",
        height=500,
        hovermode="x unified",
        legend=dict(
            yanchor="top", y=0.99, xanchor="left", x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor="#e2e2e2",
            borderwidth=1
        ),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    
    # 格式化坐标轴
    fig.update_yaxes(tickprefix="$", tickformat=".2s") # 1.5M 格式
    fig.update_xaxes(tickformat=",d")
    
    st.plotly_chart(fig, use_container_width=True)

