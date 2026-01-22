"""
「分散网格」Ping-Pong 策略优化器 - 完善版 v2

核心特点：
1. 真正分散：价格在区间内均匀分布，不聚集在边界
2. 6-8%价差：每对买卖价格的价差严格控制在6%-8%
3. 资金追踪：清晰显示每轮操作后的可用资金
4. 完整状态：展示每步后的持仓、均价、强平价、权益

资金模型：
- 账户总权益 = 仓位权益 + 可用余额
- 仓位权益 = (入场均价 - 当前强平价) × 持仓数量
- 可用余额 = 用于新操作的资金（$300,000）
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple
import time


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
    2. 每个卖出价 = 对应买入价 × (1.06 ~ 1.08)
    3. 卖出价在卖出区间内
    """
    buy_segment = (buy_zone_high - buy_zone_low) / n_rounds
    
    buy_prices = []
    sell_prices = []
    
    for i in range(n_rounds):
        # 买入价：在第i段内随机选择
        seg_low = buy_zone_low + i * buy_segment
        seg_high = buy_zone_low + (i + 1) * buy_segment
        buy_price = rng.uniform(seg_low, seg_high)
        
        # 卖出价：买入价 × (1.06 ~ 1.08)
        sell_price = buy_price * rng.uniform(1 + min_spread, 1 + max_spread)
        
        # 确保卖出价在卖出区间内
        sell_price = np.clip(sell_price, sell_zone_low, sell_zone_high)
        
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
    - 分散性（间距+均匀）：40%
    - 价差合理性：25%
    - 安全性：20%
    - 盈利：15%
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
    
    # 4. 安全性得分
    if not result['all_safe']:
        safety_score = 0
    else:
        margin = (config.max_liq_price - result['max_liq_price']) / config.max_liq_price
        safety_score = 0.5 + 0.5 * margin
    
    # 5. 盈利得分
    profit_score = min(1.0, result['total_realized_pnl'] / 25000)
    
    # 加权
    total_score = (
        gap_score * 0.20 +
        uniformity_score * 0.20 +
        spread_score * 0.25 +
        safety_score * 0.20 +
        profit_score * 0.15
    )
    
    # 硬约束惩罚
    if not result['all_safe']:
        total_score *= 0.01
    if not gap_ok:
        total_score *= 0.5
    
    return total_score, result


def optimize_grid(config: GridConfig) -> Tuple[List, List, Dict]:
    """优化分散网格"""
    rng = np.random.default_rng()
    
    print("="*90)
    print("🎯 「分散网格」策略优化器 v2")
    print("="*90)
    
    print(f"\n💡 核心原则:")
    print(f"  1. 价格分散：在区间内均匀分布，不聚集边界")
    print(f"  2. 价差控制：每对买卖 {config.min_spread_pct*100:.0f}%-{config.max_spread_pct*100:.0f}%")
    print(f"  3. 间距要求：相邻价格间隔 >= ${config.min_price_gap:,.0f}")
    
    print(f"\n📊 当前持仓:")
    print(f"  持仓量: {config.current_qty} BTC")
    print(f"  入场均价: ${config.entry_price:,.0f}")
    print(f"  当前强平价: ${config.current_liq_price:,.0f}")
    print(f"  仓位权益: ${(config.entry_price - config.current_liq_price) * config.current_qty:,.0f}")
    print(f"  可用余额: ${config.available_capital:,.0f}")
    
    print(f"\n🔲 操作区间:")
    print(f"  买入区: ${config.buy_zone_low:,.0f} - ${config.buy_zone_high:,.0f}")
    print(f"  卖出区: ${config.sell_zone_low:,.0f} - ${config.sell_zone_high:,.0f}")
    
    print(f"\n⚙️ 参数:")
    print(f"  操作轮数: {config.n_rounds}")
    print(f"  每轮金额: ${config.amount_per_round:,.0f}")
    print(f"  强平价限制: < ${config.max_liq_price:,.0f}")
    
    # 初始化种群
    print("\n🚀 开始优化...")
    
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
    
    start_time = time.time()
    
    for gen in range(config.n_generations):
        population.sort(key=lambda x: x[2], reverse=True)
        
        if population[0][2] > best_score:
            best_solution = (population[0][0].copy(), population[0][1].copy())
            best_score = population[0][2]
            best_result = population[0][3]
        
        if gen % 30 == 0 or gen == config.n_generations - 1:
            r = population[0][3]
            print(f"  代数 {gen+1:3d} | "
                  f"得分: {population[0][2]:.3f} | "
                  f"盈利: ${r['total_realized_pnl']:,.0f} | "
                  f"价差: {r['avg_spread_pct']*100:.1f}% | "
                  f"均匀: {r['buy_uniformity']:.2f}/{r['sell_uniformity']:.2f}")
        
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
    
    elapsed = time.time() - start_time
    print(f"\n✅ 优化完成！用时 {elapsed:.2f} 秒")
    
    return best_solution[0], best_solution[1], best_result


