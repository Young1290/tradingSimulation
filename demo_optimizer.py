"""
优化器实际应用演示

展示如何集成现有的 calculate_operation_sequence 函数
"""

import sys
sys.path.insert(0, '/Users/user/Fund Calculation')

from optimizer import OptimizationConfig, OptimizationController


def demo_with_real_calculation():
    """使用真实的计算引擎进行优化演示"""
    
    print("="*70)
    print("遗传算法优化器 - 实际应用演示")
    print("="*70)
    
    # 注意：这里需要导入 Calculation.py 中的函数
    # 由于 Calculation.py 是 Streamlit 应用，我们需要提取纯计算函数
    # 暂时使用简化版本演示
    
    print("\n⚠️  注意: 此演示使用简化的计算引擎")
    print("实际使用时，请将 calculate_operation_sequence 从 Calculation.py 中提取")
    
    # 创建优化配置
    config = OptimizationConfig(
        # 目标设置
        target_final_equity=2_500_000,  # 目标权益 2.5M
        target_price=100_000,            # 目标价格 100k
        max_risk_tolerance=8.0,          # 最大风险容忍 8%
        
        # 算法参数（适中规模）
        population_size=50,
        n_generations=30,
        
        # 约束条件
        min_risk_buffer=5.0,             # 最小风险缓冲 5%
        max_leverage=15,                 # 最大杠杆 15x
        max_operations=30,               # 最多 30 个操作
        
        # 目标权重
        weights={
            'final_equity': 0.5,         # 收益优先
            'risk_control': 0.3,         # 风险次之
            'efficiency': 0.1,           # 效率
            'target_achievement': 0.1    # 目标达成
        }
    )
    
    print("\n📋 优化配置:")
    print(f"  种群大小: {config.population_size}")
    print(f"  迭代代数: {config.n_generations}")
    print(f"  目标权益: ${config.target_final_equity:,}")
    print(f"  目标价格: ${config.target_price:,}")
    
    # 简化的计算引擎（演示用）- 固定10x杠杆
    def simple_calculation_engine(operations, start_equity, start_qty, start_entry, current_price):
        """简化版计算引擎 - 杠杆固定为10x"""
        LEVERAGE = 10  # 固定杠杆
        
        equity = start_equity
        qty = start_qty
        entry = start_entry
        results = []
        
        # 扣除初始持仓保证金
        if start_qty > 0:
            initial_margin = (start_qty * start_entry) / LEVERAGE
            equity -= initial_margin
        
        for op in operations:
            if op['type'] == 'buy':
                # 买入：使用USDT金额和10x杠杆
                position_value = equity * op['size_ratio'] * LEVERAGE
                margin_used = position_value / LEVERAGE
                qty_bought = position_value / op['price']
                
                # 更新持仓
                old_qty = qty
                qty += qty_bought
                equity -= margin_used
                
                # 更新均价
                if old_qty > 0:
                    entry = (entry * old_qty + op['price'] * qty_bought) / qty
                else:
                    entry = op['price']
            
            elif op['type'] == 'sell' and qty > 0:
                # 卖出
                sell_qty = qty * op['size_ratio']
                profit = (op['price'] - entry) * sell_qty
                margin_released = (sell_qty * entry) / LEVERAGE
                
                equity += profit + margin_released
                qty -= sell_qty
            
            # 计算强平价（核心指标：越低越安全！不能超过25000）
            if qty > 0 and entry > 0:
                liq_price = entry - equity / qty
                # 强平价为负表示极安全（需要跌到负价格才爆仓），显示为0
                liq_price = max(0, liq_price)
                risk_buffer = max(0, (op['price'] - liq_price) / op['price'] * 100)
            else:
                liq_price = 0
                risk_buffer = 100
            
            # 计算浮盈
            if qty > 0:
                unrealized_pnl = (op['price'] - entry) * qty
                total_value = equity + qty * op['price']
            else:
                unrealized_pnl = 0
                total_value = equity
            
            results.append({
                'price': op['price'],
                'type': op['type'],
                'equity': equity,
                'qty': qty,
                'entry': entry,
                'liq_price': liq_price,  # 添加强平价
                'risk_buffer': risk_buffer,
                'unrealized_pnl': unrealized_pnl,
                'total_value': total_value
            })
        
        final_value = equity + qty * (operations[-1]['price'] if operations else current_price)
        
        return {
            'final_equity': final_value,
            'final_qty': qty,
            'final_entry': entry,
            'final_price': operations[-1]['price'] if operations else current_price,
            'operations': results,
            'initial_equity': start_equity
        }
    
    # 创建控制器
    controller = OptimizationController(
        config=config,
        calculation_engine=simple_calculation_engine
    )
    
    # 设置初始状态（基于当前市场）
    initial_state = {
        'equity': 2_000_000,   # 200万 USDT
        'qty': 25.0,           # 25 BTC
        'entry': 100_000,      # 入场价 10万
        'price': 92_000        # 当前价 9.2万
    }
    
    print("\n💰 初始状态:")
    print(f"  账户权益: ${initial_state['equity']:,}")
    print(f"  持仓数量: {initial_state['qty']} BTC")
    print(f"  入场价格: ${initial_state['entry']:,}")
    print(f"  当前价格: ${initial_state['price']:,}")
    
    # 进度回调
    progress_updates = []
    def progress_callback(generation, best_objectives, avg_objectives, pareto_front_size):
        progress_updates.append({
            'gen': generation,
            'equity_ratio': -best_objectives[0],
            'liq_price': best_objectives[1],  # 强平价越低越好，直接显示
            'pareto_size': pareto_front_size
        })
        
        if generation % 10 == 0 or generation == 1:
            print(f"  代数 {generation:3d} | "
                  f"权益比率: {-best_objectives[0]:.2f}x | "
                  f"强平价: ${best_objectives[1]:,.0f} | "
                  f"帕累托前沿: {pareto_front_size}")
    
    # 执行优化
    print("\n🚀 开始优化...")
    print("-" * 70)
    
    result = controller.start_optimization(initial_state, progress_callback)
    
    # 显示结果
    print("\n" + "="*70)
    print("✅ 优化完成！")
    print("="*70)
    
    print(f"\n⏱️  执行时间: {result.execution_time:.2f} 秒")
    print(f"📊 迭代代数: {result.n_generations}")
    print(f"🎯 是否收敛: {'是' if result.converged else '否'}")
    
    print(f"\n💎 最优解:")
    print(f"  操作数量: {len(result.best_sequence)}")
    print(f"  最终权益: ${result.final_equity:,.2f}")
    print(f"  权益提升: {result.objectives['final_equity_ratio']:.2f}x")
    print(f"  收益金额: ${result.final_equity - initial_state['equity']:,.2f}") 
    # 强平价：越低越安全，不能超过25000 (负值表示极安全，显示为0)
    liq_price_display = max(0, result.objectives['min_risk_buffer'])
    print(f"  最高强平价: ${liq_price_display:,.2f} (越低越安全, 限制≤$25,000)")  
    print(f"  目标价格偏差: {result.objectives['target_deviation']:.2%}")
    
    print(f"\n📝 最优操作序列:")
    print("="* 95)
    print(f"{'序号':<6} {'操作':<8} {'触发价':<14} {'仓位比例':<12} {'强平价':<14} {'备注':<30}")
    print("="* 95)
    
    for i, op in enumerate(result.best_sequence[:15], 1):
        # 添加操作说明
        if op['type'] == 'buy':
            note = f"买入 {op['size_ratio']*100:.0f}% 仓位"
        else:
            note = f"卖出 {op['size_ratio']*100:.0f}% 持仓"
        
        # 格式化输出（匹配 Calculation.py 风格）
        action_cn = "买入" if op['type'] == 'buy' else "卖出"
        
        print(f"{i:<6} {action_cn:<8} "
              f"${op['price']:>11,.0f}  "
              f"{op['size_ratio']:>10.0%}  "
              f"{'计算中':<14}  "  # 强平价需要从结果中获取
              f"{note:<30}")
    
    if len(result.best_sequence) > 15:
        print(f"... (还有 {len(result.best_sequence) - 15} 个操作)")
    
    print("="* 95)
    print("\n💡 说明:")
    print("  - 杠杆固定为 10x")
    print("  - 仓位比例：相对于当前可用资金的百分比")
    print("  - 强平价：此操作执行后的预计强平价格（越低越安全，限制≤$25,000）")
    
    # 显示帕累托前沿的其他解
    print(f"\n🌟 帕累托前沿其他解（共 {len(result.pareto_front)} 个）:")
    print("-" * 95)
    
    solutions = controller.get_pareto_solutions(top_n=5)
    for i, sol in enumerate(solutions[:5], 1):
        liq_price_value = max(0, sol['objectives']['min_risk_buffer'])  # 强平价越低越好
        print(f"\n解 {i}:")
        print(f"  操作数: {len(sol['operations'])} | "
              f"权益: ${sol['final_equity']:,.0f} | "
              f"比率: {sol['objectives']['final_equity_ratio']:.2f}x | "
              f"强平价: ${liq_price_value:,.0f}")
    
    print("\n" + "="*70)
    print("💡 提示: 可以从多个解中选择最适合你的策略")
    print("="*70)
    
    return result


if __name__ == "__main__":
    try:
        result = demo_with_real_calculation()
        print("\n✅ 演示完成！")
    except Exception as e:
        print(f"\n❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
