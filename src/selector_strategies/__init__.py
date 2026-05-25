# -*- coding: utf-8 -*-
"""
选股策略模块

提供多种选股策略：
- technical: 技术指标筛选（MA多头排列、MACD金叉、RSI超卖等）
- one_line_three_ma: 一阳穿三线（阳线突破MA5/MA10/MA20）
- sector: 板块轮动筛选（热点板块龙头、资金流入等）
- ai: AI智能选股（基于市场情绪和新闻）
"""

from src.selector_strategies.technical import TechnicalStrategy
from src.selector_strategies.one_line_three_ma import OneLineThreeMAStrategy
from src.selector_strategies.base import BaseStrategy, StrategyResult

__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "TechnicalStrategy",
    "OneLineThreeMAStrategy",
]