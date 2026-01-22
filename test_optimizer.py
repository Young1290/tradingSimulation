"""
优化器测试脚本

测试遗传算法优化器的基本功能
"""

import sys
import numpy as np
from optimizer import OptimizationConfig, OptimizationController
from optimizer.chromosome import decode_chromosome, encode_chromosome, is_valid_sequence


# 模拟计算引擎（简化版本）
def mock_calculation_engine(operations, start_equity, start_qty, start_entry, current_price):
    """
    模拟的计算引擎（用于测试）
    
    实际使用时会调用 Calculation.py 中的 calculate_operation_sequence
    """
    final_equity = start_equity
    final_qty = start_qty
    final_entry = start_entry
    operation_results = []
    
    for i, op in enumerate(operations):
        # 简化计算逻辑
        if op['type'] == 'buy':
            # 模拟买入
            cost = final_equity * 0.3  # 使用30%权益
            qty_bought = cost / op['price']
            final_qty += qty_bought
            final_equity -= cost * 0.01  # 手续费
            final_entry = op['price']
        
        elif op['type'] == 'sell':
            # 模拟卖出
            if final_qty > 0:
                sell_qty = final_qty * op['size_ratio']
                revenue = sell_qty * op['price']
                profit = (op['price'] - final_entry) * sell_qty
                final_equity += revenue + profit - revenue * 0.01
                final_qty -= sell_qty
        
        # 计算当前风险缓冲
        if final_qty > 0 and final_entry > 0:
            liq_price = final_entry - final_equity / final_qty
            risk_buffer = (op['price'] - liq_price) / op['price'] * 100
        else:
            risk_buffer = 100
        
        operation_results.append({
            'price': op['price'],
            'type': op['type'],
            'equity': final_equity,
            'risk_buffer': risk_buffer
        })
    
    return {
        'final_equity': final_equity,
        'final_qty': final_qty,
        'final_entry': final_entry,
        'final_price': operations[-1]['price'] if operations else current_price,
        'operations': operation_results,
        'initial_equity': start_equity
    }


def test_chromosome_encoding():
    """测试染色体编码/解码"""
    print("\n" + "="*60)
    print("测试 1: 染色体编码/解码")
    print("="*60)
    
    # 创建测试操作序列（移除leverage字段）
    operations = [
        {'price': 85000.0, 'type': 'buy', 'size_ratio': 0.5},
        {'price': 92000.0, 'type': 'sell', 'size_ratio': 0.3}
    ]
    
    # 编码
    chromosome = encode_chromosome(operations)
    print(f"原始操作序列: {operations}")
    print(f"编码后染色体: {chromosome[:6]}")  # 只显示前6个 (2个操作 * 3参数)
    
    # 解码
    decoded = decode_chromosome(chromosome)
    print(f"解码后序列: {decoded}")
    
    # 验证
    assert len(decoded) == len(operations), "解码后长度不匹配"
    assert decoded[0]['price'] == 85000.0, "价格解码错误"
    print("✅ 编码/解码测试通过")


def test_sequence_validation():
    """测试序列有效性检查"""
    print("\n" + "="*60)
    print("测试 2: 序列有效性检查")
    print("="*60)
    
    # 有效序列
    valid_seq = [
        {'price': 80000, 'type': 'buy', 'size_ratio': 0.5},
        {'price': 90000, 'type': 'sell', 'size_ratio': 0.5}
    ]
    assert is_valid_sequence(valid_seq) == True, "有效序列判断错误"
    print("✅ 有效序列通过")
    
    # 无效序列（价格倒序）
    invalid_seq = [
        {'price': 90000, 'type': 'buy', 'size_ratio': 0.5},
        {'price': 80000, 'type': 'sell', 'size_ratio': 0.5}
    ]
    assert is_valid_sequence(invalid_seq) == False, "无效序列判断错误"
    print("✅ 无效序列检测通过")


