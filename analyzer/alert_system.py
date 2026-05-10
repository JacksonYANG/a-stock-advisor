"""
异动预警系统
监控股票的价格/量能异动，触发时推送通知

功能:
- 价格异动: 涨跌幅突破阈值
- 放量异动: 量比突增/缩量异常
- 涨停预警: 接近涨停/涨停封板
- 炸板预警: 涨停打开
- 跌破/突破关键价位: 均线/支撑阻力位
- 策略信号预警: 策略出现买卖信号时
"""

import time
import threading
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import pandas as pd

from config import Config
from data_provider.base import DataFetcherManager
from analyzer.technical import TechnicalAnalyzer
from analyzer.strategy_engine import get_strategy_engine, StrategySignal


class AlertType(Enum):
    """预警类型"""
    PRICE_SPIKE = "价格异动"           # 涨跌幅突增
    VOLUME_SPIKE = "放量异动"          # 量比突增
    VOLUME_SHRINK = "缩量异常"         # 异常缩量
    LIMIT_UP_APPROACH = "接近涨停"     # 涨幅>9%
    LIMIT_UP_SEALED = "涨停封板"       # 涨停封板
    LIMIT_UP_BROKEN = "炸板预警"       # 涨停打开
    MA_BREAK = "均线突破/跌破"         # 均线突破
    SUPPORT_BREAK = "支撑跌破"        # 跌破支撑
    STRATEGY_SIGNAL = "策略信号"       # 策略发出信号
    RISK_WARNING = "风险预警"          # 系统风险


@dataclass
class Alert:
    """预警信息"""
    alert_type: AlertType
    code: str
    name: str
    timestamp: str = ""
    message: str = ""
    severity: str = "normal"   # normal / warning / danger
    current_price: float = 0.0
    change_pct: float = 0.0
    volume_ratio: float = 0.0
    related_indicator: str = ""  # 相关指标
    strategy_name: str = ""       # 触发策略

    def to_telegram_msg(self) -> str:
        icon = {
            AlertType.LIMIT_UP_SEALED: "🔴",
            AlertType.LIMIT_UP_BROKEN: "💥",
            AlertType.LIMIT_UP_APPROACH: "🟠",
            AlertType.PRICE_SPIKE: "📈",
            AlertType.VOLUME_SPIKE: "🔔",
            AlertType.VOLUME_SHRINK: "📉",
            AlertType.MA_BREAK: "⚡",
            AlertType.SUPPORT_BREAK: "⚠️",
            AlertType.STRATEGY_SIGNAL: "🎯",
            AlertType.RISK_WARNING: "🚨",
        }.get(self.alert_type, "📌")

        severity_icon = {
            "danger": "🔴",
            "warning": "🟡",
            "normal": "⚪",
        }.get(self.severity, "⚪")

        # 使用 HTML 格式（与重构后的 notifier 一致）
        return (
            f"<b>{severity_icon} {self.alert_type.value} {icon}</b>\n"
            f"<b>{self.code} {self.name}</b>\n"
            f"价格: <b>{self.current_price:.2f}</b> ({self.change_pct:+.2f}%)\n"
            f"{self.message}"
        )


@dataclass
class AlertRule:
    """预警规则"""
    name: str = ""
    enabled: bool = True

    # 监控标的
    codes: List[str] = field(default_factory=list)  # 空=全部自选股
    watch_list_only: bool = False                    # 仅监控自选股

    # 价格异动条件
    price_change_threshold: float = 5.0   # 涨跌幅阈值（%）

    # 量能异动条件
    volume_spike_threshold: float = 2.0  # 放量倍数阈值
    volume_shrink_threshold: float = 0.3 # 缩量倍数阈值

    # 涨停预警
    enable_limit_up: bool = True
    enable_board_break: bool = True

    # 均线异动
    ma_cross_alert: bool = True          # 均线金叉/死叉
    ma_support_alert: bool = True         # 跌破均线支撑

    # 策略信号
    enable_strategy_signal: bool = True   # 策略发出信号时预警

    # 发送配置
    send_telegram: bool = True
    send_wechat: bool = False
    send_email: bool = False


