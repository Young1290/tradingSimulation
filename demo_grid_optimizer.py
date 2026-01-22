"""
网格解套优化器 - 固定价格网格，优化仓位分配

核心思路：
1. 预设价格网格（多个触发价位）
2. 只优化每个价位的仓位大小
3. 模拟真实震荡行情中的多点操作
"""

import sys
sys.path.insert(0, '/Users/user/Fund Calculation')

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import time


@dataclass
class GridConfig:
    """网格策略配置"""
    # 持仓状态
    initial_equity: float = 2_000_000
    entry_price: float = 100_150
    position_value: float = 2_500_000
    current_liq_price: float = 20_030
    
    # 价格网格（预设的触发价位）
    buy_grid: List[float] = field(default_factory=lambda: [
        82000, 83000, 84000, 85000, 86000, 87000
    ])
    sell_grid: List[float] = field(default_factory=lambda: [
        89000, 90000, 91000, 92000, 93000, 94000
    ])
    
    # 约束
    max_liq_price: float = 30_000
    leverage: int = 10
    
    # 目标
    target_btc_price: float = 120_000
    target_profit: float = 500_000
    
    # 每个网格的最大仓位
    max_position_per_grid: float = 200_000  # 每个价位最多投入20万
    min_position_per_grid: float = 0        # 可以选择不在某价位操作
    
    # 遗传算法参数
    population_size: int = 300
    n_generations: int = 150


def simulate_grid_strategy(
    buy_positions: List[float],  # 每个买入价位的仓位
    sell_positions: List[float],  # 每个卖出价位的仓位
    config: GridConfig
) -> Dict:
    """
    模拟网格策略执行
    
    Args:
        buy_positions: 长度与buy_grid相同，表示每个价位的买入金额
        sell_positions: 长度与sell_grid相同，表示每个价位的卖出金额
    """
    equity = config.initial_equity
    qty = config.position_value / config.entry_price
    entry = config.entry_price
    
    initial_margin = config.position_value / config.leverage
    available_equity = equity - initial_margin
    
    operations = []
    max_liq_price = config.current_liq_price
    
    # 将买卖操作合并并按价格排序
    all_ops = []
    for i, price in enumerate(config.buy_grid):
        if buy_positions[i] > 0:
            all_ops.append({'price': price, 'action': 'buy', 'value': buy_positions[i]})
    for i, price in enumerate(config.sell_grid):
        if sell_positions[i] > 0:
            all_ops.append({'price': price, 'action': 'sell', 'value': sell_positions[i]})
    
    # 按价格排序（模拟价格从低到高再回落的震荡）
    all_ops.sort(key=lambda x: x['price'])
    
    for op in all_ops:
        op_price = op['price']
        op_action = op['action']
        op_value = op['value']
        
        if op_action == 'buy' and available_equity > 0:
            actual_value = min(op_value, available_equity * config.leverage)
            margin_used = actual_value / config.leverage
            qty_bought = actual_value / op_price
            
            old_qty = qty
            old_entry = entry
            qty += qty_bought
            available_equity -= margin_used
            
            if qty > 0:
                entry = (old_entry * old_qty + op_price * qty_bought) / qty
        
        elif op_action == 'sell' and qty > 0:
            sell_value = min(op_value, qty * op_price)
            sell_qty = sell_value / op_price
            
            realized_pnl = (op_price - entry) * sell_qty
            margin_released = (sell_qty * entry) / config.leverage
            
            available_equity += realized_pnl + margin_released
            qty -= sell_qty
        
        # 计算强平价
        if qty > 0:
            total_margin = qty * entry / config.leverage
            current_equity = available_equity + total_margin
            liq_price = entry - current_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        max_liq_price = max(max_liq_price, liq_price)
        
        operations.append({
            'price': op_price,
            'action': op_action,
            'value': op_value,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'available_equity': available_equity
        })
    
    # 最终状态
    total_equity = available_equity + (qty * entry / config.leverage) if qty > 0 else available_equity
    
    if qty > 0:
        profit_at_target = (config.target_btc_price - entry) * qty
    else:
        profit_at_target = total_equity - config.initial_equity
    
    return {
        'final_qty': qty,
        'final_entry': entry,
        'final_equity': total_equity,
        'max_liq_price': max_liq_price,
        'profit_at_target': profit_at_target,
        'entry_reduction': config.entry_price - entry,
        'operations': operations,
        'num_operations': len(operations)
    }


