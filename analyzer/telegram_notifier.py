"""
Telegram 通知模块（重构版）
参考 daily_stock_analysis 项目，输出专业的决策仪表盘格式报告
"""

import json
import re
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from rich.console import Console

from config import Config
from data_provider.stock_names import get_stock_name, resolve_stock_name

console = Console()

# Telegram 消息最大长度
TG_MAX_LEN = 4096


class TelegramNotifier:
    """Telegram Bot 通知器"""

    def __init__(self):
        self.config = Config.get()
        self.token = self.config.TELEGRAM_BOT_TOKEN
        self.chat_id = self.config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def get_bot_info(self) -> Optional[dict]:
        if not self.token:
            return None
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
        except Exception as e:
            console.print(f"[red]✗ 获取 Bot 信息失败: {e}[/red]")
        return None

    def get_updates(self) -> List[dict]:
        if not self.token:
            return []
        try:
            resp = requests.get(f"{self.base_url}/getUpdates", timeout=10)
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        except Exception as e:
            console.print(f"[red]✗ 获取更新失败: {e}[/red]")
        return []

    def find_chat_id(self) -> Optional[str]:
        updates = self.get_updates()
        for update in updates:
            msg = update.get("message") or update.get("my_chat_member", {})
            chat = msg.get("chat", {})
            if chat:
                return str(chat.get("id", ""))
        return None

    def send_message(self, text: str, chat_id: str = "", parse_mode: str = "HTML") -> bool:
        """发送消息（默认用 HTML 模式，比 Markdown 更稳定）"""
        if not self.token:
            return False

        target_chat = chat_id or self.chat_id
        if not target_chat:
            target_chat = self.find_chat_id()
            if target_chat:
                self.chat_id = target_chat
            else:
                return False

        try:
            payload = {
                "chat_id": target_chat,
                "text": text,
                "parse_mode": parse_mode,
            }
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=30,
            )
            data = resp.json()
            if data.get("ok"):
                return True
            else:
                # HTML 失败则尝试纯文本
                if parse_mode is not None:
                    return self.send_message(text, chat_id, parse_mode=None)
                return False
        except Exception as e:
            console.print(f"[red]✗ 发送 Telegram 消息失败: {e}[/red]")
            return False

    def send_photo(self, photo_path: str, caption: str = "", chat_id: str = "") -> bool:
        """发送图片"""
        if not self.token:
            return False
        target_chat = chat_id or self.chat_id
        if not target_chat:
            return False

        try:
            with open(photo_path, "rb") as f:
                payload = {
                    "chat_id": target_chat,
                    "caption": caption[:1024] if caption else "",
                }
                resp = requests.post(
                    f"{self.base_url}/sendPhoto",
                    data=payload,
                    files={"photo": f},
                    timeout=60,
                )
                return resp.json().get("ok", False)
        except Exception as e:
            console.print(f"[red]✗ 发送图片失败: {e}[/red]")
            return False

    # ==================== 报告格式化（决策仪表盘） ====================

    def format_tech_report(self, tech, quote=None, ai_advice=None, signals=None) -> str:
        """
        格式化单只股票的完整分析报告
        参考原项目的 dashboard report 格式，使用 Telegram HTML
        """
        lines = []

        # 股票名称解析
        name = resolve_stock_name(tech.code, quote)
        change_pct = quote.change_pct if quote else 0
        arrow = "🟢" if change_pct > 0 else "🔴" if change_pct < 0 else "⚪"

        # 决策类型
        if tech.buy_score >= 60:
            decision = "买入"
            decision_emoji = "🟢"
        elif tech.buy_score >= 40:
            decision = "观望"
            decision_emoji = "🟡"
        else:
            decision = "卖出"
            decision_emoji = "🔴"

        # ===== 标题 =====
        lines.append(f"<b>{decision_emoji} {name}({tech.code}) {arrow}</b>")
        lines.append("")

        # ===== 核心结论 =====
        if ai_advice and hasattr(ai_advice, 'one_sentence') and ai_advice.one_sentence:
            lines.append(f"<b>📌 核心结论</b>")
            lines.append(f"  {ai_advice.one_sentence}")
            lines.append(f"  决策: <b>{decision}</b> | 评分: <b>{tech.buy_score}/100</b>")
            if hasattr(ai_advice, 'confidence') and ai_advice.confidence:
                lines.append(f"  信心: {ai_advice.confidence}% | 时间: {getattr(ai_advice, 'time_sensitivity', '中线')}")
            lines.append("")

        # ===== 行情快照 =====
        lines.append(f"<b>💰 行情快照</b>")
        price_str = f"  价格: <b>{tech.current_price:.2f}</b>"
        if quote:
            price_str += f"  涨跌: {change_pct:+.2f}%"
            if quote.high:
                price_str += f"  高: {quote.high:.2f}  低: {quote.low:.2f}"
        lines.append(price_str)
        lines.append("")

        # ===== 数据透视 =====
        lines.append(f"<b>📊 数据透视</b>")
        # 趋势
        trend = tech.trend_status.value
        lines.append(f"  趋势: {trend}")
        lines.append(f"  MA5={tech.ma5:.2f} MA10={tech.ma10:.2f} MA20={tech.ma20:.2f} MA60={tech.ma60:.2f}")
        # MACD
        lines.append(f"  MACD: {tech.macd_status.value} (DIF={tech.dif:.3f} DEA={tech.dea:.3f})")
        # RSI
        lines.append(f"  RSI6={tech.rsi6:.1f} RSI12={tech.rsi12:.1f} RSI24={tech.rsi24:.1f} → {tech.rsi_status.value}")
        # KDJ
        lines.append(f"  KDJ: K={tech.k_value:.1f} D={tech.d_value:.1f} J={tech.j_value:.1f}")
        # 布林带
        lines.append(f"  布林带: 位置{tech.boll_position:.0%} (上{tech.boll_upper:.2f} 中{tech.boll_middle:.2f} 下{tech.boll_lower:.2f})")
        # 成交量
        lines.append(f"  成交量: 量比={tech.volume_ratio:.2f} {tech.volume_status.value}")
        # 乖离率
        lines.append(f"  乖离率: BIAS5={tech.bias5:.2f}% BIAS10={tech.bias10:.2f}%")
        lines.append("")

        # ===== 支撑/压力位 =====
        lines.append(f"<b>📍 关键点位</b>")
        if tech.support_levels:
            lines.append(f"  支撑: {' / '.join(f'{x:.2f}' for x in tech.support_levels[:3])}")
        if tech.resistance_levels:
            lines.append(f"  压力: {' / '.join(f'{x:.2f}' for x in tech.resistance_levels[:3])}")
        lines.append("")

        # ===== AI 作战计划 =====
        if ai_advice:
            lines.append(f"<b>🎯 作战计划</b>")
            if ai_advice.entry_price:
                lines.append(f"  理想买入: {ai_advice.entry_price:.2f}")
            if ai_advice.stop_loss:
                lines.append(f"  止损: {ai_advice.stop_loss:.2f}")
            if ai_advice.target_price:
                lines.append(f"  目标: {ai_advice.target_price:.2f}")
            if ai_advice.stop_loss and ai_advice.target_price:
                risk_reward = (ai_advice.target_price - tech.current_price) / (tech.current_price - ai_advice.stop_loss) if tech.current_price > ai_advice.stop_loss else 0
                lines.append(f"  盈亏比: {risk_reward:.1f}:1")
            if hasattr(ai_advice, 'battle_plan') and ai_advice.battle_plan:
                bp = ai_advice.battle_plan
                if bp.get('suggested_position'):
                    lines.append(f"  建议仓位: {bp['suggested_position']}")
                if bp.get('risk_control'):
                    lines.append(f"  风控: {bp['risk_control']}")
            lines.append("")

            # 持仓建议
            if hasattr(ai_advice, 'position_advice') and ai_advice.position_advice:
                pa = ai_advice.position_advice
                lines.append(f"<b>💼 持仓建议</b>")
                if pa.get('no_position'):
                    lines.append(f"  空仓: {pa['no_position']}")
                if pa.get('has_position'):
                    lines.append(f"  持仓: {pa['has_position']}")
                lines.append("")

            # AI 详细分析
            if hasattr(ai_advice, 'analysis_detail') and ai_advice.analysis_detail:
                lines.append(f"<b>🤖 AI 解读</b>")
                lines.append(f"  {ai_advice.analysis_detail}")
                lines.append("")

            # 看多因素
            if ai_advice.key_factors:
                lines.append(f"<b>✅ 看多因素</b>")
                for f in ai_advice.key_factors[:3]:
                    lines.append(f"  • {f}")
                lines.append("")

            # 风险提示
            if ai_advice.risk_warnings:
                lines.append(f"<b>⚠️ 风险提示</b>")
                for f in ai_advice.risk_warnings[:3]:
                    lines.append(f"  • {f}")
                lines.append("")

        # ===== 策略信号 =====
        if signals:
            lines.append(f"<b>📐 策略信号</b>")
            for s in signals[:3]:
                emoji = "🟢" if s.signal_type == "买入" else "🔴" if s.signal_type == "卖出" else "🟡"
                lines.append(f"  {emoji} {s.strategy_name}: {s.signal_type} ({s.strength:.0%})")
            lines.append("")

        # ===== 操作建议汇总 =====
        score_emoji = "🟢" if tech.buy_score >= 60 else "🟡" if tech.buy_score >= 40 else "🔴"
        lines.append(f"{score_emoji} <b>综合评分: {tech.buy_score}/100 → {tech.operation}</b>")
        if tech.operation_reason:
            lines.append(f"  {tech.operation_reason}")

        return "\n".join(lines)

    def format_dashboard_report(self, results: list, phase: str = "full") -> str:
        """
        生成决策仪表盘格式的汇总报告
        类似原项目的 generate_dashboard_report()

        Args:
            results: 分析结果列表，每项包含 (code, tech, quote, ai_advice, signals)
            phase: 分析阶段

        Returns:
            Telegram HTML 格式的汇总报告
        """
        if not results:
            return "⚠ 无分析结果"

        # 统计
        buy_count = sum(1 for r in results if r.get('tech').buy_score >= 60)
        sell_count = sum(1 for r in results if r.get('tech').buy_score < 40)
        hold_count = len(results) - buy_count - sell_count

        phase_names = {
            "pre_market": "🌅 盘前分析",
            "mid_day": "☀️ 午盘分析",
            "after_close": "🌙 收市分析",
            "full": "📊 完整分析",
        }
        phase_name = phase_names.get(phase, "📊 分析")

        lines = []
        lines.append(f"<b>🎯 {phase_name} {datetime.now().strftime('%Y-%m-%d %H:%M')}</b>")
        lines.append(f"分析 {len(results)} 只 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}")
        lines.append("")

        # 按评分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.get('tech').buy_score, reverse=True)

        # ===== 汇总表 =====
        lines.append(f"<b>📊 评分汇总</b>")
        for r in sorted_results:
            tech = r.get('tech')
            quote = r.get('quote')
            name = resolve_stock_name(tech.code, quote)
            change_pct = quote.change_pct if quote else 0
            score = tech.buy_score

            if score >= 60:
                emoji = "🟢"
            elif score >= 40:
                emoji = "🟡"
            else:
                emoji = "🔴"

            lines.append(f"  {emoji} {name}({tech.code}): {score}分 {tech.operation} | {change_pct:+.2f}%")
        lines.append("")

        return "\n".join(lines)

    def format_market_report(self, overview) -> str:
        """格式化市场总览报告"""
        lines = ["<b>📋 A股市场总览</b>", ""]

        for name, idx in overview.indices.items():
            arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
            lines.append(f"  {arrow} {name}: {idx.price:.2f} ({idx.change_pct:+.2f}%)")

        lines.append("")
        total = overview.up_count + overview.down_count + overview.flat_count
        if total > 0:
            lines.append(f"  📈 上涨: {overview.up_count}  📉 下跌: {overview.down_count}")
            lines.append(f"  涨停: {overview.limit_up_count}  跌停: {overview.limit_down_count}")

        if overview.top_sectors:
            lines.append("")
            lines.append(f"<b>🔥 领涨板块</b>")
            for s in overview.top_sectors[:3]:
                lines.append(f"  🟢 {s.name}: {s.change_pct:+.2f}%")

        return "\n".join(lines)

    def format_sentiment_report(self, sentiment) -> str:
        """格式化市场情绪报告"""
        emoji = {
            "极寒": "💨", "恐惧": "😰", "低迷": "😟",
            "中性": "😐", "回暖": "🙂", "活跃": "😊", "高潮": "🔥",
        }.get(sentiment.sentiment_label, "🌡️")

        lines = [
            f"<b>{emoji} 市场情绪: {sentiment.sentiment_label} ({sentiment.sentiment_score:.0f}/100)</b>",
            f"  涨停: {sentiment.limit_up_count}家 | 跌停: {sentiment.limit_down_count}家",
            f"  上涨: {sentiment.advance_count}家 | 下跌: {sentiment.decline_count}家",
        ]
        if hasattr(sentiment, 'limit_up_broken_rate') and sentiment.limit_up_broken_rate > 0:
            lines.append(f"  炸板率: {sentiment.limit_up_broken_rate:.1f}%")
        if hasattr(sentiment, 'continuity_height') and sentiment.continuity_height > 0:
            lines.append(f"  连板高度: {sentiment.continuity_height}板")
        if hasattr(sentiment, 'hsgt_net_value') and sentiment.hsgt_net_value:
            lines.append(f"  北向净流入: {sentiment.hsgt_net_value:+.2f}亿")
        if hasattr(sentiment, 'hot_sectors') and sentiment.hot_sectors:
            lines.append(f"  热门板块: {', '.join(sentiment.hot_sectors[:3])}")

        return "\n".join(lines)

    # ==================== 紧凑仪表盘（新版，减少消息数） ====================

    def format_compact_dashboard(
        self,
        results: list,
        phase: str = "full",
        sentiment=None,
        score_deltas: dict = None,
        regime_result=None,
    ) -> str:
        """
        紧凑仪表盘：所有 15 只股票放一条消息，评分+操作+涨跌幅+变化箭头

        Args:
            results: 分析结果列表，每项 {'code','tech','quote','ai_advice','signals'}
            phase: 分析阶段
            sentiment: MarketSentiment 对象 (可选)
            score_deltas: {code: delta} 评分变化量 (可选)
            regime_result: RegimeResult 市场状态 (可选)
        """
        if not results:
            return "⚠ 无分析结果"

        # 统计
        buy_count = sum(1 for r in results if r.get("tech").buy_score >= 60)
        sell_count = sum(1 for r in results if r.get("tech").buy_score < 40)
        hold_count = len(results) - buy_count - sell_count

        phase_names = {
            "pre_market": "🌅 盘前分析",
            "mid_day": "☀️ 午盘分析",
            "after_close": "🌙 收市分析",
            "full": "📊 完整分析",
        }
        phase_name = phase_names.get(phase, "📊 分析")
        score_deltas = score_deltas or {}

        lines = []
        lines.append(f"<b>🎯 {phase_name} {datetime.now().strftime('%Y-%m-%d %H:%M')}</b>")
        lines.append(f"分析{len(results)}只 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}")
        lines.append("")
        lines.append("<b>📊 自选股评分</b>")

        # 按评分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.get("tech").buy_score, reverse=True)

        for r in sorted_results:
            tech = r.get("tech")
            quote = r.get("quote")
            name = resolve_stock_name(tech.code, quote)
            change_pct = quote.change_pct if quote else 0
            score = tech.buy_score

            if score >= 60:
                emoji = "🟢"
            elif score >= 40:
                emoji = "🟡"
            else:
                emoji = "🔴"

            # 评分变化指示
            delta_str = ""
            delta = score_deltas.get(tech.code)
            if delta is not None:
                if delta >= 15:
                    delta_str = f" ⬆️{delta:+d}"
                elif delta <= -15:
                    delta_str = f" ⬇️{delta:+d}"
                elif abs(delta) >= 5:
                    delta_str = f" {delta:+d}"

            # Resonance indicator
            resonance_icon = ""
            resonance = getattr(tech, 'resonance_score', 0.0)
            if resonance >= 0.7:
                resonance_icon = " 🔥"
            elif resonance >= 0.5:
                resonance_icon = " ⚡"

            lines.append(
                f"  {emoji} {name}({tech.code}): {score}分 {tech.operation} | {change_pct:+.2f}%{delta_str}{resonance_icon}"
            )

        # 紧凑市场情绪（追加到仪表盘末尾）
        if sentiment:
            lines.append("")
            sent_emoji = {
                "极寒": "💨", "恐惧": "😰", "低迷": "😟",
                "中性": "😐", "回暖": "🙂", "活跃": "😊", "高潮": "🔥",
            }.get(sentiment.sentiment_label, "🌡️")

            sentiment_line = (
                f"🌡️ 市场情绪: {sent_emoji}{sentiment.sentiment_label} "
                f"({sentiment.sentiment_score:.0f}/100)"
            )
            extras = []
            extras.append(f"涨停:{sentiment.limit_up_count}家")
            extras.append(f"跌停:{sentiment.limit_down_count}家")
            if hasattr(sentiment, "hsgt_net_value") and sentiment.hsgt_net_value:
                extras.append(f"北向{sentiment.hsgt_net_value:+.1f}亿")
            sentiment_line += " | " + " | ".join(extras)
            lines.append(sentiment_line)

        # 市场状态（追加到仪表盘末尾）
        if regime_result:
            from analyzer.market_regime import MarketRegimeDetector
            regime_detector = MarketRegimeDetector()
            lines.append(regime_detector.format_regime_line(regime_result))

        # 底部时间戳（追加到仪表盘末尾）
        lines.append(f"⏰ {datetime.now().strftime('%H:%M')} | {len(results)}/{len(results)}只")

        return "\n".join(lines)

    def format_stock_highlights(
        self,
        results: list,
        score_deltas: dict = None,
        prev_scores: dict = None,
    ) -> list:
        """
        为"高亮"股票生成紧凑报告列表

        高亮条件：
        - 评分变化 >= 15 (突变)
        - 评分 >= 75 (强买入)
        - 评分 < 30 (强卖出)
        - 决策类型翻转 (buy ↔ sell)

        Returns:
            list of dict: [{'code', 'name', 'tech', 'quote', 'ai_advice',
                            'reason', 'chart_path'}]
            只包含满足高亮条件的股票
        """
        score_deltas = score_deltas or {}
        prev_scores = prev_scores or {}
        highlights = []

        for r in results:
            tech = r.get("tech")
            quote = r.get("quote")
            ai_advice = r.get("ai_advice")
            code = tech.code

            score = tech.buy_score
            delta = score_deltas.get(code, 0)
            reasons = []

            # 检查高亮条件
            if abs(delta) >= 15:
                reasons.append(f"评分突变{delta:+d}")

            if score >= 75:
                reasons.append("强买入信号")

            if score < 30:
                reasons.append("强卖出信号")

            # 决策类型翻转
            if code in prev_scores:
                prev_score = prev_scores[code]
                if (prev_score >= 60 and score < 40) or (prev_score < 40 and score >= 60):
                    reasons.append("决策翻转")

            if reasons:
                name = resolve_stock_name(code, quote)
                highlights.append({
                    "code": code,
                    "name": name,
                    "tech": tech,
                    "quote": quote,
                    "ai_advice": ai_advice,
                    "signals": r.get("signals", []),
                    "reason": " | ".join(reasons),
                })

        # 按评分排序：高分的优先
        highlights.sort(key=lambda x: x["tech"].buy_score, reverse=True)
        return highlights

    def format_highlight_report(self, highlight: dict) -> str:
        """
        生成单只高亮股票的紧凑报告（~200-300 字）

        Args:
            highlight: format_stock_highlights 返回的字典
        """
        tech = highlight["tech"]
        quote = highlight["quote"]
        ai_advice = highlight["ai_advice"]
        name = highlight["name"]
        code = highlight["code"]
        reason = highlight["reason"]

        score = tech.buy_score
        change_pct = quote.change_pct if quote else 0

        if score >= 60:
            emoji, decision = "🟢", "买入"
        elif score >= 40:
            emoji, decision = "🟡", "观望"
        else:
            emoji, decision = "🔴", "卖出"

        lines = []
        lines.append(f"<b>{emoji} {name}({code}) {score}分 {decision}</b> [{reason}]")
        lines.append(f"  💰 {tech.current_price:.2f} ({change_pct:+.2f}%) | {tech.operation}")

        # AI 一句话结论
        if ai_advice:
            if hasattr(ai_advice, "one_sentence") and ai_advice.one_sentence:
                lines.append(f"  📌 {ai_advice.one_sentence}")
            elif ai_advice.summary:
                lines.append(f"  📌 {ai_advice.summary}")

        # 关键价位
        price_parts = []
        if ai_advice:
            if ai_advice.entry_price:
                price_parts.append(f"买入:{ai_advice.entry_price:.2f}")
            if ai_advice.stop_loss:
                price_parts.append(f"止损:{ai_advice.stop_loss:.2f}")
            if ai_advice.target_price:
                price_parts.append(f"目标:{ai_advice.target_price:.2f}")
        if tech.support_levels:
            price_parts.append(f"支撑:{tech.support_levels[0]:.2f}")
        if tech.resistance_levels:
            price_parts.append(f"压力:{tech.resistance_levels[0]:.2f}")
        if price_parts:
            lines.append(f"  📍 {' | '.join(price_parts)}")

        # 策略信号（最多2条）
        signals = highlight.get("signals", [])
        if signals:
            sig_parts = []
            for s in signals[:2]:
                s_emoji = "🟢" if s.signal_type == "买入" else "🔴" if s.signal_type == "卖出" else "🟡"
                sig_parts.append(f"{s_emoji}{s.strategy_name}:{s.signal_type}")
            lines.append(f"  📐 {' '.join(sig_parts)}")

        return "\n".join(lines)

    # ==================== 消息分割 ====================

    def split_message(self, text: str, max_len: int = TG_MAX_LEN) -> list:
        """智能分割消息（按 --- 分隔线切分，保证不超过 Telegram 限制）"""
        if len(text) <= max_len:
            return [text]

        chunks = []
        # 优先按 --- 分割
        sections = text.split("\n---\n")

        current = ""
        for section in sections:
            if len(current) + len(section) + 5 > max_len:
                if current:
                    chunks.append(current)
                # 如果单个 section 太长，按行分割
                if len(section) > max_len:
                    lines = section.split("\n")
                    current = ""
                    for line in lines:
                        if len(current) + len(line) + 1 > max_len:
                            if current:
                                chunks.append(current)
                            current = line
                        else:
                            current += "\n" + line if current else line
                else:
                    current = section
            else:
                current += "\n---\n" + section if current else section

        if current:
            chunks.append(current)

        return chunks


def get_notifier() -> Optional[TelegramNotifier]:
    """获取通知器实例"""
    notifier = TelegramNotifier()
    if notifier.is_configured:
        return notifier
    return None
