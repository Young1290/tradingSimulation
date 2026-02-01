import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Tuple
import time

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


# ==========================================
# 2.3 分散网格优化器 (Dispersed Grid Optimizer)
# ==========================================

@dataclass
class GridConfig:
    """分散网格配置"""
    
    # 当前持仓状态
    current_qty: float = 25.0           # 持仓数量 (BTC)
    entry_price: float = 100_150        # 入场均价
    current_liq_price: float = 20_030   # 当前强平价
    available_capital: float = 300_000  # 可用余额（用于操作）
    
    # 买入区间（在此范围内分散买入）
    buy_zone_low: float = 83_000
    buy_zone_high: float = 86_000
    
    # 卖出区间（在此范围内分散卖出）
    sell_zone_low: float = 89_000
    sell_zone_high: float = 92_000
    
    # 目标价差 6%-8%
    min_spread_pct: float = 0.06
    max_spread_pct: float = 0.08
    
    # 最小价格间距
    min_price_gap: float = 800
    
    # 硬约束
    max_liq_price: float = 28_000
    leverage: int = 10
    
    # 目标价格（用于计算预期盈利）
    target_btc_price: float = 120_000
    
    # 操作参数
    n_rounds: int = 3
    amount_per_round: float = 100_000
    
    # 算法参数
    population_size: int = 500
    n_generations: int = 300


def generate_paired_prices(
    buy_zone_low: float, buy_zone_high: float,
    sell_zone_low: float, sell_zone_high: float,
    min_spread: float, max_spread: float,
    n_rounds: int, rng
) -> Tuple[List[float], List[float]]:
    """
    生成配对的买卖价格
    
    确保：
    1. 买入价在买入区间内均匀分布
    2. 卖出价在卖出区间内均匀分布
    3. 买卖价格独立分散（不再强制基于价差计算）
    """
    buy_segment = (buy_zone_high - buy_zone_low) / n_rounds
    sell_segment = (sell_zone_high - sell_zone_low) / n_rounds
    
    buy_prices = []
    sell_prices = []
    
    for i in range(n_rounds):
        # 买入价：在第i段内随机选择
        buy_seg_low = buy_zone_low + i * buy_segment
        buy_seg_high = buy_zone_low + (i + 1) * buy_segment
        buy_price = rng.uniform(buy_seg_low, buy_seg_high)
        
        # 卖出价：在第i段内随机选择（独立分布）
        sell_seg_low = sell_zone_low + i * sell_segment
        sell_seg_high = sell_zone_low + (i + 1) * sell_segment
        sell_price = rng.uniform(sell_seg_low, sell_seg_high)
        
        buy_prices.append(buy_price)
        sell_prices.append(sell_price)
    
    return buy_prices, sell_prices


def simulate_grid_strategy(
    buy_prices: List[float],
    sell_prices: List[float],
    config: GridConfig
) -> Dict:
    """
    模拟网格策略执行
    
    强平价公式：Liq_Price = Entry_Price - Total_Equity / Position_Qty
    
    - 买入时：仓位增加，需要新增保证金，总权益增加
    - 卖出时：仓位减少，释放保证金 + 实现盈亏
    """
    # 初始状态
    qty = config.current_qty
    entry = config.entry_price
    
    # 从当前强平价推算初始总权益
    # Liq = Entry - Equity/Qty => Equity = (Entry - Liq) * Qty
    initial_equity = (config.entry_price - config.current_liq_price) * config.current_qty
    total_equity = initial_equity
    available_balance = config.available_capital
    
    operations = []
    all_liq_prices = [config.current_liq_price]  # 追踪所有强平价
    total_realized_pnl = 0
    spreads = []
    spread_ok_count = 0
    
    for round_idx in range(config.n_rounds):
        buy_price = buy_prices[round_idx]
        sell_price = sell_prices[round_idx]
        buy_amount = config.amount_per_round
        
        # 计算价差
        spread = sell_price - buy_price
        spread_pct = spread / buy_price
        spreads.append(spread_pct)
        
        if config.min_spread_pct <= spread_pct <= config.max_spread_pct:
            spread_ok_count += 1
        
        # ========== 买入操作 ==========
        margin_needed = buy_amount / config.leverage
        
        # 检查可用资金
        if available_balance < margin_needed:
            operations.append({
                'round': round_idx + 1,
                'type': 'skip',
                'reason': '资金不足'
            })
            continue
        
        qty_bought = buy_amount / buy_price
        
        # 保存旧状态
        old_qty = qty
        old_entry = entry
        
        # 更新持仓
        qty += qty_bought
        available_balance -= margin_needed
        
        # 更新入场均价（加权平均）
        entry = (old_entry * old_qty + buy_price * qty_bought) / qty
        
        # 更新总权益（增加使用的保证金）
        total_equity += margin_needed
        
        # 计算强平价: Liq = Entry - Equity / Qty
        liq_price = entry - total_equity / qty
        liq_price = max(0, liq_price)
        all_liq_prices.append(liq_price)
        
        buy_ok = liq_price < config.max_liq_price
        
        operations.append({
            'round': round_idx + 1,
            'type': 'buy',
            'price': buy_price,
            'amount': buy_amount,
            'qty_change': qty_bought,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'available_balance': available_balance,
            'total_equity': total_equity,
            'liq_ok': buy_ok
        })
        
        # ========== 卖出操作 ==========
        sell_qty = qty_bought  # 卖出刚买入的数量
        sell_value = sell_qty * sell_price
        realized_pnl = (sell_price - buy_price) * sell_qty
        total_realized_pnl += realized_pnl
        
        # 更新持仓
        qty -= sell_qty
        
        # 卖出时：总权益增加实现盈亏
        total_equity += realized_pnl
        
        # 释放的保证金回到可用余额
        margin_released = margin_needed  # 简化：释放的就是之前用的
        available_balance += margin_released + realized_pnl
        
        # 计算强平价
        if qty > 0:
            liq_price = entry - total_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        all_liq_prices.append(liq_price)
        
        operations.append({
            'round': round_idx + 1,
            'type': 'sell',
            'price': sell_price,
            'amount': sell_value,
            'qty_change': -sell_qty,
            'qty_after': qty,
            'entry_after': entry,
            'spread': spread,
            'spread_pct': spread_pct,
            'realized_pnl': realized_pnl,
            'liq_price': liq_price,
            'available_balance': available_balance,
            'total_equity': total_equity,
            'liq_ok': liq_price < config.max_liq_price
        })
    
    # 计算分散度指标
    buy_gaps = []
    sell_gaps = []
    sorted_buys = sorted(buy_prices)
    sorted_sells = sorted(sell_prices)
    
    for i in range(len(sorted_buys) - 1):
        buy_gaps.append(sorted_buys[i+1] - sorted_buys[i])
    for i in range(len(sorted_sells) - 1):
        sell_gaps.append(sorted_sells[i+1] - sorted_sells[i])
    
    min_buy_gap = min(buy_gaps) if buy_gaps else float('inf')
    min_sell_gap = min(sell_gaps) if sell_gaps else float('inf')
    
    # 计算均匀度
    if len(buy_gaps) > 0:
        ideal_buy_gap = (config.buy_zone_high - config.buy_zone_low) / (config.n_rounds - 1)
        buy_uniformity = 1 - np.std(buy_gaps) / ideal_buy_gap if ideal_buy_gap > 0 else 0
        buy_uniformity = max(0, min(1, buy_uniformity))
    else:
        buy_uniformity = 1.0
    
    if len(sell_gaps) > 0:
        ideal_sell_gap = (config.sell_zone_high - config.sell_zone_low) / (config.n_rounds - 1)
        sell_uniformity = 1 - np.std(sell_gaps) / ideal_sell_gap if ideal_sell_gap > 0 else 0
        sell_uniformity = max(0, min(1, sell_uniformity))
    else:
        sell_uniformity = 1.0
    
    # 预期盈利
    if qty > 0:
        profit_at_target = (config.target_btc_price - entry) * qty
    else:
        profit_at_target = 0
    
    # 计算最大强平价
    max_liq_price = max(all_liq_prices)
    
    return {
        'final_qty': qty,
        'final_entry': entry,
        'entry_reduction': config.entry_price - entry,
        'max_liq_price': max_liq_price,
        'final_liq_price': liq_price,
        'total_realized_pnl': total_realized_pnl,
        'final_available_balance': available_balance,
        'final_total_equity': total_equity,
        'profit_at_target': profit_at_target,
        'operations': operations,
        'spreads': spreads,
        'avg_spread_pct': np.mean(spreads) if spreads else 0,
        'spread_ok_count': spread_ok_count,
        'buy_uniformity': buy_uniformity,
        'sell_uniformity': sell_uniformity,
        'min_buy_gap': min_buy_gap,
        'min_sell_gap': min_sell_gap,
        'all_safe': all(op.get('liq_ok', True) for op in operations if 'liq_ok' in op)
    }