def evaluate_grid_solution(
    buy_positions: List[float],
    sell_positions: List[float],
    config: GridConfig
) -> Tuple[float, Dict]:
    """评估网格策略"""
    result = simulate_grid_strategy(buy_positions, sell_positions, config)
    
    # 1. 盈利得分
    profit_score = result['profit_at_target'] / config.target_profit
    profit_score = min(profit_score, 2.0)
    
    # 2. 均价降低得分
    entry_reduction_score = result['entry_reduction'] / 5000
    entry_reduction_score = max(0, entry_reduction_score)
    
    # 3. 强平价安全得分
    liq_price = result['max_liq_price']
    if liq_price > config.max_liq_price + 5000:
        liq_score = -10
    elif liq_price > config.max_liq_price:
        liq_score = -2 * (liq_price - config.max_liq_price) / 5000
    else:
        safety_margin = (config.max_liq_price - liq_price) / config.max_liq_price
        liq_score = 0.3 + 0.2 * safety_margin
    
    # 4. 网格覆盖得分（鼓励在多个价位操作）
    active_buys = sum(1 for p in buy_positions if p > 0)
    active_sells = sum(1 for p in sell_positions if p > 0)
    coverage_score = (active_buys + active_sells) / (len(config.buy_grid) + len(config.sell_grid))
    
    # 5. 操作平衡得分
    if active_buys > 0 and active_sells > 0:
        balance_score = 0.3 + 0.2 * min(active_buys, active_sells) / max(active_buys, active_sells)
    else:
        balance_score = 0.1
    
    total_score = (
        profit_score * 0.30 +
        entry_reduction_score * 0.25 +
        liq_score * 0.15 +
        coverage_score * 0.20 +  # 增加覆盖权重
        balance_score * 0.10
    )
    
    if liq_price > config.max_liq_price + 5000:
        total_score *= 0.01
    elif liq_price > config.max_liq_price:
        total_score *= 0.3
    
    return total_score, result


