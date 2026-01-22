"""
优化配置模块

定义优化算法的所有参数和目标设置
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class OptimizationConfig:
    """优化配置类"""
    
    # ==================== 优化目标 ====================
    target_final_equity: Optional[float] = None  # 目标最终权益
    target_price: Optional[float] = None  # 目标BTC价格
    max_risk_tolerance: float = 5.0  # 最大风险容忍度 (%)
    
    # ==================== 算法参数 ====================
    population_size: int = 100  # 种群大小
    n_generations: int = 50  # 迭代代数
    crossover_prob: float = 0.9  # 交叉概率
    mutation_prob: float = 0.2  # 变异率
    tournament_size: int = 3  # 锦标赛选择大小
    elite_ratio: float = 0.1  # 精英保留比例
    
    # ==================== 约束条件 ====================
    min_equity: float = 0  # 最小权益（不能爆仓）
    min_risk_buffer: float = 5.0  # 最小风险缓冲 (%)
    max_leverage: int = 20  # 最大杠杆倍数
    max_operations: int = 50  # 最大操作次数
    min_operations: int = 1  # 最小操作次数
    
    # ==================== 染色体参数 ====================
    max_chromosome_length: int = 20  # 最大操作数量
    price_range: tuple = (60000, 120000)  # 价格范围
    leverage_range: tuple = (1, 20)  # 杠杆范围
    size_ratio_range: tuple = (0.1, 1.0)  # 仓位比例范围
    
    # ==================== 目标权重 ====================
    weights: Dict[str, float] = field(default_factory=lambda: {
        'final_equity': 0.4,      # 最终权益
        'risk_control': 0.3,      # 风险控制
        'efficiency': 0.1,        # 操作效率
        'target_achievement': 0.2  # 目标达成
    })
    
    # ==================== 性能优化 ====================
    use_parallel: bool = True  # 是否使用并行计算
    n_processes: Optional[int] = None  # 并行进程数（None = CPU核心数）
    use_cache: bool = True  # 是否使用缓存
    early_stopping_patience: int = 10  # 早停耐心值
    early_stopping_min_delta: float = 0.001  # 早停最小改善
    
    def __post_init__(self):
        """验证配置参数"""
        # 验证权重和为1
        total_weight = sum(self.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"权重总和必须为1.0，当前为 {total_weight}")
        
        # 验证参数范围
        if self.population_size < 10:
            raise ValueError("种群大小至少为10")
        
        if self.n_generations < 1:
            raise ValueError("迭代代数至少为1")
        
        if not 0 <= self.crossover_prob <= 1:
            raise ValueError("交叉概率必须在[0,1]之间")
        
        if not 0 <= self.mutation_prob <= 1:
            raise ValueError("变异率必须在[0,1]之间")
        
        if self.max_operations < self.min_operations:
            raise ValueError("最大操作次数必须大于等于最小操作次数")
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'target_final_equity': self.target_final_equity,
            'target_price': self.target_price,
            'max_risk_tolerance': self.max_risk_tolerance,
            'population_size': self.population_size,
            'n_generations': self.n_generations,
            'crossover_prob': self.crossover_prob,
            'mutation_prob': self.mutation_prob,
            'weights': self.weights
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OptimizationConfig':
        """从字典创建配置"""
        return cls(**data)
