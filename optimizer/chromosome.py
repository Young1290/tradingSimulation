"""
染色体编码/解码模块

处理操作序列与染色体之间的转换
"""

import numpy as np
from typing import List, Dict, Tuple


def decode_chromosome(chromosome: np.ndarray) -> List[Dict]:
    """
    将染色体解码为操作序列
    
    Args:
        chromosome: [price1, action1, size1, price2, action2, size2, ...]
                   形状: (max_ops * 3,)  # 改为3个参数：价格、动作、仓位
    
    Returns:
        操作序列列表:
        [
            {'price': 85000.0, 'type': 'buy', 'size_ratio': 0.5},
            {'price': 92000.0, 'type': 'sell', 'size_ratio': 0.3},
            ...
        ]
    """
    operations = []
    n_ops = len(chromosome) // 3  # 改为每个操作3个参数
    
    for i in range(n_ops):
        idx = i * 3
        price = chromosome[idx]
        action_code = int(chromosome[idx + 1])
        size_ratio = chromosome[idx + 2]
        
        # 跳过无效操作（价格为0或极小值，表示未使用的槽位）
        if price < 1000 or size_ratio < 0.01:
            continue
        
        # 将动作代码转换为类型（只有买入/卖出，移除adjust）
        action_types = ['buy', 'sell']
        action_type = action_types[action_code % len(action_types)]
        
        operations.append({
            'price': round(float(price), 2),
            'type': action_type,
            'size_ratio': round(float(size_ratio), 2)
        })
    
    # 按价格排序（确保时间顺序）
    operations.sort(key=lambda x: x['price'])
    
    return operations


def encode_chromosome(operations: List[Dict], max_length: int = 20) -> np.ndarray:
    """
    将操作序列编码为染色体
    
    Args:
        operations: 操作序列列表
        max_length: 染色体最大长度（最多操作数）
    
    Returns:
        染色体数组，形状: (max_length * 3,)
    """
    chromosome = np.zeros(max_length * 3)
    
    for i, op in enumerate(operations[:max_length]):
        # 将类型转换为动作代码
        action_code = {'buy': 0, 'sell': 1}.get(op['type'], 0)
        
        idx = i * 3
        chromosome[idx:idx + 3] = [
            op['price'],
            action_code,
            op['size_ratio']
        ]
    
    return chromosome


def is_valid_sequence(operations: List[Dict]) -> bool:
    """
    检查操作序列是否有效
    
    验证规则:
    1. 序列不为空
    2. 价格按升序排列（时间顺序）
    3. 所有参数在有效范围内
    
    Args:
        operations: 操作序列
    
    Returns:
        是否有效
    """
    if not operations:
        return False
    
    # 检查价格顺序
    prices = [op['price'] for op in operations]
    if prices != sorted(prices):
        return False
    
    # 检查参数范围
    for op in operations:
        # 价格范围检查
        if not (10000 <= op['price'] <= 200000):  # 扩大范围以适应未来
            return False
        
        # 仓位比例检查
        if not (0.01 <= op['size_ratio'] <= 1.0):
            return False
        
        # 类型检查（只有buy和sell）
        if op['type'] not in ['buy', 'sell']:
            return False
    
    return True


def create_random_chromosome(config, rng: np.random.Generator = None) -> np.ndarray:
    """
    创建随机染色体
    
    Args:
        config: OptimizationConfig 对象
        rng: 随机数生成器
    
    Returns:
        随机染色体
    """
    if rng is None:
        rng = np.random.default_rng()
    
    # 随机操作数量（3-15个操作）
    n_ops = rng.integers(3, min(config.max_chromosome_length, 15) + 1)
    
    chromosome = np.zeros(config.max_chromosome_length * 3)
    
    # 生成随机价格（排序的）
    prices = np.sort(rng.uniform(
        config.price_range[0],
        config.price_range[1],
        n_ops
    ))
    
    for i in range(n_ops):
        idx = i * 3
        chromosome[idx] = prices[i]  # 价格
        chromosome[idx + 1] = rng.integers(0, 2)  # 动作类型 (0=buy, 1=sell)
        chromosome[idx + 2] = rng.uniform(
            config.size_ratio_range[0],
            config.size_ratio_range[1]
        )  # 仓位比例
    
    return chromosome