def evaluate_solution(
    buy_prices: List[float],
    sell_prices: List[float],
    config: GridConfig
) -> Tuple[float, Dict]:
    """
    评估方案
    
    权重分配：
    - 安全性（强平价）：40% - 硬约束（在上限内=满分，超限=0分）
    - 分散性（间距+均匀）：30%
    - 价差合理性：20%
    - 盈利：10%
    
    注意：安全性采用二元评分，不再奖励"过度安全"，
    这样AI可以生成接近强平价上限的方案
    """
    result = simulate_grid_strategy(buy_prices, sell_prices, config)
    
    # 1. 间距得分（相邻价格必须 >= min_price_gap）
    gap_ok = (result['min_buy_gap'] >= config.min_price_gap and 
              result['min_sell_gap'] >= config.min_price_gap)
    gap_score = 1.0 if gap_ok else 0.3
    
    # 2. 均匀度得分
    uniformity_score = (result['buy_uniformity'] + result['sell_uniformity']) / 2
    
    # 3. 价差得分（每对都要在6-8%）
    spread_ratio = result['spread_ok_count'] / config.n_rounds
    avg_spread = result['avg_spread_pct']
    if config.min_spread_pct <= avg_spread <= config.max_spread_pct:
        spread_score = spread_ratio
    else:
        spread_score = spread_ratio * 0.5
    
    # 4. 安全性得分（强平价约束 - 权重提高至40%）
    # 修改：只要在上限内就给满分，不再奖励"过度安全"
    # 这样AI可以生成接近上限的方案，而不是总是追求极低的强平价
    if not result['all_safe']:
        safety_score = 0  # 超限直接0分
    else:
        safety_score = 1.0  # 在上限内直接满分
    
    # 5. 盈利得分
    profit_score = min(1.0, result['total_realized_pnl'] / 25000)
    
    # 加权（安全性优先）
    total_score = (
        gap_score * 0.15 +
        uniformity_score * 0.15 +
        spread_score * 0.20 +
        safety_score * 0.40 +
        profit_score * 0.10
    )
    
    # 硬约束惩罚
    if not result['all_safe']:
        total_score *= 0.01
    if not gap_ok:
        total_score *= 0.5
    
    return total_score, result


