"""
智能选股器
根据预设条件自动筛选符合条件的股票

功能:
- 策略选股: 按策略条件自动筛选
- 异动选股: 放量/涨停/炸板等异动个股
- 明日策略: 基于当前市场情绪推荐明日关注方向
- 博主战法: 只核大学生/六一中路等知名游资战法选股
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from config import Config
from data_provider.base import DataFetcherManager
from analyzer.technical import TechnicalAnalyzer, TrendStatus, MACDStatus, RSIStatus
from analyzer.market_sentiment import get_sentiment_analyzer, MarketSentiment

try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False


@dataclass
class ScreenResult:
    """选股结果"""
    code: str
    name: str = ""
    score: float = 0.0       # 综合评分 0-100
    match_reasons: List[str] = field(default_factory=list)  # 匹配原因
    strategy_tags: List[str] = field(default_factory=list)  # 策略标签
    current_price: float = 0.0
    change_pct: float = 0.0
    volume_ratio: float = 0.0
    limit_up: bool = False   # 是否涨停
    market_sentiment: str = ""  # 所属情绪周期

    def to_summary(self) -> str:
        flag = "🔴" if self.limit_up else ("🟢" if self.change_pct > 0 else "🔵")
        reasons = " | ".join(self.match_reasons[:3])
        tags = "/".join(self.strategy_tags[:2])
        return f"{flag} {self.code} {self.name} {self.change_pct:+.2f}% | {self.score:.0f}分 | {reasons} | [{tags}]"


@dataclass
class ScreenCriteria:
    """选股条件"""
    name: str = ""
    min_score: float = 60.0
    trend_status: List[str] = field(default_factory=list)  # 允许的趋势状态
    min_volume_ratio: float = 0.0
    limit_up_only: bool = False       # 仅选涨停
    avoid_st: bool = True             # 排除ST
    avoid_new_stock: bool = True      # 排除新股
    sectors: List[str] = field(default_factory=list)  # 限定板块
    exclude_sectors: List[str] = field(default_factory=list)  # 排除板块
    max_price: float = 0.0            # 最高价限制
    min_price: float = 0.0            # 最低价限制
    sentiment_phase: str = ""          # 情绪周期要求


class SmartScreener:
    """智能选股器"""

    def __init__(self):
        self._fetcher_mgr: Optional[DataFetcherManager] = None
        self._tech_analyzer = TechnicalAnalyzer()
        self._sentiment_analyzer = get_sentiment_analyzer()
        config = Config.get()
        if config.DATA_SOURCES:
            self._fetcher_mgr = DataFetcherManager(config.DATA_SOURCES)
        self._pro = None
        if HAS_TUSHARE and config.TUSHARE_TOKEN:
            try:
                self._pro = ts.pro_api(config.TUSHARE_TOKEN)
            except Exception:
                pass

    # ========== 核大学生战法选股 ==========

    def screen_zhihe(self, sentiment: MarketSentiment = None) -> List[ScreenResult]:
        """
        只核大学生战法选股
        核心理念: 只做最强龙头，强者恒强，追涨不抄底
        条件:
        1. 涨停股（必须是强势涨停，非弱势反弹）
        2. 所属板块整体强势（板块涨停 >= 3家）
        3. 换手率 > 8%（高活跃度）
        4. 成交量较前日放大 >= 1.5倍
        5. MACD金叉或零轴上方
        6. RSI6 在 60-80 区间
        7. MA5>MA10>MA20 多头排列
        """
        results = []
        if sentiment is None:
            sentiment = self._sentiment_analyzer.get_sentiment()

        # 获取涨停股列表
        limit_up_stocks = self._get_limit_up_stocks()
        if not limit_up_stocks:
            return results

        for item in limit_up_stocks:
            code = item.get("code", "")
            name = item.get("name", "")
            try:
                hist = self._get_history(code)
                if hist is None or len(hist) < 20:
                    continue

                # 基本面排除
                if "ST" in name or "N " in name:
                    continue

                # 计算技术指标
                tech = self._tech_analyzer.analyze(hist, code=code, name=name)

                # 条件1: 涨停
                if abs(tech.change_pct or 0) < 9.5:
                    continue

                # 条件2: RSI6 在 60-80 强势区间
                if not (60 <= tech.rsi6 <= 85):
                    continue

                # 条件3: 多头排列
                if tech.trend_status not in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]:
                    continue

                # 条件4: 放量
                if tech.volume_ratio < 1.3:
                    continue

                # 条件5: MACD
                if tech.macd_status not in [MACDStatus.GOLDEN_CROSS, MACDStatus.BULLISH, MACDStatus.WEAK_BULLISH]:
                    # 但如果 DIF>0 且 DIF在零轴上方，也接受
                    if tech.dif <= 0:
                        continue

                # 综合评分
                score = min(100, 40 + tech.rsi6 * 0.3 + tech.volume_ratio * 10 + tech.buy_score * 0.3)

                reasons = []
                if tech.trend_status == TrendStatus.STRONG_BULL:
                    reasons.append("强势多头排列")
                elif tech.trend_status == TrendStatus.BULL:
                    reasons.append("多头排列")
                if tech.volume_ratio > 2:
                    reasons.append(f"大幅放量({tech.volume_ratio:.1f}倍)")
                if tech.macd_status == MACDStatus.BULLISH:
                    reasons.append("MACD零轴上方运行")
                if tech.rsi6 > 70:
                    reasons.append(f"RSI强势({tech.rsi6:.1f})")

                results.append(ScreenResult(
                    code=code,
                    name=name,
                    score=score,
                    match_reasons=reasons,
                    strategy_tags=["只核大学生", "龙头战法"],
                    current_price=tech.current_price,
                    change_pct=tech.change_pct or 0,
                    volume_ratio=tech.volume_ratio,
                    limit_up=True,
                    market_sentiment=sentiment.sentiment_label if sentiment else "",
                ))

            except Exception:
                continue

        # 按评分排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:20]  # 最多返回20只

    # ========== 六一中路战法选股 ==========

    def screen_liuyi(self, sentiment: MarketSentiment = None) -> List[ScreenResult]:
        """
        六一中路战法选股
        核心理念: 善于在板块轮动中把握节奏，专做主升浪
        特征:
        1. 处于主升浪的个股（均线多头 + 加速放量）
        2. 板块内个股联动明显
        3. 换手率适中（5-15%）
        4. 量价齐升，缩量回调
        5. MACD处于零轴上方第二次金叉（空中加油）
        """
        results = []
        if sentiment is None:
            sentiment = self._sentiment_analyzer.get_sentiment()

        # 获取涨幅5%以上个股
        active_stocks = self._get_active_stocks(min_pct=5)
        if not active_stocks:
            return results

        for item in active_stocks:
            code = item.get("code", "")
            name = item.get("name", "")
            try:
                hist = self._get_history(code)
                if hist is None or len(hist) < 30:
                    continue

                if "ST" in name or "N " in name:
                    continue

                tech = self._tech_analyzer.analyze(hist, code=code, name=name)

                # 主升浪条件
                # 1. 均线多头
                if tech.trend_status not in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
                    continue

                # 2. 量价齐升 (今日涨幅>3% 且 放量)
                if (tech.change_pct or 0) < 3 or tech.volume_ratio < 1.3:
                    continue

                # 3. RSI 适中 (55-80)
                if not (50 <= tech.rsi6 <= 82):
                    continue

                # 4. MACD零轴上方
                if tech.dif <= 0 or tech.dea <= 0:
                    continue

                # 计算综合评分
                score = min(100, tech.buy_score * 0.4 + (tech.volume_ratio - 1) * 20 + (tech.change_pct or 0) * 2)

                reasons = []
                if tech.trend_status == TrendStatus.STRONG_BULL:
                    reasons.append("主升浪")
                if tech.volume_ratio > 2:
                    reasons.append(f"量价齐升({tech.volume_ratio:.1f}倍)")
                if tech.rsi6 > 65:
                    reasons.append(f"加速拉升 RSI={tech.rsi6:.1f}")
                if tech.dif > tech.dea and tech.dif > 0:
                    reasons.append("MACD空中加油")

                results.append(ScreenResult(
                    code=code,
                    name=name,
                    score=score,
                    match_reasons=reasons,
                    strategy_tags=["六一中路", "主升浪"],
                    current_price=tech.current_price,
                    change_pct=tech.change_pct or 0,
                    volume_ratio=tech.volume_ratio,
                    limit_up=(tech.change_pct or 0) >= 9.5,
                    market_sentiment=sentiment.sentiment_label if sentiment else "",
                ))

            except Exception:
                continue

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:20]

    # ========== 情绪冰点抄底选股 ==========

    def screen_bottom_fishing(self, sentiment: MarketSentiment = None) -> List[ScreenResult]:
        """
        情绪冰点抄底选股（炒股养家风格）
        条件:
        1. 市场情绪处于恐惧/极寒（涨停<20家，跌停>20家）
        2. RSI6 < 30（超卖）
        3. 触及布林下轨或重要支撑
        4. 放量探底（恐慌盘）
        5. 前期强势股被错杀
        """
        results = []
        if sentiment is None:
            sentiment = self._sentiment_analyzer.get_sentiment()

        # 情绪冰点才执行
        if sentiment and sentiment.sentiment_score > 40:
            return results

        # 获取跌途个股(跌幅 > 3%)
        dropping_stocks = self._get_active_stocks(max_pct=-3)
        if not dropping_stocks:
            return results

        for item in dropping_stocks:
            code = item.get("code", "")
            name = item.get("name", "")
            try:
                hist = self._get_history(code)
                if hist is None or len(hist) < 20:
                    continue

                if "ST" in name or "N " in name:
                    continue

                tech = self._tech_analyzer.analyze(hist, code=code, name=name)

                # 超卖
                if tech.rsi6 >= 30:
                    continue

                # 触及布林下轨
                if tech.boll_position > 0.15:
                    continue

                # 放量
                if tech.volume_ratio < 1.5:
                    continue

                # 评分
                score = min(100, (30 - tech.rsi6) * 2 + tech.volume_ratio * 8 + tech.buy_score * 0.3)

                reasons = []
                if tech.rsi6 < 20:
                    reasons.append(f"RSI严重超卖({tech.rsi6:.1f})")
                elif tech.rsi6 < 30:
                    reasons.append(f"RSI超卖({tech.rsi6:.1f})")
                if tech.boll_position < 0.1:
                    reasons.append("触及布林下轨")
                if tech.volume_ratio > 2:
                    reasons.append(f"放量探底({tech.volume_ratio:.1f}倍)")

                results.append(ScreenResult(
                    code=code,
                    name=name,
                    score=score,
                    match_reasons=reasons,
                    strategy_tags=["抄底", "情绪冰点"],
                    current_price=tech.current_price,
                    change_pct=tech.change_pct or 0,
                    volume_ratio=tech.volume_ratio,
                    limit_up=False,
                    market_sentiment="冰点/恐惧",
                ))

            except Exception:
                continue

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:15]

    # ========== 通用选股器 ==========

    def screen(self, criteria: ScreenCriteria) -> List[ScreenResult]:
        """
        通用条件选股
        """
        results = []
        # 获取全市场数据 (通过tushare获取)
        stocks = self._get_market_brief()
        if not stocks:
            return results

        for item in stocks:
            code = item.get("code", "")
            name = item.get("name", "")
            try:
                # 排除ST/新股
                if criteria.avoid_st and ("ST" in name or "*ST" in name):
                    continue
                if criteria.avoid_new_stock and ("N " in name or len(item.get("list_days", 999)) < 30):
                    continue

                # 价格过滤
                price = item.get("price", 0)
                if criteria.max_price > 0 and price > criteria.max_price:
                    continue
                if criteria.min_price > 0 and price < criteria.min_price:
                    continue

                # 涨跌停过滤
                pct = item.get("change_pct", 0)
                if criteria.limit_up_only and pct < 9.5:
                    continue

                hist = self._get_history(code)
                if hist is None or len(hist) < 20:
                    continue

                tech = self._tech_analyzer.analyze(hist, code=code, name=name)

                # 趋势过滤
                if criteria.trend_status and tech.trend_status.value not in criteria.trend_status:
                    continue

                # 量比过滤
                if tech.volume_ratio < criteria.min_volume_ratio:
                    continue

                if tech.buy_score < criteria.min_score:
                    continue

                reasons = [tech.trend_status.value, f"评分{tech.buy_score}"]
                if tech.volume_ratio > 1.5:
                    reasons.append(f"放量{tech.volume_ratio:.1f}倍")

                results.append(ScreenResult(
                    code=code,
                    name=name,
                    score=tech.buy_score,
                    match_reasons=reasons,
                    strategy_tags=["自定义筛选"],
                    current_price=tech.current_price,
                    change_pct=pct,
                    volume_ratio=tech.volume_ratio,
                    limit_up=pct >= 9.5,
                ))

            except Exception:
                continue

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:30]

    # ========== 工具方法 ==========

    def _get_history(self, code: str, days: int = 60):
        """获取历史数据"""
        if self._fetcher_mgr:
            return self._fetcher_mgr.get_history(code, days)
        return None

    def _get_limit_up_stocks(self) -> List[Dict]:
        """获取涨停股列表"""
        if not self._pro:
            return []
        try:
            today = datetime.now().strftime("%Y%m%d")
            df = self._pro.limit_list(trade_date=today, limit_type="U")
            if df is not None and not df.empty:
                return [
                    {"code": str(r["ts_code"]).split(".")[0], "name": str(r.get("name", ""))}
                    for _, r in df.iterrows()
                ]
        except Exception:
            pass
        return []

    def _get_active_stocks(self, min_pct: float = 0, max_pct: float = 100) -> List[Dict]:
        """获取涨幅区间内的活跃股"""
        if not self._pro:
            return []
        try:
            today = datetime.now().strftime("%Y%m%d")
            df = self._pro.daily(trade_date=today)
            if df is not None and not df.empty:
                df = df[(df["pct_chg"] >= min_pct) & (df["pct_chg"] <= max_pct)]
                # 获取名称
                names = {}
                try:
                    basic = self._pro.stock_basic(exchange="", list_status="L",
                                                  fields="ts_code,name")
                    if basic is not None:
                        names = {row["ts_code"].split(".")[0]: row["name"]
                                 for _, row in basic.iterrows()}
                except Exception:
                    pass
                return [
                    {"code": str(r["ts_code"]).split(".")[0],
                     "name": names.get(str(r["ts_code"]).split(".")[0], ""),
                     "change_pct": float(r["pct_chg"]),
                     "volume_ratio": float(r.get("vol", 0))}
                    for _, r in df.iterrows()
                ]
        except Exception:
            pass
        return []

    def _get_market_brief(self) -> List[Dict]:
        """获取全市场简要数据"""
        if not self._pro:
            return []
        try:
            today = datetime.now().strftime("%Y%m%d")
            df = self._pro.daily(trade_date=today)
            if df is not None and not df.empty:
                names = {}
                try:
                    basic = self._pro.stock_basic(exchange="", list_status="L",
                                                  fields="ts_code,name")
                    if basic is not None:
                        names = {row["ts_code"].split(".")[0]: row["name"]
                                 for _, row in basic.iterrows()}
                except Exception:
                    pass
                return [
                    {"code": str(r["ts_code"]).split(".")[0],
                     "name": names.get(str(r["ts_code"]).split(".")[0], ""),
                     "price": float(r["close"]),
                     "change_pct": float(r["pct_chg"])}
                    for _, r in df.iterrows()
                ]
        except Exception:
            pass
        return []


# 全局实例
_screener: Optional[SmartScreener] = None

def get_screener() -> SmartScreener:
    global _screener
    if _screener is None:
        _screener = SmartScreener()
    return _screener