def mutate_chromosome(chromosome: np.ndarray, config, mutation_rate: float = 0.2,
                     rng: np.random.Generator = None) -> np.ndarray:
    """
    对染色体进行变异
    
    Args:
        chromosome: 原始染色体
        config: 优化配置
        mutation_rate: 变异率
        rng: 随机数生成器
    
    Returns:
        变异后的染色体
    """
    if rng is None:
        rng = np.random.default_rng()
    
    mutated = chromosome.copy()
    n_ops = len(chromosome) // 3  # 改为3参数
    
    for i in range(n_ops):
        if rng.random() < mutation_rate:
            idx = i * 3
            
            # 跳过未使用的槽位
            if mutated[idx] < 1000:
                continue
            
            # 随机选择变异类型（移除leverage_adjust）
            mutation_type = rng.choice([
                'price_shift',      # 价格微调
                'action_flip',      # 买卖翻转
                'size_change',      # 仓位调整
                'delete_operation'  # 删除操作
            ])
            
            if mutation_type == 'price_shift':
                # 价格 ±5%
                shift = rng.uniform(-0.05, 0.05)
                mutated[idx] = np.clip(
                    mutated[idx] * (1 + shift),
                    config.price_range[0],
                    config.price_range[1]
                )
            
            elif mutation_type == 'action_flip':
                # 在buy/sell之间翻转
                current_action = int(mutated[idx + 1])
                if current_action == 0:  # buy -> sell
                    mutated[idx + 1] = 1
                elif current_action == 1:  # sell -> buy
                    mutated[idx + 1] = 0
            
            elif mutation_type == 'size_change':
                # 仓位 ±20%
                shift = rng.uniform(-0.2, 0.2)
                mutated[idx + 2] = np.clip(
                    mutated[idx + 2] + shift,
                    config.size_ratio_range[0],
                    config.size_ratio_range[1]
                )
            
            elif mutation_type == 'delete_operation':
                # 删除此操作（设为0）
                mutated[idx:idx + 3] = 0
    
    # 重新排序价格（保持时间顺序）
    operations = []
    for i in range(n_ops):
        idx = i * 3
        if mutated[idx] >= 1000:
            operations.append({
                'price': mutated[idx],
                'action': mutated[idx + 1],
                'size': mutated[idx + 2]
            })
    
    operations.sort(key=lambda x: x['price'])
    
    # 重建染色体
    result = np.zeros_like(chromosome)
    for i, op in enumerate(operations):
        idx = i * 3
        result[idx:idx + 3] = [op['price'], op['action'], op['size']]
    
    return result


def crossover_chromosomes(parent1: np.ndarray, parent2: np.ndarray,
                         config, rng: np.random.Generator = None) -> Tuple[np.ndarray, np.ndarray]:
    """
    单点交叉
    
    Args:
        parent1: 父代1
        parent2: 父代2
        config: 优化配置
        rng: 随机数生成器
    
    Returns:
        (子代1, 子代2)
    """
    if rng is None:
        rng = np.random.default_rng()
    
    # 找到两个父代的有效操作数
    n_ops1 = sum(1 for i in range(len(parent1) // 3) if parent1[i * 3] >= 1000)
    n_ops2 = sum(1 for i in range(len(parent2) // 3) if parent2[i * 3] >= 1000)
    
    if n_ops1 == 0 or n_ops2 == 0:
        return parent1.copy(), parent2.copy()
    
    # 随机选择交叉点（以操作为单位）
    max_point = min(n_ops1, n_ops2)
    if max_point <= 1:
        return parent1.copy(), parent2.copy()
    
    crossover_point = rng.integers(1, max_point) * 3  # 改为3参数
    
    # 执行交叉
    child1 = np.concatenate([parent1[:crossover_point], parent2[crossover_point:]])
    child2 = np.concatenate([parent2[:crossover_point], parent1[crossover_point:]])
    
    return child1, child2
