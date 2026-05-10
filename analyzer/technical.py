"""
技术指标分析引擎
参考 daily_stock_analysis 的 StockTrendAnalyzer
计算 MA/MACD/RSI/KDJ/布林带/成交量/筹码分布等指标
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class TrendStatus(Enum):
    """趋势状态"""
    STRONG_BULL = "强势多头"     # MA5>MA10>MA20>MA60
    BULL = "多头排列"           # MA5>MA10>MA20
    WEAK_BULL = "偏多"          # MA5>MA10
    NEUTRAL = "震荡"            # 均线交织
    WEAK_BEAR = "偏空"          # MA5<MA10
    BEAR = "空头排列"           # MA5<MA10<MA20
    STRONG_BEAR = "强势空头"    # MA5<MA10<MA20<MA60


class MACDStatus(Enum):
    """MACD状态"""
    GOLDEN_CROSS = "金叉"       # DIF上穿DEA
    DEATH_CROSS = "死叉"        # DIF下穿DEA
    BULLISH = "多头运行"        # DIF>DEA>0
    WEAK_BULLISH = "弱多头"     # DIF>DEA 但 DEA<0
    BEARISH = "空头运行"        # DIF<DEA<0
    WEAK_BEARISH = "弱空头"     # DIF<DEA 但 DEA>0
    CONVERGING = "收敛中"       # DIF与DEA距离缩小


class RSIStatus(Enum):
    """RSI状态"""
    OVERBOUGHT = "超买"         # RSI>80
    STRONG_BUY = "强势"         # 70<RSI<80
    NEUTRAL = "中性"            # 30<RSI<70
    WEAK = "弱势"               # 20<RSI<30
    OVERSOLD = "超卖"           # RSI<20


class VolumeStatus(Enum):
    """成交量状态"""
    HEAVY_UP = "放量上涨"
    SHRINK_UP = "缩量上涨"
    HEAVY_DOWN = "放量下跌"
    SHRINK_DOWN = "缩量下跌"
    NORMAL = "平量"


@dataclass
class TechnicalResult:
    """技术分析结果"""
    code: str
    name: str = ""
    current_price: float = 0.0

    # 均线
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    trend_status: TrendStatus = TrendStatus.NEUTRAL

    # MACD
    dif: float = 0.0
    dea: float = 0.0
    macd_bar: float = 0.0
    macd_status: MACDStatus = MACDStatus.CONVERGING

    # RSI
    rsi6: float = 50.0
    rsi12: float = 50.0
    rsi24: float = 50.0
    rsi_status: RSIStatus = RSIStatus.NEUTRAL

    # KDJ
    k_value: float = 50.0
    d_value: float = 50.0
    j_value: float = 50.0

    # 布林带
    boll_upper: float = 0.0
    boll_middle: float = 0.0
    boll_lower: float = 0.0
    boll_position: float = 0.5  # 当前价格在布林带中的位置 0~1

    # 成交量
    volume_ratio: float = 1.0
    volume_status: VolumeStatus = VolumeStatus.NORMAL

    # BIAS 乖离率
    bias5: float = 0.0
    bias10: float = 0.0
    bias20: float = 0.0

    # 支撑/压力
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)

    # 综合评分
    buy_score: int = 50        # 0-100
    score_reasons: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)

    # 信号置信度
    signal_confidence: Optional[Any] = None  # SignalConfidence object
    resonance_score: float = 0.0  # Quick access

    # 操作建议
    operation: str = "观望"    # 买入/持有/卖出/观望
    operation_reason: str = ""

    def to_summary(self) -> str:
        """生成简要摘要"""
        lines = [
            f"📊 {self.code} {self.name} - 技术分析",
            f"{'='*50}",
            f"💰 当前价格: {self.current_price:.2f}",
            f"",
            f"📈 均线趋势: {self.trend_status.value}",
            f"   MA5={self.ma5:.2f}  MA10={self.ma10:.2f}  MA20={self.ma20:.2f}  MA60={self.ma60:.2f}",
            f"",
            f"📉 MACD: {self.macd_status.value}",
            f"   DIF={self.dif:.4f}  DEA={self.dea:.4f}  BAR={self.macd_bar:.4f}",
            f"",
            f"📊 RSI: {self.rsi_status.value}",
            f"   RSI(6)={self.rsi6:.1f}  RSI(12)={self.rsi12:.1f}  RSI(24)={self.rsi24:.1f}",
            f"",
            f"📦 KDJ: K={self.k_value:.1f}  D={self.d_value:.1f}  J={self.j_value:.1f}",
            f"",
            f"📏 布林带: 上轨={self.boll_upper:.2f}  中轨={self.boll_middle:.2f}  下轨={self.boll_lower:.2f}",
            f"   位置: {self.boll_position:.1%}",
            f"",
            f"🔊 成交量: {self.volume_status.value} (量比={self.volume_ratio:.2f})",
            f"",
            f"📐 乖离率: BIAS5={self.bias5:.2f}%  BIAS10={self.bias10:.2f}%  BIAS20={self.bias20:.2f}%",
            f"",
            f"🎯 综合评分: {self.buy_score}/100",
            f"📋 操作建议: [bold]{self.operation}[/bold]",
        ]

        if self.score_reasons:
            lines.append(f"\n✅ 看多因素:")
            for r in self.score_reasons:
                lines.append(f"   • {r}")

        if self.risk_warnings:
            lines.append(f"\n⚠️ 风险提示:")
            for r in self.risk_warnings:
                lines.append(f"   • {r}")

        if self.support_levels:
            lines.append(f"\n📍 支撑位: {', '.join(f'{x:.2f}' for x in self.support_levels)}")
        if self.resistance_levels:
            lines.append(f"🔴 压力位: {', '.join(f'{x:.2f}' for x in self.resistance_levels)}")

        return "\n".join(lines)


class TechnicalAnalyzer:
    """技术分析引擎"""

    def __init__(self):
        pass

    def analyze(self, df: pd.DataFrame, code: str = "", name: str = "") -> TechnicalResult:
        """
        执行完整技术分析

        Args:
            df: 历史K线数据 (columns: date, open, high, low, close, volume, amount)
            code: 股票代码
            name: 股票名称

        Returns:
            TechnicalResult 技术分析结果
        """
        if df is None or len(df) < 20:
            return TechnicalResult(code=code, name=name)

        result = TechnicalResult(code=code, name=name)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        result.current_price = float(close.iloc[-1])

        # 1. 均线分析
        self._calc_ma(result, close)

        # 2. MACD 分析
        self._calc_macd(result, close)

        # 3. RSI 分析
        self._calc_rsi(result, close)

        # 4. KDJ 分析
        self._calc_kdj(result, high, low, close)

        # 5. 布林带
        self._calc_bollinger(result, close)

        # 6. 成交量分析
        self._calc_volume(result, close, volume)

        # 7. BIAS 乖离率
        self._calc_bias(result, close)

        # 8. 支撑/压力位
        self._calc_support_resistance(result, close, high, low)

        # 9. 综合评分与操作建议
        self._calc_score(result)

        return result

    def _calc_ma(self, result: TechnicalResult, close: pd.Series):
        """计算移动均线"""
        result.ma5 = float(close.rolling(5).mean().iloc[-1])
        result.ma10 = float(close.rolling(10).mean().iloc[-1])
        result.ma20 = float(close.rolling(20).mean().iloc[-1])
        result.ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else float(close.mean())

        # 判断趋势状态
        ma5, ma10, ma20, ma60 = result.ma5, result.ma10, result.ma20, result.ma60

        if ma5 > ma10 > ma20 > ma60:
            result.trend_status = TrendStatus.STRONG_BULL
        elif ma5 > ma10 > ma20:
            result.trend_status = TrendStatus.BULL
        elif ma5 > ma10:
            result.trend_status = TrendStatus.WEAK_BULL
        elif ma5 < ma10 < ma20 < ma60:
            result.trend_status = TrendStatus.STRONG_BEAR
        elif ma5 < ma10 < ma20:
            result.trend_status = TrendStatus.BEAR
        elif ma5 < ma10:
            result.trend_status = TrendStatus.WEAK_BEAR
        else:
            result.trend_status = TrendStatus.NEUTRAL

    def _calc_macd(self, result: TechnicalResult, close: pd.Series):
        """计算 MACD"""
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_bar = 2 * (dif - dea)

        result.dif = float(dif.iloc[-1])
        result.dea = float(dea.iloc[-1])
        result.macd_bar = float(macd_bar.iloc[-1])

        # 判断 MACD 状态
        dif_val = result.dif
        dea_val = result.dea

        if len(dif) >= 2:
            prev_dif = float(dif.iloc[-2])
            prev_dea = float(dea.iloc[-2])
            crossed_up = prev_dif <= prev_dea and dif_val > dea_val
            crossed_down = prev_dif >= prev_dea and dif_val < dea_val

            if crossed_up:
                result.macd_status = MACDStatus.GOLDEN_CROSS
            elif crossed_down:
                result.macd_status = MACDStatus.DEATH_CROSS
            elif dif_val > dea_val and dea_val > 0:
                result.macd_status = MACDStatus.BULLISH
            elif dif_val > dea_val:
                result.macd_status = MACDStatus.WEAK_BULLISH
            elif dif_val < dea_val and dea_val < 0:
                result.macd_status = MACDStatus.BEARISH
            elif dif_val < dea_val:
                result.macd_status = MACDStatus.WEAK_BEARISH
            else:
                result.macd_status = MACDStatus.CONVERGING

    def _calc_rsi(self, result: TechnicalResult, close: pd.Series):
        """计算 RSI"""
        delta = close.diff()

        def _rsi(period):
            gain = delta.where(delta > 0, 0).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss.replace(0, np.inf)
            return 100 - (100 / (1 + rs))

        rsi6 = _rsi(6)
        rsi12 = _rsi(12)
        rsi24 = _rsi(24)

        result.rsi6 = float(rsi6.iloc[-1]) if not pd.isna(rsi6.iloc[-1]) else 50.0
        result.rsi12 = float(rsi12.iloc[-1]) if not pd.isna(rsi12.iloc[-1]) else 50.0
        result.rsi24 = float(rsi24.iloc[-1]) if not pd.isna(rsi24.iloc[-1]) else 50.0

        avg_rsi = (result.rsi6 + result.rsi12 + result.rsi24) / 3
        if avg_rsi > 80:
            result.rsi_status = RSIStatus.OVERBOUGHT
        elif avg_rsi > 70:
            result.rsi_status = RSIStatus.STRONG_BUY
        elif avg_rsi > 30:
            result.rsi_status = RSIStatus.NEUTRAL
        elif avg_rsi > 20:
            result.rsi_status = RSIStatus.WEAK
        else:
            result.rsi_status = RSIStatus.OVERSOLD

    def _calc_kdj(self, result: TechnicalResult, high: pd.Series, low: pd.Series, close: pd.Series):
        """计算 KDJ"""
        low_9 = low.rolling(window=9).min()
        high_9 = high.rolling(window=9).max()

        rsv = (close - low_9) / (high_9 - low_9).replace(0, np.inf) * 100

        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d

        result.k_value = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50.0
        result.d_value = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50.0
        result.j_value = float(j.iloc[-1]) if not pd.isna(j.iloc[-1]) else 50.0

    def _calc_bollinger(self, result: TechnicalResult, close: pd.Series):
        """计算布林带"""
        period = 20
        ma = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()

        result.boll_upper = float((ma + 2 * std).iloc[-1])
        result.boll_middle = float(ma.iloc[-1])
        result.boll_lower = float((ma - 2 * std).iloc[-1])

        # 价格在布林带中的位置
        band_width = result.boll_upper - result.boll_lower
        if band_width > 0:
            result.boll_position = (result.current_price - result.boll_lower) / band_width
        else:
            result.boll_position = 0.5

    def _calc_volume(self, result: TechnicalResult, close: pd.Series, volume: pd.Series):
        """分析成交量"""
        vol_ma5 = volume.rolling(5).mean()
        result.volume_ratio = float(volume.iloc[-1] / vol_ma5.iloc[-1]) if vol_ma5.iloc[-1] > 0 else 1.0

        price_change = float(close.iloc[-1] - close.iloc[-2]) if len(close) >= 2 else 0
        is_up = price_change > 0
        is_heavy = result.volume_ratio > 1.5
        is_shrink = result.volume_ratio < 0.7

        if is_up and is_heavy:
            result.volume_status = VolumeStatus.HEAVY_UP
        elif is_up and is_shrink:
            result.volume_status = VolumeStatus.SHRINK_UP
        elif not is_up and is_heavy:
            result.volume_status = VolumeStatus.HEAVY_DOWN
        elif not is_up and is_shrink:
            result.volume_status = VolumeStatus.SHRINK_DOWN
        else:
            result.volume_status = VolumeStatus.NORMAL

    def _calc_bias(self, result: TechnicalResult, close: pd.Series):
        """计算乖离率"""
        current = result.current_price
        if result.ma5 > 0:
            result.bias5 = (current - result.ma5) / result.ma5 * 100
        if result.ma10 > 0:
            result.bias10 = (current - result.ma10) / result.ma10 * 100
        if result.ma20 > 0:
            result.bias20 = (current - result.ma20) / result.ma20 * 100

    def _calc_support_resistance(self, result: TechnicalResult, close: pd.Series, high: pd.Series, low: pd.Series):
        """计算支撑/压力位"""
        levels = []

        # 均线作为支撑/压力
        for ma_val in [result.ma5, result.ma10, result.ma20, result.ma60]:
            if ma_val > 0:
                levels.append(ma_val)

        # 布林带上下轨
        if result.boll_upper > 0:
            levels.append(result.boll_upper)
        if result.boll_lower > 0:
            levels.append(result.boll_lower)

        current = result.current_price
        result.support_levels = sorted([l for l in levels if l < current], reverse=True)[:3]
        result.resistance_levels = sorted([l for l in levels if l > current])[:3]

    def _calc_score(self, result: TechnicalResult):
        """综合评分"""
        score = 50  # 基准分
        reasons = []
        warnings = []

        # --- 趋势评分 (±20分) ---
        trend_scores = {
            TrendStatus.STRONG_BULL: 20,
            TrendStatus.BULL: 15,
            TrendStatus.WEAK_BULL: 5,
            TrendStatus.NEUTRAL: 0,
            TrendStatus.WEAK_BEAR: -5,
            TrendStatus.BEAR: -15,
            TrendStatus.STRONG_BEAR: -20,
        }
        ts = trend_scores[result.trend_status]
        score += ts
        if ts > 0:
            reasons.append(f"均线{result.trend_status.value}(+{ts}分)")
        elif ts < 0:
            warnings.append(f"均线{result.trend_status.value}({ts}分)")

        # --- MACD 评分 (±15分) ---
        macd_scores = {
            MACDStatus.GOLDEN_CROSS: 15,
            MACDStatus.BULLISH: 10,
            MACDStatus.WEAK_BULLISH: 5,
            MACDStatus.CONVERGING: 0,
            MACDStatus.WEAK_BEARISH: -5,
            MACDStatus.BEARISH: -10,
            MACDStatus.DEATH_CROSS: -15,
        }
        ms = macd_scores[result.macd_status]
        score += ms
        if ms > 0:
            reasons.append(f"MACD {result.macd_status.value}(+{ms}分)")
        elif ms < 0:
            warnings.append(f"MACD {result.macd_status.value}({ms}分)")

        # --- RSI 评分 (±10分) ---
        rsi_scores = {
            RSIStatus.OVERSOLD: 10,     # 超卖可能是买入机会
            RSIStatus.WEAK: 5,
            RSIStatus.NEUTRAL: 0,
            RSIStatus.STRONG_BUY: -5,   # 高位注意风险
            RSIStatus.OVERBOUGHT: -10,
        }
        rs = rsi_scores[result.rsi_status]
        score += rs
        if result.rsi_status == RSIStatus.OVERSOLD:
            reasons.append(f"RSI超卖可能反弹(+{rs}分)")
        elif result.rsi_status == RSIStatus.OVERBOUGHT:
            warnings.append(f"RSI超买注意回调({rs}分)")

        # --- KDJ 评分 (±10分) ---
        if result.j_value < 0:
            score += 10
            reasons.append(f"KDJ超卖(J={result.j_value:.1f})(+10分)")
        elif result.j_value > 100:
            score -= 10
            warnings.append(f"KDJ超买(J={result.j_value:.1f})(-10分)")
        elif result.k_value > result.d_value and result.k_value < 50:
            score += 5
            reasons.append(f"KDJ低位金叉(+5分)")

        # --- 成交量评分 (±10分) ---
        vol_scores = {
            VolumeStatus.HEAVY_UP: 10,
            VolumeStatus.SHRINK_UP: 0,
            VolumeStatus.NORMAL: 0,
            VolumeStatus.SHRINK_DOWN: -3,
            VolumeStatus.HEAVY_DOWN: -10,
        }
        vs = vol_scores[result.volume_status]
        score += vs
        if vs > 0:
            reasons.append(f"成交量{result.volume_status.value}(+{vs}分)")
        elif vs < 0:
            warnings.append(f"成交量{result.volume_status.value}({vs}分)")

        # --- BIAS 高位追高警告 ---
        if result.bias5 > 5:
            score -= 15
            warnings.append(f"乖离率过高(BIAS5={result.bias5:.1f}%)，追高风险大(-15分)")
        elif result.bias5 > 3:
            score -= 5
            warnings.append(f"短期乖离偏大(BIAS5={result.bias5:.1f}%)(-5分)")

        # --- 布林带位置 ---
        if result.boll_position > 0.95:
            score -= 5
            warnings.append(f"触及布林上轨({result.boll_position:.0%})(-5分)")
        elif result.boll_position < 0.05:
            score += 5
            reasons.append(f"触及布林下轨({result.boll_position:.0%})可能反弹(+5分)")

        # 限幅
        score = max(0, min(100, score))
        result.buy_score = score
        result.score_reasons = reasons
        result.risk_warnings = warnings

        # 操作建议
        if score >= 75:
            result.operation = "积极买入"
            result.operation_reason = "多项技术指标共振看多"
        elif score >= 60:
            result.operation = "逢低买入"
            result.operation_reason = "技术面偏多，可寻找合适买点"
        elif score >= 45:
            result.operation = "持有观望"
            result.operation_reason = "多空分歧较大，建议等待方向明确"
        elif score >= 30:
            result.operation = "减仓观望"
            result.operation_reason = "技术面偏空，建议控制仓位"
        else:
            result.operation = "考虑卖出"
            result.operation_reason = "多项技术指标看空"

        # Signal confidence evaluation
        from analyzer.signal_confidence import SignalConfidenceAnalyzer
        conf_analyzer = SignalConfidenceAnalyzer()
        confidence = conf_analyzer.evaluate(result)
        result.signal_confidence = confidence
        result.resonance_score = confidence.resonance_score