def optimize_grid_strategy(config: GridConfig) -> Tuple[List[float], List[float], Dict]:
    """使用遗传算法优化网格仓位分配"""
    rng = np.random.default_rng()
    
    n_buy_grids = len(config.buy_grid)
    n_sell_grids = len(config.sell_grid)
    
    print("="*80)
    print("🔲 网格解套优化器")
    print("="*80)
    
    print(f"\n📊 当前持仓状态:")
    print(f"  本金: ${config.initial_equity:,.0f}")
    print(f"  持仓价值: ${config.position_value:,.0f}")
    print(f"  入场均价: ${config.entry_price:,.0f}")
    print(f"  当前强平价: ${config.current_liq_price:,.0f}")
    
    print(f"\n🔲 价格网格:")
    print(f"  买入价位: {[f'${p:,.0f}' for p in config.buy_grid]}")
    print(f"  卖出价位: {[f'${p:,.0f}' for p in config.sell_grid]}")
    
    print(f"\n🎯 优化目标:")
    print(f"  强平价限制: < ${config.max_liq_price:,.0f}")
    print(f"  目标价格: ${config.target_btc_price:,.0f}")
    print(f"  目标盈利: > ${config.target_profit:,.0f}")
    
    # 初始化种群
    print(f"\n🚀 开始优化（种群={config.population_size}, 代数={config.n_generations}）...")
    
    population = []
    for _ in range(config.population_size):
        # 随机生成每个价位的仓位
        buy_pos = rng.uniform(0, config.max_position_per_grid, n_buy_grids)
        sell_pos = rng.uniform(0, config.max_position_per_grid * 0.5, n_sell_grids)
        
        # 随机置零一些价位（模拟不在所有价位操作）
        for i in range(n_buy_grids):
            if rng.random() < 0.3:
                buy_pos[i] = 0
        for i in range(n_sell_grids):
            if rng.random() < 0.4:
                sell_pos[i] = 0
        
        score, result = evaluate_grid_solution(buy_pos, sell_pos, config)
        population.append((buy_pos.copy(), sell_pos.copy(), score, result))
    
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
        
        if gen % 20 == 0 or gen == config.n_generations - 1:
            r = population[0][3]
            n_active = sum(1 for p in population[0][0] if p > 0) + sum(1 for p in population[0][1] if p > 0)
            print(f"  代数 {gen+1:3d} | "
                  f"得分: {population[0][2]:.3f} | "
                  f"盈利: ${r['profit_at_target']:,.0f} | "
                  f"均价降: ${r['entry_reduction']:,.0f} | "
                  f"活跃网格: {n_active}")
        
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
            child_buy = np.where(
                rng.random(n_buy_grids) < 0.5,
                population[idx1][0],
                population[idx2][0]
            )
            child_sell = np.where(
                rng.random(n_sell_grids) < 0.5,
                population[idx1][1],
                population[idx2][1]
            )
            
            # 变异
            if rng.random() < 0.4:
                mutation_idx = rng.integers(n_buy_grids)
                child_buy[mutation_idx] = rng.uniform(0, config.max_position_per_grid)
                if rng.random() < 0.3:
                    child_buy[mutation_idx] = 0
            
            if rng.random() < 0.4:
                mutation_idx = rng.integers(n_sell_grids)
                child_sell[mutation_idx] = rng.uniform(0, config.max_position_per_grid * 0.5)
                if rng.random() < 0.3:
                    child_sell[mutation_idx] = 0
            
            score, result = evaluate_grid_solution(child_buy, child_sell, config)
            new_population.append((child_buy.copy(), child_sell.copy(), score, result))
        
        population = new_population
    
    elapsed = time.time() - start_time
    print(f"\n✅ 优化完成！用时 {elapsed:.2f} 秒")
    
    return best_buy, best_sell, best_result


