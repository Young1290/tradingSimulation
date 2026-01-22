"""
解套优化器 - 针对你的实际持仓情况

策略目标：
1. 在震荡区间 $82,000 - $94,000 内进行微操
2. 逐步降低持仓均价
3. 保持强平价 < $25,000（严格约束，最高<$30,000）
4. 在 BTC $120,000 时盈利 > $500,000
"""

import sys
sys.path.insert(0, '/Users/user/Fund Calculation')

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple
import time


@dataclass
class BreakevenConfig:
    """解套优化配置"""
    # 当前持仓状态
    initial_equity: float = 2_000_000      # 本金
    entry_price: float = 100_150           # 入场均价
    position_value: float = 2_500_000      # 持仓价值
    current_liq_price: float = 20_030      # 当前强平价
    
    # 震荡区间（操作价格范围）
    swing_low: float = 82_000              # 震荡区间低点
    swing_high: float = 94_000             # 震荡区间高点
    
    # 约束条件
    max_liq_price: float = 25_000          # 强平价严格上限
    absolute_max_liq_price: float = 30_000 # 强平价绝对上限
    
    # 目标条件
    target_btc_price: float = 120_000      # 目标BTC价格
    target_profit: float = 500_000         # 目标盈利
    
    # 杠杆固定
    leverage: int = 10
    
    # 遗传算法参数
    population_size: int = 100
    n_generations: int = 50
    mutation_rate: float = 0.2
    crossover_rate: float = 0.8
    
    # 操作限制
    max_operations: int = 20               # 最多操作次数
    min_operation_value: float = 50_000    # 最小单次操作金额
    max_operation_value: float = 500_000   # 最大单次操作金额


def calculate_position_metrics(
    equity: float,
    qty: float,
    entry_price: float,
    current_price: float,
    leverage: int = 10
) -> Dict:
    """计算持仓指标"""
    
    # 计算强平价：Liq = Entry - Equity / Qty
    if qty > 0:
        liq_price = entry_price - equity / qty
        liq_price = max(0, liq_price)  # 负数表示极安全
    else:
        liq_price = 0
    
    # 计算浮盈
    if qty > 0:
        unrealized_pnl = (current_price - entry_price) * qty
        position_value = qty * current_price
    else:
        unrealized_pnl = 0
        position_value = 0
    
    # 计算在目标价格的盈利
    profit_at_target = lambda target_price: (target_price - entry_price) * qty if qty > 0 else 0
    
    return {
        'liq_price': liq_price,
        'unrealized_pnl': unrealized_pnl,
        'position_value': position_value,
        'entry_price': entry_price,
        'qty': qty,
        'equity': equity,
        'profit_at_target': profit_at_target
    }


