"""
资金划转引擎 (Fund Transfer Engine)
用于计算和执行 Luno 现货与 Binance 合约之间的资金划转
"""

def calculate_min_margin_required(long_qty, long_entry, short_qty, short_entry, mm_rate, current_price, safety_multiplier=1.5):
    """
    计算 Binance 合约持仓所需的最小保证金
    
    Args:
        long_qty: 多单数量 (BTC)
        long_entry: 多单均价
        short_qty: 空单数量 (BTC)
        short_entry: 空单均价
        mm_rate: 维持保证金率 (例如 0.005 = 0.5%)
        current_price: 当前价格
        safety_multiplier: 安全系数 (默认1.5倍)
    
    Returns:
        float: 最小保证金需求 (USDT)
    """
    # 计算总持仓价值
    long_position_value = long_qty * current_price
    short_position_value = short_qty * current_price
    total_position_value = long_position_value + short_position_value
    
    # 维持保证金 = 持仓价值 × 维持保证金率
    maintenance_margin = total_position_value * mm_rate
    
    # 加上安全缓冲
    min_margin_with_buffer = maintenance_margin * safety_multiplier
    
    return min_margin_with_buffer


def calculate_available_to_transfer(direction, luno_value, binance_equity, long_qty, long_entry, 
                                    short_qty, short_entry, mm_rate, current_price):
    """
    计算可划转的最大金额
    
    Args:
        direction: 'luno_to_binance' 或 'binance_to_luno'
        luno_value: Luno 现货价值
        binance_equity: Binance 权益
        long_qty, long_entry, short_qty, short_entry: 持仓信息
        mm_rate: 维持保证金率
        current_price: 当前价格
    
    Returns:
        float: 最大可划转金额 (USDT)
    """
    if direction == 'luno_to_binance':
        # Luno 可以全部划转
        return luno_value
    
    elif direction == 'binance_to_luno':
        # Binance 需要保留足够保证金
        min_margin = calculate_min_margin_required(
            long_qty, long_entry, short_qty, short_entry, 
            mm_rate, current_price, safety_multiplier=1.5
        )
        
        # 可划出 = 当前权益 - 最小保证金需求
        available = binance_equity - min_margin
        
        # 确保不为负数
        return max(0.0, available)
    
    return 0.0


def validate_transfer(direction, amount, luno_value, binance_equity, long_qty, long_entry,
                     short_qty, short_entry, mm_rate, current_price, calc_liq_price_func=None, min_buffer_percent=10.0):
    """
    验证划转是否安全
    
    Args:
        calc_liq_price_func: 强平价计算函数（避免循环导入）
    
    Returns:
        tuple: (is_valid: bool, error_message: str, warning_message: str)
    """
    # 基本验证
    if amount <= 0:
        return False, "划转金额必须大于 0", ""
    
    if amount != amount or amount == float('inf'):  # 检查 NaN 和 Infinity
        return False, "划转金额无效", ""
    
    # 方向特定验证
    if direction == 'luno_to_binance':
        if amount > luno_value:
            return False, f"划转金额超过 Luno 可用余额 (${luno_value:,.0f})", ""
        
        # 划转后 Luno 余额
        luno_after = luno_value - amount
        if luno_after < 0:
            return False, "划转后 Luno 余额不足", ""
        
        return True, "", ""
    
    elif direction == 'binance_to_luno':
        if amount > binance_equity:
            return False, f"划转金额超过 Binance 可用权益 (${binance_equity:,.0f})", ""
        
        # 计算划转后的权益
        binance_after = binance_equity - amount
        
        # 计算最小保证金需求
        min_margin = calculate_min_margin_required(
            long_qty, long_entry, short_qty, short_entry,
            mm_rate, current_price, safety_multiplier=1.2  # 使用1.2倍验证（比可用额度计算更宽松）
        )
        
        if binance_after < min_margin:
            return False, f"划转后保证金不足，至少需保留 ${min_margin:,.0f}", ""
        
        # 计算划转后的风险缓冲（如果提供了计算函数）
        if calc_liq_price_func and current_price > 0:
            liq_price_after = calc_liq_price_func(binance_after, long_qty, long_entry, 
                                            short_qty, short_entry, mm_rate, current_price)
            buffer_after = (current_price - liq_price_after) / current_price * 100
            
            if buffer_after < min_buffer_percent:
                warning = f"⚠️ 划转后风险缓冲较低 ({buffer_after:.1f}%)，建议保持在 {min_buffer_percent}% 以上"
                return True, "", warning
        
        return True, "", ""
    
    return False, "未知的划转方向", ""


def execute_transfer(direction, amount, luno_value, binance_equity):
    """
    执行资金划转
    
    Returns:
        tuple: (new_luno_value, new_binance_equity)
    """
    if direction == 'luno_to_binance':
        new_luno = luno_value - amount
        new_binance = binance_equity + amount
    elif direction == 'binance_to_luno':
        new_luno = luno_value + amount
        new_binance = binance_equity - amount
    else:
        return luno_value, binance_equity
    
    return new_luno, new_binance


def calculate_transfer_impact(direction, amount, luno_value, binance_equity, 
                              long_qty, long_entry, short_qty, short_entry, 
                              mm_rate, current_price, calc_liq_price_func):
    """
    计算划转对系统的影响
    
    Args:
        calc_liq_price_func: 强平价计算函数（避免循环导入）
    
    Returns:
        dict: 包含划转前后的各项指标
    """
    # 当前状态
    current_liq = calc_liq_price_func(binance_equity, long_qty, long_entry, 
                                 short_qty, short_entry, mm_rate, current_price)
    current_buffer = (current_price - current_liq) / current_price * 100 if current_price > 0 else 0
    
    # 执行划转后的状态
    new_luno, new_binance = execute_transfer(direction, amount, luno_value, binance_equity)
    
    new_liq = calc_liq_price_func(new_binance, long_qty, long_entry,
                            short_qty, short_entry, mm_rate, current_price)
    new_buffer = (current_price - new_liq) / current_price * 100 if current_price > 0 else 0
    
    return {
        'luno_before': luno_value,
        'luno_after': new_luno,
        'luno_change': new_luno - luno_value,
        'binance_before': binance_equity,
        'binance_after': new_binance,
        'binance_change': new_binance - binance_equity,
        'liq_price_before': current_liq,
        'liq_price_after': new_liq,
        'liq_price_change': new_liq - current_liq,
        'buffer_before': current_buffer,
        'buffer_after': new_buffer,
        'buffer_change': new_buffer - current_buffer,
        'total_portfolio_before': luno_value + binance_equity,
        'total_portfolio_after': new_luno + new_binance,
    }
