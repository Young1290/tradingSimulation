"""
遗传算法优化器模块

提供自动化交易序列优化功能，使用NSGA-II多目标遗传算法
"""

from .config import OptimizationConfig
from .controller import OptimizationController
from .chromosome import decode_chromosome, encode_chromosome, is_valid_sequence

__version__ = "1.0.0"
__all__ = [
    'OptimizationConfig',
    'OptimizationController',
    'decode_chromosome',
    'encode_chromosome',
    'is_valid_sequence'
]