def simulate_operations(
    operations: List[Dict],
    config: BreakevenConfig
) -> Dict:
    """
    模拟执行操作序列
    
    操作格式：
    {
        'price': 触发价格,
        'action': 'buy' 或 'sell',
        'value': USDT金额
    }
    """
    # 初始状态
    equity = config.initial_equity
    qty = config.position_value / config.entry_price  # 约25 BTC
    entry = config.entry_price
    
    # 扣除初始持仓保证金
    initial_margin = config.position_value / config.leverage
    available_equity = equity - initial_margin  # 可用资金
    
    operation_results = []
    max_liq_price = config.current_liq_price  # 记录过程中的最高强平价
    
    # 按价格排序操作
    sorted_ops = sorted(operations, key=lambda x: x['price'])
    
    for op in sorted_ops:
        op_price = op['price']
        op_action = op['action']
        op_value = op['value']
        
        # 检查操作价格是否在震荡区间内
        if not (config.swing_low <= op_price <= config.swing_high):
            continue  # 跳过区间外的操作
        
        if op_action == 'buy' and available_equity > 0:
            # 买入：使用可用资金
            actual_value = min(op_value, available_equity * config.leverage)
            margin_used = actual_value / config.leverage
            qty_bought = actual_value / op_price
            
            # 更新持仓
            old_qty = qty
            old_entry = entry
            qty += qty_bought
            available_equity -= margin_used
            
            # 更新均价（加权平均）
            if qty > 0:
                entry = (old_entry * old_qty + op_price * qty_bought) / qty
        
        elif op_action == 'sell' and qty > 0:
            # 卖出
            sell_value = min(op_value, qty * op_price)
            sell_qty = sell_value / op_price
            
            # 计算实现盈亏
            realized_pnl = (op_price - entry) * sell_qty
            margin_released = (sell_qty * entry) / config.leverage
            
            available_equity += realized_pnl + margin_released
            qty -= sell_qty
        
        # 计算当前强平价
        if qty > 0:
            current_equity = available_equity + (config.position_value / config.leverage)
            liq_price = entry - current_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        max_liq_price = max(max_liq_price, liq_price)
        
        operation_results.append({
            'price': op_price,
            'action': op_action,
            'value': op_value,
            'qty_after': qty,
            'entry_after': entry,
            'liq_price': liq_price,
            'available_equity': available_equity
        })
    
    # 计算最终状态
    total_equity = available_equity + (qty * entry / config.leverage) if qty > 0 else available_equity
    
    # 计算在目标价格时的盈利
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
        'entry_reduction': config.entry_price - entry,  # 均价降低了多少
        'operations': operation_results,
        'num_operations': len(operation_results)
    }


def create_random_operations(config: BreakevenConfig, n_ops: int = None, rng=None) -> List[Dict]:
    """
    创建随机操作序列 - 网格策略
    
    使用预定义的价格网格，模拟真实震荡行情中的多个价位操作：
    - 买入价格网格: $82,000, $83,000, $84,000, $85,000, $86,000, $87,000
    - 卖出价格网格: $89,000, $90,000, $91,000, $92,000, $93,000, $94,000
    
    每个价位可以有不同的仓位大小
    """
    if rng is None:
        rng = np.random.default_rng()
    
    if n_ops is None:
        n_ops = rng.integers(8, config.max_operations + 1)
    
    # 定义买入和卖出的价格网格
    buy_prices = [82000, 82500, 83000, 83500, 84000, 84500, 85000, 85500, 86000, 86500, 87000, 87500]
    sell_prices = [88500, 89000, 89500, 90000, 90500, 91000, 91500, 92000, 92500, 93000, 93500, 94000]
    
    operations = []
    
    # 决定买卖分配
    n_buys = max(3, int(n_ops * 0.55) + rng.integers(-1, 2))
    n_sells = max(2, n_ops - n_buys)
    
    # 随机选择买入价位（不重复）
    selected_buy_prices = rng.choice(buy_prices, size=min(n_buys, len(buy_prices)), replace=False)
    
    for price in selected_buy_prices:
        # 随机添加一些价格波动 (-200 到 +200)
        price_with_noise = price + rng.uniform(-200, 200)
        
        # 根据价格决定仓位大小（越低越大胆）
        price_ratio = (price - config.swing_low) / (88000 - config.swing_low)
        if price_ratio < 0.3:
            # 最低价位，敢于大仓
            value = rng.uniform(config.max_operation_value * 0.5, config.max_operation_value)
        elif price_ratio < 0.6:
            # 中间价位
            value = rng.uniform(config.min_operation_value * 2, config.max_operation_value * 0.6)
        else:
            # 接近中间，小仓试探
            value = rng.uniform(config.min_operation_value, config.min_operation_value * 3)
        
        operations.append({
            'price': round(price_with_noise, 2),
            'action': 'buy',
            'value': round(value, 2)
        })
    
    # 随机选择卖出价位（不重复）
    selected_sell_prices = rng.choice(sell_prices, size=min(n_sells, len(sell_prices)), replace=False)
    
    for price in selected_sell_prices:
        # 随机添加一些价格波动
        price_with_noise = price + rng.uniform(-200, 200)
        
        # 根据价格决定仓位大小（越高卖越多）
        price_ratio = (price - 88000) / (config.swing_high - 88000)
        if price_ratio > 0.7:
            # 最高价位，敢于多卖
            value = rng.uniform(config.max_operation_value * 0.4, config.max_operation_value * 0.7)
        elif price_ratio > 0.4:
            # 中间价位
            value = rng.uniform(config.min_operation_value * 1.5, config.max_operation_value * 0.4)
        else:
            # 刚过中间，小额卖出
            value = rng.uniform(config.min_operation_value, config.min_operation_value * 2)
        
        operations.append({
            'price': round(price_with_noise, 2),
            'action': 'sell',
            'value': round(value, 2)
        })
    
    return operations


