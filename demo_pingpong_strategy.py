"""
波段网格（Ping-Pong）策略模拟器

核心策略：
1. 买卖交替：禁止连续买入，必须"买-卖-买-卖"交替
2. 逻辑闭环：每笔买入对应一笔卖出
3. 强平价全程 < $28,500
4. 资金利用：每次 30%-40%

指定操作序列：
- Step 1: $84k-$85k 买入 ~$100k
- Step 2: $89k-$90k 卖出 Step 1 数量
- Step 3: $81k-$82k 买入 ~$150k  
- Step 4: $93k-$94k 卖出 Step 3 数量
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict
import time


@dataclass
class PingPongConfig:
    """Ping-Pong策略配置"""
    
    # 当前持仓状态
    current_qty: float = 25.0
    entry_price: float = 100_150
    available_capital: float = 300_000
    current_liq_price: float = 20_030
    
    # 硬约束
    max_liq_price: float = 28_500
    leverage: int = 10
    
    # 目标
    target_btc_price: float = 120_000


def simulate_pingpong_strategy(operations: List[Dict], config: PingPongConfig) -> Dict:
    """
    模拟 Ping-Pong 策略
    
    每个操作格式：
    {
        'step': 1,
        'action': 'buy' | 'sell',
        'price_low': float,
        'price_high': float,
        'value': float (买入金额) 或 'match_prev' (卖出匹配上一笔买入)
    }
    """
    # 初始状态
    qty = config.current_qty
    entry = config.entry_price
    
    # 计算初始权益：Liq = Entry - Equity/Qty => Equity = (Entry - Liq) * Qty
    total_equity = (config.entry_price - config.current_liq_price) * config.current_qty
    available_capital = config.available_capital
    
    results = []
    pending_buy_qty = 0  # 上一笔买入的数量（用于匹配卖出）
    pending_buy_entry = 0  # 上一笔买入的价格
    
    liq_price = config.current_liq_price
    
    print("="*90)
    print("🏓 波段网格（Ping-Pong）策略模拟")
    print("="*90)
    
    print(f"\n📊 初始状态:")
    print(f"  持仓量: {qty:.4f} BTC")
    print(f"  入场均价: ${entry:,.2f}")
    print(f"  强平价: ${liq_price:,.2f}")
    print(f"  可用资金: ${available_capital:,.0f}")
    print(f"  账户权益: ${total_equity:,.0f}")
    
    print(f"\n🎯 硬约束: 强平价全程 < ${config.max_liq_price:,.0f}")
    
    print("\n" + "="*90)
    print("📋 操作执行详情")
    print("="*90)
    
    for i, op in enumerate(operations):
        step = op.get('step', i + 1)
        action = op['action']
        price_low = op['price_low']
        price_high = op['price_high']
        
        # 取价格区间中点
        price = (price_low + price_high) / 2
        
        print(f"\n{'='*90}")
        print(f"📌 Step {step}: {op.get('description', '')}")
        print(f"{'='*90}")
        
        old_qty = qty
        old_entry = entry
        old_liq = liq_price
        old_equity = total_equity
        
        if action == 'buy':
            buy_value = op['value']
            margin_needed = buy_value / config.leverage
            
            print(f"\n  🟢 买入操作:")
            print(f"     价格区间: ${price_low:,.0f} - ${price_high:,.0f}")
            print(f"     执行价格: ${price:,.0f}")
            print(f"     买入金额: ${buy_value:,.0f}")
            print(f"     所需保证金: ${margin_needed:,.0f}")
            
            # 检查资金
            if available_capital < margin_needed:
                print(f"     ⚠️ 资金不足！可用: ${available_capital:,.0f}")
                buy_value = available_capital * config.leverage
                margin_needed = available_capital
                print(f"     调整为: ${buy_value:,.0f}")
            
            # 执行买入
            qty_bought = buy_value / price
            qty += qty_bought
            available_capital -= margin_needed
            
            # 更新均价
            entry = (old_entry * old_qty + price * qty_bought) / qty
            
            # 更新权益
            total_equity += margin_needed
            
            # 记录待卖出
            pending_buy_qty = qty_bought
            pending_buy_entry = price
            
            print(f"\n  📊 执行结果:")
            print(f"     买入数量: {qty_bought:.4f} BTC")
            print(f"     新持仓量: {qty:.4f} BTC (+{qty_bought:.4f})")
            print(f"     新均价: ${entry:,.2f} (原 ${old_entry:,.2f})")
            print(f"     剩余可用资金: ${available_capital:,.0f}")
            
        elif action == 'sell':
            # 卖出匹配上一笔买入
            if op.get('value') == 'match_prev':
                sell_qty = pending_buy_qty
            else:
                sell_qty = op['value'] / price
            
            sell_value = sell_qty * price
            
            print(f"\n  🔴 卖出操作:")
            print(f"     价格区间: ${price_low:,.0f} - ${price_high:,.0f}")
            print(f"     执行价格: ${price:,.0f}")
            print(f"     卖出数量: {sell_qty:.4f} BTC")
            print(f"     卖出价值: ${sell_value:,.0f}")
            
            # 计算盈亏
            realized_pnl = (price - pending_buy_entry) * sell_qty
            margin_released = (sell_qty * entry) / config.leverage
            
            print(f"\n  💰 盈亏计算:")
            print(f"     买入价: ${pending_buy_entry:,.0f}")
            print(f"     卖出价: ${price:,.0f}")
            print(f"     价差: ${price - pending_buy_entry:,.0f}")
            print(f"     实现盈亏: ${realized_pnl:,.2f}")
            
            # 执行卖出
            qty -= sell_qty
            total_equity += realized_pnl
            
            print(f"\n  📊 执行结果:")
            print(f"     卖出数量: {sell_qty:.4f} BTC")
            print(f"     新持仓量: {qty:.4f} BTC (-{sell_qty:.4f})")
            print(f"     新权益: ${total_equity:,.0f} (+${realized_pnl:,.2f})")
            
            # 重置待卖出
            pending_buy_qty = 0
            pending_buy_entry = 0
        
        # 计算新强平价
        if qty > 0:
            liq_price = entry - total_equity / qty
            liq_price = max(0, liq_price)
        else:
            liq_price = 0
        
        # 检查强平价约束
        liq_ok = liq_price < config.max_liq_price
        liq_change = liq_price - old_liq
        
        print(f"\n  ⚠️ 强平价变化:")
        print(f"     操作前: ${old_liq:,.2f}")
        print(f"     操作后: ${liq_price:,.2f} ({'↑' if liq_change > 0 else '↓'} ${abs(liq_change):,.2f})")
        print(f"     约束检查: {'✅ 安全' if liq_ok else '❌ 超标!'} (限制 < ${config.max_liq_price:,.0f})")
        
        if liq_ok:
            safety_margin = config.max_liq_price - liq_price
            print(f"     安全垫: ${safety_margin:,.2f}")
        
        results.append({
            'step': step,
            'action': action,
            'price': price,
            'qty_change': qty - old_qty,
            'qty_after': qty,
            'entry_after': entry,
            'liq_before': old_liq,
            'liq_after': liq_price,
            'liq_change': liq_change,
            'equity_after': total_equity,
            'liq_ok': liq_ok
        })
    
    # 计算最终收益
    if qty > 0:
        profit_at_target = (config.target_btc_price - entry) * qty
    else:
        profit_at_target = total_equity - (config.entry_price - config.current_liq_price) * config.current_qty
    
    return {
        'final_qty': qty,
        'final_entry': entry,
        'final_liq_price': liq_price,
        'final_equity': total_equity,
        'profit_at_target': profit_at_target,
        'entry_reduction': config.entry_price - entry,
        'steps': results,
        'all_steps_safe': all(r['liq_ok'] for r in results)
    }


def compare_with_pyramid(pingpong_result: Dict, config: PingPongConfig):
    """
    与金字塔策略（连续买入）对比
    """
    print("\n" + "="*90)
    print("📊 策略对比：Ping-Pong vs 连续买入")
    print("="*90)
    
    # 模拟连续买入相同金额
    qty = config.current_qty
    entry = config.entry_price
    total_equity = (config.entry_price - config.current_liq_price) * config.current_qty
    
    # 连续买入 $100k @ $84.5k + $150k @ $81.5k = $250k
    buys = [
        (84500, 100000),
        (81500, 150000),
    ]
    
    pyramid_steps = []
    for price, value in buys:
        margin = value / config.leverage
        qty_bought = value / price
        old_entry = entry
        qty += qty_bought
        total_equity += margin
        entry = (old_entry * (qty - qty_bought) + price * qty_bought) / qty
        liq_price = entry - total_equity / qty
        pyramid_steps.append({
            'price': price,
            'value': value,
            'liq_price': liq_price
        })
    
    pyramid_max_liq = max(s['liq_price'] for s in pyramid_steps)
    pyramid_final_liq = pyramid_steps[-1]['liq_price']
    
    # Ping-Pong 最大强平价
    pingpong_max_liq = max(r['liq_after'] for r in pingpong_result['steps'])
    pingpong_final_liq = pingpong_result['final_liq_price']
    
    print(f"\n{'  策略':<20} {'最大强平价':<18} {'最终强平价':<18} {'是否安全':<12}")
    print("-"*70)
    print(f"  {'Ping-Pong':<18} ${pingpong_max_liq:>12,.2f}    ${pingpong_final_liq:>12,.2f}    {'✅' if pingpong_max_liq < config.max_liq_price else '❌'}")
    print(f"  {'连续买入':<18} ${pyramid_max_liq:>12,.2f}    ${pyramid_final_liq:>12,.2f}    {'✅' if pyramid_max_liq < config.max_liq_price else '❌'}")
    print("-"*70)
    
    liq_diff = pyramid_max_liq - pingpong_max_liq
    print(f"\n  💡 Ping-Pong 策略最大强平价比连续买入低 ${liq_diff:,.2f}")
    
    if pingpong_max_liq < config.max_liq_price and pyramid_max_liq >= config.max_liq_price:
        print(f"  🎯 关键优势：Ping-Pong 全程安全，连续买入会超标！")


def display_summary(result: Dict, config: PingPongConfig):
    """显示最终汇总"""
    print("\n" + "="*90)
    print("💎 策略执行汇总")
    print("="*90)
    
    print(f"\n📈 最终状态:")
    print(f"  持仓量: {result['final_qty']:.4f} BTC")
    print(f"  入场均价: ${result['final_entry']:,.2f} (降低 ${result['entry_reduction']:,.2f})")
    print(f"  最终强平价: ${result['final_liq_price']:,.2f}")
    print(f"  账户权益: ${result['final_equity']:,.0f}")
    print(f"  BTC@${config.target_btc_price:,.0f}盈利: ${result['profit_at_target']:,.2f}")
    
    print(f"\n⚠️ 风险评估:")
    if result['all_steps_safe']:
        print(f"  ✅ 全程强平价均 < ${config.max_liq_price:,.0f}，策略安全执行")
    else:
        print(f"  ❌ 存在步骤强平价超标！")
    
    print(f"\n📊 每步强平价变化:")
    print("-"*70)
    print(f"{'  Step':<8} {'操作':<8} {'价格':<12} {'强平价':<14} {'变化':<14} {'状态':<8}")
    print("-"*70)
    print(f"  {'初始':<6} {'-':<8} {'-':<12} ${config.current_liq_price:>10,.0f}    {'-':<14} {'✅':<8}")
    
    for r in result['steps']:
        action = '🟢买入' if r['action'] == 'buy' else '🔴卖出'
        change_str = f"{'↑' if r['liq_change'] > 0 else '↓'} ${abs(r['liq_change']):,.0f}"
        status = '✅' if r['liq_ok'] else '❌'
        print(f"  {r['step']:<6} {action:<6} ${r['price']:>10,.0f} ${r['liq_after']:>10,.0f}    {change_str:<14} {status:<8}")
    print("-"*70)


def main():
    """主函数"""
    config = PingPongConfig(
        current_qty=25.0,
        entry_price=100_150,
        available_capital=300_000,
        current_liq_price=20_030,
        max_liq_price=28_500,
        leverage=10,
        target_btc_price=120_000
    )
    
    # 用户指定的4步操作序列
    operations = [
        {
            'step': 1,
            'action': 'buy',
            'price_low': 84000,
            'price_high': 85000,
            'value': 100000,
            'description': '初次接针 - 在 $84k-$85k 买入 $100k'
        },
        {
            'step': 2,
            'action': 'sell',
            'price_low': 89000,
            'price_high': 90000,
            'value': 'match_prev',
            'description': '短线获利 - 在 $89k-$90k 卖出 Step 1 数量'
        },
        {
            'step': 3,
            'action': 'buy',
            'price_low': 81000,
            'price_high': 82000,
            'value': 150000,
            'description': '二次深跌 - 在 $81k-$82k 买入 $150k'
        },
        {
            'step': 4,
            'action': 'sell',
            'price_low': 93000,
            'price_high': 94000,
            'value': 'match_prev',
            'description': '波段止盈 - 在 $93k-$94k 卖出 Step 3 数量'
        }
    ]
    
    # 执行模拟
    result = simulate_pingpong_strategy(operations, config)
    
    # 显示汇总
    display_summary(result, config)
    
    # 与连续买入对比
    compare_with_pyramid(result, config)
    
    print("\n" + "="*90)
    print("✅ Ping-Pong 策略模拟完成！")
    print("="*90)
    
    return result


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