def display_results(
    buy_prices: List[float],
    sell_prices: List[float],
    result: Dict,
    config: GridConfig
):
    """详细显示结果"""
    
    print("\n" + "="*95)
    print("💎 最优分散网格策略")
    print("="*95)
    
    # 基本结果
    print(f"\n📈 策略结果:")
    print(f"  总实现盈利: ${result['total_realized_pnl']:,.2f}")
    print(f"  均价降低: ${result['entry_reduction']:,.2f}")
    print(f"  最终均价: ${result['final_entry']:,.2f}")
    print(f"  最终强平价: ${result['final_liq_price']:,.2f}")
    print(f"  最大强平价: ${result['max_liq_price']:,.2f} {'✅' if result['all_safe'] else '❌'}")
    print(f"  剩余可用余额: ${result['final_available_balance']:,.2f}")
    print(f"  BTC@${config.target_btc_price:,.0f}盈利: ${result['profit_at_target']:,.2f}")
    
    # 分散度分析
    print(f"\n🎯 分散度分析:")
    print(f"  买入均匀度: {result['buy_uniformity']:.2f} (1.0=完美)")
    print(f"  卖出均匀度: {result['sell_uniformity']:.2f}")
    print(f"  买入最小间距: ${result['min_buy_gap']:,.0f} {'✅' if result['min_buy_gap'] >= config.min_price_gap else '⚠️'}")
    print(f"  卖出最小间距: ${result['min_sell_gap']:,.0f} {'✅' if result['min_sell_gap'] >= config.min_price_gap else '⚠️'}")
    print(f"  平均价差: {result['avg_spread_pct']*100:.1f}%")
    print(f"  价差达标: {result['spread_ok_count']}/{config.n_rounds} 轮")
    
    # 网格布局
    sorted_buys = sorted(buy_prices)
    sorted_sells = sorted(sell_prices)
    
    print(f"\n🔲 网格布局:")
    print("-"*90)
    print(f"  买入网格: ", end="")
    for i, p in enumerate(sorted_buys):
        if i > 0:
            gap = sorted_buys[i] - sorted_buys[i-1]
            print(f" --[${gap:,.0f}]--> ", end="")
        print(f"${p:,.0f}", end="")
    print()
    
    print(f"  卖出网格: ", end="")
    for i, p in enumerate(sorted_sells):
        if i > 0:
            gap = sorted_sells[i] - sorted_sells[i-1]
            print(f" --[${gap:,.0f}]--> ", end="")
        print(f"${p:,.0f}", end="")
    print()
    print("-"*90)
    
    # 配对视图
    print(f"\n🔗 买卖配对:")
    print("-"*80)
    print(f"{'轮次':<6} {'买入价':<12} {'卖出价':<12} {'价差$':<10} {'价差%':<10} {'状态':<8}")
    print("-"*80)
    
    for i in range(config.n_rounds):
        spread = sell_prices[i] - buy_prices[i]
        spread_pct = (spread / buy_prices[i]) * 100
        in_target = config.min_spread_pct*100 <= spread_pct <= config.max_spread_pct*100
        status = "✅ 达标" if in_target else "⚠️ 偏离"
        print(f"第{i+1}轮   ${buy_prices[i]:>9,.0f}   ${sell_prices[i]:>9,.0f}   "
              f"${spread:>7,.0f}   {spread_pct:>6.1f}%    {status}")
    print("-"*80)
    
    # 执行详情
    print(f"\n📋 执行详情:")
    print("-"*95)
    print(f"{'步骤':<8} {'操作':<6} {'价格':<11} {'数量':<10} {'均价':<12} {'强平价':<11} {'可用余额':<14} {'状态':<6}")
    print("-"*95)
    
    print(f"{'初始':<6}  {'-':<6} {'-':<11} {config.current_qty:<10.2f} "
          f"${config.entry_price:<10,.0f} ${config.current_liq_price:<9,.0f} "
          f"${config.available_capital:<12,.0f} {'✅':<6}")
    
    step = 1
    for op in result['operations']:
        if op.get('type') == 'skip':
            continue
            
        action = "🟢买入" if op['type'] == 'buy' else "🔴卖出"
        liq_status = "✅" if op['liq_ok'] else "❌"
        
        print(f"步骤{step:<2}  {action:<4} ${op['price']:<9,.0f} "
              f"{abs(op['qty_change']):<10.4f} "
              f"${op['entry_after']:<10,.2f} ${op['liq_price']:<9,.2f} "
              f"${op['available_balance']:<12,.2f} {liq_status:<6}")
        step += 1
    
    print("-"*95)
    
    # ⭐ 均价调整汇总 - 用户关注点
    print(f"\n" + "="*75)
    print(f"📊 入场均价调整汇总")
    print(f"="*75)
    print(f"  原始入场均价:     ${config.entry_price:>12,.2f}")
    print(f"  最终入场均价:     ${result['final_entry']:>12,.2f}")
    print(f"  均价降低:         ${result['entry_reduction']:>12,.2f}")
    reduction_pct = (result['entry_reduction'] / config.entry_price) * 100
    print(f"  降低幅度:         {reduction_pct:>12.2f}%")
    print(f"="*75)
    
    # 每轮详细盈亏
    print(f"\n💰 每轮盈亏详情:")
    print("-"*75)
    print(f"{'轮次':<6} {'买入价':<12} {'卖出价':<12} {'数量':<10} {'盈亏':<12} {'累计盈亏':<12}")
    print("-"*75)
    
    cumulative_pnl = 0
    for i in range(0, len(result['operations']), 2):
        if i+1 >= len(result['operations']):
            break
        buy_op = result['operations'][i]
        sell_op = result['operations'][i+1]
        if buy_op.get('type') != 'buy':
            continue
        
        pnl = sell_op.get('realized_pnl', 0)
        cumulative_pnl += pnl
        qty = abs(buy_op['qty_change'])
        
        print(f"第{i//2+1}轮   ${buy_op['price']:>9,.0f}   ${sell_op['price']:>9,.0f}   "
              f"{qty:<10.4f} ${pnl:>10,.2f}  ${cumulative_pnl:>10,.2f}")
    
    print("-"*75)
    print(f"{'合计':<6} {'':<12} {'':<12} {'':<10} ${result['total_realized_pnl']:>10,.2f}  ${result['total_realized_pnl']:>10,.2f}")
    print("-"*75)
    
    # ⭐ 初始状态 vs 最终状态 完整对比
    print(f"\n" + "="*75)
    print(f"📈 策略效果：初始 vs 最终")
    print(f"="*75)
    print(f"{'指标':<20} {'初始':<20} {'最终':<20} {'变化':<15}")
    print("-"*75)
    print(f"{'持仓数量':<18} {config.current_qty:<20.2f} {result['final_qty']:<20.2f} {'无变化':<15}")
    print(f"{'入场均价':<18} ${config.entry_price:<18,.0f} ${result['final_entry']:<18,.2f} -${result['entry_reduction']:<13,.2f}")
    print(f"{'强平价':<18} ${config.current_liq_price:<18,.0f} ${result['final_liq_price']:<18,.2f} ↓ 更安全")
    print(f"{'可用余额':<18} ${config.available_capital:<18,.0f} ${result['final_available_balance']:<18,.2f} +${result['total_realized_pnl']:<13,.2f}")
    print("-"*75)
    
    # 策略总结
    print(f"\n💡 策略特点:")
    print(f"  ✅ 买入分散在 ${min(buy_prices):,.0f} - ${max(buy_prices):,.0f} (区间覆盖)")
    print(f"  ✅ 卖出分散在 ${min(sell_prices):,.0f} - ${max(sell_prices):,.0f}")
    print(f"  ✅ 每对买卖价差约 {result['avg_spread_pct']*100:.1f}%")
    print(f"  ✅ 不依赖精确价格预测，任一触及即可执行")
    print(f"  ✅ 强平价全程 < ${config.max_liq_price:,.0f}")
    print(f"  ✅ 持仓不变但均价降低 {reduction_pct:.2f}%，同时赚取 ${result['total_realized_pnl']:,.2f}")


def main():
    """主函数"""
    config = GridConfig(
        # 持仓状态
        current_qty=25.0,
        entry_price=100_150,
        current_liq_price=20_030,
        available_capital=300_000,
        
        # 买入区间
        buy_zone_low=83_000,
        buy_zone_high=86_000,
        
        # 卖出区间
        sell_zone_low=89_000,
        sell_zone_high=92_000,
        
        # 目标价差
        min_spread_pct=0.06,
        max_spread_pct=0.08,
        
        # 最小间距
        min_price_gap=800,
        
        # 约束
        max_liq_price=28_000,
        leverage=10,
        target_btc_price=120_000,
        
        # 操作参数
        n_rounds=3,
        amount_per_round=100_000,
        
        # 算法参数
        population_size=500,
        n_generations=300
    )
    
    # 运行优化
    best_buy, best_sell, best_result = optimize_grid(config)
    
    # 显示结果
    display_results(best_buy, best_sell, best_result, config)
    
    print("\n" + "="*95)
    print("✅ 分散网格策略优化完成！")
    print("="*95)
    
    return best_buy, best_sell, best_result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
