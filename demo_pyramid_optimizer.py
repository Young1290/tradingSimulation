"""
金字塔式分批解套策略优化器

核心策略：
1. 金字塔买入：越低价买入仓位越大
2. 分批止盈：在高位分多个价位逐步卖出
3. 严格风控：强平价 < $28,500

用户参数：
- 当前持仓：多单 25 BTC @ $100,150
- 可用子弹：$300,000 USDT
- 震荡区间：$82,000 - $94,000
- 目标：BTC@$120,000 盈利 > $550,000
- 硬约束：强平价 < $28,500
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import time


@dataclass
class PyramidConfig:
    """金字塔策略配置"""
    
    # ========== 当前持仓状态 ==========
    current_qty: float = 25.0              # 当前持仓 25 BTC
    entry_price: float = 100_150           # 入场均价
    available_capital: float = 300_000     # 可用子弹 $300,000
    current_liq_price: float = 20_030      # 当前强平价
    
    # ========== 震荡区间 ==========
    swing_low: float = 82_000              # 区间低点
    swing_high: float = 94_000             # 区间高点
    
    # ========== 硬约束 ==========
    max_liq_price: float = 28_500          # 强平价硬上限（安全垫）
    leverage: int = 10                      # 固定杠杆
    
    # ========== 目标 ==========
    target_btc_price: float = 120_000      # 目标价格
    target_profit: float = 550_000         # 目标盈利 > $550,000
    
    # ========== 金字塔买入网格 ==========
    # 价格越低，买入比例越高
    buy_levels: List[Tuple[float, float]] = field(default_factory=lambda: [
        # (价格, 最大占用资金比例)
        (82000, 0.35),   # 最低位，最多用35%资金
        (83000, 0.25),   # 次低位，25%
        (84000, 0.18),   # 低位，18%
        (85000, 0.12),   # 中低位，12%
        (86000, 0.07),   # 中位，7%
        (87000, 0.03),   # 中高位，3%
    ])
    
    # ========== 分批止盈网格 ==========
    sell_levels: List[Tuple[float, float]] = field(default_factory=lambda: [
        # (价格, 卖出仓位比例)
        (89000, 0.08),   # 刚过中间，小额试水
        (90000, 0.12),   # 
        (91000, 0.15),   # 
        (92000, 0.20),   # 高位，加大卖出
        (93000, 0.22),   # 
        (94000, 0.23),   # 最高位，最大卖出
    ])
    
    # ========== 遗传算法参数 ==========
    population_size: int = 400
    n_generations: int = 200
    mutation_rate: float = 0.35
    elite_ratio: float = 0.1


def calculate_liq_price(entry: float, equity: float, qty: float) -> float:
    """计算强平价"""
    if qty <= 0:
        return 0
    liq = entry - equity / qty
    return max(0, liq)


def simulate_pyramid_strategy(
    buy_ratios: List[float],   # 每个买入价位实际使用的资金比例 (0-1)
    sell_ratios: List[float],  # 每个卖出价位实际卖出的比例 (0-1)
    config: PyramidConfig
) -> Dict:
    """
    模拟金字塔策略执行
    
    重要：使用与Calculation.py一致的强平价计算
    强平价 = 入场均价 - 账户权益 / 持仓数量
    
    账户权益 = 现有权益 - 占用保证金 + 浮动盈亏
    但因为我们按价格顺序执行，此时没有浮盈，所以：
    账户权益 ≈ 初始权益 + 新增保证金
    """
    # 初始状态
    qty = config.current_qty
    entry = config.entry_price
    
    # 用户提供的初始状态：
    # - 已有25 BTC持仓，均价$100,150
    # - 可用子弹 $300,000
    # - 当前强平价 $20,030
    #
    # 反推当前账户权益：
    # Liq = Entry - Equity/Qty
    # 20,030 = 100,150 - Equity/25
    # Equity = (100,150 - 20,030) * 25 = $2,003,000
    
    # 初始账户总权益
    initial_total_equity = (config.entry_price - config.current_liq_price) * config.current_qty
    
    # 账户权益 = 初始权益，可用于加仓的是额外的$300,000
    total_equity = initial_total_equity
    available_capital = config.available_capital  # 可用于加仓的资金 $300,000
    
    operations = []
    max_liq_price = config.current_liq_price
    
    # ===== 执行买入操作（金字塔式）=====
    for i, (price, max_ratio) in enumerate(config.buy_levels):
        actual_ratio = buy_ratios[i] * max_ratio
        buy_amount = config.available_capital * actual_ratio  # 用于买入的名义金额
        
        if buy_amount < 1000:
            continue
        
        # 检查是否有足够可用资金
        margin_needed = buy_amount / config.leverage
        if available_capital < margin_needed:
            buy_amount = available_capital * config.leverage
            margin_needed = available_capital
        
        if buy_amount < 1000:
            continue
        
        # 执行买入
        qty_bought = buy_amount / price
        
        old_qty = qty
        old_entry = entry
        qty += qty_bought
        available_capital -= margin_needed
        
        # 更新均价（加权平均）
        entry = (old_entry * old_qty + price * qty_bought) / qty
        
        # 新增买入会增加账户权益（保证金）
        total_equity += margin_needed
        
        # 计算强平价 = Entry - Equity / Qty
        liq_price = entry - total_equity / qty
        liq_price = max(0, liq_price)
        max_liq_price = max(max_liq_price, liq_price)
        
        operations.append({
            'price': price,
            'action': 'buy',
            'value': buy_amount,
            'qty_change': qty_bought,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'available_capital': available_capital,
            'total_equity': total_equity
        })
    
    # ===== 执行卖出操作（分批止盈）=====
    for i, (price, max_ratio) in enumerate(config.sell_levels):
        actual_ratio = sell_ratios[i] * max_ratio
        
        sell_qty = qty * actual_ratio
        
        if sell_qty < 0.001 or qty <= 0:
            continue
        
        sell_value = sell_qty * price
        
        # 执行卖出
        realized_pnl = (price - entry) * sell_qty
        margin_released = (sell_qty * entry) / config.leverage
        
        # 卖出后：权益变化 = 实现盈亏（保证金返还不算，因为仓位减少）
        # 实际上权益因为盈亏而变化
        total_equity += realized_pnl
        
        qty -= sell_qty
        
        # 计算强平价
        if qty > 0:
            liq_price = entry - total_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        max_liq_price = max(max_liq_price, liq_price)
        
        operations.append({
            'price': price,
            'action': 'sell',
            'value': sell_value,
            'qty_change': -sell_qty,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'available_capital': available_capital,
            'total_equity': total_equity
        })
    
    # 最终状态
    final_equity = total_equity
    if qty > 0:
        profit_at_target = (config.target_btc_price - entry) * qty
    else:
        profit_at_target = final_equity - initial_total_equity
    
    return {
        'final_qty': qty,
        'final_entry': entry,
        'final_equity': final_equity,
        'max_liq_price': max_liq_price,
        'profit_at_target': profit_at_target,
        'entry_reduction': config.entry_price - entry,
        'operations': operations,
        'num_operations': len(operations),
        'total_buy': sum(op['value'] for op in operations if op['action'] == 'buy'),
        'total_sell': sum(op['value'] for op in operations if op['action'] == 'sell')
    }


def evaluate_pyramid_solution(
    buy_ratios: List[float],
    sell_ratios: List[float],
    config: PyramidConfig
) -> Tuple[float, Dict]:
    """评估金字塔策略"""
    result = simulate_pyramid_strategy(buy_ratios, sell_ratios, config)
    
    # 1. 盈利得分（目标 > $550,000）
    profit_score = result['profit_at_target'] / config.target_profit
    profit_score = min(profit_score, 2.0)
    
    # 2. 均价降低得分
    entry_reduction_score = result['entry_reduction'] / 5000
    entry_reduction_score = max(0, entry_reduction_score)
    
    # 3. 强平价安全得分（硬约束：< $28,500）
    liq_price = result['max_liq_price']
    if liq_price > config.max_liq_price + 3000:
        liq_score = -20  # 严重违规
    elif liq_price > config.max_liq_price:
        liq_score = -5 * (liq_price - config.max_liq_price) / 1000
    else:
        # 在安全范围内，越低越好
        safety_margin = (config.max_liq_price - liq_price) / config.max_liq_price
        liq_score = 0.5 + 0.5 * safety_margin
    
    # 4. 金字塔结构得分（买入应该是低位多、高位少）
    buy_amounts = [buy_ratios[i] * config.buy_levels[i][1] for i in range(len(buy_ratios))]
    pyramid_score = 0
    for i in range(len(buy_amounts) - 1):
        if buy_amounts[i] >= buy_amounts[i + 1]:
            pyramid_score += 0.1
    pyramid_score = min(1.0, pyramid_score)
    
    # 5. 分批操作得分（不能单点梭哈）
    active_buys = sum(1 for r in buy_ratios if r > 0.1)
    active_sells = sum(1 for r in sell_ratios if r > 0.1)
    diversification_score = min(1.0, (active_buys + active_sells) / 8)
    
    # 6. 资金利用率得分
    capital_usage = result['total_buy'] / config.available_capital
    if capital_usage < 0.5:
        usage_score = capital_usage
    elif capital_usage <= 1.0:
        usage_score = 1.0 - abs(capital_usage - 0.8) * 0.5
    else:
        usage_score = 0.5
    
    # 加权总分
    total_score = (
        profit_score * 0.30 +
        entry_reduction_score * 0.20 +
        liq_score * 0.20 +
        pyramid_score * 0.10 +
        diversification_score * 0.10 +
        usage_score * 0.10
    )
    
    # 硬约束惩罚
    if liq_price > config.max_liq_price + 3000:
        total_score *= 0.01
    elif liq_price > config.max_liq_price:
        total_score *= 0.2
    
    return total_score, result


def optimize_pyramid_strategy(config: PyramidConfig) -> Tuple[List[float], List[float], Dict]:
    """使用遗传算法优化金字塔策略"""
    rng = np.random.default_rng()
    
    n_buy_levels = len(config.buy_levels)
    n_sell_levels = len(config.sell_levels)
    
    print("="*80)
    print("🔺 金字塔式分批解套策略优化器")
    print("="*80)
    
    print(f"\n📊 当前持仓状态:")
    print(f"  持仓量: {config.current_qty} BTC")
    print(f"  入场均价: ${config.entry_price:,.0f}")
    print(f"  当前强平价: ${config.current_liq_price:,.0f}")
    print(f"  可用子弹: ${config.available_capital:,.0f}")
    
    print(f"\n🔺 金字塔买入网格（越低越重仓）:")
    for price, ratio in config.buy_levels:
        max_amount = config.available_capital * ratio
        print(f"  ${price:,} → 最高 ${max_amount:,.0f} ({ratio*100:.0f}%)")
    
    print(f"\n📉 分批止盈网格:")
    for price, ratio in config.sell_levels:
        print(f"  ${price:,} → 最高卖出 {ratio*100:.0f}% 持仓")
    
    print(f"\n🎯 优化目标:")
    print(f"  目标价格: ${config.target_btc_price:,.0f}")
    print(f"  目标盈利: > ${config.target_profit:,.0f}")
    print(f"  强平价上限: < ${config.max_liq_price:,.0f} (硬约束)")
    
    print(f"\n⚙️ 算法参数:")
    print(f"  种群大小: {config.population_size}")
    print(f"  迭代代数: {config.n_generations}")
    
    # 初始化种群
    print("\n🚀 开始优化...")
    
    population = []
    for _ in range(config.population_size):
        # 生成金字塔式买入比例（低位高、高位低）
        buy_ratios = []
        for i in range(n_buy_levels):
            # 低位倾向于高比例
            base_ratio = 1.0 - (i / n_buy_levels) * 0.5
            ratio = rng.uniform(0, base_ratio)
            buy_ratios.append(ratio)
        
        # 生成分批卖出比例
        sell_ratios = []
        for i in range(n_sell_levels):
            ratio = rng.uniform(0.3, 1.0)
            sell_ratios.append(ratio)
        
        score, result = evaluate_pyramid_solution(buy_ratios, sell_ratios, config)
        population.append((buy_ratios.copy(), sell_ratios.copy(), score, result))
    
    best_buy = None
    best_sell = None
    best_score = float('-inf')
    best_result = None
    
    start_time = time.time()
    
    for gen in range(config.n_generations):
        # 排序
        population.sort(key=lambda x: x[2], reverse=True)
        
        if population[0][2] > best_score:
            best_buy = population[0][0].copy()
            best_sell = population[0][1].copy()
            best_score = population[0][2]
            best_result = population[0][3]
        
        if gen % 25 == 0 or gen == config.n_generations - 1:
            r = population[0][3]
            print(f"  代数 {gen+1:3d} | "
                  f"得分: {population[0][2]:.3f} | "
                  f"盈利: ${r['profit_at_target']:,.0f} | "
                  f"均价降: ${r['entry_reduction']:,.0f} | "
                  f"强平价: ${r['max_liq_price']:,.0f}")
        
        # 生成下一代
        new_population = []
        
        # 精英保留
        elite_count = max(5, int(config.population_size * config.elite_ratio))
        for i in range(elite_count):
            new_population.append(population[i])
        
        # 交叉和变异
        while len(new_population) < config.population_size:
            idx1 = rng.choice(len(population) // 3)
            idx2 = rng.choice(len(population) // 3)
            
            # 交叉
            child_buy = []
            for i in range(n_buy_levels):
                if rng.random() < 0.5:
                    child_buy.append(population[idx1][0][i])
                else:
                    child_buy.append(population[idx2][0][i])
            
            child_sell = []
            for i in range(n_sell_levels):
                if rng.random() < 0.5:
                    child_sell.append(population[idx1][1][i])
                else:
                    child_sell.append(population[idx2][1][i])
            
            # 变异
            if rng.random() < config.mutation_rate:
                idx = rng.integers(n_buy_levels)
                child_buy[idx] = rng.uniform(0, 1)
            
            if rng.random() < config.mutation_rate:
                idx = rng.integers(n_sell_levels)
                child_sell[idx] = rng.uniform(0, 1)
            
            score, result = evaluate_pyramid_solution(child_buy, child_sell, config)
            new_population.append((child_buy, child_sell, score, result))
        
        population = new_population
    
    elapsed = time.time() - start_time
    print(f"\n✅ 优化完成！用时 {elapsed:.2f} 秒")
    
    return best_buy, best_sell, best_result


def display_pyramid_results(
    buy_ratios: List[float],
    sell_ratios: List[float],
    result: Dict,
    config: PyramidConfig
):
    """显示金字塔策略结果"""
    print("\n" + "="*90)
    print("💎 最优金字塔策略")
    print("="*90)
    
    # 检查是否满足目标
    profit_ok = result['profit_at_target'] >= config.target_profit
    liq_ok = result['max_liq_price'] < config.max_liq_price
    
    print(f"\n📈 策略结果:")
    print(f"  最终持仓: {result['final_qty']:.4f} BTC")
    print(f"  最终均价: ${result['final_entry']:,.2f} (降低 ${result['entry_reduction']:,.2f})")
    print(f"  最高强平价: ${result['max_liq_price']:,.2f} {'✅' if liq_ok else '❌'} (限制 < ${config.max_liq_price:,.0f})")
    print(f"  BTC@${config.target_btc_price:,.0f}盈利: ${result['profit_at_target']:,.2f} {'✅' if profit_ok else '❌'} (目标 > ${config.target_profit:,.0f})")
    
    # 金字塔买入详情
    print(f"\n🔺 金字塔买入计划（总投入: ${result['total_buy']:,.0f}）:")
    print("-"*75)
    print(f"{'价位':<12} {'最大可用':<14} {'实际投入':<14} {'使用率':<10} {'策略':<25}")
    print("-"*75)
    
    buy_ops = [op for op in result['operations'] if op['action'] == 'buy']
    for i, (price, max_ratio) in enumerate(config.buy_levels):
        max_amount = config.available_capital * max_ratio
        actual_ratio = buy_ratios[i]
        actual_amount = max_amount * actual_ratio
        
        if actual_amount >= 1000:
            usage_pct = actual_ratio * 100
            if price <= 83000:
                strategy = "🔥 最低位，重仓补"
            elif price <= 85000:
                strategy = "📈 低位，积极买入"
            else:
                strategy = "🔍 中间位，试探性买"
            print(f"${price:>9,}   ${max_amount:>11,.0f}   ${actual_amount:>11,.0f}   {usage_pct:>6.1f}%   {strategy}")
    print("-"*75)
    
    # 分批止盈详情
    print(f"\n📉 分批止盈计划（总卖出: ${result['total_sell']:,.0f}）:")
    print("-"*75)
    print(f"{'价位':<12} {'卖出比例':<12} {'预计金额':<14} {'策略':<30}")
    print("-"*75)
    
    for i, (price, max_ratio) in enumerate(config.sell_levels):
        actual_ratio = sell_ratios[i] * max_ratio
        # 估算卖出金额
        estimated_sell = result['final_qty'] * actual_ratio * price
        
        if actual_ratio >= 0.01:
            if price >= 93000:
                strategy = "💰 最高位，大额止盈"
            elif price >= 91000:
                strategy = "📊 高位，积极获利"
            else:
                strategy = "🔍 刚过中间，小额测试"
            print(f"${price:>9,}   {actual_ratio*100:>8.1f}%   ${estimated_sell:>11,.0f}   {strategy}")
    print("-"*75)
    
    # 操作执行详情
    if result['operations']:
        print(f"\n📋 操作执行详情（按时间顺序）:")
        print("-"*95)
        print(f"{'序号':<6} {'操作':<8} {'触发价':<12} {'金额/数量':<16} {'执行后均价':<14} {'强平价':<12}")
        print("-"*95)
        
        for i, op in enumerate(result['operations'], 1):
            action_cn = "🟢买入" if op['action'] == 'buy' else "🔴卖出"
            liq_status = "✅" if op['liq_price'] < config.max_liq_price else "⚠️"
            
            if op['action'] == 'buy':
                amount_str = f"${op['value']:,.0f}"
            else:
                amount_str = f"{abs(op['qty_change']):.4f} BTC"
            
            print(f"{i:<6} {action_cn:<6} "
                  f"${op['price']:>10,} "
                  f"{amount_str:>14} "
                  f"${op['entry_after']:>12,.2f} "
                  f"${op['liq_price']:>10,.2f} {liq_status}")
        print("-"*95)
    
    # 策略总结
    print(f"\n🎯 策略总结:")
    print(f"  1. 金字塔买入: 在 {len(buy_ops)} 个低位价位投入 ${result['total_buy']:,.0f}")
    print(f"  2. 分批止盈: 在多个高位价位分批卖出")
    print(f"  3. 均价从 ${config.entry_price:,.0f} 降至 ${result['final_entry']:.2f} (降低 ${result['entry_reduction']:.2f})")
    print(f"  4. 当 BTC 达 ${config.target_btc_price:,.0f} 时，预期盈利 ${result['profit_at_target']:.2f}")
    
    # 风险提示
    print(f"\n⚠️ 风险评估:")
    if liq_ok:
        margin = config.max_liq_price - result['max_liq_price']
        print(f"  ✅ 强平价安全，距离上限还有 ${margin:,.2f} 安全垫")
    else:
        excess = result['max_liq_price'] - config.max_liq_price
        print(f"  ❌ 警告！强平价 ${result['max_liq_price']:,.2f} 超过上限 ${excess:,.2f}")
    
    if profit_ok:
        excess = result['profit_at_target'] - config.target_profit
        print(f"  ✅ 盈利目标达成，超出目标 ${excess:,.2f}")
    else:
        gap = config.target_profit - result['profit_at_target']
        print(f"  ⚠️ 盈利 ${result['profit_at_target']:,.2f} 未达目标，差距 ${gap:,.2f}")


def main():
    """主函数"""
    config = PyramidConfig(
        # 当前持仓状态（用户提供）
        current_qty=25.0,
        entry_price=100_150,
        available_capital=300_000,
        current_liq_price=20_030,
        
        # 震荡区间
        swing_low=82_000,
        swing_high=94_000,
        
        # 硬约束
        max_liq_price=28_500,  # 强平价必须 < $28,500
        leverage=10,
        
        # 目标
        target_btc_price=120_000,
        target_profit=550_000,  # 盈利 > $550,000
        
        # 金字塔买入网格（低位重仓）
        buy_levels=[
            (82000, 0.40),  # 最低位，最多用40%资金 = $120,000
            (83000, 0.25),  # 次低位，25% = $75,000
            (84000, 0.15),  # 低位，15% = $45,000
            (85000, 0.10),  # 中低位，10% = $30,000
            (86000, 0.06),  # 中位，6% = $18,000
            (87000, 0.04),  # 中高位，4% = $12,000
        ],
        
        # 分批止盈网格
        sell_levels=[
            (89000, 0.05),   # 刚过中间，5%
            (90000, 0.08),   # 8%
            (91000, 0.12),   # 12%
            (92000, 0.18),   # 18%
            (93000, 0.25),   # 25%
            (94000, 0.32),   # 最高位，32%
        ],
        
        # 算法参数
        population_size=400,
        n_generations=200,
        mutation_rate=0.35,
        elite_ratio=0.1
    )
    
    # 运行优化
    best_buy, best_sell, best_result = optimize_pyramid_strategy(config)
    
    # 显示结果
    display_pyramid_results(best_buy, best_sell, best_result, config)
    
    print("\n" + "="*90)
    print("✅ 金字塔优化完成！")
    print("="*90)
    
    return best_buy, best_sell, best_result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
