# -*- coding: utf-8 -*-
"""
选股策略基类

所有选股策略需要继承此类并实现 select 方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class SignalStrength(Enum):
    """信号强度枚举"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    WEAK = "观望"
    SELL = "卖出"


@dataclass
class StrategyResult:
    """
    单只股票的策略分析结果

    Attributes:
        code: 股票代码
        name: 股票名称
        score: 综合评分 (0-100)
        signal: 信号强度
        reasons: 选入理由列表
        risks: 风险因素列表
        indicators: 关键指标数据
        strategy_name: 策略名称
    """
    code: str
    name: str = ""
    score: int = 0
    signal: SignalStrength = SignalStrength.WEAK
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    indicators: Dict[str, Any] = field(default_factory=dict)
    strategy_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "score": self.score,
            "signal": self.signal.value,
            "reasons": self.reasons,
            "risks": self.risks,
            "indicators": self.indicators,
            "strategy_name": self.strategy_name,
        }


@dataclass
class SelectionResult:
    """
    选股结果汇总

    Attributes:
        candidate_pool_size: 候选池总数
        total_analyzed: 分析成功的股票数量
        selected_count: 选入的股票数量
        results: 所有股票的分析结果列表
        top_picks: 得分最高的股票列表
        timestamp: 选股时间
        strategy_names: 使用的策略名称列表
    """
    candidate_pool_size: int = 0
    total_analyzed: int = 0
    selected_count: int = 0
    results: List[StrategyResult] = field(default_factory=list)
    top_picks: List[StrategyResult] = field(default_factory=list)
    timestamp: str = ""
    strategy_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_pool_size": self.candidate_pool_size,
            "total_analyzed": self.total_analyzed,
            "selected_count": self.selected_count,
            "results": [r.to_dict() for r in self.results],
            "top_picks": [r.to_dict() for r in self.top_picks],
            "timestamp": self.timestamp,
            "strategy_names": self.strategy_names,
        }


class BaseStrategy(ABC):
    """
    选股策略抽象基类

    子类需要实现:
        - select(): 执行选股逻辑
        - get_name(): 返回策略名称
    """

    @abstractmethod
    def select(
        self,
        stock_codes: List[str],
        top_n: int = 10,
        **kwargs
    ) -> SelectionResult:
        """
        执行选股

        Args:
            stock_codes: 候选股票代码列表
            top_n: 选出前 N 只股票
            **kwargs: 策略特定参数

        Returns:
            SelectionResult: 选股结果
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """返回策略名称"""
        pass

    def get_description(self) -> str:
        """返回策略描述"""
        return ""

    def _get_stock_name(self, code: str) -> str:
        """获取股票名称"""
        from src.analyzer import STOCK_NAME_MAP
        return STOCK_NAME_MAP.get(code, "")