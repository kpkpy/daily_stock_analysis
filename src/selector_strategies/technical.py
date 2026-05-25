# -*- coding: utf-8 -*-
"""
技术指标选股策略

筛选条件：
1. 均线多头排列 (MA5 > MA10 > MA20)
2. MACD 金叉或即将金叉
3. RSI 不超买 (RSI < 70)
4. 量能配合 (成交量放大)
5. 价格在合理区间 (乖离率不过高)
"""

import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

from src.selector_strategies.base import (
    BaseStrategy,
    StrategyResult,
    SelectionResult,
    SignalStrength,
)
from src.stock_analyzer import StockTrendAnalyzer, TrendStatus, MACDStatus, RSIStatus
from data_provider import DataFetcherManager

logger = logging.getLogger(__name__)


class TechnicalStrategy(BaseStrategy):
    """
    技术指标选股策略

    基于以下指标进行筛选和评分：
    - 均线排列：多头排列加分，空头排列减分
    - MACD：金叉加分，零轴上金叉加倍
    - RSI：30-50区间最佳，超买减分
    - 量能：缩量回调优先，放量过猛减分
    - 乖离率：低乖离加分，高乖离风险提示
    """

    def __init__(
        self,
        min_score: int = 60,
        bias_threshold: float = 5.0,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        volume_shrink_ratio: float = 0.7,
        volume_heavy_ratio: float = 1.5,
        prefer_free_source: bool = True,
    ):
        """
        初始化策略

        Args:
            min_score: 最低筛选分数（默认60分）
            bias_threshold: 乖离率阈值（默认5%）
            rsi_oversold: RSI超卖阈值（默认30）
            rsi_overbought: RSI超买阈值（默认70）
            volume_shrink_ratio: 缩量判断比例（默认0.7）
            volume_heavy_ratio: 放量判断比例（默认1.5）
            prefer_free_source: 优先使用免费数据源（默认True）
        """
        self.min_score = min_score
        self.bias_threshold = bias_threshold
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.volume_shrink_ratio = volume_shrink_ratio
        self.volume_heavy_ratio = volume_heavy_ratio
        self.prefer_free_source = prefer_free_source

        self.trend_analyzer = StockTrendAnalyzer()
        self.fetcher = DataFetcherManager()

    def get_name(self) -> str:
        return "technical"

    def get_description(self) -> str:
        return "技术指标筛选：均线多头 + MACD金叉 + RSI合理区间"

    def select(
        self,
        stock_codes: List[str],
        top_n: int = 10,
        **kwargs
    ) -> SelectionResult:
        """
        执行技术指标选股

        Args:
            stock_codes: 候选股票代码列表
            top_n: 选出前 N 只股票
            **kwargs: 额外参数
                - max_workers: 并发线程数（默认5）
                - min_data_days: 最少数据天数（默认60）

        Returns:
            SelectionResult: 选股结果
        """
        from datetime import datetime

        max_workers = kwargs.get("max_workers", 5)
        min_data_days = kwargs.get("min_data_days", 60)

        results: List[StrategyResult] = []
        total_analyzed = 0

        logger.info(f"技术指标选股开始，候选池 {len(stock_codes)} 只股票")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_code = {
                executor.submit(
                    self._analyze_single_stock,
                    code,
                    min_data_days
                ): code
                for code in stock_codes
            }

            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                        total_analyzed += 1
                except Exception as e:
                    logger.warning(f"分析 {code} 失败: {e}")

        # 按分数排序
        results.sort(key=lambda x: x.score, reverse=True)

        # 筛选得分 >= min_score 的股票
        qualified = [r for r in results if r.score >= self.min_score]

        # 取前 top_n 只
        top_picks = qualified[:top_n]

        logger.info(
            f"技术指标选股完成：分析 {total_analyzed} 只，"
            f"合格 {len(qualified)} 只，推荐 {len(top_picks)} 只"
        )

        return SelectionResult(
            total_analyzed=total_analyzed,
            selected_count=len(top_picks),
            results=results,
            top_picks=top_picks,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            strategy_names=[self.get_name()],
        )

    def _analyze_single_stock(
        self,
        code: str,
        min_data_days: int = 60
    ) -> Optional[StrategyResult]:
        """
        分析单只股票

        Args:
            code: 股票代码
            min_data_days: 最少数据天数

        Returns:
            StrategyResult 或 None（数据不足时）
        """
        try:
            # 获取历史数据
            df, _ = self.fetcher.get_daily_data(code, days=min_data_days + 20)
            if df is None or len(df) < min_data_days:
                logger.debug(f"{code} 数据不足，跳过")
                return None

            # 使用趋势分析器计算指标
            trend_result = self.trend_analyzer.analyze(df, code)

            # 计算综合评分
            score = self._calculate_score(trend_result)

            # 生成选入理由和风险因素
            reasons = []
            risks = []

            # 均线分析
            if trend_result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
                reasons.append(f"均线多头排列（{trend_result.trend_status.value}）")
            elif trend_result.trend_status == TrendStatus.WEAK_BULL:
                reasons.append(f"弱势多头，关注MA20支撑")
            else:
                risks.append(f"趋势偏弱（{trend_result.trend_status.value}）")

            # MACD 分析
            if trend_result.macd_status in [
                MACDStatus.GOLDEN_CROSS_ZERO,
                MACDStatus.GOLDEN_CROSS
            ]:
                reasons.append(f"MACD {trend_result.macd_status.value}")
            elif trend_result.macd_status == MACDStatus.BULLISH:
                reasons.append("MACD 多头运行")
            elif trend_result.macd_status == MACDStatus.DEATH_CROSS:
                risks.append("MACD 死叉，注意风险")

            # RSI 分析
            if trend_result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.WEAK]:
                reasons.append(f"RSI {trend_result.rsi_status.value}，可能反弹")
            elif trend_result.rsi_status == RSIStatus.OVERBOUGHT:
                risks.append("RSI 超买，追高风险")
            elif trend_result.rsi_status == RSIStatus.STRONG_BUY:
                reasons.append("RSI 强势区间")

            # 乖离率分析
            if abs(trend_result.bias_ma5) > self.bias_threshold:
                risks.append(f"乖离率 {trend_result.bias_ma5:.1f}%，偏离MA5较大")
            elif trend_result.bias_ma5 < 0:
                reasons.append("价格在MA5下方，可能回踩买入")

            # 量能分析
            from src.stock_analyzer import VolumeStatus
            if trend_result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
                reasons.append("缩量回调，关注支撑")
            elif trend_result.volume_status == VolumeStatus.HEAVY_VOLUME_UP:
                reasons.append("放量上涨，动能较强")
            elif trend_result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
                risks.append("放量下跌，注意风险")

            # 信号强度
            if score >= 80:
                signal = SignalStrength.STRONG_BUY
            elif score >= 70:
                signal = SignalStrength.BUY
            elif score >= 50:
                signal = SignalStrength.HOLD
            else:
                signal = SignalStrength.WEAK

            return StrategyResult(
                code=code,
                name=self._get_stock_name(code),
                score=score,
                signal=signal,
                reasons=reasons,
                risks=risks,
                indicators={
                    "trend_status": trend_result.trend_status.value,
                    "ma_alignment": trend_result.ma_alignment,
                    "current_price": round(trend_result.current_price, 2),
                    "ma5": round(trend_result.ma5, 2),
                    "ma10": round(trend_result.ma10, 2),
                    "ma20": round(trend_result.ma20, 2),
                    "bias_ma5": round(trend_result.bias_ma5, 2),
                    "macd_status": trend_result.macd_status.value,
                    "macd_dif": round(trend_result.macd_dif, 4),
                    "macd_dea": round(trend_result.macd_dea, 4),
                    "rsi_6": round(trend_result.rsi_6, 2),
                    "rsi_12": round(trend_result.rsi_12, 2),
                    "volume_status": trend_result.volume_status.value,
                    "buy_signal": trend_result.buy_signal.value,
                },
                strategy_name=self.get_name(),
            )

        except Exception as e:
            logger.debug(f"分析 {code} 异常: {e}")
            return None

    def _calculate_score(self, trend_result) -> int:
        """
        计算综合评分 (0-100)

        评分规则：
        - 均线排列 (最高30分)
        - MACD信号 (最高25分)
        - RSI状态 (最高20分)
        - 量能配合 (最高15分)
        - 乖离率 (最高10分，扣分项)
        """
        score = 50  # 基础分

        # 1. 均线排列 (最高30分)
        if trend_result.trend_status == TrendStatus.STRONG_BULL:
            score += 30
        elif trend_result.trend_status == TrendStatus.BULL:
            score += 20
        elif trend_result.trend_status == TrendStatus.WEAK_BULL:
            score += 10
        elif trend_result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            score -= 20
        elif trend_result.trend_status == TrendStatus.WEAK_BEAR:
            score -= 10

        # 2. MACD信号 (最高25分)
        if trend_result.macd_status == MACDStatus.GOLDEN_CROSS_ZERO:
            score += 25
        elif trend_result.macd_status == MACDStatus.GOLDEN_CROSS:
            score += 20
        elif trend_result.macd_status == MACDStatus.BULLISH:
            score += 15
        elif trend_result.macd_status == MACDStatus.CROSSING_UP:
            score += 10
        elif trend_result.macd_status == MACDStatus.DEATH_CROSS:
            score -= 15

        # 3. RSI状态 (最高20分)
        if trend_result.rsi_status == RSIStatus.OVERSOLD:
            score += 20  # 超卖可能反弹
        elif trend_result.rsi_status == RSIStatus.WEAK:
            score += 15
        elif trend_result.rsi_status == RSIStatus.NEUTRAL:
            score += 5
        elif trend_result.rsi_status == RSIStatus.STRONG_BUY:
            score += 10
        elif trend_result.rsi_status == RSIStatus.OVERBOUGHT:
            score -= 10

        # 4. 量能配合 (最高15分)
        from src.stock_analyzer import VolumeStatus
        if trend_result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            score += 15  # 缩量回调是好买点
        elif trend_result.volume_status == VolumeStatus.HEAVY_VOLUME_UP:
            score += 10
        elif trend_result.volume_status == VolumeStatus.SHRINK_VOLUME_UP:
            score -= 5  # 无量上涨不健康
        elif trend_result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            score -= 15

        # 5. 乖离率 (扣分项)
        if abs(trend_result.bias_ma5) > self.bias_threshold * 2:
            score -= 15  # 乖离过大
        elif abs(trend_result.bias_ma5) > self.bias_threshold:
            score -= 5

        # 限制在 0-100 之间
        return max(0, min(100, score))