def test_optimization_workflow():
    """测试完整优化流程"""
    print("\n" + "="*60)
    print("测试 3: 完整优化流程（小规模）")
    print("="*60)
    
    # 创建配置（小规模快速测试）
    config = OptimizationConfig(
        population_size=20,  # 小种群
        n_generations=10,    # 少代数
        target_final_equity=2500000,
        target_price=100000,
        max_risk_tolerance=10.0
    )
    
    print(f"配置: 种群={config.population_size}, 代数={config.n_generations}")
    
    # 创建控制器
    controller = OptimizationController(
        config=config,
        calculation_engine=mock_calculation_engine
    )
    
    # 初始状态
    initial_state = {
        'equity': 2_000_000,
        'qty': 25,
        'entry': 100000,
        'price': 92000
    }
    
    print(f"初始状态: 权益=${initial_state['equity']:,}")
    
    # 进度回调
    def progress_callback(generation, best_objectives, avg_objectives, pareto_front_size):
        if generation % 5 == 0:
            print(f"  代数 {generation} | 帕累托前沿: {pareto_front_size} | "
                  f"最优目标: {best_objectives}")
    
    # 执行优化
    print("\n开始优化...")
    result = controller.start_optimization(initial_state, progress_callback)
    
    # 显示结果
    print("\n" + "-"*60)
    print("优化结果:")
    print("-"*60)
    print(f"执行时间: {result.execution_time:.2f} 秒")
    print(f"总代数: {result.n_generations}")
    print(f"是否收敛: {result.converged}")
    print(f"最优序列操作数: {len(result.best_sequence)}")
    print(f"预期最终权益: ${result.final_equity:,.2f}")
    print(f"\n目标值:")
    for key, value in result.objectives.items():
        print(f"  {key}: {value:.4f}")
    
    print(f"\n最优操作序列:")
    for i, op in enumerate(result.best_sequence[:5]):  # 只显示前5个
        print(f"  {i+1}. 价格={op['price']:,.0f}, 类型={op['type']}, "
              f"仓位={op['size_ratio']:.2f}")
    
    if len(result.best_sequence) > 5:
        print(f"  ... (还有 {len(result.best_sequence) - 5} 个操作)")
    
    print("\n✅ 优化流程测试完成")


def test_pareto_solutions():
    """测试帕累托前沿解"""
    print("\n" + "="*60)
    print("测试 4: 获取帕累托前沿多个解")
    print("="*60)
    
    config = OptimizationConfig(
        population_size=30,
        n_generations=15
    )
    
    controller = OptimizationController(
        config=config,
        calculation_engine=mock_calculation_engine
    )
    
    initial_state = {
        'equity': 2_000_000,
        'qty': 25,
        'entry': 100000,
        'price': 92000
    }
    
    # 执行优化
    result = controller.start_optimization(initial_state)
    
    # 获取前5个帕累托解
    solutions = controller.get_pareto_solutions(top_n=5)
    
    print(f"帕累托前沿包含 {len(result.pareto_front)} 个解")
    print(f"展示前 {len(solutions)} 个解:\n")
    
    for i, sol in enumerate(solutions):
        print(f"解 {i+1}:")
        print(f"  操作数: {len(sol['operations'])}")
        print(f"  最终权益: ${sol['final_equity']:,.2f}")
        print(f"  权益比率: {sol['objectives']['final_equity_ratio']:.4f}")
        print(f"  强平价: ${-sol['objectives']['min_risk_buffer']:,.2f}")  # 注意取负值
        print()
    
    print("✅ 帕累托解测试完成")


def main():
    """主测试函数"""
    print("="*60)
    print("遗传算法优化器测试套件")
    print("="*60)
    
    try:
        # 运行所有测试
        test_chromosome_encoding()
        test_sequence_validation()
        test_optimization_workflow()
        test_pareto_solutions()
        
        print("\n" + "="*60)
        print("🎉 所有测试通过！优化器工作正常")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