class AlertSystem:
    """异动预警系统"""

    def __init__(self):
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._rules: Dict[str, AlertRule] = {}
        self._last_alerts: Dict[str, datetime] = {}  # 防重复 / rate-limit
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        self._fetcher_mgr: Optional[DataFetcherManager] = None
        self._tech_analyzer = TechnicalAnalyzer()
        self._strategy_engine = get_strategy_engine()
        self._previous_state: Dict[str, Dict] = {}  # 上一轮状态
        self._notifier = None

        # Daily alert summary accumulator
        self._daily_alerts: List[Alert] = []
        self._last_summary_time: Optional[datetime] = None
        self._summary_callbacks: List[Callable[[str], None]] = []

        config = Config.get()
        if config.DATA_SOURCES:
            self._fetcher_mgr = DataFetcherManager(config.DATA_SOURCES)

        # 默认规则
        self._init_default_rules()

    def _init_default_rules(self):
        """初始化默认规则"""
        default = AlertRule(
            name="默认规则",
            enabled=True,
            price_change_threshold=5.0,
            volume_spike_threshold=2.0,
            enable_limit_up=True,
            enable_board_break=True,
            ma_cross_alert=True,
            enable_strategy_signal=True,
        )
        self._rules["default"] = default

    def add_rule(self, rule: AlertRule, rule_id: str = None) -> str:
        """添加预警规则"""
        if rule_id is None:
            rule_id = rule.name or f"rule_{len(self._rules)}"
        self._rules[rule_id] = rule
        return rule_id

    def remove_rule(self, rule_id: str):
        """删除预警规则"""
        if rule_id in self._rules:
            del self._rules[rule_id]

    def register_callback(self, callback: Callable[[Alert], None]):
        """注册预警回调"""
        self._alert_callbacks.append(callback)

    def check_and_alert(self, code: str, name: str = "") -> List[Alert]:
        """
        检查单只股票的异动并生成预警
        返回所有触发的预警列表
        """
        alerts = []
        if not self._fetcher_mgr:
            return alerts

        # 获取实时行情
        quote = self._fetcher_mgr.get_quote(code)
        if not quote:
            return alerts

        # 获取历史数据（用于计算指标）
        hist = self._fetcher_mgr.get_history(code, 60)
        if hist is None or hist.empty:
            return alerts

        # 计算技术指标
        try:
            tech = self._tech_analyzer.analyze(hist, code=code, name=name or quote.name)
        except Exception:
            return alerts

        current_price = quote.price
        change_pct = quote.change_pct
        volume_ratio = tech.volume_ratio

        # === 价格异动检查 ===
        for rule_id, rule in self._rules.items():
            if not rule.enabled:
                continue

            alert = self._check_rule(
                rule, rule_id, code, name or quote.name,
                current_price, change_pct, volume_ratio, tech, quote
            )
            if alert:
                alerts.extend(alert)

        return alerts

    def _check_rule(self, rule: AlertRule, rule_id: str, code: str, name: str,
                    price: float, change_pct: float, vol_ratio: float,
                    tech, quote) -> List[Alert]:
        """检查单条规则"""
        alerts = []
        now = datetime.now()

        # === 1. 涨停相关 ===
        if change_pct >= 9.5:
            # 涨停封板
            if rule.enable_limit_up:
                # 检查是否之前没有涨停（防重复）
                prev = self._previous_state.get(code, {}).get("limit_up", False)
                if not prev and quote.high == quote.low:
                    alert = Alert(
                        alert_type=AlertType.LIMIT_UP_SEALED,
                        code=code, name=name,
                        timestamp=now.strftime("%H:%M:%S"),
                        message="股价涨停封板！",
                        severity="danger" if change_pct >= 9.9 else "warning",
                        current_price=price, change_pct=change_pct,
                        volume_ratio=vol_ratio,
                        related_indicator=f"封板量",
                    )
                    # FIX: dedup BEFORE appending — don't add if suppressed
                    if not self._is_deduped(code, AlertType.LIMIT_UP_SEALED):
                        alerts.append(alert)

        # === 2. 炸板预警 ===
        if rule.enable_board_break and change_pct >= 9.5:
            prev = self._previous_state.get(code, {})
            was_sealed = prev.get("sealed", False)
            if was_sealed and price < quote.close * 1.09:
                alert = Alert(
                    alert_type=AlertType.LIMIT_UP_BROKEN,
                    code=code, name=name,
                    timestamp=now.strftime("%H:%M:%S"),
                    message=f"涨停炸板！当前涨幅{change_pct:.1f}%，注意封板稳定性",
                    severity="danger",
                    current_price=price, change_pct=change_pct,
                    volume_ratio=vol_ratio,
                    related_indicator="炸板",
                )
                if not self._is_deduped(code, AlertType.LIMIT_UP_BROKEN):
                    alerts.append(alert)

        # === 3. 价格异动 ===
        if abs(change_pct) >= rule.price_change_threshold:
            prev_pct = self._previous_state.get(code, {}).get("change_pct", 0)
            if abs(change_pct - prev_pct) > 2:  # 相比上轮有明显变化
                alert = Alert(
                    alert_type=AlertType.PRICE_SPIKE,
                    code=code, name=name,
                    timestamp=now.strftime("%H:%M:%S"),
                    message=f"价格异动脉冲！涨跌幅达{change_pct:.1f}%，量比{vol_ratio:.1f}",
                    severity="warning",
                    current_price=price, change_pct=change_pct,
                    volume_ratio=vol_ratio,
                )
                if not self._is_deduped(code, AlertType.PRICE_SPIKE):
                    alerts.append(alert)

        # === 4. 放量异动 ===
        if vol_ratio >= rule.volume_spike_threshold:
            prev_vol = self._previous_state.get(code, {}).get("volume_ratio", 0)
            if prev_vol == 0 or vol_ratio / prev_vol > 1.3:
                alert = Alert(
                    alert_type=AlertType.VOLUME_SPIKE,
                    code=code, name=name,
                    timestamp=now.strftime("%H:%M:%S"),
                    message=f"量能突增！量比达{vol_ratio:.1f}倍",
                    severity="normal",
                    current_price=price, change_pct=change_pct,
                    volume_ratio=vol_ratio,
                )
                if not self._is_deduped(code, AlertType.VOLUME_SPIKE):
                    alerts.append(alert)

        # === 5. 均线突破 ===
        if rule.ma_cross_alert:
            from analyzer.technical import TrendStatus
            prev_trend = self._previous_state.get(code, {}).get("trend_status")
            if prev_trend and prev_trend != tech.trend_status:
                if tech.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                    alert = Alert(
                        alert_type=AlertType.MA_BREAK,
                        code=code, name=name,
                        timestamp=now.strftime("%H:%M:%S"),
                        message=f"均线多头排列形成！{tech.trend_status.value}",
                        severity="normal",
                        current_price=price, change_pct=change_pct,
                        volume_ratio=vol_ratio,
                        related_indicator=f"MA5={tech.ma5:.2f} MA10={tech.ma10:.2f}",
                    )
                    if not self._is_deduped(code, AlertType.MA_BREAK):
                        alerts.append(alert)
                elif tech.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
                    alert = Alert(
                        alert_type=AlertType.MA_BREAK,
                        code=code, name=name,
                        timestamp=now.strftime("%H:%M:%S"),
                        message=f"均线空头排列形成！{tech.trend_status.value}",
                        severity="warning",
                        current_price=price, change_pct=change_pct,
                        volume_ratio=vol_ratio,
                        related_indicator=f"MA5={tech.ma5:.2f} MA10={tech.ma10:.2f}",
                    )
                    if not self._is_deduped(code, AlertType.MA_BREAK):
                        alerts.append(alert)

        # === 6. 跌破均线支撑 ===
        if rule.ma_support_alert and change_pct < 0:
            prev_price = self._previous_state.get(code, {}).get("price", 0)
            prev_ma5 = self._previous_state.get(code, {}).get("ma5", 0)
            if prev_price > prev_ma5 and price < tech.ma5:
                alert = Alert(
                    alert_type=AlertType.SUPPORT_BREAK,
                    code=code, name=name,
                    timestamp=now.strftime("%H:%M:%S"),
                    message=f"跌破MA5({tech.ma5:.2f})支撑，注意风险",
                    severity="warning",
                    current_price=price, change_pct=change_pct,
                    volume_ratio=vol_ratio,
                    related_indicator=f"MA5={tech.ma5:.2f}",
                )
                if not self._is_deduped(code, AlertType.SUPPORT_BREAK):
                    alerts.append(alert)

        return alerts

    # Rate-limit window: 10 minutes per stock per alert_type
    _RATE_LIMIT_SECONDS: int = 600

    def _is_deduped(self, code: str, alert_type: AlertType) -> bool:
        """
        Check if this (code, alert_type) was already alerted within the
        rate-limit window.  Returns True if the alert should be suppressed.
        On first occurrence (or after window expires), records the timestamp
        and returns False.
        """
        key = f"{code}:{alert_type.value}"
        now = datetime.now()
        last = self._last_alerts.get(key)
        if last is not None and (now - last).total_seconds() < self._RATE_LIMIT_SECONDS:
            return True  # suppress
        # Record this occurrence and allow
        self._last_alerts[key] = now
        return False

    def update_state(self, code: str, state: Dict):
        """更新监控状态"""
        self._previous_state[code] = state

    def send_alerts(self, alerts: List[Alert]):
        """发送预警（仅触发回调，不直接发送 Telegram，避免与 callback 重复）"""
        if not alerts:
            return

        # Accumulate for daily summary
        self._daily_alerts.extend(alerts)

        for alert in alerts:
            # 回调
            for cb in self._alert_callbacks:
                try:
                    cb(alert)
                except Exception:
                    pass

    def register_summary_callback(self, callback: Callable[[str], None]):
        """注册日报摘要回调"""
        self._summary_callbacks.append(callback)

    def maybe_send_summary(self, interval_hours: int = 2) -> Optional[str]:
        """
        If enough time has passed since the last summary, build and return
        a summary string and fire summary callbacks.  Returns None if not
        due yet.
        """
        now = datetime.now()
        if self._last_summary_time is None:
            self._last_summary_time = now
            return None

        if (now - self._last_summary_time).total_seconds() < interval_hours * 3600:
            return None

        if not self._daily_alerts:
            self._last_summary_time = now
            return None

        summary = self._build_summary()
        self._last_summary_time = now
        self._daily_alerts.clear()

        for cb in self._summary_callbacks:
            try:
                cb(summary)
            except Exception:
                pass

        return summary

    def _build_summary(self) -> str:
        """Build a text summary of accumulated alerts."""
        from collections import Counter
        type_counts = Counter(a.alert_type.value for a in self._daily_alerts)
        lines = [f"<b>📋 预警摘要</b> ({len(self._daily_alerts)} 条)"]
        for atype, count in type_counts.most_common():
            lines.append(f"  {atype}: {count}次")
        # List unique stocks
        stocks = {}
        for a in self._daily_alerts:
            stocks.setdefault(a.code, a.name)
        if stocks:
            lines.append("涉及个股:")
            for code, name in list(stocks.items())[:10]:
                lines.append(f"  {code} {name}")
        return "\n".join(lines)

    def start_monitoring(self, codes: List[str] = None, interval: int = 60):
        """
        启动实时监控（后台线程轮询）
        codes: 监控的股票列表，空=使用自选股
        interval: 轮询间隔（秒）
        """
        if self._running:
            return

        config = Config.get()
        watch_codes = codes or config.WATCH_LIST
        if not watch_codes:
            return

        self._running = True

        def _monitor_loop():
            while self._running:
                try:
                    for code in watch_codes:
                        alerts = self.check_and_alert(code)
                        if alerts:
                            self.send_alerts(alerts)

                        # 更新状态
                        quote = self._fetcher_mgr.get_quote(code) if self._fetcher_mgr else None
                        hist = self._fetcher_mgr.get_history(code, 20) if self._fetcher_mgr else None
                        if quote and hist is not None:
                            tech = self._tech_analyzer.analyze(hist, code=code, name="")
                            self._previous_state[code] = {
                                "price": quote.price,
                                "change_pct": quote.change_pct,
                                "volume_ratio": tech.volume_ratio,
                                "trend_status": tech.trend_status,
                                "ma5": tech.ma5,
                                "limit_up": quote.change_pct >= 9.9,
                                "sealed": quote.change_pct >= 9.9 and quote.high == quote.low,
                            }

                except Exception:
                    pass

                time.sleep(interval)

        self._monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        """停止监控"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None


# 全局实例
_alert_system: Optional[AlertSystem] = None

def get_alert_system() -> AlertSystem:
    global _alert_system
    if _alert_system is None:
        _alert_system = AlertSystem()
    return _alert_system
