# -*- coding: utf-8 -*-
"""
股票选股引擎

整合多种选股策略，提供统一的选股接口：
1. 技术指标筛选
2. 板块轮动筛选
3. AI智能选股

使用方式：
    from src.stock_selector import StockSelector

    selector = StockSelector()
    result = selector.run_selection(
        candidate_pool=["600519", "000001", ...],
        top_n=10,
        strategies=["technical"]
    )
"""

import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Union

from src.config import get_config, Config
from src.selector_strategies.base import SelectionResult, StrategyResult
from src.selector_strategies.technical import TechnicalStrategy
from src.selector_strategies.one_line_three_ma import OneLineThreeMAStrategy
from src.notification import NotificationService
from src.analyzer import STOCK_NAME_MAP

logger = logging.getLogger(__name__)


class StockSelector:
    """
    股票选股引擎

    整合多种选股策略，支持：
    - 多策略组合筛选
    - 综合评分排序
    - 结果推送通知
    """

    AVAILABLE_STRATEGIES = {
        "technical": TechnicalStrategy,
        "one_line_three_ma": OneLineThreeMAStrategy,
        "one_line": OneLineThreeMAStrategy,  # 别名
        "onelinethree_ma": OneLineThreeMAStrategy,  # 别名（无下划线）
        "oneline": OneLineThreeMAStrategy,  # 别名（更短）
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategies: Optional[List[str]] = None,
    ):
        """
        初始化选股引擎

        Args:
            config: 配置对象（默认使用全局配置）
            strategies: 启用的策略列表（默认 ["technical"]）
        """
        self.config = config or get_config()
        self.strategies = strategies or ["technical"]
        self.notifier = NotificationService()

        # 初始化策略实例
        self._strategy_instances: Dict[str, Any] = {}
        for strategy_name in self.strategies:
            if strategy_name in self.AVAILABLE_STRATEGIES:
                self._strategy_instances[strategy_name] = self.AVAILABLE_STRATEGIES[strategy_name]()
                logger.info(f"已加载策略: {strategy_name}")
            else:
                logger.warning(f"未知策略: {strategy_name}")

    def run_selection(
        self,
        candidate_pool: Optional[List[str]] = None,
        top_n: int = 10,
        strategies: Optional[List[str]] = None,
        **kwargs
    ) -> SelectionResult:
        """
        执行选股

        Args:
            candidate_pool: 候选股票池（默认从配置读取）
            top_n: 选出前 N 只股票
            strategies: 本次使用的策略（默认使用初始化时的策略）
            **kwargs: 策略参数
                - max_workers: 并发线程数
                - min_data_days: 最少数据天数

        Returns:
            SelectionResult: 选股结果
        """
        # 获取候选池
        if candidate_pool is None:
            candidate_pool = self._load_candidate_pool()

        if not candidate_pool:
            logger.warning("候选股票池为空，无法执行选股")
            return SelectionResult(
                candidate_pool_size=0,
                total_analyzed=0,
                selected_count=0,
                results=[],
                top_picks=[],
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategy_names=self.strategies,
            )

        # 确定使用的策略
        active_strategies = strategies or self.strategies

        # 执行各策略选股
        all_results: List[StrategyResult] = []
        strategy_names_used: List[str] = []
        candidate_pool_size = len(candidate_pool)

        for strategy_name in active_strategies:
            if strategy_name not in self._strategy_instances:
                logger.warning(f"策略 {strategy_name} 未初始化，跳过")
                continue

            strategy = self._strategy_instances[strategy_name]
            logger.info(f"执行策略: {strategy_name}")

            try:
                result = strategy.select(
                    stock_codes=candidate_pool,
                    top_n=top_n,
                    **kwargs
                )

                all_results.extend(result.results)
                strategy_names_used.append(strategy_name)

                # 如果只有一个策略，直接返回
                if len(active_strategies) == 1:
                    return result

            except Exception as e:
                logger.error(f"策略 {strategy_name} 执行失败: {e}")

        # 多策略合并结果
        merged_result = self._merge_results(
            all_results=all_results,
            strategy_names=strategy_names_used,
            top_n=top_n
        )

        return merged_result

    def _merge_results(
        self,
        all_results: List[StrategyResult],
        strategy_names: List[str],
        top_n: int
    ) -> SelectionResult:
        """
        合并多策略结果

        Args:
            all_results: 所有策略的分析结果
            strategy_names: 使用的策略名称
            top_n: 选出前 N 只

        Returns:
            SelectionResult: 合并后的选股结果
        """
        # 按股票代码聚合评分
        code_scores: Dict[str, StrategyResult] = {}

        for result in all_results:
            code = result.code
            if code not in code_scores:
                code_scores[code] = result
            else:
                # 多策略时取平均分
                existing = code_scores[code]
                avg_score = (existing.score + result.score) / 2
                existing.score = int(avg_score)
                existing.reasons.extend(result.reasons)
                existing.risks.extend(result.risks)
                existing.strategy_name = "merged"

        # 按分数排序
        sorted_results = sorted(
            code_scores.values(),
            key=lambda x: x.score,
            reverse=True
        )

        # 取前 top_n
        top_picks = sorted_results[:top_n]

        # 统计合格数量（分数 >= 60）
        qualified = [r for r in sorted_results if r.score >= 60]

        return SelectionResult(
            candidate_pool_size=candidate_pool_size,
            total_analyzed=total_analyzed,
            selected_count=len(top_picks),
            results=results,
            top_picks=top_picks,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            strategy_names=[self.get_name()],
        )

    def _load_candidate_pool(self) -> List[str]:
        """
        加载候选股票池

        支持来源：
        1. 环境变量 CANDIDATE_POOL（逗号分隔）
        2. 文件 candidate_pool.txt（每行一个代码）
        3. 配置文件 candidate_pool 字段
        4. 默认候选池（主板龙头股）

        Returns:
            股票代码列表
        """
        candidate_pool: List[str] = []

        # 1. 环境变量
        env_pool = os.getenv("CANDIDATE_POOL", "")
        if env_pool:
            candidate_pool.extend([
                c.strip().upper() for c in env_pool.split(",")
                if c.strip()
            ])

        # 2. 配置字段
        config_pool = getattr(self.config, "candidate_pool", [])
        if config_pool:
            candidate_pool.extend([
                c.strip().upper() for c in config_pool
                if c.strip() and c.strip().upper() not in candidate_pool
            ])

        # 3. 文件
        pool_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "candidate_pool.txt"
        )
        if os.path.exists(pool_file):
            try:
                with open(pool_file, "r", encoding="utf-8") as f:
                    file_codes = [
                        line.strip().upper()
                        for line in f
                        if line.strip() and not line.startswith("#")
                    ]
                    candidate_pool.extend([
                        c for c in file_codes
                        if c not in candidate_pool
                    ])
                logger.info(f"从文件加载候选池: {len(file_codes)} 只")
            except Exception as e:
                logger.warning(f"读取候选池文件失败: {e}")

        # 4. 默认候选池（主板龙头股，排除创业板）
        if not candidate_pool:
            candidate_pool = self._get_default_candidate_pool()
            logger.info(f"使用默认候选池: {len(candidate_pool)} 只")

        # 去重
        candidate_pool = list(set(candidate_pool))
        logger.info(f"候选股票池: {len(candidate_pool)} 只")

        return candidate_pool

    def _get_default_candidate_pool(self) -> List[str]:
        """
        获取默认候选股票池

        筛选标准：
        - 主板龙头股（排除创业板，降低准入门槛）
        - 流动性好（日均成交额 > 1亿）
        - 基本面稳健（非ST、无退市风险）
        - 覆盖主要行业龙头

        Returns:
            默认候选股票代码列表
        """
        default_pool = [
            # === 白酒 ===
            "600519", "000858", "000568", "600779", "600809",
            "000799", "002304", "603589", "603369", "600197",

            # === 银行 ===
            "600036", "601318", "601166", "600030", "600000",
            "601398", "601939", "601288", "600015", "600048",
            "601988", "601169", "600016", "601818", "002142",

            # === 保险/券商 ===
            "601336", "601628", "600030", "601211", "600837",
            "601688", "000776", "601066", "600958", "600918",

            # === 消费 ===
            "600887", "000895", "000333", "600690", "002507",
            "600104", "603288", "600298", "002568", "603027",
            "605499", "603259", "603345", "002714", "000596",
            "600519", "603517", "603156", "000729", "600559",

            # === 医药 ===
            "600276", "000538", "600332", "600196", "600079",
            "600521", "002411", "600535", "300015", "002007",
            "002294", "600436", "002001", "600211", "603259",
            "600763", "002038", "002304", "600161", "000963",

            # === 新能源/汽车 ===
            "002594", "600104", "601633", "601238", "000625",
            "600418", "601127", "000800", "000957", "600733",
            "601012", "603799", "601899", "600547", "002460",
            "601899", "002176", "002466", "002812", "603659",

            # === 科技/电子 ===
            "002415", "002475", "600588", "000725", "002049",
            "603986", "601138", "002008", "600570", "002230",
            "002456", "603019", "002414", "600745", "002600",
            "603228", "002916", "002841", "603160", "002920",

            # === 资源/化工 ===
            "600028", "601088", "600309", "601899", "600547",
            "000792", "600486", "601225", "601666", "600997",
            "600188", "600348", "601699", "600019", "600971",
            "601168", "601117", "600096", "002493", "600585",

            # === 地产基建 ===
            "600048", "601668", "600000", "000002", "601186",
            "601618", "600068", "601117", "600585", "600820",
            "601669", "601800", "601390", "600376", "001979",

            # === 公用事业 ===
            "600900", "600011", "601985", "600674", "600886",
            "600027", "601016", "003816", "600795", "600905",

            # === 其他优质 ===
            "601766", "601360", "000001", "601857", "600029",
            "601919", "600050", "600031", "601179", "600893",
            "601727", "601111", "000100", "601211", "600025",
            "600699", "002027", "002555", "002624", "603260",
            "600703", "002463", "002236", "002180", "002714",
            "600705", "603712", "002714", "002049", "600563",
        ]

        # 去重
        return list(set(default_pool))

    def generate_report(self, result: SelectionResult) -> str:
        """
        生成选股报告（决策仪表盘风格）

        Args:
            result: 选股结果

        Returns:
            Markdown 格式的报告
        """
        from datetime import datetime

        lines = []

        # 统计信号分布
        from src.selector_strategies.base import SignalStrength
        strong_buy_count = sum(1 for r in result.top_picks if r.signal == SignalStrength.STRONG_BUY)
        buy_count = sum(1 for r in result.top_picks if r.signal == SignalStrength.BUY)
        hold_count = sum(1 for r in result.top_picks if r.signal == SignalStrength.HOLD)

        lines.extend([
            f"# 🎯 {datetime.now().strftime('%Y-%m-%d')} 盘前选股仪表盘",
            "",
            f"> 候选池 **{result.candidate_pool_size}** 只 | 分析 **{result.total_analyzed}** 只 | 推荐 **{result.selected_count}** 只 | "
            f"🟢强烈买入:{strong_buy_count} 🟡买入:{buy_count} ⚪观望:{hold_count}",
            "",
            f"**选股策略**: {', '.join(result.strategy_names)}",
            "",
            "---",
            "",
        ])

        if not result.top_picks:
            lines.extend([
                "## ⚠️ 今日无推荐",
                "",
                "候选池中暂无符合条件的股票，可能原因：",
                "- 市场整体趋势偏弱",
                "- 多数股票乖离率过高",
                "- 技术指标未触发买入信号",
                "",
                "建议：观望为主，等待更好时机。",
                "",
            ])
        else:
            # 汇总摘要
            lines.extend([
                "## 📊 选股结果摘要",
                "",
            ])
            for pick in result.top_picks:
                name = pick.name or STOCK_NAME_MAP.get(pick.code, f"股票{pick.code}")
                emoji = self._get_signal_emoji(pick.signal)
                score_desc = self._get_score_desc(pick.score)
                reasons_short = pick.reasons[:2] if pick.reasons else ["技术指标筛选"]
                lines.append(
                    f"{emoji} **{name}({pick.code})**: {pick.signal.value} | "
                    f"评分 {pick.score} ({score_desc}) | {', '.join(reasons_short)}"
                )
            lines.extend([
                "",
                "---",
                "",
            ])

            # 逐股详细分析
            for pick in result.top_picks:
                name = pick.name or STOCK_NAME_MAP.get(pick.code, f"股票{pick.code}")
                emoji = self._get_signal_emoji(pick.signal)

                lines.extend([
                    f"## {emoji} {name} ({pick.code})",
                    "",
                ])

                # 评分与信号
                lines.extend([
                    f"**综合评分**: {pick.score} 分 ({self._get_score_desc(pick.score)})",
                    f"**信号强度**: {pick.signal.value}",
                    "",
                ])

                # 选入理由
                if pick.reasons:
                    lines.append("**✅ 选入理由**:")
                    for reason in pick.reasons:
                        lines.append(f"- {reason}")
                    lines.append("")

                # 风险提示
                if pick.risks:
                    lines.append("**⚠️ 风险提示**:")
                    for risk in pick.risks:
                        lines.append(f"- {risk}")
                    lines.append("")

                # 技术指标数据
                if pick.indicators:
                    ind = pick.indicators
                    lines.extend([
                        "### 📊 技术指标",
                        "",
                        f"| 指标 | 数值 | 状态 |",
                        f"|------|------|------|",
                        f"| 当前价格 | ¥{ind.get('current_price', 'N/A')} | - |",
                        f"| 均线排列 | {ind.get('trend_status', 'N/A')} | {self._get_trend_status_desc(ind.get('trend_status', ''))} |",
                        f"| MA5/10/20 | {ind.get('ma5', 'N/A')}/{ind.get('ma10', 'N/A')}/{ind.get('ma20', 'N/A')} | - |",
                        f"| 乖离率(MA5) | {ind.get('bias_ma5', 'N/A')}% | {self._get_bias_desc(ind.get('bias_ma5', 0))} |",
                        f"| MACD | {ind.get('macd_status', 'N/A')} | {self._get_macd_desc(ind.get('macd_status', ''))} |",
                        f"| RSI(6) | {ind.get('rsi_6', 'N/A')} | {self._get_rsi_desc(ind.get('rsi_6', 50))} |",
                        f"| 量能状态 | {ind.get('volume_status', 'N/A')} | - |",
                        "",
                    ])

                lines.extend([
                    "---",
                    "",
                ])

        # 免责声明
        lines.extend([
            "## ⚠️ 免责声明",
            "",
            "本报告仅供参考，不构成投资建议。股市有风险，投资需谨慎。",
            "选股结果基于历史技术指标，不代表未来走势。",
            "",
            f"生成时间: {result.timestamp}",
        ])

        return "\n".join(lines)

    def _get_score_desc(self, score: int) -> str:
        """获取评分描述"""
        if score >= 80:
            return "极佳"
        elif score >= 70:
            return "优秀"
        elif score >= 60:
            return "良好"
        elif score >= 50:
            return "中等"
        else:
            return "较弱"

    def _get_trend_status_desc(self, trend: str) -> str:
        """获取趋势状态描述"""
        if "强势多头" in trend or "多头排列" in trend:
            return "✅ 良好"
        elif "弱势多头" in trend or "盘整" in trend:
            return "🟡 一般"
        elif "空头" in trend:
            return "❌ 较弱"
        return "-"

    def _get_bias_desc(self, bias: float) -> str:
        """获取乖离率描述"""
        try:
            bias_val = float(bias)
            if abs(bias_val) > 5:
                return "⚠️ 偏高"
            elif abs(bias_val) > 3:
                return "🟡 中等"
            else:
                return "✅ 正常"
        except:
            return "-"

    def _get_macd_desc(self, macd: str) -> str:
        """获取MACD状态描述"""
        if "金叉" in macd:
            return "✅ 买入信号"
        elif "多头" in macd:
            return "🟡 多头运行"
        elif "死叉" in macd:
            return "❌ 卖出信号"
        return "-"

    def _get_rsi_desc(self, rsi: float) -> str:
        """获取RSI状态描述"""
        try:
            rsi_val = float(rsi)
            if rsi_val < 30:
                return "✅ 超卖(可能反弹)"
            elif rsi_val < 50:
                return "🟡 弱势区间"
            elif rsi_val < 70:
                return "🟡 强势区间"
            else:
                return "⚠️ 超买(风险)"
        except:
            return "-"

    def _get_signal_emoji(self, signal) -> str:
        """获取信号强度对应的 emoji"""
        from src.selector_strategies.base import SignalStrength
        if signal == SignalStrength.STRONG_BUY:
            return "🟢"
        elif signal == SignalStrength.BUY:
            return "🟡"
        elif signal == SignalStrength.HOLD:
            return "⚪"
        else:
            return "🔴"

    def send_notification(
        self,
        result: SelectionResult,
        send_notification: bool = True
    ) -> bool:
        """
        发送选股结果通知

        Args:
            result: 选股结果
            send_notification: 是否发送通知

        Returns:
            是否发送成功
        """
        if not send_notification:
            return False

        if not self.notifier.is_available():
            logger.warning("通知服务不可用")
            return False

        report = self.generate_report(result)
        success = self.notifier.send(report)

        if success:
            logger.info("选股报告推送成功")
        else:
            logger.warning("选股报告推送失败")

        return success


def run_premarket_selection(
    config: Optional[Config] = None,
    candidate_pool: Optional[List[str]] = None,
    top_n: int = 10,
    strategies: Optional[List[str]] = None,
    send_notification: bool = True,
    **kwargs
) -> SelectionResult:
    """
    执行盘前选股（便捷函数）

    Args:
        config: 配置对象
        candidate_pool: 候选股票池
        top_n: 选出数量
        strategies: 策略列表
        send_notification: 是否推送通知
        **kwargs: 其他参数

    Returns:
        SelectionResult: 选股结果
    """
    selector = StockSelector(
        config=config,
        strategies=strategies
    )

    result = selector.run_selection(
        candidate_pool=candidate_pool,
        top_n=top_n,
        **kwargs
    )

    if send_notification:
        selector.send_notification(result)

    return result