def display_grid_results(
    buy_positions: List[float],
    sell_positions: List[float],
    result: Dict,
    config: GridConfig
):
    """显示网格策略结果"""
    print("\n" + "="*90)
    print("💎 最优网格策略")
    print("="*90)
    
    print(f"\n📈 优化结果:")
    print(f"  活跃买入网格: {sum(1 for p in buy_positions if p > 0)}/{len(config.buy_grid)}")
    print(f"  活跃卖出网格: {sum(1 for p in sell_positions if p > 0)}/{len(config.sell_grid)}")
    print(f"  最终均价: ${result['final_entry']:,.2f} (降低 ${result['entry_reduction']:,.2f})")
    print(f"  最高强平价: ${result['max_liq_price']:.2f} (限制 < ${config.max_liq_price:,.0f}) {'✅' if result['max_liq_price'] < config.max_liq_price else '❌'}")
    print(f"  BTC@${config.target_btc_price:,.0f}盈利: ${result['profit_at_target']:,.2f} {'✅' if result['profit_at_target'] > config.target_profit else '❌'}")
    
    # 网格仓位分布
    print(f"\n📊 买入网格仓位分配:")
    print("-"*70)
    print(f"{'价位':<12} {'仓位(USDT)':<15} {'占比':<10} {'策略':<30}")
    print("-"*70)
    
    total_buy = sum(buy_positions)
    for i, price in enumerate(config.buy_grid):
        pos = buy_positions[i]
        if pos > 0:
            pct = pos / total_buy * 100 if total_buy > 0 else 0
            if price <= 83000:
                strategy = "🔥 最低位，重仓补"
            elif price <= 85000:
                strategy = "📈 低位，积极买入"
            else:
                strategy = "🔍 中间位，小额试探"
            print(f"${price:>9,}   ${pos:>12,.0f}   {pct:>6.1f}%   {strategy}")
    print("-"*70)
    print(f"{'买入总计':<12} ${total_buy:>12,.0f}")
    
    print(f"\n📊 卖出网格仓位分配:")
    print("-"*70)
    print(f"{'价位':<12} {'仓位(USDT)':<15} {'占比':<10} {'策略':<30}")
    print("-"*70)
    
    total_sell = sum(sell_positions)
    for i, price in enumerate(config.sell_grid):
        pos = sell_positions[i]
        if pos > 0:
            pct = pos / total_sell * 100 if total_sell > 0 else 0
            if price >= 93000:
                strategy = "💰 最高位，大额卖出"
            elif price >= 91000:
                strategy = "📊 高位，积极获利"
            else:
                strategy = "🔍 刚过中间，小额测试"
            print(f"${price:>9,}   ${pos:>12,.0f}   {pct:>6.1f}%   {strategy}")
    print("-"*70)
    print(f"{'卖出总计':<12} ${total_sell:>12,.0f}")
    
    # 操作执行详情
    if result['operations']:
        print(f"\n📋 操作执行详情（按价格排序）:")
        print("-"*90)
        print(f"{'序号':<6} {'操作':<8} {'触发价':<12} {'金额':<14} {'执行后均价':<14} {'强平价':<12}")
        print("-"*90)
        
        for i, op in enumerate(result['operations'], 1):
            action_cn = "🟢买入" if op['action'] == 'buy' else "🔴卖出"
            liq_status = "✅" if op['liq_price'] < config.max_liq_price else "⚠️"
            print(f"{i:<6} {action_cn:<6} "
                  f"${op['price']:>10,} "
                  f"${op['value']:>12,.0f} "
                  f"${op['entry_after']:>12,.2f} "
                  f"${op['liq_price']:>10,.2f} {liq_status}")
        print("-"*90)
    
    print(f"\n🎯 策略总结:")
    print(f"  1. 在 {sum(1 for p in buy_positions if p > 0)} 个买入价位 + {sum(1 for p in sell_positions if p > 0)} 个卖出价位操作")
    print(f"  2. 总买入 ${total_buy:,.0f}，总卖出 ${total_sell:,.0f}")
    print(f"  3. 均价从 ${config.entry_price:,.0f} 降至 ${result['final_entry']:.2f} (降低 ${result['entry_reduction']:.2f})")
    print(f"  4. 当 BTC 达 ${config.target_btc_price:,.0f} 时，预期盈利 ${result['profit_at_target']:.2f}")


def main():
    """主函数"""
    config = GridConfig(
        # 持仓状态
        initial_equity=2_000_000,
        entry_price=100_150,
        position_value=2_500_000,
        current_liq_price=20_030,
        
        # 买入网格（$82k-$87.5k，每500间隔）
        buy_grid=[82000, 82500, 83000, 83500, 84000, 84500, 85000, 85500, 86000, 86500, 87000, 87500],
        
        # 卖出网格（$88.5k-$94k，每500间隔）  
        sell_grid=[88500, 89000, 89500, 90000, 90500, 91000, 91500, 92000, 92500, 93000, 93500, 94000],
        
        # 约束
        max_liq_price=30_000,
        leverage=10,
        
        # 目标
        target_btc_price=120_000,
        target_profit=500_000,
        
        # 每格最大仓位
        max_position_per_grid=150_000,  # 每个价位最多15万
        
        # 算法参数
        population_size=300,
        n_generations=150
    )
    
    # 运行优化
    best_buy, best_sell, best_result = optimize_grid_strategy(config)
    
    # 显示结果
    display_grid_results(best_buy, best_sell, best_result, config)
    
    print("\n" + "="*90)
    print("✅ 网格优化完成！")
    print("="*90)
    
    return best_buy, best_sell, best_result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
