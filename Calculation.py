import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
from datetime import datetime

# ==========================================
# 0. 页面配置 (复刻 NanoBanana 风格)
# ==========================================

st.set_page_config(page_title="Capital Commander", layout="wide", page_icon="🍌")

# 强制亮色模式CSS (Light Mode)
# 移除 .stApp background-color: #0e1117, 改为默认白色 (Streamlit default is white in light mode, but we force it)
# 加上 borders 样式优化
st.markdown("""
<style>
    /* 全局背景设为白色 */
    .stApp { background-color: #ffffff; color: #333333; }
    
    /* 减小全局字体 */
    html, body, [class*="css"] {
        font-size: 13px;
    }
    
    /* 标题字体缩小 */
    h1 { font-size: 1.8rem !important; color: #1a1a1a !important; }
    h2 { font-size: 1.3rem !important; color: #1a1a1a !important; }
    h3 { font-size: 1.1rem !important; color: #1a1a1a !important; }
    h4 { font-size: 0.95rem !important; color: #1a1a1a !important; }
    
    /* Metric 样式：浅灰背景，深灰边框，紧凑 */
    .stMetric { 
        background-color: #f8f9fa; 
        border: 1px solid #dee2e6; 
        padding: 8px; 
        border-radius: 6px; 
    }
    .stMetric label { font-size: 0.75rem !important; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.2rem !important; }
    
    /* 关键高亮 */
    .highlight { color: #00c853; font-weight: bold; }
    .danger { color: #ff2b2b; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("资金盘推演")
st.caption("Binance 独立全仓模拟 | 动态资金调动推演")

# ==========================================
# 0.5 Binance API 集成
# ==========================================

@st.cache_data(ttl=30)  # 缓存 10 秒
def get_binance_btc_price():
    """从 Binance API 获取 BTC/USDT 实时价格"""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": "BTCUSDT"}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data['price'])
    except Exception as e:
        st.error(f"⚠️ 无法获取 Binance 价格: {str(e)}")
        return None

# ==========================================
# 1. 数据输入 - 替代侧边栏
# ==========================================

# 初始化 session state 保存最后有效价格
if 'last_valid_price' not in st.session_state:
    st.session_state.last_valid_price = None

# 获取实时价格（每30秒自动刷新）
live_price = get_binance_btc_price()

if live_price and live_price > 0:
    # 成功获取有效价格
    current_price = live_price
    st.session_state.last_valid_price = live_price  # 保存为最后有效价格
elif st.session_state.last_valid_price:
    # API 失败或返回 0，使用上次保存的有效价格
    current_price = st.session_state.last_valid_price
else:
    # 完全没有历史数据，使用合理的默认值
    current_price = 97200.0  # 备用默认值（避免除零错误）
    st.warning("⚠️ 暂时无法获取实时价格，使用默认值 $97,200")

# 这些将在 Portfolio Overview 中作为可编辑字段显示
# 暂时用默认值初始化
luno_spot_value = 1_000_000.0
binance_equity = 2_000_000.0
long_size_usdt = 2_500_000.0
long_entry = 100000.0
short_size_usdt = 0.0
short_entry = 0.0

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

# 计算持仓数量
long_qty = long_size_usdt / long_entry if long_entry else 0
short_qty = short_size_usdt / short_entry if short_entry else 0

# ==========================================
# 2. 后端计算引擎 (Engine)
# ==========================================

def calc_liq_price(equity, l_q, l_e, s_q, s_e, mm, curr_p):
    """ 
    计算 Binance 全仓强平价 (Cross Margin Liquidation Price)
    
    公式推导：
    在强平点 P_liq 时：
    Wallet Balance + Unrealized PnL(at P_liq) = Maintenance Margin(at P_liq)
    
    其中：
    - Wallet Balance = Equity - Unrealized PnL(at current price)
    - Unrealized PnL = (P - Entry) * Position Size (多单为正，空单为负)
    - Maintenance Margin = Position Size * P * MM Rate
    """
    
    # 1. 计算当前未实现盈亏
    current_long_pnl = (curr_p - l_e) * l_q
    current_short_pnl = (s_e - curr_p) * s_q
    current_unrealized_pnl = current_long_pnl + current_short_pnl
    
    # 2. 计算 Wallet Balance (钱包余额，不含未实现盈亏)
    wallet_balance = equity - current_unrealized_pnl
    
    # 3. 在强平价 P 时的公式：
    # WB + (P - l_e)*l_q + (s_e - P)*s_q = (l_q + s_q) * P * mm
    # WB + P*l_q - l_e*l_q + s_e*s_q - P*s_q = (l_q + s_q) * P * mm
    # WB - l_e*l_q + s_e*s_q = P * [(l_q + s_q)*mm - l_q + s_q]
    # WB - l_e*l_q + s_e*s_q = P * [(l_q + s_q)*mm - (l_q - s_q)]
    
    numerator = wallet_balance - l_e * l_q + s_e * s_q
    denominator = (l_q + s_q) * mm - (l_q - s_q)
    
    if abs(denominator) < 1e-10: 
        return 0.0
    
    liq_price = numerator / denominator
    return max(0.0, liq_price)

# 当前状态计算
current_liq = calc_liq_price(binance_equity, long_qty, long_entry, short_qty, short_entry, mm_rate, current_price)
current_buffer = (current_price - current_liq) / current_price * 100 if current_price > 0 else 0

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
    
    # operation_points 用于图表标记
    operation_points = []
    
    # 按价格排序操作
    sorted_ops = sorted(operations, key=lambda x: x['price'])
    
    for op in sorted_ops:
        op_price = op['price']
        op_action = op['action']
        op_amount_type = op['amount_type']
        op_amount = op['amount']
        
        # 计算从当前价到操作点的P&L变化
        price_delta = op_price - current_p
        pnl = price_delta * (qty - short_qty)
        equity += pnl
        current_p = op_price  # 更新"当前价"为操作价
        
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
            else:  # USDT金额
                buy_qty = op_amount / op_price if op_price > 0 else 0
            
            # 更新加权平均入场价
            total_cost = qty * avg_entry + buy_qty * op_price
            qty += buy_qty
            avg_entry = total_cost / qty if qty > 0 else op_price
            
            operation_points.append({
                'price': op_price,
                'equity': equity,
                'action': '买入',
                'qty_change': buy_qty
            })
    
    return equity, qty, avg_entry, operation_points

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
            luno_spot_value = st.number_input("Luno 现货价值", value=luno_spot_value, step=10000.0, key="edit_luno")
            binance_equity = st.number_input("Binance 权益", value=binance_equity, step=10000.0, key="edit_equity")
        
        with col_edit2:
            st.subheader("合约持仓")
            long_size_usdt = st.number_input("做多持仓价值", value=long_size_usdt, step=10000.0, key="edit_long_size")
            long_entry = st.number_input("做多均价", value=long_entry, step=100.0, key="edit_long_entry")
            short_size_usdt = st.number_input("做空持仓价值", value=short_size_usdt, step=10000.0, key="edit_short_size")
            if short_size_usdt > 0:
                short_entry = st.number_input("做空均价", value=short_entry, step=100.0, key="edit_short_entry")
        
        # 重新计算持仓数量
        long_qty = long_size_usdt / long_entry if long_entry else 0
        short_qty = short_size_usdt / short_entry if (short_entry and short_size_usdt > 0) else 0
    
    # 计算总资产组合
    luno_btc_qty = luno_spot_value / current_price if current_price > 0 else 0
    total_portfolio = binance_equity + luno_spot_value
    
    # Row 1: 总资产
    st.markdown("#### 总资产组合")
    p1, p2 = st.columns(2)
    p1.metric("总资产", f"${total_portfolio:,.0f}", help="Binance + Luno 总资产")
    total_position_value = (long_qty - short_qty) * current_price + luno_spot_value
    p2.metric("总持仓价值", f"${total_position_value:,.0f}", 
              help="全部持仓价值（含现货和合约净头寸）")
    
    st.markdown("---")
    
    # Row 2: Binance 合约
    st.markdown("#### Binance 合约")
    b1, b2 = st.columns(2)
    b1.metric("Binance 权益", f"${binance_equity:,.0f}", help="合约账户净值")
    b2.metric("未实现盈亏", f"${(current_price-long_entry)*long_qty + (short_entry-current_price)*short_qty:,.0f}")
    
    st.markdown("---")
    
    # Row 3: Luno 现货
    st.markdown("#### Luno 现货")
    l1, l2 = st.columns(2)
    l1.metric("现货价值", f"${luno_spot_value:,.0f}", help="现货资产价值")
    l2.metric("现货持仓", f"${luno_spot_value:,.0f}", help="现货持仓价值")
    
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

# Row 2: Operation Sequencer (左) + Target Price Calculator (右)
row2_col1, row2_col2 = st.columns(2)

# --- 2. Operation Sequencer (Left) ---
# 操作序列编辑器：定义多个买入/卖出操作
with row2_col1.container(border=True):
    st.header("2. 操作序列")
    
    # 添加新操作
    st.markdown("#### ➕ 添加新操作")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        new_price = st.number_input("触发价格", value=st.session_state.new_op_price, step=100.0, key="input_price")
        st.session_state.new_op_price = new_price
    
    with col2:
        new_action = st.selectbox("动作", ["买入", "卖出"], index=0 if st.session_state.new_op_action == "买入" else 1, key="input_action")
        st.session_state.new_op_action = new_action
    
    # 金额输入 - 优先使用 USDT 金额
    amount_mode = st.radio("金额方式", ["USDT金额", "百分比"], horizontal=True, key="input_amount_mode")
    st.session_state.new_op_amount_type = amount_mode
    
    if amount_mode == "USDT金额":
        new_amount_usdt = st.number_input("金额 (USDT)", value=st.session_state.new_op_amount, step=10000.0, key="input_amount")
        st.session_state.new_op_amount = new_amount_usdt
        new_amount = new_amount_usdt

    else:
        new_percent = st.slider("百分比 (%)", 0.0, 100.0, st.session_state.new_op_percent, 1.0, key="input_percent")
        st.session_state.new_op_percent = new_percent
        new_amount = new_percent
    
    with col3:
        st.write("")  # spacing
        st.write("")  # spacing
        if st.button("➕ 添加", use_container_width=True):
            new_op = {
                'price': new_price,
                'action': new_action,
                'amount_type': amount_mode,
                'amount': new_amount
            }
            st.session_state.operations.append(new_op)
            st.rerun()
    
    st.markdown("---")
    
    # 显示操作列表
    st.markdown("#### 📋 操作列表与预览")
    
    if len(st.session_state.operations) == 0:
        st.info("暂无操作。点击上方「➕ 添加」按钮添加操作。")
    else:
        # 计算整个操作序列的执行结果（用于显示）
        sim_equity = binance_equity
        sim_qty = long_qty
        sim_entry = long_entry
        sim_price = current_price
        
        # 按价格排序
        sorted_ops = sorted(st.session_state.operations, key=lambda x: x['price'])
        
        # 表格表头
        h1, h2, h3, h4, h5, h6, h7 = st.columns([0.8, 1.2, 1.2, 1.4, 1.4, 1.2, 0.5])
        h1.markdown("**操作**")
        h2.markdown("**触发价**")
        h3.markdown("**金额**")
        h4.markdown("**权益**")
        h5.markdown("**持仓**")
        h6.markdown("**强平价**")
        h7.write("") # 删除按钮列
        
        st.markdown("---")
        
        for idx, op in enumerate(sorted_ops):
            # 模拟执行到这个操作
            op_price = op['price']
            
            # 价格变动的PnL
            price_delta = op_price - sim_price
            pnl = price_delta * (sim_qty - short_qty)
            sim_equity += pnl
            sim_price = op_price
            
            # --- 执行操作并计算实际金额 ---
            effective_usdt = 0.0
            
            if op['action'] == "卖出":
                if op['amount_type'] == "百分比":
                    sell_qty = sim_qty * (op['amount'] / 100)
                    effective_usdt = sell_qty * op_price
                else:
                    sell_qty = op['amount'] / op_price if op_price > 0 else 0
                    sell_qty = min(sell_qty, sim_qty)
                    effective_usdt = sell_qty * op_price
                
                realized_pnl = (op_price - sim_entry) * sell_qty
                sim_equity += realized_pnl
                sim_qty -= sell_qty
                
            else:  # 买入
                if op['amount_type'] == "百分比":
                    buy_value = (sim_qty * op_price) * (op['amount'] / 100)
                    buy_qty = buy_value / op_price if op_price > 0 else 0
                    effective_usdt = buy_value
                else:
                    buy_qty = op['amount'] / op_price if op_price > 0 else 0
                    effective_usdt = op['amount']
                
                total_cost = sim_qty * sim_entry + buy_qty * op_price
                sim_qty += buy_qty
                sim_entry = total_cost / sim_qty if sim_qty > 0 else op_price
            
            # 计算强平价
            sim_liq = calc_liq_price(sim_equity, sim_qty, sim_entry, short_qty, short_entry, mm_rate, op_price)
            
            # 格式化显示金额 (总是显示 USDT 估值)
            if op['amount_type'] == "百分比":
                amount_str = f"{op['amount']:.0f}% (${effective_usdt:,.0f})"
            else:
                amount_str = f"${effective_usdt:,.0f}"
            
            # 显示行
            c1, c2, c3, c4, c5, c6, c7 = st.columns([0.8, 1.2, 1.4, 1.4, 1.4, 1.2, 0.5]) # 调整列宽给金额
            
            # 操作类型带颜色
            action_color = "green" if op['action'] == "买入" else "red"
            
            c1.markdown(f"**{op['action']}**")
            c2.markdown(f"${op_price:,.0f}")
            c3.markdown(amount_str)
            c4.markdown(f"${sim_equity:,.0f}")
            c5.markdown(f"${sim_qty * op_price:,.0f}")
            
            # 强平价根据风险变色
            liq_delta = sim_liq - current_liq
            liq_color = "red" if liq_delta > 0 else "green"
            c6.markdown(f":{liq_color}[${sim_liq:,.0f}]")
            
            # 删除按钮
            if c7.button("🗑️", key=f"del_{idx}_{op_price}", help="删除此操作"):
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
        
        equity_change = sim_equity - binance_equity
        final_col1.metric("最终权益", f"${sim_equity:,.0f}", 
                         delta=f"{equity_change:+,.0f}",
                         help="执行所有操作后的权益")
        
        # 使用最后一个操作的价格计算持仓价值
        final_position_value = sim_qty * sorted_ops[-1]['price'] if len(sorted_ops) > 0 else sim_qty * current_price
        position_value_change = final_position_value - (long_qty * current_price)
        final_col2.metric("最终持仓价值", f"${final_position_value:,.0f}", 
                         delta=f"{position_value_change:+,.0f}",
                         delta_color="off",
                         help=f"执行所有操作后的持仓价值 ({sim_qty:.2f} BTC)")
        
        liq_change = sim_liq - current_liq
        final_col3.metric("最终强平价", f"${sim_liq:,.0f}", 
                         delta=f"{liq_change:+,.0f}",
                         delta_color="inverse" if liq_change > 0 else "normal",
                         help="执行所有操作后的强平价")
    
    # 快速清空
    if len(st.session_state.operations) > 0:
        if st.button("�️ 清空所有操作"):
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
    hold_pnl = (target_price - current_price) * (long_qty - short_qty)
    hold_equity_final = binance_equity + hold_pnl
    
    # === 情景 B: 执行操作序列（考虑第2板块的所有操作） ===
    op_points_for_chart = [] # 存储用于绘图的操作点
    
    if len(st.session_state.operations) > 0:
        # 计算操作序列到达目标价的结果
        seq_equity, seq_qty, seq_entry, op_points = calculate_operation_sequence(
            st.session_state.operations,
            binance_equity,
            long_qty,
            long_entry,
            current_price
        )
        op_points_for_chart = op_points # 保存给图表使用
        
        # 从最后一个操作点到目标价的PnL
        if len(op_points) > 0:
            last_op_price = op_points[-1]['price']
            final_pnl = (target_price - last_op_price) * (seq_qty - short_qty)
        else:
            final_pnl = (target_price - current_price) * (seq_qty - short_qty)
        
        adjusted_equity_final = seq_equity + final_pnl
        adjusted_qty_display = seq_qty
        strategy_label = f"操作序列 ({len(st.session_state.operations)}步)"
    else:
        # 没有操作，等同于 Hold
        adjusted_equity_final = hold_equity_final
        adjusted_qty_display = long_qty
        strategy_label = "无操作 (= Hold)"
    
    # 显示对比
    col_hold, col_adjusted = st.columns(2)
    
    with col_hold:
        st.markdown("**情景 A: Hold (死扛)**")
        st.info("💡 不考虑任何操作，保持当前持仓到目标价")
        st.metric("最终权益", f"${hold_equity_final:,.0f}")
        st.metric("总盈亏", f"${hold_pnl:,.0f}", 
                  delta=f"vs 现在",
                  delta_color="normal")
        st.caption(f"持仓价值: ${long_qty * target_price:,.0f}")
    
    with col_adjusted:
        st.markdown(f"**情景 B: {strategy_label}**")
        if len(st.session_state.operations) > 0:
            st.info(f"⚙️ 考虑第2板块的 {len(st.session_state.operations)} 个操作")
        st.metric("最终权益", f"${adjusted_equity_final:,.0f}")
        total_pnl_adjusted = adjusted_equity_final - binance_equity
        st.metric("总盈亏", f"${total_pnl_adjusted:,.0f}", 
                  delta=f"vs 现在",
                  delta_color="normal")
        st.caption(f"持仓价值: ${adjusted_qty_display * target_price:,.0f}")
    
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
    
    # 2. 计算 Adjusted 曲线 - 分段计算以清晰展示斜率变化
    pnl_adjusted_curve = []
    
    # 获取排序后的操作列表
    sorted_ops = sorted(st.session_state.operations, key=lambda x: x['price'])
    
    # 预计算所有点的 PnL
    for p in x_prices:
        # 找出在当前价和这个价格p之间已经触发的操作
        triggered_ops = []
        if p >= current_price:
            triggered_ops = [op for op in sorted_ops if current_price < op['price'] <= p]
        else:
            # 价格下跌的情况（暂时不处理，因为大部分场景是上涨）
            pnl_adjusted_curve.append((p - current_price) * (long_qty - short_qty))
            continue
        
        if len(triggered_ops) == 0:
            # 还没触发任何操作，跟Hold一样
            pnl = (p - current_price) * (long_qty - short_qty)
            pnl_adjusted_curve.append(pnl)
        else:
            # 执行操作序列
            # 初始状态
            sim_price = current_price
            sim_qty = long_qty
            sim_entry = long_entry
            sim_equity = binance_equity
            
            # 逐个执行触发的操作
            for op in triggered_ops:
                # 1. 价格变动到操作价
                price_move_pnl = (op['price'] - sim_price) * (sim_qty - short_qty)
                sim_equity += price_move_pnl
                sim_price = op['price']
                
                # 2. 执行操作
                if op['action'] == '卖出':
                    if op['amount_type'] == '百分比':
                        sell_qty = sim_qty * (op['amount'] / 100)
                    else:
                        sell_qty = min(op['amount'] / op['price'], sim_qty)
                    
                    realized_pnl = (op['price'] - sim_entry) * sell_qty
                    sim_equity += realized_pnl
                    sim_qty -= sell_qty
                    
                else:  # 买入
                    if op['amount_type'] == '百分比':
                        buy_value = (sim_qty * op['price']) * (op['amount'] / 100)
                        buy_qty = buy_value / op['price']
                    else:
                        buy_qty = op['amount'] / op['price']
                    
                    total_cost = sim_qty * sim_entry + buy_qty * op['price']
                    sim_qty += buy_qty
                    sim_entry = total_cost / sim_qty if sim_qty > 0 else op['price']
            
            # 3. 从最后一个操作价到目标价格p
            final_move_pnl = (p - sim_price) * (sim_qty - short_qty)
            sim_equity += final_move_pnl
            
            # 转换为盈亏
            pnl_adjusted_curve.append(sim_equity - binance_equity)

    # 绘制图表
    fig = go.Figure()
    
    # 先添加填充区域（收益差异可视化）
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_adjusted_curve,
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip',
        name='调仓策略上界'
    ))
    
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_hold_curve,
        mode='lines',
        line=dict(width=0),
        fillcolor='rgba(0, 200, 83, 0.1)',  # 绿色半透明填充
        fill='tonexty',  # 填充到上一条线
        showlegend=False,
        hoverinfo='skip',
        name='Hold基准下界'
    ))
    
    # Hold 线 - 灰色虚线
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_hold_curve, 
        mode='lines', 
        name='Hold (死扛)',
        line=dict(color='#999999', dash='dash', width=3),
        hovertemplate='<b>Hold</b><br>价格: $%{x:,.0f}<br>盈亏: $%{y:,.0f}<extra></extra>'
    ))
    
    # Adjusted 线 - 绿色实线，更粗
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_adjusted_curve, 
        mode='lines', 
        name='Adjusted (调仓策略)',
        line=dict(color='#00c853', width=4),
        hovertemplate='<b>调仓策略</b><br>价格: $%{x:,.0f}<br>盈亏: $%{y:,.0f}<extra></extra>'
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