def evaluate_solution(operations: List[Dict], config: BreakevenConfig) -> Tuple[float, Dict]:
    """
    评估解的质量
    
    目标（多目标优化，转为单目标加权）：
    1. 最大化在目标价格时的盈利 (权重最高)
    2. 最大化均价降低幅度 (权重高)
    3. 保持强平价安全 (硬约束)
    4. 鼓励适当数量的操作
    
    返回：(适应度分数, 结果详情)
    """
    result = simulate_operations(operations, config)
    
    # 计算各目标的得分
    
    # 1. 目标价格盈利得分（目标：> $500,000）
    profit_score = result['profit_at_target'] / config.target_profit
    profit_score = min(profit_score, 2.0)  # 上限200%
    
    # 2. 均价降低得分（降低越多越好，大幅提高权重）
    entry_reduction_score = result['entry_reduction'] / 5000  # 每降5000得1分（更敏感）
    entry_reduction_score = max(0, entry_reduction_score)
    
    # 3. 强平价安全得分（必须 < 25000，但不要过于保守）
    liq_price = result['max_liq_price']
    if liq_price > config.absolute_max_liq_price:
        # 超过绝对上限 (>30000)，严重惩罚
        liq_score = -10
    elif liq_price > config.max_liq_price:
        # 超过严格上限 (25000-30000)，中等惩罚
        liq_score = -2 * (liq_price - config.max_liq_price) / 5000
    else:
        # 在安全范围内，给予基础分（不再过度奖励过低的强平价）
        # 只要安全就好，不需要过于保守
        safety_margin = (config.max_liq_price - liq_price) / config.max_liq_price
        liq_score = 0.3 + 0.2 * safety_margin  # 基础0.3分，最高0.5分
    
    # 4. 操作数量得分（鼓励4-8次操作）
    n_ops = result['num_operations']
    if n_ops == 0:
        ops_score = -1
    elif n_ops < 3:
        ops_score = 0.1  # 太少
    elif n_ops <= 5:
        ops_score = 0.3  # 适中
    elif n_ops <= 8:
        ops_score = 0.5  # 最佳范围
    elif n_ops <= 12:
        ops_score = 0.4  # 稍多
    else:
        ops_score = 0.2  # 太多
    
    # 5. 买卖平衡得分（鼓励有买有卖）
    n_buys = sum(1 for op in result['operations'] if op['action'] == 'buy')
    n_sells = sum(1 for op in result['operations'] if op['action'] == 'sell')
    if n_buys > 0 and n_sells > 0:
        balance_score = 0.3 + 0.2 * min(n_buys, n_sells) / max(n_buys, n_sells)
    else:
        balance_score = 0.1  # 只有单向操作
    
    # 加权总分（调整权重）
    total_score = (
        profit_score * 0.35 +        # 盈利最重要
        entry_reduction_score * 0.25 +  # 降低均价很重要
        liq_score * 0.15 +           # 安全性（只要在范围内即可）
        ops_score * 0.15 +           # 操作数量
        balance_score * 0.10         # 买卖平衡
    )
    
    # 如果强平价超过绝对上限，大幅降低分数
    if liq_price > config.absolute_max_liq_price:
        total_score *= 0.01  # 严重惩罚
    elif liq_price > config.max_liq_price:
        total_score *= 0.3  # 中等惩罚
    
    return total_score, result


