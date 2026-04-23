"""
策略引擎模块
加载 YAML 策略文件，结合技术分析结果进行策略匹配和评分增强
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from rich.console import Console

console = Console()

STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"


@dataclass
class StrategySignal:
    """策略信号"""
    strategy_name: str = ""
    signal_type: str = ""       # 买入/卖出/观望
    strength: float = 0.0       # 信号强度 0-1
    reasons: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)
    suggested_action: str = ""  # 建议操作
    stop_loss_pct: float = 3.0  # 止损百分比
    position_pct: float = 20.0  # 建议仓位
    timeframe: str = ""         # 时间框架
    suitable_market: str = ""   # 适合市场

    def to_summary(self) -> str:
        lines = [
            f"📐 策略: {self.strategy_name}",
            f"   信号: {self.signal_type} (强度: {self.strength:.0%})",
            f"   建议: {self.suggested_action}",
            f"   止损: {self.stop_loss_pct}%  仓位: {self.position_pct}%",
        ]
        for r in self.reasons:
            lines.append(f"   ✅ {r}")
        for w in self.risk_warnings:
            lines.append(f"   ⚠️ {w}")
        return "\n".join(lines)


class StrategyEngine:
    """策略引擎"""

    def __init__(self):
        self.strategies: Dict[str, dict] = {}
        self._load_all_strategies()

    def list_strategies(self) -> List[dict]:
        """列出所有已加载策略"""
        return list(self.strategies.values())

    def _load_all_strategies(self):
        """加载所有策略文件"""
        if not STRATEGIES_DIR.exists():
            console.print(f"[yellow]⚠ 策略目录不存在: {STRATEGIES_DIR}[/yellow]")
            return

        for f in STRATEGIES_DIR.glob("*.yaml"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                    if data and "name" in data:
                        self.strategies[data["name"]] = data
                        console.print(f"[dim]  ✓ 已加载策略: {data['name']}[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠ 加载策略 {f.name} 失败: {e}[/yellow]")

        console.print(f"[green]✓ 共加载 {len(self.strategies)} 个策略[/green]")

    def evaluate_all(self, tech_result) -> List[StrategySignal]:
        """
        对技术分析结果运行所有策略，返回信号列表
        """
        signals = []
        for name, strategy in self.strategies.items():
            try:
                signal = self._evaluate_strategy(strategy, tech_result)
                if signal and signal.signal_type != "观望":
                    signals.append(signal)
            except Exception as e:
                console.print(f"[dim]⚠ 策略 {name} 评估失败: {e}[/dim]")

        # 按信号强度排序
        signals.sort(key=lambda s: s.strength, reverse=True)
        return signals

    def _evaluate_strategy(self, strategy: dict, tech) -> Optional[StrategySignal]:
        """评估单个策略"""
        signal = StrategySignal(strategy_name=strategy.get("name", ""))

        # 基本信息
        signal.timeframe = strategy.get("timeframe", "")
        signal.suitable_market = strategy.get("suitable_market", "")

        # 解析风控参数
        rm = strategy.get("risk_management", {})
        if isinstance(rm, dict):
            stop_str = str(rm.get("stop_loss", "3%"))
            signal.stop_loss_pct = self._parse_pct(stop_str)
            pos_str = str(rm.get("position_size", "20%"))
            signal.position_pct = self._parse_pct(pos_str)

        # 评估买入条件
        buy_score, buy_reasons = self._evaluate_entry(strategy, tech)
        # 评估卖出条件
        sell_score, sell_reasons = self._evaluate_exit(strategy, tech)

        if buy_score > sell_score and buy_score >= 0.4:
            signal.signal_type = "买入"
            signal.strength = min(1.0, buy_score)
            signal.reasons = buy_reasons
            signal.risk_warnings = sell_reasons
            signal.suggested_action = f"根据{strategy.get('name', '')}策略，建议买入"
        elif sell_score > buy_score and sell_score >= 0.5:
            signal.signal_type = "卖出"
            signal.strength = min(1.0, sell_score)
            signal.reasons = sell_reasons
            signal.suggested_action = f"根据{strategy.get('name', '')}策略，建议卖出"
        else:
            signal.signal_type = "观望"
            signal.strength = 0
            signal.suggested_action = "未满足该策略的明确条件"

        return signal

    def _evaluate_entry(self, strategy: dict, tech) -> tuple:
        """评估买入条件"""
        conditions = strategy.get("entry_conditions", [])
        if isinstance(conditions, dict):
            # 多种模式
            all_conditions = []
            for phase, conds in conditions.items():
                if isinstance(conds, list):
                    all_conditions.extend(conds)
            conditions = all_conditions

        if not conditions:
            return 0, []

        matched = 0
        reasons = []
        total = len(conditions)

        for cond in conditions:
            cond_str = str(cond).lower()
            hit, reason = self._check_condition(cond_str, tech)
            if hit:
                matched += 1
                if reason:
                    reasons.append(reason)

        score = matched / total if total > 0 else 0
        return score, reasons

    def _evaluate_exit(self, strategy: dict, tech) -> tuple:
        """评估卖出条件"""
        conditions = strategy.get("exit_conditions", [])
        if not conditions:
            return 0, []

        matched = 0
        reasons = []
        total = len(conditions)

        for cond in conditions:
            cond_str = str(cond).lower()
            hit, reason = self._check_exit_condition(cond_str, tech)
            if hit:
                matched += 1
                if reason:
                    reasons.append(reason)

        score = matched / total if total > 0 else 0
        return score, reasons

    def _check_condition(self, cond: str, tech) -> tuple:
        """检查单个买入条件"""
        from analyzer.technical import TrendStatus, MACDStatus, RSIStatus, VolumeStatus

        # 趋势相关
        if "多头排列" in cond or "ma5>ma10>ma20" in cond:
            if tech.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
                return True, f"趋势: {tech.trend_status.value}"
            return False, ""

        if "ma5" in cond and "ma10" in cond and ("上穿" in cond or "金叉" in cond):
            if tech.trend_status in [TrendStatus.WEAK_BULL, TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                return True, f"MA5({tech.ma5:.2f}) > MA10({tech.ma10:.2f})"
            return False, ""

        # MACD 相关
        if "macd" in cond and "金叉" in cond:
            if tech.macd_status == MACDStatus.GOLDEN_CROSS:
                return True, "MACD金叉"
            return False, ""

        if "macd" in cond and "零轴" in cond and "上" in cond:
            if tech.dif > 0 and tech.dea > 0:
                return True, f"MACD零轴上方(DIF={tech.dif:.4f})"
            return False, ""

        if "macd" in cond:
            if tech.macd_status in [MACDStatus.GOLDEN_CROSS, MACDStatus.BULLISH, MACDStatus.WEAK_BULLISH]:
                return True, f"MACD: {tech.macd_status.value}"
            return False, ""

        # RSI 相关
        if "rsi" in cond:
            rsi_val = None
            if "rsi6" in cond:
                rsi_val = tech.rsi6
            elif "rsi" in cond:
                rsi_val = tech.rsi6

            if rsi_val:
                if "超卖" in cond or "< 25" in cond or "< 20" in cond:
                    if rsi_val < 30:
                        return True, f"RSI超卖({rsi_val:.1f})"
                elif "< 70" in cond or "60-80" in cond:
                    if 40 < rsi_val < 80:
                        return True, f"RSI中性偏强({rsi_val:.1f})"
                elif "> 70" in cond or "超买" in cond:
                    if rsi_val > 70:
                        return True, f"RSI偏强({rsi_val:.1f})"
                elif "50" in cond and "<" in cond:
                    if rsi_val < 50:
                        return True, f"RSI回落({rsi_val:.1f})"
            return False, ""

        # 成交量相关
        if "量" in cond and ("放大" in cond or "倍" in cond):
            if tech.volume_ratio > 1.5:
                return True, f"放量(量比={tech.volume_ratio:.2f})"
            return False, ""

        if "缩量" in cond or "萎缩" in cond:
            if tech.volume_ratio < 0.8:
                return True, f"缩量(量比={tech.volume_ratio:.2f})"
            return False, ""

        if "换手" in cond:
            # 换手率需要额外数据，跳过
            return True, ""

        # 布林带
        if "布林" in cond and "下轨" in cond:
            if tech.boll_position < 0.1:
                return True, f"触及布林下轨({tech.boll_position:.0%})"
            return False, ""

        # 均线支撑
        if "ma5" in cond and ("支撑" in cond or "站上" in cond):
            if tech.current_price > tech.ma5:
                return True, f"站上MA5({tech.ma5:.2f})"
            return False, ""

        if "ma10" in cond and "支撑" in cond:
            if tech.current_price > tech.ma10:
                return True, f"MA10支撑({tech.ma10:.2f})"
            return False, ""

        if "ma20" in cond and ("支撑" in cond or "回调" in cond):
            if tech.current_price > tech.ma20:
                return True, f"MA20上方({tech.ma20:.2f})"
            return False, ""

        # KDJ
        if "kdj" in cond and "j" in cond:
            if "50" in cond:
                if tech.j_value < 50:
                    return True, f"KDJ-J回落({tech.j_value:.1f})"
            elif "超卖" in cond or "< 0" in cond:
                if tech.j_value < 20:
                    return True, f"KDJ超卖(J={tech.j_value:.1f})"

        # 大盘相关（需要额外数据，给默认通过）
        if "大盘" in cond or "暴跌" in cond or "系统性风险" in cond:
            return True, ""

        # 板块相关（需要额外数据，给默认通过）
        if "板块" in cond or "涨停" in cond:
            return True, ""

        # 乖离率
        if "bias" in cond:
            if "5%" in cond or "3%" in cond:
                if tech.bias5 < 3:
                    return True, f"BIAS5适中({tech.bias5:.2f}%)"

        # 封板 / 涨停相关
        if "封板" in cond or "涨停" in cond or "连板" in cond:
            return True, ""

        # 竞价相关
        if "竞价" in cond:
            return True, ""

        return False, ""

    def _check_exit_condition(self, cond: str, tech) -> tuple:
        """检查单个卖出条件"""
        from analyzer.technical import MACDStatus, RSIStatus

        # MACD 死叉
        if "macd" in cond and "死叉" in cond:
            if tech.macd_status == MACDStatus.DEATH_CROSS:
                return True, "MACD死叉"
            return False, ""

        # RSI 超买
        if "rsi" in cond and ("超买" in cond or "> 80" in cond or "> 70" in cond):
            if tech.rsi_status == RSIStatus.OVERBOUGHT or tech.rsi6 > 75:
                return True, f"RSI偏高({tech.rsi6:.1f})"
            return False, ""

        # 跌破均线
        if "跌破" in cond:
            if "ma5" in cond:
                if tech.current_price < tech.ma5:
                    return True, f"跌破MA5({tech.ma5:.2f})"
            elif "ma10" in cond:
                if tech.current_price < tech.ma10:
                    return True, f"跌破MA10({tech.ma10:.2f})"
            elif "ma20" in cond:
                if tech.current_price < tech.ma20:
                    return True, f"跌破MA20({tech.ma20:.2f})"
            return False, ""

        # 缩量
        if "缩量" in cond or "量能萎缩" in cond:
            if tech.volume_ratio < 0.6:
                return True, f"缩量({tech.volume_ratio:.2f})"
            return False, ""

        # 放量滞涨
        if "放量" in cond and "滞涨" in cond:
            if tech.volume_ratio > 1.5 and tech.current_price < tech.ma5:
                return True, "放量滞涨"
            return False, ""

        # 炸板 / 涨停板相关
        if "炸板" in cond or "涨停" in cond or "连板" in cond:
            return False, ""  # 需要分时数据

        # 低开
        if "低开" in cond:
            return False, ""  # 需要次日数据

        # 上影线
        if "上影线" in cond:
            return False, ""  # 需要K线形态分析

        return False, ""

    def _parse_pct(self, s: str) -> float:
        """从字符串解析百分比"""
        import re
        match = re.search(r'(\d+(?:\.\d+)?)', s)
        if match:
            return float(match.group(1))
        return 3.0

    def get_enhanced_score(self, tech_result) -> tuple:
        """
        基于所有策略信号，增强技术分析的评分
        Returns: (调整后的分数, 策略信号列表)
        """
        signals = self.evaluate_all(tech_result)
        if not signals:
            return tech_result.buy_score, []

        # 策略加权调整分数
        buy_signals = [s for s in signals if s.signal_type == "买入"]
        sell_signals = [s for s in signals if s.signal_type == "卖出"]

        strategy_adjustment = 0
        for s in buy_signals:
            strategy_adjustment += int(s.strength * 10)  # 每个买入信号最多+10
        for s in sell_signals:
            strategy_adjustment -= int(s.strength * 10)  # 每个卖出信号最多-10

        # 限幅调整
        strategy_adjustment = max(-15, min(15, strategy_adjustment))
        adjusted_score = max(0, min(100, tech_result.buy_score + strategy_adjustment))

        return adjusted_score, signals


# 全局策略引擎实例
_engine = None

def get_strategy_engine() -> StrategyEngine:
    """获取策略引擎单例"""
    global _engine
    if _engine is None:
        _engine = StrategyEngine()
    return _engine
