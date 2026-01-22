"""
遗传算法引擎

实现NSGA-II多目标遗传算法的核心逻辑
"""

import numpy as np
from typing import List, Tuple, Callable, Dict
from .config import OptimizationConfig
from .chromosome import (
    create_random_chromosome,
    mutate_chromosome,
    crossover_chromosomes,
    decode_chromosome,
    is_valid_sequence
)
from .fitness import (
    evaluate_objectives,
    evaluate_constraints,
    fast_non_dominated_sort,
    crowding_distance_assignment,
    calculate_constraint_penalty
)


class Individual:
    """个体类"""
    
    def __init__(self, chromosome: np.ndarray):
        self.chromosome = chromosome
        self.objectives = None  # 目标值
        self.constraints = None  # 约束违反度
        self.rank = None  # 帕累托等级
        self.crowding_distance = 0.0  # 拥挤度距离
        self.operations = None  # 解码后的操作序列
        self.result = None  # 计算结果
    
    def __repr__(self):
        return f"Individual(rank={self.rank}, cd={self.crowding_distance:.2f})"


class GeneticAlgorithmEngine:
    """遗传算法引擎"""
    
    def __init__(self, config: OptimizationConfig, calculation_engine: Callable,
                 initial_state: Dict):
        """
        初始化遗传算法引擎
        
        Args:
            config: 优化配置
            calculation_engine: 计算引擎函数（现有的 calculate_operation_sequence）
            initial_state: 初始状态 {equity, qty, entry, price}
        """
        self.config = config
        self.calculation_engine = calculation_engine
        self.initial_state = initial_state
        self.rng = np.random.default_rng()
        
        # 种群
        self.population: List[Individual] = []
        self.generation = 0
        
        # 历史记录
        self.history = []
        
        # 缓存（如果启用）
        self.fitness_cache = {} if config.use_cache else None
    
    def initialize_population(self):
        """初始化种群"""
        self.population = []
        
        for _ in range(self.config.population_size):
            chromosome = create_random_chromosome(self.config, self.rng)
            individual = Individual(chromosome)
            self.population.append(individual)
        
        # 评估初始种群
        self._evaluate_population(self.population)
        
        # 计算帕累托等级和拥挤度
        self._assign_ranks_and_crowding()
    
    def _evaluate_population(self, population: List[Individual]):
        """评估种群中的所有个体"""
        for individual in population:
            self._evaluate_individual(individual)
    
    def _evaluate_individual(self, individual: Individual):
        """评估单个个体"""
        # 检查缓存
        if self.config.use_cache:
            cache_key = tuple(individual.chromosome)
            if cache_key in self.fitness_cache:
                cached = self.fitness_cache[cache_key]
                individual.objectives = cached['objectives']
                individual.constraints = cached['constraints']
                individual.operations = cached['operations']
                individual.result = cached['result']
                return
        
        # 解码染色体
        operations = decode_chromosome(individual.chromosome)
        individual.operations = operations
        
        # 检查序列有效性
        if not is_valid_sequence(operations):
            # 无效序列：设置惩罚值
            individual.objectives = np.array([1e6, 1e6, 1e6, 1e6])
            individual.constraints = np.array([1e6, 1e6, 1e6])
            individual.result = None
            return
        
        # 使用计算引擎评估
        try:
            result = self.calculation_engine(
                operations,
                self.initial_state['equity'],
                self.initial_state['qty'],
                self.initial_state['entry'],
                self.initial_state['price']
            )
            individual.result = result
            
            # 计算目标值
            individual.objectives = evaluate_objectives(
                result, self.config, self.initial_state
            )
            
            # 计算约束违反
            individual.constraints = evaluate_constraints(
                result, self.config, self.initial_state
            )
            
            # 缓存结果
            if self.config.use_cache:
                self.fitness_cache[tuple(individual.chromosome)] = {
                    'objectives': individual.objectives,
                    'constraints': individual.constraints,
                    'operations': operations,
                    'result': result
                }
        
        except Exception as e:
            # 计算错误：设置惩罚值
            print(f"评估错误: {e}")
            individual.objectives = np.array([1e6, 1e6, 1e6, 1e6])
            individual.constraints = np.array([1e6, 1e6, 1e6])
            individual.result = None
    
    def _assign_ranks_and_crowding(self):
        """分配帕累托等级和拥挤度距离"""
        # 提取所有目标值
        objectives = np.array([ind.objectives for ind in self.population])
        
        # 快速非支配排序
        fronts = fast_non_dominated_sort(objectives)
        
        # 分配等级
        for rank, front in enumerate(fronts):
            for idx in front:
                self.population[idx].rank = rank
        
        # 计算每个前沿的拥挤度
        for front in fronts:
            if len(front) > 0:
                front_objectives = objectives[front]
                distances = crowding_distance_assignment(objectives, front)
                
                for i, idx in enumerate(front):
                    self.population[idx].crowding_distance = distances[i]
    
    def tournament_selection(self, tournament_size: int = None) -> Individual:
        """锦标赛选择"""
        if tournament_size is None:
            tournament_size = self.config.tournament_size
        
        # 随机选择tournament_size个个体
        candidates = self.rng.choice(self.population, tournament_size, replace=False)
        
        # 选择最优的（rank最小，若相同则crowding_distance最大）
        best = min(candidates, key=lambda x: (x.rank, -x.crowding_distance))
        
        return best
    
    def create_offspring(self) -> List[Individual]:
        """创建后代种群"""
        offspring = []
        
        while len(offspring) < self.config.population_size:
            # 选择父代
            parent1 = self.tournament_selection()
            parent2 = self.tournament_selection()
            
            # 交叉
            if self.rng.random() < self.config.crossover_prob:
                child1_chr, child2_chr = crossover_chromosomes(
                    parent1.chromosome,
                    parent2.chromosome,
                    self.config,
                    self.rng
                )
            else:
                child1_chr = parent1.chromosome.copy()
                child2_chr = parent2.chromosome.copy()
            
            # 变异
            if self.rng.random() < self.config.mutation_prob:
                child1_chr = mutate_chromosome(
                    child1_chr,
                    self.config,
                    self.config.mutation_prob,
                    self.rng
                )
            
            if self.rng.random() < self.config.mutation_prob:
                child2_chr = mutate_chromosome(
                    child2_chr,
                    self.config,
                    self.config.mutation_prob,
                    self.rng
                )
            
            # 创建后代个体
            offspring.append(Individual(child1_chr))
            if len(offspring) < self.config.population_size:
                offspring.append(Individual(child2_chr))
        
        return offspring[:self.config.population_size]
    
    def environmental_selection(self, combined_population: List[Individual]) -> List[Individual]:
        """环境选择（NSGA-II选择策略）"""
        # 评估新个体
        self._evaluate_population(combined_population)
        
        # 分配等级和拥挤度
        objectives = np.array([ind.objectives for ind in combined_population])
        fronts = fast_non_dominated_sort(objectives)
        
        for rank, front in enumerate(fronts):
            for idx in front:
                combined_population[idx].rank = rank
        
        for front in fronts:
            if len(front) > 0:
                distances = crowding_distance_assignment(objectives, front)
                for i, idx in enumerate(front):
                    combined_population[idx].crowding_distance = distances[i]
        
        # 选择下一代
        next_generation = []
        for front in fronts:
            if len(next_generation) + len(front) <= self.config.population_size:
                # 整个前沿都加入
                next_generation.extend([combined_population[i] for i in front])
            else:
                # 按拥挤度排序，选择最分散的
                front_individuals = [combined_population[i] for i in front]
                front_individuals.sort(key=lambda x: x.crowding_distance, reverse=True)
                
                remaining = self.config.population_size - len(next_generation)
                next_generation.extend(front_individuals[:remaining])
                break
        
        return next_generation
    
    def evolve_generation(self):
        """进化一代"""
        # 创建后代
        offspring = self.create_offspring()
        
        # 合并父代和子代
        combined = self.population + offspring
        
        # 环境选择
        self.population = self.environmental_selection(combined)
        
        # 更新代数
        self.generation += 1
        
        # 记录历史
        self._record_history()
    
    def _record_history(self):
        """记录当前代的统计信息"""
        objectives = np.array([ind.objectives for ind in self.population])
        
        # 找到帕累托前沿
        front0_indices = [i for i, ind in enumerate(self.population) if ind.rank == 0]
        if front0_indices:
            front0_objectives = objectives[front0_indices]
            best_objectives = front0_objectives.min(axis=0)
            avg_objectives = front0_objectives.mean(axis=0)
        else:
            best_objectives = objectives.min(axis=0)
            avg_objectives = objectives.mean(axis=0)
        
        self.history.append({
            'generation': self.generation,
            'best_objectives': best_objectives,
            'avg_objectives': avg_objectives,
            'population_diversity': self._calculate_diversity(),
            'pareto_front_size': len(front0_indices)
        })
    
    def _calculate_diversity(self) -> float:
        """计算种群多样性"""
        # 使用目标空间的标准差作为多样性度量
        objectives = np.array([ind.objectives for ind in self.population])
        diversity = np.mean(np.std(objectives, axis=0))
        return float(diversity)
    
    def get_pareto_front(self) -> List[Individual]:
        """获取帕累托最优前沿"""
        return [ind for ind in self.population if ind.rank == 0]
    
    def get_best_individual(self) -> Individual:
        """
        获取最优个体（从帕累托前沿中选择）
        
        使用加权和方法选择最平衡的解
        """
        pareto_front = self.get_pareto_front()
        
        if not pareto_front:
            # 如果没有帕累托前沿，返回rank最小的
            return min(self.population, key=lambda x: x.rank)
        
        # 计算加权得分
        weights = np.array([
            self.config.weights['final_equity'],
            self.config.weights['risk_control'],
            self.config.weights['efficiency'],
            self.config.weights['target_achievement']
        ])
        
        best_individual = None
        best_score = float('inf')
        
        for ind in pareto_front:
            # 归一化目标值（取绝对值）
            normalized_obj = np.abs(ind.objectives)
            
            # 计算加权得分
            score = np.dot(normalized_obj, weights)
            
            if score < best_score:
                best_score = score
                best_individual = ind
        
        return best_individual
