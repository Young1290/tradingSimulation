"""
适应度评估模块

计算多目标适应度值
"""

import numpy as np
from typing import Dict, Tuple


def evaluate_objectives(result: Dict, config, initial_state: Dict) -> np.ndarray:
    """
    计算四个目标函数值
    
    注意：所有目标都转换为最小化问题（最大化目标取负值）
    
    Args:
        result: 操作序列执行结果
        config: 优化配置
        initial_state: 初始状态
    
    Returns:
        [obj1, obj2, obj3, obj4]
        - obj1: 最终权益比率（越大越好，取负值）
        - obj2: 最高强平价（越低越安全，直接最小化）
        - obj3: 操作次数（越少越好）
        - obj4: 目标价格偏差（越小越好）
    """
    final_equity = result.get('final_equity', 0)
    initial_equity = initial_state.get('equity', 1)
    operations = result.get('operations', [])
    final_price = result.get('final_price', initial_state.get('price', 0))
    
    # 提取所有操作的强平价（用户核心准则：越低越安全）
    liq_prices = [
        op.get('liq_price', 0) 
        for op in operations 
        if 'liq_price' in op and op.get('liq_price', 0) > 0
    ]
    max_liq_price = max(liq_prices) if liq_prices else 0
    
    # 目标1: 最大化最终权益比率（取负值以最小化）
    equity_ratio = final_equity / max(initial_equity, 1)
    obj1 = -equity_ratio
    
    # 目标2: 最小化强平价（强平价越低越安全！）
    # 直接使用强平价值，不取负（因为要最小化）
    obj2 = max_liq_price
    
    # 目标3: 最小化操作次数
    num_operations = len(operations)
    obj3 = num_operations
    
    # 目标4: 最小化目标价格偏差
    if config.target_price:
        price_deviation = abs(config.target_price - final_price) / max(config.target_price, 1)
        obj4 = price_deviation
    else:
        obj4 = 0
    
    return np.array([obj1, obj2, obj3, obj4])


def evaluate_constraints(result: Dict, config, initial_state: Dict) -> np.ndarray:
    """
    计算约束违反度
    
    约束格式: g(x) <= 0 表示满足约束
    
    Args:
        result: 操作序列执行结果
        config: 优化配置
        initial_state: 初始状态
    
    Returns:
        [constr1, constr2, constr3]
        所有值 <= 0 表示满足所有约束
    """
    final_equity = result.get('final_equity', 0)
    operations = result.get('operations', [])
    
    # 提取强平价
    liq_prices = [
        op.get('liq_price', 0) 
        for op in operations 
        if 'liq_price' in op and op.get('liq_price', 0) > 0
    ]
    max_liq_price = max(liq_prices) if liq_prices else 0
    
    # 约束1: 权益必须 > min_equity（不能爆仓）
    constr1 = config.min_equity - final_equity
    
    # 约束2: 强平价必须 <= 25000（用户核心准则！）
    max_allowed_liq_price = getattr(config, 'max_liq_price', 25000)
    constr2 = max_liq_price - max_allowed_liq_price
    
    # 约束3: 操作次数必须 <= max_operations
    num_operations = len(operations)
    constr3 = num_operations - config.max_operations
    
    return np.array([constr1, constr2, constr3])


def calculate_fitness_score(objectives: np.ndarray, config) -> float:
    """
    计算加权适应度得分（用于单目标排序）
    
    Args:
        objectives: 目标值数组
        config: 优化配置
    
    Returns:
        加权得分（越小越好）
    """
    weights = np.array([
        config.weights['final_equity'],
        config.weights['risk_control'],
        config.weights['efficiency'],
        config.weights['target_achievement']
    ])
    
    # 归一化目标值（简单方法：取绝对值）
    normalized_obj = np.abs(objectives)
    
    # 加权求和
    score = np.dot(normalized_obj, weights)
    
    return score


def calculate_constraint_penalty(constraints: np.ndarray) -> float:
    """
    计算约束违反惩罚值
    
    Args:
        constraints: 约束违反度数组
    
    Returns:
        总惩罚值（>=0，0表示无违反）
    """
    # 只惩罚违反的约束（>0的部分）
    violations = np.maximum(constraints, 0)
    
    # 总惩罚 = 违反值之和
    penalty = np.sum(violations)
    
    return penalty


def dominates(obj1: np.ndarray, obj2: np.ndarray) -> bool:
    """
    检查obj1是否帕累托支配obj2
    
    支配定义：
    - obj1在所有目标上不差于obj2
    - obj1至少在一个目标上好于obj2
    
    Args:
        obj1: 目标值数组1
        obj2: 目标值数组2
    
    Returns:
        obj1是否支配obj2
    """
    # 因为都是最小化，所以越小越好
    better_or_equal = np.all(obj1 <= obj2)
    strictly_better = np.any(obj1 < obj2)
    
    return better_or_equal and strictly_better


def fast_non_dominated_sort(objectives: np.ndarray) -> list:
    """
    快速非支配排序（NSGA-II算法核心）
    
    Args:
        objectives: 目标值矩阵 (population_size, n_objectives)
    
    Returns:
        前沿列表: [[front0_indices], [front1_indices], ...]
    """
    n = len(objectives)
    
    # 初始化
    domination_count = np.zeros(n, dtype=int)  # 被支配次数
    dominated_solutions = [[] for _ in range(n)]  # 该解支配的解集合
    fronts = [[]]  # 前沿
    
    # 计算支配关系
    for i in range(n):
        for j in range(i + 1, n):
            if dominates(objectives[i], objectives[j]):
                dominated_solutions[i].append(j)
                domination_count[j] += 1
            elif dominates(objectives[j], objectives[i]):
                dominated_solutions[j].append(i)
                domination_count[i] += 1
    
    # 第一前沿：未被任何解支配的解
    for i in range(n):
        if domination_count[i] == 0:
            fronts[0].append(i)
    
    # 后续前沿
    current_front = 0
    while fronts[current_front]:
        next_front = []
        for i in fronts[current_front]:
            for j in dominated_solutions[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        
        if next_front:
            fronts.append(next_front)
            current_front += 1
        else:
            break
    
    return fronts


def crowding_distance_assignment(objectives: np.ndarray, front_indices: list) -> np.ndarray:
    """
    计算拥挤度距离（NSGA-II算法核心）
    
    Args:
        objectives: 目标值矩阵
        front_indices: 前沿中的个体索引
    
    Returns:
        拥挤度距离数组
    """
    n = len(front_indices)
    n_obj = objectives.shape[1]
    
    distances = np.zeros(n)
    
    # 对每个目标
    for m in range(n_obj):
        # 按第m个目标排序
        sorted_indices = sorted(range(n), key=lambda i: objectives[front_indices[i], m])
        
        # 边界点距离设为无穷大
        distances[sorted_indices[0]] = np.inf
        distances[sorted_indices[-1]] = np.inf
        
        # 计算中间点的拥挤度
        obj_min = objectives[front_indices[sorted_indices[0]], m]
        obj_max = objectives[front_indices[sorted_indices[-1]], m]
        obj_range = obj_max - obj_min
        
        if obj_range > 0:
            for i in range(1, n - 1):
                curr_idx = sorted_indices[i]
                prev_idx = sorted_indices[i - 1]
                next_idx = sorted_indices[i + 1]
                
                distances[curr_idx] += (
                    objectives[front_indices[next_idx], m] -
                    objectives[front_indices[prev_idx], m]
                ) / obj_range
    
    return distances
