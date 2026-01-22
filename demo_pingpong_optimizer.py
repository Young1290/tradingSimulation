"""
Ping-Pong 波段网格策略优化器

使用遗传算法优化：
1. 每轮的买入价格
2. 每轮的卖出价格
3. 每轮的操作金额

约束：
- 买卖交替（买-卖-买-卖）
- 强平价全程 < $28,500
- 资金利用 30%-50%
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple
import time


@dataclass
class PingPongOptConfig:
    """Ping-Pong优化器配置"""
    
    # 当前持仓状态
    current_qty: float = 25.0
    entry_price: float = 100_150
    available_capital: float = 300_000
    current_liq_price: float = 20_030
    
    # 震荡区间
    swing_low: float = 81_000
    swing_high: float = 95_000
    
    # 硬约束
    max_liq_price: float = 28_500
    leverage: int = 10
    
    # 目标
    target_btc_price: float = 120_000
    target_profit: float = 550_000
    
    # 操作轮数（每轮 = 1买1卖）
    n_rounds: int = 3
    
    # 每轮操作金额范围
    min_buy_amount: float = 50_000
    max_buy_amount: float = 200_000
    
    # 算法参数
    population_size: int = 500
    n_generations: int = 200
    mutation_rate: float = 0.3


def simulate_pingpong_rounds(
    buy_prices: List[float],    # 每轮买入价格
    sell_prices: List[float],   # 每轮卖出价格
    buy_amounts: List[float],   # 每轮买入金额
    config: PingPongOptConfig
) -> Dict:
    """
    模拟多轮 Ping-Pong 操作
    """
    # 初始状态
    qty = config.current_qty
    entry = config.entry_price
    total_equity = (config.entry_price - config.current_liq_price) * config.current_qty
    available_capital = config.available_capital
    
    operations = []
    max_liq_price = config.current_liq_price
    total_realized_pnl = 0
    
    for round_idx in range(config.n_rounds):
        buy_price = buy_prices[round_idx]
        sell_price = sell_prices[round_idx]
        buy_amount = buy_amounts[round_idx]
        
        # ===== 买入操作 =====
        margin_needed = buy_amount / config.leverage
        
        if available_capital < margin_needed:
            buy_amount = available_capital * config.leverage
            margin_needed = available_capital
        
        if buy_amount < 10000:
            continue
            
        qty_bought = buy_amount / buy_price
        old_qty = qty
        old_entry = entry
        qty += qty_bought
        available_capital -= margin_needed
        
        entry = (old_entry * old_qty + buy_price * qty_bought) / qty
        total_equity += margin_needed
        
        liq_price = entry - total_equity / qty
        liq_price = max(0, liq_price)
        max_liq_price = max(max_liq_price, liq_price)
        
        operations.append({
            'round': round_idx + 1,
            'action': 'buy',
            'price': buy_price,
            'value': buy_amount,
            'qty_change': qty_bought,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'liq_ok': liq_price < config.max_liq_price
        })
        
        # ===== 卖出操作（卖出刚买入的数量）=====
        sell_qty = qty_bought
        sell_value = sell_qty * sell_price
        
        realized_pnl = (sell_price - buy_price) * sell_qty
        total_realized_pnl += realized_pnl
        
        qty -= sell_qty
        total_equity += realized_pnl
        
        if qty > 0:
            liq_price = entry - total_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        max_liq_price = max(max_liq_price, liq_price)
        
        operations.append({
            'round': round_idx + 1,
            'action': 'sell',
            'price': sell_price,
            'value': sell_value,
            'qty_change': -sell_qty,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'realized_pnl': realized_pnl,
            'liq_ok': liq_price < config.max_liq_price
        })
    
    # 最终状态
    if qty > 0:
        profit_at_target = (config.target_btc_price - entry) * qty
    else:
        profit_at_target = total_equity - (config.entry_price - config.current_liq_price) * config.current_qty
    
    return {
        'final_qty': qty,
        'final_entry': entry,
        'final_liq_price': liq_price,
        'max_liq_price': max_liq_price,
        'final_equity': total_equity,
        'profit_at_target': profit_at_target,
        'entry_reduction': config.entry_price - entry,
        'total_realized_pnl': total_realized_pnl,
        'operations': operations,
        'all_steps_safe': all(op['liq_ok'] for op in operations)
    }


def evaluate_pingpong_solution(
    buy_prices: List[float],
    sell_prices: List[float],
    buy_amounts: List[float],
    config: PingPongOptConfig
) -> Tuple[float, Dict]:
    """评估 Ping-Pong 方案"""
    result = simulate_pingpong_rounds(buy_prices, sell_prices, buy_amounts, config)
    
    # 1. 利润得分（实现盈亏 + 目标价盈利）
    realized_pnl_score = result['total_realized_pnl'] / 50000  # 每赚5万得1分
    target_profit_score = result['profit_at_target'] / config.target_profit
    profit_score = realized_pnl_score * 0.3 + target_profit_score * 0.7
    profit_score = min(profit_score, 2.0)
    
    # 2. 均价降低得分
    entry_reduction_score = result['entry_reduction'] / 3000
    entry_reduction_score = max(0, entry_reduction_score)
    
    # 3. 强平价安全得分
    max_liq = result['max_liq_price']
    if not result['all_steps_safe']:
        liq_score = -20
    elif max_liq > config.max_liq_price:
        liq_score = -10
    else:
        safety_margin = (config.max_liq_price - max_liq) / config.max_liq_price
        liq_score = 0.5 + 0.5 * safety_margin
    
    # 4. 价差得分（买卖价差越大越好）
    total_spread = 0
    for i in range(len(buy_prices)):
        spread = sell_prices[i] - buy_prices[i]
        total_spread += spread
    spread_score = total_spread / (5000 * len(buy_prices))
    spread_score = min(1.0, max(0, spread_score))
    
    # 5. 操作轮数得分
    n_valid_ops = len([op for op in result['operations'] if op['liq_ok']])
    rounds_score = n_valid_ops / (config.n_rounds * 2)
    
    # 加权总分
    total_score = (
        profit_score * 0.35 +
        entry_reduction_score * 0.20 +
        liq_score * 0.20 +
        spread_score * 0.15 +
        rounds_score * 0.10
    )
    
    # 硬约束惩罚
    if not result['all_steps_safe']:
        total_score *= 0.01
    
    return total_score, result


def optimize_pingpong_strategy(config: PingPongOptConfig) -> Tuple[List, List, List, Dict]:
    """使用遗传算法优化 Ping-Pong 策略"""
    rng = np.random.default_rng()
    
    print("="*90)
    print("🏓 Ping-Pong 波段网格策略优化器")
    print("="*90)
    
    print(f"\n📊 当前持仓状态:")
    print(f"  持仓量: {config.current_qty} BTC")
    print(f"  入场均价: ${config.entry_price:,.0f}")
    print(f"  当前强平价: ${config.current_liq_price:,.0f}")
    print(f"  可用子弹: ${config.available_capital:,.0f}")
    
    print(f"\n🎯 优化目标:")
    print(f"  震荡区间: ${config.swing_low:,.0f} - ${config.swing_high:,.0f}")
    print(f"  操作轮数: {config.n_rounds} 轮（每轮1买1卖）")
    print(f"  强平价上限: < ${config.max_liq_price:,.0f}")
    print(f"  目标盈利: > ${config.target_profit:,.0f}")
    
    print(f"\n⚙️ 算法参数:")
    print(f"  种群大小: {config.population_size}")
    print(f"  迭代代数: {config.n_generations}")
    
    # 买入价格范围 (低位)
    buy_price_low = config.swing_low
    buy_price_high = (config.swing_low + config.swing_high) / 2 - 1000  # $87,000
    
    # 卖出价格范围 (高位)
    sell_price_low = (config.swing_low + config.swing_high) / 2 + 1000  # $89,000
    sell_price_high = config.swing_high
    
    print(f"\n🔍 搜索范围:")
    print(f"  买入价格: ${buy_price_low:,.0f} - ${buy_price_high:,.0f}")
    print(f"  卖出价格: ${sell_price_low:,.0f} - ${sell_price_high:,.0f}")
    print(f"  每轮金额: ${config.min_buy_amount:,.0f} - ${config.max_buy_amount:,.0f}")
    
    # 初始化种群
    print("\n🚀 开始优化...")
    
    population = []
    for _ in range(config.population_size):
        # 生成买入价格（在买入区间内随机）
        buy_prices = []
        for i in range(config.n_rounds):
            price = rng.uniform(buy_price_low, buy_price_high)
            buy_prices.append(price)
        
        # 生成卖出价格（在卖出区间内随机）
        sell_prices = []
        for i in range(config.n_rounds):
            price = rng.uniform(sell_price_low, sell_price_high)
            sell_prices.append(price)
        
        # 生成买入金额（在范围内随机）
        buy_amounts = []
        for i in range(config.n_rounds):
            amount = rng.uniform(config.min_buy_amount, config.max_buy_amount)
            buy_amounts.append(amount)
        
        score, result = evaluate_pingpong_solution(buy_prices, sell_prices, buy_amounts, config)
        population.append((buy_prices.copy(), sell_prices.copy(), buy_amounts.copy(), score, result))
    
    best_buy = None
    best_sell = None
    best_amounts = None
    best_score = float('-inf')
    best_result = None
    
    start_time = time.time()
    
    for gen in range(config.n_generations):
        population.sort(key=lambda x: x[3], reverse=True)
        
        if population[0][3] > best_score:
            best_buy = population[0][0].copy()
            best_sell = population[0][1].copy()
            best_amounts = population[0][2].copy()
            best_score = population[0][3]
            best_result = population[0][4]
        
        if gen % 25 == 0 or gen == config.n_generations - 1:
            r = population[0][4]
            print(f"  代数 {gen+1:3d} | "
                  f"得分: {population[0][3]:.3f} | "
                  f"实现盈利: ${r['total_realized_pnl']:,.0f} | "
                  f"均价降: ${r['entry_reduction']:,.0f} | "
                  f"最大强平: ${r['max_liq_price']:,.0f}")
        
        # 生成下一代
        new_population = []
        
        # 精英保留
        elite_count = max(5, config.population_size // 10)
        for i in range(elite_count):
            new_population.append(population[i])
        
        # 交叉和变异
        while len(new_population) < config.population_size:
            idx1 = rng.choice(len(population) // 3)
            idx2 = rng.choice(len(population) // 3)
            
            # 交叉
            child_buy = []
            child_sell = []
            child_amounts = []
            
            for i in range(config.n_rounds):
                if rng.random() < 0.5:
                    child_buy.append(population[idx1][0][i])
                    child_sell.append(population[idx1][1][i])
                    child_amounts.append(population[idx1][2][i])
                else:
                    child_buy.append(population[idx2][0][i])
                    child_sell.append(population[idx2][1][i])
                    child_amounts.append(population[idx2][2][i])
            
            # 变异
            if rng.random() < config.mutation_rate:
                idx = rng.integers(config.n_rounds)
                child_buy[idx] = rng.uniform(buy_price_low, buy_price_high)
            
            if rng.random() < config.mutation_rate:
                idx = rng.integers(config.n_rounds)
                child_sell[idx] = rng.uniform(sell_price_low, sell_price_high)
            
            if rng.random() < config.mutation_rate:
                idx = rng.integers(config.n_rounds)
                child_amounts[idx] = rng.uniform(config.min_buy_amount, config.max_buy_amount)
            
            score, result = evaluate_pingpong_solution(child_buy, child_sell, child_amounts, config)
            new_population.append((child_buy.copy(), child_sell.copy(), child_amounts.copy(), score, result))
        
        population = new_population
    
    elapsed = time.time() - start_time
    print(f"\n✅ 优化完成！用时 {elapsed:.2f} 秒")
    
    return best_buy, best_sell, best_amounts, best_result


def display_pingpong_results(
    buy_prices: List[float],
    sell_prices: List[float],
    buy_amounts: List[float],
    result: Dict,
    config: PingPongOptConfig
):
    """显示优化结果"""
    print("\n" + "="*90)
    print("💎 最优 Ping-Pong 策略")
    print("="*90)
    
    profit_ok = result['profit_at_target'] >= config.target_profit
    liq_ok = result['all_steps_safe']
    
    print(f"\n📈 策略结果:")
    print(f"  总操作轮数: {config.n_rounds} 轮（{len(result['operations'])} 步操作）")
    print(f"  实现盈利: ${result['total_realized_pnl']:,.2f}")
    print(f"  均价降低: ${result['entry_reduction']:,.2f}")
    print(f"  最终均价: ${result['final_entry']:,.2f}")
    print(f"  最大强平价: ${result['max_liq_price']:,.2f} {'✅' if liq_ok else '❌'}")
    print(f"  BTC@${config.target_btc_price:,.0f}盈利: ${result['profit_at_target']:,.2f} {'✅' if profit_ok else '❌'}")
    
    # 每轮详情
    print(f"\n🏓 优化后的 Ping-Pong 操作序列:")
    print("-"*95)
    print(f"{'轮次':<6} {'操作':<8} {'价格':<12} {'金额':<14} {'价差':<12} {'盈亏':<14} {'强平价':<12}")
    print("-"*95)
    
    for i in range(config.n_rounds):
        buy_op = result['operations'][i * 2]
        sell_op = result['operations'][i * 2 + 1]
        
        spread = sell_prices[i] - buy_prices[i]
        pnl = sell_op.get('realized_pnl', 0)
        
        print(f"第{i+1}轮  🟢买入   ${buy_prices[i]:>10,.0f} ${buy_amounts[i]:>12,.0f}   -             -             ${buy_op['liq_price']:>10,.0f} {'✅' if buy_op['liq_ok'] else '❌'}")
        print(f"      🔴卖出   ${sell_prices[i]:>10,.0f} ${sell_op['value']:>12,.0f}   ${spread:>10,.0f}  ${pnl:>12,.2f}  ${sell_op['liq_price']:>10,.0f} {'✅' if sell_op['liq_ok'] else '❌'}")
        print()
    print("-"*95)
    
    # 策略总结
    total_buy = sum(buy_amounts)
    total_spread = sum(sell_prices[i] - buy_prices[i] for i in range(config.n_rounds))
    avg_spread = total_spread / config.n_rounds
    
    print(f"\n🎯 策略总结:")
    print(f"  1. 总投入资金: ${total_buy:,.0f}")
    print(f"  2. 总实现盈利: ${result['total_realized_pnl']:,.2f}")
    print(f"  3. 平均买卖价差: ${avg_spread:,.0f}")
    print(f"  4. 均价从 ${config.entry_price:,.0f} 降至 ${result['final_entry']:,.2f}")
    print(f"  5. BTC@${config.target_btc_price:,.0f} 预期盈利: ${result['profit_at_target']:,.2f}")
    
    print(f"\n⚠️ 风险评估:")
    if liq_ok:
        safety = config.max_liq_price - result['max_liq_price']
        print(f"  ✅ 全程安全！最大强平价 ${result['max_liq_price']:,.0f}，安全垫 ${safety:,.0f}")
    else:
        print(f"  ❌ 存在超标步骤！")


def main():
    """
    主函数 - 「吃鱼身」6%-8%确定性波动套利策略
    
    核心理念：
    - 不追求买在最低、卖在最高
    - 追求在 6%-8% 确定性波动中来回套利
    
    参数：
    - 参考价: $86,800
    - 目标价差: 6% - 8%
    - 资金分配: $300k 分 3 份, 每份 $100k - $120k
    """
    
    # 参考价格
    reference_price = 86_800
    
    # 目标价差 6%-8%
    # 设计：限制卖出区间更窄，强制6-8%价差
    #
    # 买入范围: $83,500 - $85,500 
    # 卖出范围: $88,500 - $91,000 (确保价差6-8%)
    
    buy_low = 83_500
    buy_high = 85_500
    
    # 卖出范围：确保6-8%价差
    # $83,500 * 1.07 = $89,345
    # $85,500 * 1.07 = $91,485
    sell_low = 88_500   # 低位卖出 (约5-6%价差)
    sell_high = 91_000  # 高位卖出 (约7-8%价差)
    
    config = PingPongOptConfig(
        # 持仓状态
        current_qty=25.0,
        entry_price=100_150,
        available_capital=300_000,
        current_liq_price=20_030,
        
        # 波动区间 (强制6%-8%价差)
        swing_low=buy_low,
        swing_high=sell_high,
        
        # 约束
        max_liq_price=28_000,
        leverage=10,
        
        # 目标
        target_btc_price=120_000,
        target_profit=550_000,
        
        # 操作轮数: 3轮
        n_rounds=3,
        
        # 资金分配: $300k / 3 = 每份 $100k-$120k
        min_buy_amount=100_000,
        max_buy_amount=120_000,
        
        # 算法参数
        population_size=500,
        n_generations=200,
        mutation_rate=0.3
    )
    
    print("\n" + "🐟"*30)
    print("  「吃鱼身」6%-8% 确定性波动套利策略")
    print("  不追求极端，追求确定性波动来回套利")
    print("🐟"*30)
    
    print(f"\n📊 策略参数:")
    print(f"  参考价格: ${reference_price:,.0f}")
    print(f"  买入区间: ${buy_low:,.0f} - ${buy_high:,.0f}")
    print(f"  卖出区间: ${sell_low:,.0f} - ${sell_high:,.0f}")
    print(f"  强制价差: 6% - 8% (${buy_low*0.06:,.0f} - ${buy_high*0.08:,.0f})")
    print(f"  资金分配: ${config.available_capital:,.0f} ÷ 3轮 = ${config.min_buy_amount:,.0f} - ${config.max_buy_amount:,.0f}/轮")
    
    # 运行优化
    best_buy, best_sell, best_amounts, best_result = optimize_pingpong_strategy(config)
    
    # 显示结果
    display_pingpong_results(best_buy, best_sell, best_amounts, best_result, config)
    
    # 计算实际价差百分比
    print("\n" + "="*90)
    print("📊 价差分析")
    print("="*90)
    print(f"\n{'轮次':<8} {'买入价':<14} {'卖出价':<14} {'价差':<12} {'价差%':<10}")
    print("-"*60)
    for i in range(len(best_buy)):
        spread = best_sell[i] - best_buy[i]
        spread_pct = (spread / best_buy[i]) * 100
        print(f"第{i+1}轮    ${best_buy[i]:>10,.0f}    ${best_sell[i]:>10,.0f}    ${spread:>8,.0f}    {spread_pct:>6.1f}%")
    print("-"*60)
    
    avg_spread_pct = sum((best_sell[i] - best_buy[i]) / best_buy[i] * 100 for i in range(len(best_buy))) / len(best_buy)
    print(f"\n  平均价差: {avg_spread_pct:.1f}%  {'✅ 在6%-8%目标范围内' if 6 <= avg_spread_pct <= 8 else '⚠️ 偏离目标范围'}")
    
    print("\n" + "="*90)
    print("✅ 「吃鱼身」策略优化完成！")
    print("="*90)
    
    return best_buy, best_sell, best_amounts, best_result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
