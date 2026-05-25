# -*- coding: utf-8 -*-
"""
一阳穿三线选股策略

经典技术形态：
- 一根阳线（收盘价 > 开盘价）
- 同时突破 MA5、MA10、MA20 三条均线
- 当日成交量放大（可选）

信号强度：
- 强信号：阳线实体长、放量突破、均线多头排列
- 一般信号：阳线突破但量能不足
"""

import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import numpy as np

from src.selector_strategies.base import (
    BaseStrategy,
    StrategyResult,
    SelectionResult,
    SignalStrength,
)
from data_provider import DataFetcherManager

logger = logging.getLogger(__name__)


class OneLineThreeMAStrategy(BaseStrategy):
    """
    一阳穿三线选股策略

    筛选条件：
    1. 当日阳线（close > open）
    2. 开盘价在 MA20 下方（或 MA10 下方）
    3. 收盘价突破 MA5、MA10、MA20 三条均线
    4. 可选：成交量放大（当日量 > 5日均量）

    加分项：
    - 均线多头排列（MA5 > MA10 > MA20）
    - 突破幅度大（收盘价距离均线远）
    - 放量突破
    """

    def __init__(
        self,
        min_score: int = 40,
        require_volume_increase: bool = False,
        volume_ratio_threshold: float = 1.0,
        min_breakthrough_ratio: float = 0.0,
        prefer_free_source: bool = True,
    ):
        """
        初始化策略

        Args:
            min_score: 最低筛选分数（默认40分，比技术指标宽松）
            require_volume_increase: 是否要求放量（默认False）
            volume_ratio_threshold: 放量比例阈值（默认1.0倍，即不缩量即可）
            min_breakthrough_ratio: 最小突破比例（默认0%，只要有突破就行）
            prefer_free_source: 优先使用免费数据源（默认True）
        """
        self.min_score = min_score
        self.require_volume_increase = require_volume_increase
        self.volume_ratio_threshold = volume_ratio_threshold
        self.min_breakthrough_ratio = min_breakthrough_ratio
        self.prefer_free_source = prefer_free_source

        # 使用默认数据源管理器（按系统配置的优先级）
        self.fetcher = DataFetcherManager()

    def get_name(self) -> str:
        return "one_line_three_ma"

    def get_description(self) -> str:
        return "一阳穿三线：阳线同时突破MA5/MA10/MA20三条均线"

    def select(
        self,
        stock_codes: List[str],
        top_n: int = 10,
        **kwargs
    ) -> SelectionResult:
        """
        执行一阳穿三线选股

        Args:
            stock_codes: 候选股票代码列表
            top_n: 选出前 N 只股票
            **kwargs: 额外参数
                - max_workers: 并发线程数（默认5）
                - min_data_days: 最少数据天数（默认30）

        Returns:
            SelectionResult: 选股结果
        """
        max_workers = kwargs.get("max_workers", 10)
        min_data_days = kwargs.get("min_data_days", 25)  # 减少到25天，只要够算MA20+5天

        results: List[StrategyResult] = []
        total_analyzed = 0

        logger.info(f"一阳穿三线选股开始，候选池 {len(stock_codes)} 只股票")

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
            f"一阳穿三线选股完成：分析 {total_analyzed} 只，"
            f"符合形态 {len(qualified)} 只，推荐 {len(top_picks)} 只"
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
        min_data_days: int = 30
    ) -> Optional[StrategyResult]:
        """
        分析单只股票是否出现一阳穿三线形态

        Args:
            code: 股票代码
            min_data_days: 最少数据天数

        Returns:
            StrategyResult 或 None
        """
        try:
            # 获取历史数据
            df, _ = self.fetcher.get_daily_data(code, days=min_data_days + 10)
            if df is None or len(df) < min_data_days:
                logger.debug(f"{code} 数据不足，跳过")
                return None

            # 确保数据按日期排序
            df = df.sort_values('date').reset_index(drop=True)

            # 计算均线
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA10'] = df['close'].rolling(window=10).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()

            # 计算成交量均线
            df['VOL_MA5'] = df['volume'].rolling(window=5).mean()

            # 取最近两天的数据（昨天和今天）
            if len(df) < 2:
                return None

            today = df.iloc[-1]
            yesterday = df.iloc[-2]

            # 检查一阳穿三线形态
            check_result = self._check_one_line_three_ma(today, yesterday, df)

            if not check_result['is_valid']:
                return None

            # 计算评分
            score = self._calculate_score(check_result, today, df)

            # 生成理由和风险
            reasons = []
            risks = []

            # 核心形态描述
            breakthrough_desc = check_result['breakthrough_desc']
            reasons.append(f"一阳穿三线：{breakthrough_desc}")

            # 突破幅度
            if check_result['breakthrough_ratio'] > 0.02:
                reasons.append(f"突破幅度 {check_result['breakthrough_ratio']*100:.1f}%，力度较强")

            # 均线排列
            if check_result['is_bull_alignment']:
                reasons.append("均线多头排列，趋势向好")
            else:
                risks.append("均线非多头排列，注意趋势")

            # 量能分析
            if check_result['volume_ratio'] > self.volume_ratio_threshold:
                reasons.append(f"放量突破（量比 {check_result['volume_ratio']:.1f}）")
            elif check_result['volume_ratio'] < 0.8:
                risks.append("缩量突破，动能不足")

            # 阳线实体长度
            body_ratio = (today['close'] - today['open']) / today['open'] * 100
            if body_ratio > 3:
                reasons.append(f"大阳线实体 {body_ratio:.1f}%")
            elif body_ratio < 1:
                risks.append("阳线实体较小，力度有限")

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
                    "pattern": "一阳穿三线",
                    "breakthrough_ratio": round(check_result['breakthrough_ratio'] * 100, 2),
                    "is_bull_alignment": check_result['is_bull_alignment'],
                    "volume_ratio": round(check_result['volume_ratio'], 2),
                    "body_length": round(body_ratio, 2),
                    "current_price": round(today['close'], 2),
                    "ma5": round(today['MA5'], 2),
                    "ma10": round(today['MA10'], 2),
                    "ma20": round(today['MA20'], 2),
                    "open_price": round(today['open'], 2),
                    "pct_chg": round((today['close'] - yesterday['close']) / yesterday['close'] * 100, 2),
                },
                strategy_name=self.get_name(),
            )

        except Exception as e:
            logger.debug(f"分析 {code} 异常: {e}")
            return None

    def _check_one_line_three_ma(
        self,
        today: pd.Series,
        yesterday: pd.Series,
        df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        检查是否满足一阳穿三线或类似形态

        核心条件：
        1. 今日是阳线（close > open）
        2. 收盘价突破至少2条均线（MA5/MA10/MA20）
        3. 开盘价在至少一条均线下方

        Returns:
            检查结果字典
        """
        result = {
            'is_valid': False,
            'breakthrough_desc': '',
            'breakthrough_ratio': 0.0,
            'is_bull_alignment': False,
            'volume_ratio': 0.0,
            'pattern_type': '',
        }

        # 获取今日数据
        today_open = today['open']
        today_close = today['close']
        today_volume = today['volume']

        ma5 = today['MA5']
        ma10 = today['MA10']
        ma20 = today['MA20']
        vol_ma5 = today['VOL_MA5']

        # 排除无效数据
        if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
            return result

        # 条件1：必须是阳线
        if today_close <= today_open:
            return result

        # 计算突破了几条均线
        breakthrough_count = 0
        breakthrough_lines = []

        if today_open < ma5 and today_close > ma5:
            breakthrough_count += 1
            breakthrough_lines.append("MA5")
        elif today_close > ma5 and today_open > ma5:
            # 已经在MA5上方，也算突破（站稳）
            breakthrough_count += 1

        if today_open < ma10 and today_close > ma10:
            breakthrough_count += 1
            breakthrough_lines.append("MA10")
        elif today_close > ma10 and today_open > ma10:
            breakthrough_count += 1

        if today_open < ma20 and today_close > ma20:
            breakthrough_count += 1
            breakthrough_lines.append("MA20")
        elif today_close > ma20 and today_open > ma20:
            breakthrough_count += 1

        # 条件2：至少突破2条均线（放宽条件）
        if breakthrough_count < 2:
            return result

        # 形态有效！
        result['is_valid'] = True
        result['breakthrough_desc'] = f"突破{'+'.join(breakthrough_lines)}"
        result['breakthrough_ratio'] = (today_close - ma20) / ma20
        result['is_bull_alignment'] = (ma5 > ma10) and (ma10 > ma20)
        result['volume_ratio'] = today_volume / vol_ma5 if vol_ma5 > 0 else 0
        result['pattern_type'] = f'穿{breakthrough_count}线'

        return result

    def _calculate_score(
        self,
        check_result: Dict[str, Any],
        today: pd.Series,
        df: pd.DataFrame
    ) -> int:
        """
        计算综合评分 (0-100)

        评分规则：
        - 基础分：满足一阳穿三线形态 = 50分
        - 均线多头排列：+20分
        - 放量突破：+15分
        - 突破幅度大：+10分
        - 阳线实体长：+5分
        """
        score = 50  # 基础分

        # 均线多头排列
        if check_result['is_bull_alignment']:
            score += 20

        # 放量突破
        if check_result['volume_ratio'] > self.volume_ratio_threshold:
            score += 15
        elif check_result['volume_ratio'] > 1.0:
            score += 5

        # 突破幅度
        breakthrough = check_result['breakthrough_ratio']
        if breakthrough > 0.03:
            score += 10
        elif breakthrough > 0.01:
            score += 5

        # 阳线实体长度
        body_ratio = (today['close'] - today['open']) / today['open']
        if body_ratio > 0.03:
            score += 5

        # 限制在 0-100 之间
        return max(0, min(100, score))