def optimize_grid_silent(config: GridConfig, progress_callback=None) -> Tuple[List, List, Dict]:
    """
    优化分散网格 (静默版本，适用于 Streamlit)
    
    Args:
        config: GridConfig配置对象
        progress_callback: 可选的进度回调函数，接收 (generation, total_generations, best_score, best_result)
    
    Returns:
        (best_buy_prices, best_sell_prices, best_result)
    """
    rng = np.random.default_rng()
    
    # 初始化种群
    population = []
    for _ in range(config.population_size):
        buy_prices, sell_prices = generate_paired_prices(
            config.buy_zone_low, config.buy_zone_high,
            config.sell_zone_low, config.sell_zone_high,
            config.min_spread_pct, config.max_spread_pct,
            config.n_rounds, rng
        )
        score, result = evaluate_solution(buy_prices, sell_prices, config)
        population.append((buy_prices, sell_prices, score, result))
    
    best_solution = None
    best_score = float('-inf')
    best_result = None
    
    for gen in range(config.n_generations):
        population.sort(key=lambda x: x[2], reverse=True)
        
        if population[0][2] > best_score:
            best_solution = (population[0][0].copy(), population[0][1].copy())
            best_score = population[0][2]
            best_result = population[0][3]
        
        # 调用进度回调
        if progress_callback and (gen % 10 == 0 or gen == config.n_generations - 1):
            progress_callback(gen + 1, config.n_generations, best_score, best_result)
        
        # 生成下一代
        new_population = []
        
        elite_count = max(10, config.population_size // 10)
        for i in range(elite_count):
            new_population.append(population[i])
        
        while len(new_population) < config.population_size:
            # 选择父代
            idx1 = rng.choice(len(population) // 4)
            idx2 = rng.choice(len(population) // 4)
            
            # 交叉
            child_buy = []
            child_sell = []
            for i in range(config.n_rounds):
                if rng.random() < 0.5:
                    child_buy.append(population[idx1][0][i])
                    child_sell.append(population[idx1][1][i])
                else:
                    child_buy.append(population[idx2][0][i])
                    child_sell.append(population[idx2][1][i])
            
            # 变异
            if rng.random() < 0.4:
                idx = rng.integers(config.n_rounds)
                # 小范围调整买入价
                delta = rng.uniform(-300, 300)
                child_buy[idx] = np.clip(child_buy[idx] + delta, 
                                         config.buy_zone_low, config.buy_zone_high)
                # 对应调整卖出价以保持价差
                target_spread = rng.uniform(config.min_spread_pct, config.max_spread_pct)
                child_sell[idx] = child_buy[idx] * (1 + target_spread)
                child_sell[idx] = np.clip(child_sell[idx],
                                          config.sell_zone_low, config.sell_zone_high)
            
            # 偶尔重新生成
            if rng.random() < 0.05:
                child_buy, child_sell = generate_paired_prices(
                    config.buy_zone_low, config.buy_zone_high,
                    config.sell_zone_low, config.sell_zone_high,
                    config.min_spread_pct, config.max_spread_pct,
                    config.n_rounds, rng
                )
            
            score, result = evaluate_solution(child_buy, child_sell, config)
            new_population.append((child_buy, child_sell, score, result))
        
        population = new_population
    
    return best_solution[0], best_solution[1], best_result


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
    
    # ⚠️ 修复：扣除初始持仓的保证金
    if start_qty > 0:
        initial_position_value = start_qty * start_entry
        initial_margin = initial_position_value / 10  # 10倍杠杆
        equity -= initial_margin
    
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
                effective_usdt = sell_qty * op_price
            else:  # USDT金额
                effective_usdt = op_amount
                # ⚠️ 修复：按持仓均价计算BTC数量，而不是卖出价
                sell_qty = effective_usdt / avg_entry if avg_entry > 0 else 0
                sell_qty = min(sell_qty, qty)  # 不能卖出超过持仓
            
            # ⚠️ 修复：按实际卖出数量计算盈亏
            actual_sell_value = sell_qty * avg_entry
            realized_pnl = actual_sell_value * (op_price - avg_entry) / avg_entry if avg_entry > 0 else 0
            equity += realized_pnl
            
            # ⚠️ 修复：卖出时释放对应的保证金
            margin_released = actual_sell_value / 10
            equity += margin_released
            
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
            
            # ⚠️ 修复：买入时扣除保证金（与显示逻辑一致）
            margin_required = effective_usdt / 10
            equity -= margin_required
            
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
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔶 Binance 合约 (U本位 10x)", 
        "🟦 Binance 现货",
        "🟡 币本位合约 (10x)",
        "🎯 AI智能配置"
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
            if st.button("➕ 添加", key="binance_add_btn"):
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
            if st.button("➕ 添加", key="luno_add_btn"):
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
            if st.button("➕ 添加", key="coin_add_btn"):
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
    
    # === AI智能配置 Tab ===
    with tab4:
        st.info("💡 AI自动推演最优资金配置策略，使用分散网格优化器智能分配买卖点")
        
        # 初始化session state用于保存优化结果
        if 'grid_optimization_result' not in st.session_state:
            st.session_state.grid_optimization_result = None
        if 'grid_best_buy_prices' not in st.session_state:
            st.session_state.grid_best_buy_prices = None
        if 'grid_best_sell_prices' not in st.session_state:
            st.session_state.grid_best_sell_prices = None
        # 保存优化时使用的参数（避免rerun后丢失）
        if 'grid_saved_amount_per_round' not in st.session_state:
            st.session_state.grid_saved_amount_per_round = 100000.0
        if 'grid_saved_n_rounds' not in st.session_state:
            st.session_state.grid_saved_n_rounds = 3
        # 追踪上次优化时使用的强平价上限
        if 'grid_saved_max_liq' not in st.session_state:
            st.session_state.grid_saved_max_liq = 28000.0
        
        # ========== 自动读取资产概览数据 ==========
        grid_current_qty = long_qty if long_qty > 0 else 25.0
        grid_entry_price = long_entry if long_entry > 0 else 100000.0
        grid_current_liq = current_liq if current_liq > 0 else 20000.0
        
        # 可用资金 = Binance权益 - 已用保证金
        used_margin = (grid_current_qty * grid_entry_price) / 10 if grid_current_qty > 0 else 0
        grid_available_capital = max(0, st.session_state.binance_equity - used_margin)
        
        # 目标价格使用session state中的值
        grid_target_price = st.session_state.target_price
        
        st.markdown("#### ⚙️ 策略参数")
        
        # 显示关键数据（只读）
        info_col1, info_col2 = st.columns(2)
        info_col1.metric("当前强平价", f"${grid_current_liq:,.0f}")
        info_col2.metric("可用资金", f"${grid_available_capital:,.0f}")
        
        st.markdown("---")
        
        # ========== 用户需要输入的参数（极简版）==========
        # 只需要输入2个价格，AI自动生成区间
        
        range_col1, range_col2 = st.columns(2)
        
        with range_col1:
            grid_buy_center = st.number_input(
                "📉 买入价格",
                value=80000.0,
                min_value=10000.0,
                max_value=200000.0,
                step=1000.0,
                key="grid_buy_center",
                help="AI会在此价格上下浮动生成买入区间"
            )
        
        with range_col2:
            grid_sell_center = st.number_input(
                "📈 卖出价格", 
                value=94000.0,
                min_value=10000.0,
                max_value=200000.0,
                step=1000.0,
                key="grid_sell_center",
                help="AI会在此价格上下浮动生成卖出区间"
            )
        
        # 内部自动生成区间范围（±15%浮动）
        buy_range_pct = 0.15  # 买入区间浮动比例 ±15%
        sell_range_pct = 0.04  # 卖出区间浮动比例 ±4%
        
        grid_buy_low = grid_buy_center * (1 - buy_range_pct)
        grid_buy_high = grid_buy_center * (1 + buy_range_pct)
        grid_sell_low = grid_sell_center * (1 - sell_range_pct)
        grid_sell_high = grid_sell_center * (1 + sell_range_pct)
        
        # 显示生成的区间范围
        st.caption(f"💡 生成买入区间: ${grid_buy_low:,.0f} - ${grid_buy_high:,.0f} | 卖出区间: ${grid_sell_low:,.0f} - ${grid_sell_high:,.0f}")
        
        st.markdown("---")
        
        # 强平价上限（居中显示）
        _, constraint_col, _ = st.columns([1, 1, 1])
        with constraint_col:
            grid_max_liq = st.number_input(
                "⚠️ 强平价上限", 
                value=28000.0,
                min_value=0.0,
                step=1000.0,
                key="grid_max_liq",
                help="安全约束：优化结果的强平价必须低于此值。注意：实际强平价由持仓状态决定，通常会远低于此上限"
            )
            st.caption("💡 这是安全约束上限，不是目标值。AI会在此约束下尽量优化其他目标（分散性、价差、盈利）")
        
        # 检测强平价上限是否改变，如果改变则清除旧的优化结果
        if grid_max_liq != st.session_state.grid_saved_max_liq:
            if st.session_state.grid_optimization_result is not None:
                st.warning(f"⚠️ 强平价上限已从 ${st.session_state.grid_saved_max_liq:,.0f} 改为 ${grid_max_liq:,.0f}，旧的优化结果已清除，请重新运行优化")
                st.session_state.grid_optimization_result = None
                st.session_state.grid_best_buy_prices = None
                st.session_state.grid_best_sell_prices = None
            st.session_state.grid_saved_max_liq = grid_max_liq
        
        # ========== 自动计算其他参数 ==========
        # 根据区间计算预期价差
        min_possible_spread = (grid_sell_low - grid_buy_high) / grid_buy_high if grid_buy_high > 0 else 0.03
        max_possible_spread = (grid_sell_high - grid_buy_low) / grid_buy_low if grid_buy_low > 0 else 0.15
        
        # 设置合理的价差目标范围
        grid_min_spread = max(0.03, min_possible_spread * 0.9)
        grid_max_spread = min(0.20, max_possible_spread * 1.1)
        
        # 自动计算最小间距（基于买入区间大小）
        buy_range = grid_buy_high - grid_buy_low
        grid_min_gap = max(500, buy_range / 8)
        
        # ========== 基于可用资金自动计算轮数和每轮金额 ==========
        if grid_available_capital >= 500000:
            auto_n_rounds = 5
            auto_amount_per_round = grid_available_capital * 0.20  # 提高到20%
        elif grid_available_capital >= 200000:
            auto_n_rounds = 4
            auto_amount_per_round = grid_available_capital * 0.25
        elif grid_available_capital >= 100000:
            auto_n_rounds = 3
            auto_amount_per_round = grid_available_capital * 0.30
        else:
            auto_n_rounds = 2
            auto_amount_per_round = grid_available_capital * 0.40
        
        # 设置更合理的上下限（不再固定200,000）
        auto_amount_per_round = max(50000, min(grid_available_capital * 0.5, auto_amount_per_round))
        
        st.markdown("---")
        
        # 验证参数
        validation_errors = []
        validation_warnings = []
        
        if grid_buy_high <= grid_buy_low:
            validation_errors.append("买入区间上限必须大于下限")
        if grid_sell_high <= grid_sell_low:
            validation_errors.append("卖出区间上限必须大于下限")
        if grid_sell_low <= grid_buy_high:
            validation_errors.append("卖出区间下限应高于买入区间上限以确保盈利")
        if grid_current_qty <= 0:
            validation_warnings.append("当前持仓为0，请先在「1. 资产概览」中设置持仓数据")
        if grid_available_capital < 50000:
            validation_warnings.append(f"可用资金(${grid_available_capital:,.0f})较少，建议增加资金")
        
        # 显示验证状态
        if validation_errors:
            for error in validation_errors:
                st.error(f"❌ {error}")
        if validation_warnings:
            for warning in validation_warnings:
                st.warning(f"⚠️ {warning}")
        
        # 显示AI自动计算的参数
        st.info(f"🤖 AI将自动优化：**{auto_n_rounds}轮** 操作，每轮约 **${auto_amount_per_round:,.0f}**，目标价差 **{grid_min_spread*100:.1f}%-{grid_max_spread*100:.1f}%**")
        
        # 优化按钮
        col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
        
        with col_btn2:
            can_optimize = len(validation_errors) == 0
            
            if st.button("🚀 开始AI优化", type="primary", disabled=not can_optimize):
                # 保存参数到session state
                st.session_state.grid_saved_amount_per_round = auto_amount_per_round
                st.session_state.grid_saved_n_rounds = auto_n_rounds
                st.session_state.grid_saved_max_liq = grid_max_liq  # 保存强平价上限
                
                # 创建配置（使用自动计算的参数）
                config = GridConfig(
                    current_qty=grid_current_qty,
                    entry_price=grid_entry_price,
                    current_liq_price=grid_current_liq,
                    available_capital=grid_available_capital,
                    buy_zone_low=grid_buy_low,
                    buy_zone_high=grid_buy_high,
                    sell_zone_low=grid_sell_low,
                    sell_zone_high=grid_sell_high,
                    min_spread_pct=grid_min_spread,
                    max_spread_pct=grid_max_spread,
                    min_price_gap=grid_min_gap,
                    max_liq_price=grid_max_liq,
                    leverage=10,
                    target_btc_price=grid_target_price,
                    n_rounds=auto_n_rounds,
                    amount_per_round=auto_amount_per_round,
                    population_size=200,
                    n_generations=100
                )
                
                # 显示进度
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_callback(gen, total_gen, score, result):
                    progress = gen / total_gen
                    progress_bar.progress(progress)
                    status_text.text(f"优化进度: {gen}/{total_gen} 代 | 得分: {score:.3f} | 盈利: ${result['total_realized_pnl']:,.0f}")
                
                # 执行优化
                with st.spinner("AI正在计算最优策略..."):
                    best_buy, best_sell, best_result = optimize_grid_silent(config, progress_callback)
                    
                    # 保存结果到session state
                    st.session_state.grid_optimization_result = best_result
                    st.session_state.grid_best_buy_prices = best_buy
                    st.session_state.grid_best_sell_prices = best_sell
                
                progress_bar.progress(1.0)
                status_text.text("✅ 优化完成！")
                st.success("🎉 AI优化完成！请查看下方结果")
                st.rerun()
        
        # 显示优化结果
        if st.session_state.grid_optimization_result is not None:
            result = st.session_state.grid_optimization_result
            best_buy = st.session_state.grid_best_buy_prices
            best_sell = st.session_state.grid_best_sell_prices
            saved_amount = st.session_state.grid_saved_amount_per_round
            
            st.markdown("---")
            st.markdown("#### 📊 优化结果")
            
            # 关键指标
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            metric_col1.metric("总实现盈利", f"${result['total_realized_pnl']:,.0f}")
            metric_col2.metric("均价降低", f"${result['entry_reduction']:,.0f}")
            
            # 计算安全边际
            safety_margin = grid_max_liq - result['max_liq_price']
            safety_margin_pct = (safety_margin / grid_max_liq * 100) if grid_max_liq > 0 else 0
            
            metric_col3.metric(
                "最大强平价", 
                f"${result['max_liq_price']:,.0f}", 
                delta=f"安全边际 ${safety_margin:,.0f} ({safety_margin_pct:.1f}%)" if result['all_safe'] else "❌ 超限",
                delta_color="normal" if result['all_safe'] else "inverse"
            )
            metric_col4.metric("目标价盈利", f"${result['profit_at_target']:,.0f}")
            
            st.markdown("---")
            
            # 详细结果
            with st.expander("📋 买卖配对详情", expanded=True):
                st.markdown("**买卖价格配对表**")
                
                # 创建配对表格
                pairing_data = []
                for i in range(len(best_buy)):
                    spread = best_sell[i] - best_buy[i]
                    spread_pct = (spread / best_buy[i]) * 100
                    
                    pairing_data.append({
                        '轮次': f'第{i+1}轮',
                        '买入价': f'${best_buy[i]:,.0f}',
                        '卖出价': f'${best_sell[i]:,.0f}',
                        '价差': f'${spread:,.0f}',
                        '价差%': f'{spread_pct:.2f}%'
                    })
                
                pairing_df = pd.DataFrame(pairing_data)
                st.dataframe(pairing_df, hide_index=True)
            
            st.markdown("---")
            
            # 应用和清除按钮
            apply_col1, apply_col2, apply_col3 = st.columns([1, 1, 1])
            
            with apply_col1:
                if st.button("🗑️ 清除结果"):
                    st.session_state.grid_optimization_result = None
                    st.session_state.grid_best_buy_prices = None
                    st.session_state.grid_best_sell_prices = None
                    st.rerun()
            
            with apply_col3:
                if st.button("✅ 应用到操作列表", type="primary"):
                    # 将优化结果转换为操作序列并添加（使用保存的参数）
                    for i in range(len(best_buy)):
                        # 添加买入操作
                        buy_op = {
                            'price': best_buy[i],
                            'action': '买入',
                            'amount_type': 'USDT金额',
                            'amount': saved_amount,  # 使用session state保存的值
                            'platform': 'binance',
                            'leverage': 10
                        }
                        st.session_state.operations.append(buy_op)
                        
                        # 添加卖出操作
                        sell_op = {
                            'price': best_sell[i],
                            'action': '卖出',
                            'amount_type': 'USDT金额',
                            'amount': saved_amount,  # 使用session state保存的值
                            'platform': 'binance',
                            'leverage': 10,
                            'paired_buy_price': best_buy[i]  # 记录配对的买入价用于盈亏计算
                        }
                        st.session_state.operations.append(sell_op)
                    
                    # 清除优化结果（避免重复添加）
                    st.session_state.grid_optimization_result = None
                    st.session_state.grid_best_buy_prices = None
                    st.session_state.grid_best_sell_prices = None
                    
                    st.success(f"✅ 已添加 {len(best_buy) * 2} 个操作到操作列表")
                    st.rerun()


    
    st.markdown("---")
    
    # 显示操作列表
    st.markdown("#### 📋 操作列表与预览")
    
    if len(st.session_state.operations) == 0:
        st.info("暂无操作。点击上方「➕ 添加」按钮添加操作。")
    else:
        # 计算整个操作序列的执行结果（用于显示）
        sim_binance_equity = st.session_state.binance_equity
        
        # ⚠️ 修复：扣除初始持仓的保证金
        # Binance权益包含了已用于初始持仓的保证金，需要先扣除
        if long_qty > 0:
            initial_position_value = long_qty * long_entry
            initial_margin = initial_position_value / 10  # 10倍杠杆
            sim_binance_equity -= initial_margin
        
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
        
        # 表格表头 - 添加实际盈亏列
        h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10 = st.columns([0.4, 0.7, 0.9, 0.9, 0.85, 0.85, 1.0, 0.9, 0.9, 0.9, 0.4])
        h0.markdown("**平台**")
        h1.markdown("**操作**")
        h2.markdown("**触发价**")
        h3.markdown("**金额**")
        h4.markdown("**持仓均价**")
        h5.markdown("**币本位 BTC**")
        h6.markdown("**Binance (U)**")
        h7.markdown("**强平价**")
        h8.markdown("**实际盈亏**")
        h9.markdown("**浮盈亏**")
        h10.write("") # 删除按钮列
        
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
                
                # 更新价格追踪（用于后续计算，但不计算虚拟价格变动盈亏）
                sim_price = op_price

                
                # --- 执行操作并计算实际金额 ---
                effective_usdt = 0.0
                
                # === 新增：保存操作相关信息用于PnL计算 ===
                operation_qty = 0.0  # 本次操作涉及的数量
                entry_price_before_op = sim_entry  # 操作前的持仓均价
                qty_before_op = sim_qty  # 操作前的总持仓数量
                realized_pnl_this_op = 0.0  # 本次操作的实际盈亏（仅卖出时有值）
                
                if platform == 'binance':
                    # Binance 合约操作 (10x 杠杆)
                    if op['action'] == "卖出":
                        if op['amount_type'] == "百分比":
                            sell_qty = sim_qty * (op['amount'] / 100)
                            effective_usdt = sell_qty * op_price
                        else:
                            effective_usdt = op['amount']  # 卖出的USDT金额
                            # ⚠️ 修复：按持仓均价计算BTC数量，而不是卖出价
                            # 这样$1,250,000总是代表12.5 BTC（如果均价是$100,000）
                            sell_qty = effective_usdt / sim_entry if sim_entry > 0 else 0
                            sell_qty = min(sell_qty, sim_qty)
                        
                        operation_qty = sell_qty  # 保存卖出数量用于PnL显示
                        
                        # ⚠️ 修复：计算实际盈亏
                        # 如果是AI配对操作（有paired_buy_price），使用配对买入价计算
                        # 否则使用持仓均价
                        paired_buy_price = op.get('paired_buy_price', None)
                        
                        # 计算卖出仓位价值（用于后续释放保证金计算）
                        actual_sell_value = sell_qty * sim_entry
                        
                        if paired_buy_price is not None:
                            # AI配对操作：盈亏 = 卖出数量 × (卖出价 - 买入价)
                            realized_pnl = sell_qty * (op_price - paired_buy_price)
                        else:
                            # 普通操作：使用持仓均价
                            realized_pnl = actual_sell_value * (op_price - sim_entry) / sim_entry if sim_entry > 0 else 0
                        
                        realized_pnl_this_op = realized_pnl  # 保存实际盈亏用于显示
                        sim_binance_equity += realized_pnl
                        
                        # ⚠️ 修复：卖出时释放对应的保证金
                        # 平仓释放的保证金 = 卖出仓位价值 / 10
                        margin_released = actual_sell_value / 10
                        sim_binance_equity += margin_released
                        
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
                        
                        operation_qty = buy_qty  # 保存买入数量用于PnL显示
                        
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
                        
                        operation_qty = effective_usdt / op_price if op_price > 0 else 0  # 现货卖出数量
                        sim_luno_value += effective_usdt
                    else:  # 买入
                        # 买入现货，花费 USDT
                        if op['amount_type'] == "百分比":
                            buy_value = sim_luno_value * (op['amount'] / 100)
                            effective_usdt = buy_value
                        else:
                            effective_usdt = op['amount']
                        
                        operation_qty = effective_usdt / op_price if op_price > 0 else 0  # 现货买入数量
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

                
                # 计算强平价 - Excel formula: 基于净持仓（D列）
                if platform == 'binance':
                    # 强平价 = 均价 - (初始权益 / 净持仓) × 均价
                    if net_position > 0:
                        sim_liq = sim_entry - (initial_equity_for_liq / net_position) * sim_entry
                        sim_liq = max(0.0, sim_liq)  # 强平价不能为负数
                    else:
                        sim_liq = 0
                elif platform == 'coin_margined':
                    # 币本位使用预先计算的强平价
                    sim_liq = op.get('liq_price', 0)
                    sim_liq = max(0.0, sim_liq)
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
                
                # 显示行 - 添加实际盈亏和浮盈亏列
                c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([0.4, 0.7, 0.9, 0.9, 0.85, 0.85, 1.0, 0.9, 0.9, 0.9, 0.4])
                
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
                
                # === 浮盈亏计算 ===
                # 显示操作后剩余持仓的浮盈亏，而不是操作前持仓的浮盈亏
                operation_pnl = 0.0
                
                if platform == 'binance':
                    # Binance 合约操作
                    # 公式：(操作价格 - 操作后均价) × 操作后总持仓
                    operation_pnl = (op_price - sim_entry) * sim_qty
                
                elif platform == 'binance_spot':
                    # Binance 现货操作
                    # 现货的浮盈亏计算类似，但基于现货持仓价值
                    # 简化：假设现货持仓的平均成本难以追踪，暂时显示0
                    operation_pnl = 0
                
                elif platform == 'coin_margined':
                    # 币本位合约 - 暂时显示为0（需要完整的持仓追踪）
                    operation_pnl = 0
                
                # === 显示实际盈亏（仅卖出时有值）===
                if realized_pnl_this_op > 0:
                    realized_color = "green"
                    realized_text = f"+${realized_pnl_this_op:,.0f}"
                elif realized_pnl_this_op < 0:
                    realized_color = "red"
                    realized_text = f"-${abs(realized_pnl_this_op):,.0f}"
                else:
                    realized_color = "gray"
                    realized_text = "-"
                
                c8.markdown(f":{realized_color}[{realized_text}]")
                
                # === 显示浮盈亏（带颜色）===
                if operation_pnl > 0:
                    pnl_color = "green"
                    pnl_text = f"+${operation_pnl:,.0f}"
                elif operation_pnl < 0:
                    pnl_color = "red"
                    pnl_text = f"-${abs(operation_pnl):,.0f}"
                else:
                    pnl_color = "gray"
                    pnl_text = "$0"
                
                c9.markdown(f":{pnl_color}[{pnl_text}]")
                
                # 删除按钮
                if c10.button("🗑️", key=f"del_{idx}_{op_price}", help="删除此操作"):
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
        # 最终权益 = 操作后权益 + 浮盈 + 平仓释放的保证金
        effective_qty = seq_net_position / seq_entry if seq_entry > 0 else 0
        floating_pnl = (target_price - seq_entry) * effective_qty  # Excel: (H-F)*D/F
        
        # ⚠️ 修复：到达目标价平仓时，需要加回保证金
        # 最终持仓占用的保证金
        final_margin = seq_net_position / 10 if seq_net_position > 0 else 0
        
        # 最终权益 = 可用资金 + 浮盈 + 平仓释放的保证金
        adjusted_equity_final = seq_equity + floating_pnl + final_margin
        
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
        floating_pnl = hold_pnl  # 没有操作时，浮盈等于Hold的浮盈
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
        
        # 显示剩余资金(止盈) - 添加详细说明
        st.metric(
            "剩余资金(止盈)", 
            f"${adjusted_equity_final:,.0f}",
            help="平仓后的总资金 = 可用资金 + 浮盈 + 保证金释放"
        )
        
        # 显示分解明细
        if len(st.session_state.operations) > 0:
            with st.expander("💡 计算明细"):
                st.caption(f"**可用资金**: ${seq_equity:,.0f}")
                st.caption(f"**持仓浮盈**: ${floating_pnl:,.0f}")
                st.caption(f"**保证金释放**: ${final_margin:,.0f}")
                st.caption(f"**合计**: ${adjusted_equity_final:,.0f}")
        
        # 显示纯浮盈（剩余持仓的未实现盈亏），而不是总盈利
        st.metric("浮盈", f"${floating_pnl:,.0f}", 
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
    price_min_main = min(current_price, target_price)
    price_max_main = max(current_price, target_price)
    
    # 如果有操作序列，确保包含所有操作点
    if len(st.session_state.operations) > 0:
        op_prices = [op['price'] for op in st.session_state.operations]
        price_min_main = min(price_min_main, min(op_prices))
        price_max_main = max(price_max_main, max(op_prices))
    
    # 添加缓冲（5%）使图表更美观
    price_range = price_max_main - price_min_main
    x_min = price_min_main - price_range * 0.08
    x_max = price_max_main + price_range * 0.08
    
    x_prices = np.linspace(x_min, x_max, 200)
    
    # ========== 1. 计算 Hold 曲线 (蓝色虚线) ==========
    # Hold = 从当前价开始持有，PnL = (当前模拟价 - 开仓均价) × 持仓量
    pnl_hold_curve = []
    for p in x_prices:
        pnl = (p - long_entry) * (long_qty - short_qty)
        pnl_hold_curve.append(pnl)
    
    # ========== 2. 计算操作序列曲线 (绿色实线) ==========
    # 需要分段计算，每个操作点后持仓和均价都变化
    
    # 按价格排序操作（模拟价格上涨过程中触发操作）
    sorted_ops = sorted(st.session_state.operations, key=lambda x: x['price'])
    
    # 构建关键价格点
    key_prices = [x_min]
    for op in sorted_ops:
        if x_min < op['price'] < x_max:
            key_prices.append(op['price'])
    key_prices.append(x_max)
    key_prices = sorted(set(key_prices))
    
    # 在每两个关键点之间生成密集的价格点
    x_adjusted_prices = []
    for i in range(len(key_prices) - 1):
        segment_prices = np.linspace(key_prices[i], key_prices[i + 1], 30, endpoint=False)
        x_adjusted_prices.extend(segment_prices)
    x_adjusted_prices.append(key_prices[-1])
    x_adjusted_prices = np.array(x_adjusted_prices)
    
    # 模拟执行过程 - 使用Excel公式保持一致性
    sim_qty = long_qty
    sim_entry = long_entry
    cumulative_realized_pnl = 0  # 累计已实现盈亏
    op_index = 0
    
    # Excel formula tracking variables (与操作列表一致)
    prev_price_chart = long_entry if long_qty > 0 else 0
    net_position_chart = long_qty * long_entry if long_qty > 0 else 0
    floating_position_chart = net_position_chart
    
    pnl_adjusted_curve = []
    operation_annotations = []  # 存储操作点的标注信息
    
    for p in x_adjusted_prices:
        # 检查是否触发操作
        while op_index < len(sorted_ops) and sorted_ops[op_index]['price'] <= p:
            op = sorted_ops[op_index]
            op_price = op['price']
            
            if op['action'] == '卖出':
                if op['amount_type'] == '百分比':
                    sell_qty = sim_qty * (op['amount'] / 100)
                else:
                    sell_qty = min(op['amount'] / sim_entry, sim_qty) if sim_entry > 0 else 0
                
                # 计算该笔卖出的实现盈亏
                realized_pnl = sell_qty * (op_price - sim_entry)
                cumulative_realized_pnl += realized_pnl
                sim_qty -= sell_qty
                
                # Excel: 卖出后按比例减少净持仓和浮动持仓
                sell_ratio = sell_qty / (sim_qty + sell_qty) if (sim_qty + sell_qty) > 0 else 0
                net_position_chart = net_position_chart * (1 - sell_ratio)
                floating_position_chart = floating_position_chart * (1 - sell_ratio)
                
                # 记录操作点信息
                total_pnl = cumulative_realized_pnl + (op_price - sim_entry) * sim_qty
                
                # 计算此刻 Hold 的 PnL 用于对比
                hold_pnl_now = (op_price - long_entry) * (long_qty - short_qty)
                diff_vs_hold = total_pnl - hold_pnl_now
                
                operation_annotations.append({
                    'price': op_price,
                    'action': '卖出',
                    'pnl': total_pnl,
                    'diff_vs_hold': diff_vs_hold,
                    'qty_change': sell_qty
                })
                
            else:  # 买入 - 使用Excel公式
                if op['amount_type'] == '百分比':
                    buy_value = (sim_qty * op_price) * (op['amount'] / 100)
                else:
                    buy_value = op['amount']
                
                buy_qty = buy_value / op_price if op_price > 0 else 0
                effective_usdt = buy_value
                
                # Excel formula: 保存前一个均价
                prev_avg_chart = sim_entry
                
                # Excel formula: Net Position
                prev_net_chart = net_position_chart
                net_position_chart += effective_usdt
                
                # Excel formula: Floating Position - 价格方向判断
                if prev_net_chart > 0:
                    if op_price < prev_price_chart:  # 价格下跌
                        floating_position_chart = effective_usdt + prev_net_chart - (prev_avg_chart - op_price) * prev_net_chart / prev_avg_chart
                    else:  # 价格上涨或持平
                        floating_position_chart = effective_usdt + prev_net_chart + (prev_avg_chart - op_price) * prev_net_chart / prev_avg_chart
                else:
                    floating_position_chart = effective_usdt
                
                # Excel formula: Average Price
                if floating_position_chart > 0:
                    sim_entry = ((op_price * effective_usdt) + prev_avg_chart * (floating_position_chart - effective_usdt)) / floating_position_chart
                
                sim_qty += buy_qty
                prev_price_chart = op_price
                
                # 记录操作点信息
                total_pnl = cumulative_realized_pnl + (op_price - sim_entry) * sim_qty
                
                # 计算此刻 Hold 的 PnL 用于对比
                hold_pnl_now = (op_price - long_entry) * (long_qty - short_qty)
                diff_vs_hold = total_pnl - hold_pnl_now
                
                operation_annotations.append({
                    'price': op_price,
                    'action': '买入',
                    'pnl': total_pnl,
                    'diff_vs_hold': diff_vs_hold,
                    'qty_change': buy_qty
                })
            
            op_index += 1
        
        # 计算当前价格的总PnL = 累计已实现 + 未实现
        unrealized_pnl = (p - sim_entry) * sim_qty
        total_pnl = cumulative_realized_pnl + unrealized_pnl
        pnl_adjusted_curve.append(total_pnl)
    
    # ========== 绘制图表 ==========
    fig = go.Figure()
    
    # Hold曲线（蓝色虚线）
    fig.add_trace(go.Scatter(
        x=x_prices, 
        y=pnl_hold_curve,
        mode='lines',
        name='📉 Hold (死扛)',
        line=dict(color='#3b82f6', width=3, dash='dash'),
        hovertemplate='<b>Hold策略</b><br>BTC: $%{x:,.0f}<br>PnL: $%{y:,.0f}<extra></extra>'
    ))
    
    # 操作序列曲线（绿色实线）
    if len(st.session_state.operations) > 0:
        fig.add_trace(go.Scatter(
            x=x_adjusted_prices,
            y=pnl_adjusted_curve,
            mode='lines',
            name=f'📈 操作序列 ({len(st.session_state.operations)}步)',
            line=dict(color='#22c55e', width=3),
            hovertemplate='<b>操作序列</b><br>BTC: $%{x:,.0f}<br>PnL: $%{y:,.0f}<extra></extra>'
        ))
    
    # ========== 标记关键点 ==========
    
    # 起点：当前价格
    current_pnl = (current_price - long_entry) * (long_qty - short_qty)
    fig.add_trace(go.Scatter(
        x=[current_price], y=[current_pnl],
        mode='markers+text', 
        name='当前价',
        text=['当前价'],
        textposition='top center',
        textfont=dict(size=11, color='#1e40af'),
        marker=dict(color='#3b82f6', size=14, symbol='circle', line=dict(color='white', width=2)),
        showlegend=False,
        hovertemplate=f'<b>当前价格</b><br>BTC: ${current_price:,.0f}<br>PnL: ${current_pnl:,.0f}<extra></extra>'
    ))
    
    # 目标价位置的两个点
    hold_pnl_at_target = (target_price - long_entry) * (long_qty - short_qty)
    
    # 计算操作序列在目标价的PnL
    if len(pnl_adjusted_curve) > 0:
        # 找到最接近目标价的点
        idx = np.argmin(np.abs(x_adjusted_prices - target_price))
        adjusted_pnl_at_target = pnl_adjusted_curve[idx]
    else:
        adjusted_pnl_at_target = hold_pnl_at_target
    
    # Hold 在目标价的点（灰色）
    fig.add_trace(go.Scatter(
        x=[target_price], y=[hold_pnl_at_target],
        mode='markers+text', 
        name='Hold目标',
        text=[f'Hold: ${hold_pnl_at_target/1000:.0f}k'],
        textposition='bottom center',
        textfont=dict(size=10, color='#6b7280'),
        marker=dict(color='#6b7280', size=12, symbol='circle'),
        showlegend=False,
        hovertemplate=f'<b>Hold @ 目标价</b><br>BTC: ${target_price:,.0f}<br>PnL: ${hold_pnl_at_target:,.0f}<extra></extra>'
    ))
    
    # 操作序列在目标价的点（绿色星星）
    if len(st.session_state.operations) > 0:
        fig.add_trace(go.Scatter(
            x=[target_price], y=[adjusted_pnl_at_target],
            mode='markers+text', 
            name='操作目标',
            text=[f'操作: ${adjusted_pnl_at_target/1000:.0f}k'],
            textposition='top center',
            textfont=dict(size=11, color='#16a34a', weight='bold'),
            marker=dict(color='#22c55e', size=16, symbol='star', line=dict(color='white', width=2)),
            showlegend=False,
            hovertemplate=f'<b>操作序列 @ 目标价</b><br>BTC: ${target_price:,.0f}<br>PnL: ${adjusted_pnl_at_target:,.0f}<extra></extra>'
        ))
    
    # ========== 标记每个操作点 ==========
    for i, op_ann in enumerate(operation_annotations):
        color = '#ef4444' if op_ann['action'] == '卖出' else '#22c55e'
        symbol = 'triangle-down' if op_ann['action'] == '卖出' else 'triangle-up'
        text_pos = 'bottom center' if op_ann['action'] == '卖出' else 'top center'
        
        # 差异标注文字
        diff = op_ann['diff_vs_hold']
        diff_text = f"+${diff/1000:.1f}k" if diff >= 0 else f"-${abs(diff)/1000:.1f}k"
        
        fig.add_trace(go.Scatter(
            x=[op_ann['price']], y=[op_ann['pnl']],
            mode='markers+text',
            text=[f"{op_ann['action']}"],
            textposition=text_pos,
            textfont=dict(size=10, color=color),
            showlegend=False,
            marker=dict(color=color, size=12, symbol=symbol, line=dict(width=2, color='white')),
            hovertemplate=f"<b>{op_ann['action']}</b><br>价格: ${op_ann['price']:,.0f}<br>PnL: ${op_ann['pnl']:,.0f}<br>vs Hold: {diff_text}<extra></extra>"
        ))
    
    # ========== 目标价垂直线和差异标注 ==========
    fig.add_vline(
        x=target_price, 
        line_dash="dot", 
        line_color="rgba(0,0,0,0.4)",
        line_width=2
    )
    
    # 在目标价位置添加差异标注
    if len(st.session_state.operations) > 0:
        diff_at_target = adjusted_pnl_at_target - hold_pnl_at_target
        diff_color = '#22c55e' if diff_at_target >= 0 else '#ef4444'
        diff_sign = '+' if diff_at_target >= 0 else ''
        
        # 在两条曲线中间位置添加差异标注
        mid_y = (hold_pnl_at_target + adjusted_pnl_at_target) / 2
        
        fig.add_annotation(
            x=target_price,
            y=mid_y,
            text=f"<b>差异: {diff_sign}${diff_at_target:,.0f}</b>",
            showarrow=True,
            arrowhead=0,
            arrowcolor=diff_color,
            arrowwidth=2,
            ax=80,
            ay=0,
            font=dict(size=14, color=diff_color, weight='bold'),
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor=diff_color,
            borderwidth=2,
            borderpad=6
        )
    
    # 盈亏平衡线（0线）
    fig.add_hline(y=0, line_dash="solid", line_color="rgba(0,0,0,0.2)", line_width=1)

    # ========== 布局美化 ==========
    fig.update_layout(
        title=dict(
            text="📊 策略对比：操作序列 vs Hold (到目标价)",
            font=dict(size=18)
        ),
        xaxis_title="BTC 价格 (USDT)",
        yaxis_title="盈亏 (USDT)",
        template="plotly_white",
        height=450,
        hovermode="x unified",
        legend=dict(
            yanchor="top", y=0.99, xanchor="left", x=0.01,
            bgcolor="rgba(255, 255, 255, 0.95)",
            bordercolor="#e5e7eb",
            borderwidth=1,
            font=dict(size=12)
        ),
        margin=dict(l=60, r=80, t=70, b=50),
    )
    
    # 格式化坐标轴
    fig.update_yaxes(tickprefix="$", tickformat=".2s", gridcolor='rgba(0,0,0,0.05)')
    fig.update_xaxes(tickformat=",d", gridcolor='rgba(0,0,0,0.05)')
    
    st.plotly_chart(fig, use_container_width=True)
    
    # ========== 图表下方的简明总结 ==========
    if len(st.session_state.operations) > 0:
        diff_at_target = adjusted_pnl_at_target - hold_pnl_at_target
        
        summary_cols = st.columns(3)
        with summary_cols[0]:
            st.metric("Hold 盈亏", f"${hold_pnl_at_target:,.0f}", help="持有到目标价的盈亏")
        with summary_cols[1]:
            st.metric("操作序列 盈亏", f"${adjusted_pnl_at_target:,.0f}", help="执行操作序列后到目标价的盈亏")
        with summary_cols[2]:
            delta_color = "normal" if diff_at_target >= 0 else "inverse"
            st.metric("差异", f"${diff_at_target:,.0f}", 
                     delta=f"{'多赚' if diff_at_target >= 0 else '少赚'} ${abs(diff_at_target):,.0f}",
                     delta_color=delta_color,
                     help="操作序列相比Hold的差异")