def genetic_algorithm_optimize(config: BreakevenConfig) -> Tuple[List[Dict], Dict]:
    """
    使用遗传算法寻找最优操作序列
    """
    rng = np.random.default_rng()
    
    print("="*70)
    print("🧬 解套优化器 - 遗传算法")
    print("="*70)
    
    print(f"\n📊 当前持仓状态:")
    print(f"  本金: ${config.initial_equity:,.0f}")
    print(f"  持仓价值: ${config.position_value:,.0f}")
    print(f"  入场均价: ${config.entry_price:,.0f}")
    print(f"  当前强平价: ${config.current_liq_price:,.0f}")
    
    print(f"\n🎯 优化目标:")
    print(f"  震荡区间: ${config.swing_low:,.0f} - ${config.swing_high:,.0f}")
    print(f"  强平价限制: < ${config.max_liq_price:,.0f}")
    print(f"  目标价格: ${config.target_btc_price:,.0f}")
    print(f"  目标盈利: > ${config.target_profit:,.0f}")
    
    print(f"\n⚙️ 算法参数:")
    print(f"  种群大小: {config.population_size}")
    print(f"  迭代代数: {config.n_generations}")
    
    # 初始化种群
    print("\n🚀 开始优化...")
    population = []
    for _ in range(config.population_size):
        ops = create_random_operations(config, rng=rng)
        score, result = evaluate_solution(ops, config)
        population.append((ops, score, result))
    
    best_solution = None
    best_score = float('-inf')
    best_result = None
    
    start_time = time.time()
    
    for gen in range(config.n_generations):
        # 排序（按分数降序）
        population.sort(key=lambda x: x[1], reverse=True)
        
        # 更新最优解
        if population[0][1] > best_score:
            best_solution = population[0][0]
            best_score = population[0][1]
            best_result = population[0][2]
        
        # 显示进度
        if gen % 10 == 0 or gen == config.n_generations - 1:
            top_result = population[0][2]
            print(f"  代数 {gen+1:3d} | "
                  f"最优分: {population[0][1]:.3f} | "
                  f"盈利@120k: ${top_result['profit_at_target']:,.0f} | "
                  f"均价降低: ${top_result['entry_reduction']:,.0f} | "
                  f"强平价: ${top_result['max_liq_price']:,.0f}")
        
        # 生成下一代
        new_population = []
        
        # 精英保留（前10%）
        elite_count = max(2, config.population_size // 10)
        for i in range(elite_count):
            new_population.append(population[i])
        
        # 交叉和变异生成其余个体
        while len(new_population) < config.population_size:
            # 锦标赛选择
            idx1 = rng.choice(len(population) // 2)
            idx2 = rng.choice(len(population) // 2)
            parent1 = population[idx1][0]
            parent2 = population[idx2][0]
            
            # 交叉
            if rng.random() < config.crossover_rate:
                # 单点交叉
                cut = rng.integers(1, min(len(parent1), len(parent2)))
                child = parent1[:cut] + parent2[cut:]
            else:
                child = parent1.copy()
            
            # 变异
            if rng.random() < config.mutation_rate:
                child = mutate_operations(child, config, rng)
            
            # 评估新个体
            score, result = evaluate_solution(child, config)
            new_population.append((child, score, result))
        
        population = new_population
    
    elapsed_time = time.time() - start_time
    
    print(f"\n✅ 优化完成！用时 {elapsed_time:.2f} 秒")
    
    return best_solution, best_result


def mutate_operations(operations: List[Dict], config: BreakevenConfig, rng) -> List[Dict]:
    """变异操作 - 保持低买高卖规则"""
    mutated = [op.copy() for op in operations]
    
    # 震荡区间中间价
    mid_price = (config.swing_low + config.swing_high) / 2
    
    mutation_type = rng.choice(['price', 'action', 'value', 'add', 'remove'])
    
    if mutation_type == 'price' and mutated:
        # 价格微调（保持买卖区域合理）
        idx = rng.integers(len(mutated))
        op = mutated[idx]
        shift = rng.uniform(-2000, 2000)
        new_price = op['price'] + shift
        
        # 保持在正确的价格区域
        if op['action'] == 'buy':
            # 买入只能在低位
            new_price = np.clip(new_price, config.swing_low, mid_price)
        else:
            # 卖出只能在高位
            new_price = np.clip(new_price, mid_price, config.swing_high)
        
        mutated[idx]['price'] = new_price
    
    elif mutation_type == 'action' and mutated:
        # 翻转买卖时，同时调整价格到对应区域
        idx = rng.integers(len(mutated))
        op = mutated[idx]
        
        if op['action'] == 'buy':
            # 买入变卖出：价格移到高位
            mutated[idx]['action'] = 'sell'
            mutated[idx]['price'] = rng.uniform(mid_price, config.swing_high)
        else:
            # 卖出变买入：价格移到低位
            mutated[idx]['action'] = 'buy'
            mutated[idx]['price'] = rng.uniform(config.swing_low, mid_price)
    
    elif mutation_type == 'value' and mutated:
        # 调整金额
        idx = rng.integers(len(mutated))
        shift = rng.uniform(-100000, 100000)
        mutated[idx]['value'] = np.clip(
            mutated[idx]['value'] + shift,
            config.min_operation_value,
            config.max_operation_value
        )
    
    elif mutation_type == 'add' and len(mutated) < config.max_operations:
        # 添加新操作（遵循低买高卖）
        new_op = create_random_operations(config, n_ops=1, rng=rng)[0]
        mutated.append(new_op)
    
    elif mutation_type == 'remove' and len(mutated) > 2:
        # 删除操作
        idx = rng.integers(len(mutated))
        mutated.pop(idx)
    
    return mutated


def display_results(operations: List[Dict], result: Dict, config: BreakevenConfig):
    """显示优化结果"""
    print("\n" + "="*90)
    print("💎 最优操作序列")
    print("="*90)
    
    print(f"\n📈 优化结果概览:")
    print(f"  操作数量: {result['num_operations']}")
    print(f"  最终均价: ${result['final_entry']:,.2f} (降低 ${result['entry_reduction']:,.2f})")
    print(f"  最高强平价: ${result['max_liq_price']:,.2f} (限制 < ${config.max_liq_price:,.0f}) {'✅' if result['max_liq_price'] < config.max_liq_price else '❌'}")
    print(f"  BTC@${config.target_btc_price:,.0f}时盈利: ${result['profit_at_target']:,.2f} {'✅' if result['profit_at_target'] > config.target_profit else '❌'}")
    
    # 按价格排序操作
    sorted_ops = sorted(operations, key=lambda x: x['price'])
    
    print(f"\n📝 操作序列（按价格排序）:")
    print("-"*90)
    print(f"{'序号':<6} {'操作':<8} {'触发价':<14} {'金额':<14} {'策略说明':<40}")
    print("-"*90)
    
    for i, op in enumerate(sorted_ops, 1):
        action_cn = "🟢 买入" if op['action'] == 'buy' else "🔴 卖出"
        
        # 策略说明
        if op['action'] == 'buy':
            if op['price'] < 85000:
                note = "低位补仓，大幅降低均价"
            elif op['price'] < 88000:
                note = "低位买入，降低均价"
            else:
                note = "震荡区间买入"
        else:
            if op['price'] > 92000:
                note = "高位止盈，锁定利润"
            elif op['price'] > 88000:
                note = "震荡区间卖出获利"
            else:
                note = "低位减仓"
        
        print(f"{i:<6} {action_cn:<8} ${op['price']:>11,.0f}  ${op['value']:>11,.0f}  {note}")
    
    print("-"*90)
    
    # 操作详情
    if result['operations']:
        print(f"\n📊 操作执行详情:")
        print("-"*90)
        print(f"{'序号':<6} {'操作':<8} {'触发价':<12} {'执行后均价':<14} {'强平价':<12} {'可用资金':<14}")
        print("-"*90)
        
        for i, op_result in enumerate(result['operations'], 1):
            action_cn = "买入" if op_result['action'] == 'buy' else "卖出"
            liq_status = "✅" if op_result['liq_price'] < config.max_liq_price else "⚠️"
            
            print(f"{i:<6} {action_cn:<8} "
                  f"${op_result['price']:>10,.0f} "
                  f"${op_result['entry_after']:>12,.2f} "
                  f"${op_result['liq_price']:>10,.2f} {liq_status} "
                  f"${op_result['available_equity']:>12,.2f}")
        
        print("-"*90)
    
    # 总结
    print(f"\n🎯 策略总结:")
    print(f"  1. 在 ${config.swing_low:,.0f} - ${config.swing_high:,.0f} 区间进行 {result['num_operations']} 次微操")
    print(f"  2. 均价从 ${config.entry_price:,.0f} 降至 ${result['final_entry']:,.2f} (降低 ${result['entry_reduction']:,.2f})")
    print(f"  3. 强平价保持在 ${result['max_liq_price']:.2f} (安全阈值 ${config.max_liq_price:,.0f})")
    print(f"  4. 当 BTC 达 ${config.target_btc_price:,.0f} 时，预期盈利 ${result['profit_at_target']:,.2f}")
    
    # 风险提示
    print(f"\n⚠️ 风险提示:")
    if result['max_liq_price'] > config.max_liq_price:
        print(f"  ❌ 警告：强平价 ${result['max_liq_price']:.2f} 超过安全阈值 ${config.max_liq_price:,.0f}！")
    else:
        print(f"  ✅ 强平价安全，距离阈值还有 ${config.max_liq_price - result['max_liq_price']:,.2f}")
    
    if result['profit_at_target'] < config.target_profit:
        print(f"  ⚠️ 注意：预期盈利 ${result['profit_at_target']:,.2f} 未达目标 ${config.target_profit:,.0f}")


def main():
    """主函数"""
    # 创建配置（使用你的实际持仓数据）
    config = BreakevenConfig(
        # 当前持仓状态
        initial_equity=2_000_000,
        entry_price=100_150,
        position_value=2_500_000,
        current_liq_price=20_030,
        
        # 震荡区间
        swing_low=82_000,
        swing_high=94_000,
        
        # 约束条件（放宽以探索更多可能）
        max_liq_price=30_000,           # 放宽到$30,000
        absolute_max_liq_price=35_000,  # 绝对上限$35,000
        
        # 目标
        target_btc_price=120_000,
        target_profit=500_000,
        
        # 算法参数（大幅增加以探索更多可能）
        population_size=200,       # 200个候选方案
        n_generations=100,         # 100代进化
        mutation_rate=0.3,         # 30%变异率（增加多样性）
        crossover_rate=0.8,
        
        # 操作限制（允许更多操作）
        max_operations=20,         # 最多20次操作
        min_operation_value=30_000,   # 最小3万USDT
        max_operation_value=400_000   # 最大40万USDT
    )
    
    # 运行优化
    best_ops, best_result = genetic_algorithm_optimize(config)
    
    # 显示结果
    display_results(best_ops, best_result, config)
    
    print("\n" + "="*90)
    print("✅ 优化完成！")
    print("="*90)
    
    return best_ops, best_result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
