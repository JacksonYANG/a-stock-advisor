"""
市场状态识别模块
根据大盘指数走势判断当前市场状态（牛市/熊市/震荡/反弹/回调）
不同状态使用不同的策略权重和仓位上限
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field
from enum import Enum


class MarketRegime(Enum):
    """市场状态"""
    BULL = "牛市"
    BEAR = "熊市"
    SIDEWAYS = "震荡市"
    RECOVERY = "反弹"
    CORRECTION = "回调"


@dataclass
class RegimeResult:
    """市场状态识别结果"""
    regime: MarketRegime = MarketRegime.SIDEWAYS
    confidence: float = 0.0      # 0.0-1.0
    description: str = ""
    suggested_strategy: str = "balanced"
    position_cap: float = 0.5    # 建议最大仓位
    score_adjust: int = 0        # 评分调整
    indices_status: Dict[str, dict] = field(default_factory=dict)


# 各状态对应的策略参数
REGIME_WEIGHTS = {
    MarketRegime.BULL: {
        "position_cap": 0.8,
        "score_adjust": +5,
        "suggested_strategy": "aggressive",
        "stop_loss_wider": True,
    },
    MarketRegime.BEAR: {
        "position_cap": 0.2,
        "score_adjust": -10,
        "suggested_strategy": "defensive",
        "stop_loss_wider": False,
    },
    MarketRegime.SIDEWAYS: {
        "position_cap": 0.5,
        "score_adjust": 0,
        "suggested_strategy": "balanced",
        "stop_loss_wider": False,
    },
    MarketRegime.RECOVERY: {
        "position_cap": 0.6,
        "score_adjust": +3,
        "suggested_strategy": "balanced-aggressive",
        "stop_loss_wider": True,
    },
    MarketRegime.CORRECTION: {
        "position_cap": 0.3,
        "score_adjust": -5,
        "suggested_strategy": "cautious",
        "stop_loss_wider": False,
    },
}

# 大盘指数代码
MARKET_INDICES = {
    "上证指数": "sh.000001",
    "深证成指": "sz.399001",
    "创业板指": "sz.399006",
}


def _analyze_index(df: pd.DataFrame) -> dict:
    """分析单个指数的技术状态"""
    if df is None or len(df) < 30:
        return {"trend": "unknown", "macd": "unknown", "position": "unknown", "bullish": False}

    close = df["close"]

    # 均线
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else close.mean()
    price = float(close.iloc[-1])

    # 趋势判断
    if ma5 > ma10 > ma20:
        trend = "bull"
    elif ma5 < ma10 < ma20:
        trend = "bear"
    else:
        trend = "neutral"

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()

    dif_val = float(dif.iloc[-1])
    dea_val = float(dea.iloc[-1])
    prev_dif = float(dif.iloc[-2]) if len(dif) >= 2 else dif_val
    prev_dea = float(dea.iloc[-2]) if len(dea) >= 2 else dea_val

    if prev_dif <= prev_dea and dif_val > dea_val:
        macd = "golden_cross"
    elif prev_dif >= prev_dea and dif_val < dea_val:
        macd = "death_cross"
    elif dif_val > dea_val:
        macd = "bullish"
    else:
        macd = "bearish"

    # 价格位置（相对MA60）
    if price > ma60 * 1.05:
        position = "above"
    elif price < ma60 * 0.95:
        position = "below"
    else:
        position = "near"

    bullish = trend == "bull" and macd in ("golden_cross", "bullish")
    bearish = trend == "bear" and macd in ("death_cross", "bearish")

    return {
        "trend": trend,
        "macd": macd,
        "position": position,
        "price": price,
        "ma60": ma60,
        "bullish": bullish,
        "bearish": bearish,
    }


class MarketRegimeDetector:
    """市场状态检测器"""

    def __init__(self, manager=None):
        self._manager = manager

    def detect(self) -> RegimeResult:
        """
        检测当前市场状态

        Returns:
            RegimeResult
        """
        result = RegimeResult()

        # 直接用 baostock 获取指数数据（绕过 DataFetcherManager 的代码规范化问题）
        index_results = {}
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                for name, code in MARKET_INDICES.items():
                    try:
                        rs = bs.query_history_k_data_plus(
                            code,
                            "date,close",
                            start_date=(pd.Timestamp.now() - pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
                            end_date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                            frequency="d",
                        )
                        rows = []
                        while (rs.error_code == '0') and rs.next():
                            rows.append(rs.get_row_data())
                        if rows:
                            df = pd.DataFrame(rows, columns=["date", "close"])
                            df["close"] = pd.to_numeric(df["close"], errors="coerce")
                            df = df.dropna()
                            if len(df) >= 30:
                                index_results[name] = _analyze_index(df)
                    except Exception:
                        pass
                bs.logout()
        except Exception:
            # fallback: 用 DataFetcherManager
            if not self._manager:
                try:
                    from config import Config
                    from data_provider.base import DataFetcherManager
                    self._manager = DataFetcherManager()
                    self._manager.register_sources(Config.get().DATA_SOURCES)
                except Exception:
                    return result

            for name, code in MARKET_INDICES.items():
                try:
                    hist = self._manager.get_history(code, 90)
                    if hist is not None and not hist.empty:
                        index_results[name] = _analyze_index(hist)
                except Exception:
                    pass

        if not index_results:
            return result

        result.indices_status = index_results

        # 统计多空
        bullish_count = sum(1 for v in index_results.values() if v.get("bullish"))
        bearish_count = sum(1 for v in index_results.values() if v.get("bearish"))
        above_ma60 = sum(1 for v in index_results.values() if v.get("position") == "above")
        below_ma60 = sum(1 for v in index_results.values() if v.get("position") == "below")
        total = len(index_results)

        # 判断市场状态
        if bullish_count >= 2:
            result.regime = MarketRegime.BULL
            result.confidence = min(1.0, bullish_count / total + 0.2)
            result.description = f"大盘多头排列，{bullish_count}/{total}个指数看多"
        elif bearish_count >= 2:
            result.regime = MarketRegime.BEAR
            result.confidence = min(1.0, bearish_count / total + 0.2)
            result.description = f"大盘空头排列，{bearish_count}/{total}个指数看空"
        elif above_ma60 >= 2:
            # 价格在MA60上方但短期偏弱 → 回调
            weak_count = sum(1 for v in index_results.values() if v.get("trend") == "bear" or v.get("macd") == "death_cross")
            if weak_count >= 1:
                result.regime = MarketRegime.CORRECTION
                result.confidence = 0.5 + 0.1 * weak_count
                result.description = f"高位回调中，{weak_count}个指数转弱"
            else:
                result.regime = MarketRegime.SIDEWAYS
                result.confidence = 0.4
                result.description = "MA60上方震荡，方向不明"
        elif below_ma60 >= 2:
            # 价格在MA60下方但短期转强 → 反弹
            strong_count = sum(1 for v in index_results.values() if v.get("trend") == "bull" or v.get("macd") == "golden_cross")
            if strong_count >= 1:
                result.regime = MarketRegime.RECOVERY
                result.confidence = 0.5 + 0.1 * strong_count
                result.description = f"低位反弹中，{strong_count}个指数转强"
            else:
                result.regime = MarketRegime.SIDEWAYS
                result.confidence = 0.4
                result.description = "MA60下方震荡，方向不明"
        else:
            result.regime = MarketRegime.SIDEWAYS
            result.confidence = 0.3
            result.description = "多空交织，方向不明"

        # 应用策略权重
        weights = REGIME_WEIGHTS.get(result.regime, REGIME_WEIGHTS[MarketRegime.SIDEWAYS])
        result.position_cap = weights["position_cap"]
        result.score_adjust = weights["score_adjust"]
        result.suggested_strategy = weights["suggested_strategy"]

        return result

    @staticmethod
    def adjust_score(buy_score: int, regime: MarketRegime) -> int:
        """根据市场状态调整评分"""
        weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS[MarketRegime.SIDEWAYS])
        return max(0, min(100, buy_score + weights["score_adjust"]))

    def format_regime_line(self, regime_result: RegimeResult) -> str:
        """格式化为一行市场状态文本（追加到仪表盘）"""
        regime_emoji = {
            MarketRegime.BULL: "🐂",
            MarketRegime.BEAR: "🐻",
            MarketRegime.SIDEWAYS: "↔️",
            MarketRegime.RECOVERY: "📈",
            MarketRegime.CORRECTION: "📉",
        }
        emoji = regime_emoji.get(regime_result.regime, "📊")
        return (
            f"{emoji} 市场状态: {regime_result.regime.value}"
            f"(信心{regime_result.confidence:.0%})"
            f" | 策略: {regime_result.suggested_strategy}"
            f" | 仓位≤{regime_result.position_cap:.0%}"
        )
