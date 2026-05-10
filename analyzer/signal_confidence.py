"""
多因子信号置信度评分系统
只有当多个指标方向一致（"共振"）时才推送信号，避免单指标误触发。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analyzer.technical import (
    TechnicalResult,
    TrendStatus,
    MACDStatus,
    RSIStatus,
    VolumeStatus,
)


@dataclass
class SignalConfidence:
    """信号置信度结果"""
    code: str
    name: str
    overall_confidence: float  # 0.0-1.0
    signal_type: str  # "strong_buy" / "buy" / "neutral" / "sell" / "strong_sell"
    factor_scores: Dict[str, float]  # each factor's individual score
    aligned_factors: int  # how many factors agree
    total_factors: int  # total factors checked
    resonance_score: float  # 0.0-1.0 how well factors align
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        bar_len = 20
        filled = int(self.resonance_score * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        direction = "🟢" if self.signal_type in ("strong_buy", "buy") else \
                    "🔴" if self.signal_type in ("strong_sell", "sell") else "🟡"
        return (
            f"{direction} {self.code} {self.name} | "
            f"{self.signal_type} | "
            f"置信度={self.overall_confidence:.0%} | "
            f"共振={self.resonance_score:.0%} [{bar}] | "
            f"因子对齐={self.aligned_factors}/{self.total_factors}"
        )


class SignalConfidenceAnalyzer:
    """
    多因子信号置信度分析器

    8 个因子维度:
      1. Trend      (趋势)   — MA 排列
      2. Momentum   (动量)   — MACD
      3. MeanRevert (均值回归) — RSI
      4. Stochastic (随机)   — KDJ
      5. Volatility (波动)   — Bollinger
      6. Volume     (量能)   — 成交量
      7. Bias       (乖离)   — BIAS5
      8. PricePos   (价格位置) — 支撑/压力
    """

    TOTAL_FACTORS = 8

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, tech: TechnicalResult) -> SignalConfidence:
        """从 TechnicalResult 计算信号置信度"""
        factor_scores: Dict[str, float] = {}
        reasons: List[str] = []
        warnings: List[str] = []

        # 1. Trend — MA alignment
        s = self._score_trend(tech)
        factor_scores["trend"] = s
        self._collect_reason(s, f"趋势{tech.trend_status.value}", reasons, warnings)

        # 2. Momentum — MACD
        s = self._score_momentum(tech)
        factor_scores["momentum"] = s
        self._collect_reason(s, f"MACD {tech.macd_status.value}", reasons, warnings)

        # 3. Mean Reversion — RSI
        s = self._score_mean_reversion(tech)
        factor_scores["mean_reversion"] = s
        rsi_label = tech.rsi_status.value
        self._collect_reason(s, f"RSI {rsi_label}({tech.rsi6:.0f})", reasons, warnings)

        # 4. Stochastic — KDJ
        s = self._score_stochastic(tech)
        factor_scores["stochastic"] = s
        self._collect_reason(s, f"KDJ J={tech.j_value:.0f}", reasons, warnings)

        # 5. Volatility — Bollinger
        s = self._score_volatility(tech)
        factor_scores["volatility"] = s
        self._collect_reason(s, f"布林位置{tech.boll_position:.0%}", reasons, warnings)

        # 6. Volume
        s = self._score_volume(tech)
        factor_scores["volume"] = s
        self._collect_reason(s, f"量能{tech.volume_status.value}", reasons, warnings)

        # 7. Bias — BIAS5
        s = self._score_bias(tech)
        factor_scores["bias"] = s
        self._collect_reason(s, f"乖离BIAS5={tech.bias5:.1f}%", reasons, warnings)

        # 8. Price Position — support/resistance
        s = self._score_price_position(tech)
        factor_scores["price_position"] = s
        self._collect_reason(s, "价格位置", reasons, warnings)

        # ------ resonance calculation ------
        positive = sum(1 for v in factor_scores.values() if v > 0)
        negative = sum(1 for v in factor_scores.values() if v < 0)
        net_direction = positive - negative  # >0 bullish, <0 bearish

        # Determine dominant direction
        if net_direction > 0:
            dominant = "buy"
            aligned_factors = positive
            resonance_score = self._normalize_resonance(factor_scores, positive=True)
        elif net_direction < 0:
            dominant = "sell"
            aligned_factors = negative
            resonance_score = self._normalize_resonance(factor_scores, positive=False)
        else:
            dominant = "neutral"
            aligned_factors = max(positive, negative)
            resonance_score = 0.0

        # ------ signal type & confidence thresholds ------
        signal_type, confidence = self._determine_signal(
            dominant, resonance_score, aligned_factors
        )

        return SignalConfidence(
            code=tech.code,
            name=tech.name,
            overall_confidence=confidence,
            signal_type=signal_type,
            factor_scores=factor_scores,
            aligned_factors=aligned_factors,
            total_factors=self.TOTAL_FACTORS,
            resonance_score=resonance_score,
            reasons=reasons,
            warnings=warnings,
        )

    def should_push_signal(self, confidence: SignalConfidence) -> bool:
        """
        是否应推送信号给用户。

        推送条件:
          - strong_buy / strong_sell  → 始终推送
          - buy / sell 且 confidence >= 0.6 → 推送
          - 其余 → 不推送
        """
        if confidence.signal_type in ("strong_buy", "strong_sell"):
            return True
        if confidence.signal_type in ("buy", "sell") and confidence.overall_confidence >= 0.6:
            return True
        return False

    # ------------------------------------------------------------------
    # Factor scorers (return float: negative=bearish, 0=neutral, positive=bullish)
    # ------------------------------------------------------------------

    @staticmethod
    def _score_trend(tech: TechnicalResult) -> float:
        mapping = {
            TrendStatus.STRONG_BULL: 1.5,
            TrendStatus.BULL: 1.0,
            TrendStatus.WEAK_BULL: 0.5,
            TrendStatus.NEUTRAL: 0.0,
            TrendStatus.WEAK_BEAR: -0.5,
            TrendStatus.BEAR: -1.0,
            TrendStatus.STRONG_BEAR: -1.5,
        }
        return mapping.get(tech.trend_status, 0.0)

    @staticmethod
    def _score_momentum(tech: TechnicalResult) -> float:
        mapping = {
            MACDStatus.GOLDEN_CROSS: 1.5,
            MACDStatus.BULLISH: 1.0,
            MACDStatus.WEAK_BULLISH: 0.5,
            MACDStatus.CONVERGING: 0.0,
            MACDStatus.WEAK_BEARISH: -0.5,
            MACDStatus.BEARISH: -1.0,
            MACDStatus.DEATH_CROSS: -1.5,
        }
        return mapping.get(tech.macd_status, 0.0)

    @staticmethod
    def _score_mean_reversion(tech: TechnicalResult) -> float:
        """RSI oversold = bullish opportunity, overbought = bearish risk"""
        avg_rsi = (tech.rsi6 + tech.rsi12 + tech.rsi24) / 3
        if avg_rsi < 30:
            return 1.0   # oversold → rebound opportunity
        elif avg_rsi < 40:
            return 0.5
        elif avg_rsi > 70:
            return -1.0  # overbought → correction risk
        elif avg_rsi > 60:
            return -0.5
        return 0.0

    @staticmethod
    def _score_stochastic(tech: TechnicalResult) -> float:
        """KDJ: J < 0 oversold=+1, J > 100 overbought=-1, low golden cross=+1"""
        j = tech.j_value
        k = tech.k_value
        d = tech.d_value

        if j < 0:
            return 1.0
        if j > 100:
            return -1.0
        # Low golden cross: K crosses above D, both below 50
        if k > d and k < 50:
            return 1.0
        # High death cross: K crosses below D, both above 50
        if k < d and k > 50:
            return -1.0
        return 0.0

    @staticmethod
    def _score_volatility(tech: TechnicalResult) -> float:
        """Bollinger position: near lower band → bullish, near upper → bearish"""
        pos = tech.boll_position  # 0.0 (lower) to 1.0 (upper)
        if pos < 0.2:
            return 1.0   # near lower band → bounce
        elif pos < 0.35:
            return 0.5
        elif pos > 0.8:
            return -1.0  # near upper band → reversal
        elif pos > 0.65:
            return -0.5
        return 0.0

    @staticmethod
    def _score_volume(tech: TechnicalResult) -> float:
        """Volume: heavy up = +1, heavy down = -1"""
        status = tech.volume_status
        if status == VolumeStatus.HEAVY_UP:
            return 1.0
        if status == VolumeStatus.HEAVY_DOWN:
            return -1.0
        if status == VolumeStatus.SHRINK_UP:
            return 0.3  # mild positive
        if status == VolumeStatus.SHRINK_DOWN:
            return -0.3
        return 0.0

    @staticmethod
    def _score_bias(tech: TechnicalResult) -> float:
        """BIAS5: >5% = chase risk (-1.5), <-3% = reversion opportunity (+1)"""
        b5 = tech.bias5
        if b5 > 5:
            return -1.5
        elif b5 > 3:
            return -0.8
        elif b5 < -3:
            return 1.0
        elif b5 < -1:
            return 0.5
        return 0.0

    @staticmethod
    def _score_price_position(tech: TechnicalResult) -> float:
        """Price near support = +1, near resistance = -1"""
        price = tech.current_price
        if price <= 0:
            return 0.0

        # Check proximity to nearest support/resistance
        threshold_pct = 0.015  # 1.5% proximity threshold

        for sup in tech.support_levels:
            if sup > 0 and abs(price - sup) / price < threshold_pct:
                return 1.0  # near support

        for res in tech.resistance_levels:
            if res > 0 and abs(price - res) / price < threshold_pct:
                return -1.0  # near resistance

        # Weaker signal if within 3%
        for sup in tech.support_levels:
            if sup > 0 and abs(price - sup) / price < 0.03:
                return 0.5

        for res in tech.resistance_levels:
            if res > 0 and abs(price - res) / price < 0.03:
                return -0.5

        return 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_resonance(factor_scores: Dict[str, float], positive: bool) -> float:
        """
        Calculate resonance score.

        resonance = sum of aligned factor absolute scores / (count_of_factors * max_possible_single_score)
        Normalized to 0.0 - 1.0.
        """
        if positive:
            aligned_sum = sum(v for v in factor_scores.values() if v > 0)
        else:
            aligned_sum = sum(abs(v) for v in factor_scores.values() if v < 0)

        # Max possible if all 8 factors fully aligned at 1.5 = 12.0
        max_possible = 12.0
        resonance = min(aligned_sum / max_possible, 1.0) if max_possible > 0 else 0.0
        return round(resonance, 4)

    @staticmethod
    def _determine_signal(
        dominant: str,
        resonance: float,
        aligned_factors: int,
    ) -> tuple:
        """
        Returns (signal_type, confidence) based on thresholds.

        Thresholds:
          resonance >= 0.7 AND aligned >= 5 → strong_buy/sell, confidence 0.8+
          resonance >= 0.5 AND aligned >= 4 → buy/sell, confidence 0.6+
          resonance >= 0.3 → neutral, confidence 0.3-0.5
          resonance < 0.3 → neutral, confidence 0.0-0.3
        """
        if dominant == "neutral":
            return "neutral", round(0.1 + resonance * 0.2, 4)

        direction_prefix = "" if dominant == "buy" else "strong_"

        if resonance >= 0.7 and aligned_factors >= 5:
            # Strong signal
            confidence = 0.8 + min(resonance - 0.7, 0.2)  # 0.8 ~ 1.0
            return f"strong_{dominant}", round(confidence, 4)

        if resonance >= 0.5 and aligned_factors >= 4:
            confidence = 0.6 + min(resonance - 0.5, 0.2)  # 0.6 ~ 0.8
            return dominant, round(confidence, 4)

        if resonance >= 0.3:
            confidence = 0.3 + (resonance - 0.3) * 1.5  # 0.3 ~ 0.6
            return "neutral", round(min(confidence, 0.5), 4)

        # Very low resonance — no signal
        confidence = resonance  # 0.0 ~ 0.3
        return "neutral", round(confidence, 4)

    @staticmethod
    def _collect_reason(score: float, label: str, reasons: List[str], warnings: List[str]):
        """Add a reason or warning based on factor score direction."""
        if score >= 0.5:
            reasons.append(f"{label} ✓")
        elif score <= -0.5:
            warnings.append(f"{label} ✗")
