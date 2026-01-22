"""
优化控制器

协调整个优化流程，提供高层接口
"""

import time
from typing import Dict, List, Callable, Optional
import numpy as np
from .config import OptimizationConfig
from .genetic_algorithm import GeneticAlgorithmEngine, Individual


class OptimizationResult:
    """优化结果类"""
    
    def __init__(self):
        self.best_sequence: List[Dict] = []
        self.final_equity: float = 0
        self.objectives: Dict[str, float] = {}
        self.pareto_front: List[Individual] = []
        self.optimization_history: List[Dict] = []
        self.execution_time: float = 0
        self.converged: bool = False
        self.n_generations: int = 0
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'best_sequence': self.best_sequence,
            'final_equity': self.final_equity,
            'objectives': self.objectives,
            'pareto_front_size': len(self.pareto_front),
            'execution_time': self.execution_time,
            'converged': self.converged,
            'n_generations': self.n_generations
        }


class ProgressCallback:
    """进度回调基类"""
    
    def __call__(self, generation: int, best_objectives: np.ndarray,
                 avg_objectives: np.ndarray, pareto_front_size: int):
        """
        进度回调
        
        Args:
            generation: 当前代数
            best_objectives: 最优目标值
            avg_objectives: 平均目标值
            pareto_front_size: 帕累托前沿大小
        """
        pass


class OptimizationController:
    """优化控制器"""
    
    def __init__(self, config: OptimizationConfig, calculation_engine: Callable):
        """
        初始化优化控制器
        
        Args:
            config: 优化配置
            calculation_engine: 计算引擎函数
        """
        self.config = config
        self.calculation_engine = calculation_engine
        self.engine: Optional[GeneticAlgorithmEngine] = None
        self.result: Optional[OptimizationResult] = None
        self.is_running = False
        self.should_stop = False
    
    def start_optimization(self, initial_state: Dict,
                          progress_callback: Optional[ProgressCallback] = None) -> OptimizationResult:
        """
        开始优化流程
        
        Args:
            initial_state: 初始状态 {equity, qty, entry, price}
            progress_callback: 进度回调函数
        
        Returns:
            OptimizationResult 对象
        """
        start_time = time.time()
        self.is_running = True
        self.should_stop = False
        
        # 创建结果对象
        self.result = OptimizationResult()
        
        try:
            # 初始化遗传算法引擎
            self.engine = GeneticAlgorithmEngine(
                config=self.config,
                calculation_engine=self.calculation_engine,
                initial_state=initial_state
            )
            
            # 初始化种群
            print(f"正在初始化种群（大小={self.config.population_size}）...")
            self.engine.initialize_population()
            
            # 早停检测器
            early_stopper = EarlyStopping(
                patience=self.config.early_stopping_patience,
                min_delta=self.config.early_stopping_min_delta
            )
            
            # 主优化循环
            print(f"开始优化（最大代数={self.config.n_generations}）...")
            for gen in range(self.config.n_generations):
                if self.should_stop:
                    print("优化被手动停止")
                    break
                
                # 进化一代
                self.engine.evolve_generation()
                
                # 获取当前最优解
                best_individual = self.engine.get_best_individual()
                pareto_front = self.engine.get_pareto_front()
                
                # 调用进度回调
                if progress_callback:
                    progress_callback(
                        generation=gen + 1,
                        best_objectives=best_individual.objectives,
                        avg_objectives=self.engine.history[-1]['avg_objectives'],
                        pareto_front_size=len(pareto_front)
                    )
                
                # 打印进度
                if (gen + 1) % 10 == 0:
                    print(f"代数 {gen + 1}/{self.config.n_generations} | "
                          f"帕累托前沿: {len(pareto_front)} | "
                          f"最优适应度: {best_individual.objectives}")
                
                # 早停检测
                if early_stopper(best_individual.objectives[0]):  # 使用第一个目标
                    print(f"早停：在第 {gen + 1} 代收敛")
                    self.result.converged = True
                    break
            
            # 提取最优解
            self._extract_best_solution()
            
            # 记录执行时间
            self.result.execution_time = time.time() - start_time
            self.result.n_generations = self.engine.generation
            
            print(f"\n✅ 优化完成！用时 {self.result.execution_time:.2f} 秒")
            print(f"最优序列包含 {len(self.result.best_sequence)} 个操作")
            print(f"预期最终权益: ${self.result.final_equity:,.2f}")
            
        except Exception as e:
            print(f"❌ 优化过程出错: {e}")
            raise
        
        finally:
            self.is_running = False
        
        return self.result
    
    def stop_optimization(self):
        """停止优化"""
        self.should_stop = True
    
    def get_progress(self) -> Dict:
        """
        获取优化进度
        
        Returns:
            进度信息字典
        """
        if not self.engine:
            return {
                'generation': 0,
                'progress': 0.0,
                'is_running': False
            }
        
        return {
            'generation': self.engine.generation,
            'max_generations': self.config.n_generations,
            'progress': self.engine.generation / self.config.n_generations,
            'is_running': self.is_running,
            'pareto_front_size': len(self.engine.get_pareto_front())
        }
    
    def _extract_best_solution(self):
        """从帕累托前沿中提取最优解"""
        # 获取最优个体
        best_individual = self.engine.get_best_individual()
        
        # 保存最优序列
        self.result.best_sequence = best_individual.operations
        
        # 保存目标值
        if best_individual.result:
            self.result.final_equity = best_individual.result.get('final_equity', 0)
        
        # 转换目标值（取反回来）
        self.result.objectives = {
            'final_equity_ratio': -best_individual.objectives[0],  # 取反
            'min_risk_buffer': -best_individual.objectives[1],  # 取反
            'num_operations': best_individual.objectives[2],
            'target_deviation': best_individual.objectives[3]
        }
        
        # 保存帕累托前沿
        self.result.pareto_front = self.engine.get_pareto_front()
        
        # 保存优化历史
        self.result.optimization_history = self.engine.history
    
    def get_pareto_solutions(self, top_n: int = 10) -> List[Dict]:
        """
        获取帕累托前沿的多个解
        
        Args:
            top_n: 返回前N个解
        
        Returns:
            解列表，每个解包含操作序列和目标值
        """
        if not self.result or not self.result.pareto_front:
            return []
        
        solutions = []
        for individual in self.result.pareto_front[:top_n]:
            solutions.append({
                'operations': individual.operations,
                'objectives': {
                    'final_equity_ratio': -individual.objectives[0],
                    'min_risk_buffer': -individual.objectives[1],
                    'num_operations': individual.objectives[2],
                    'target_deviation': individual.objectives[3]
                },
                'final_equity': individual.result.get('final_equity', 0) if individual.result else 0
            })
        
        return solutions


class EarlyStopping:
    """早停检测器"""
    
    def __init__(self, patience: int = 10, min_delta: float = 0.001):
        """
        Args:
            patience: 耐心值（多少代没有改善就停止）
            min_delta: 最小改善值
        """
        self.patience = patience
        self.min_delta = min_delta
        self.best_value = float('inf')
        self.counter = 0
    
    def __call__(self, current_value: float) -> bool:
        """
        检查是否应该早停
        
        Args:
            current_value: 当前值
        
        Returns:
            是否应该停止
        """
        # 当前值更好（更小）
        if current_value < self.best_value - self.min_delta:
            self.best_value = current_value
            self.counter = 0
            return False
        else:
            self.counter += 1
            if self.counter >= self.patience:
                return True  # 触发早停
            return False
    
    def reset(self):
        """重置早停检测器"""
        self.best_value = float('inf')
        self.counter = 0
