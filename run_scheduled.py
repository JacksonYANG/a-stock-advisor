#!/usr/bin/env python3
"""
A股定时分析脚本（紧凑通知版）
每天 3 个阶段 × 2-3 条消息 = 6-9 条/天（原来 100-150 条/天）

通知策略：
  pre_market:  2 条 = 紧凑仪表盘 + 高亮个股（最多 3 图）
  mid_day:     1-2 条 = 紧凑仪表盘（有变化时追加高亮）
  after_close: 2-3 条 = 紧凑仪表盘 + 高亮个股 + Top Picks
"""

import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import matplotlib
matplotlib.use('Agg')

from config import Config
from data_provider.base import DataFetcherManager
from analyzer.technical import TechnicalAnalyzer
from analyzer.ai_advisor import AIAdvisor
from analyzer.visualization import ChartGenerator
from analyzer.strategy_engine import get_strategy_engine
from analyzer.telegram_notifier import TelegramNotifier
from analyzer.score_history import save_scores, get_previous_scores, get_score_delta
from data_provider.stock_names import resolve_stock_name
from analyzer.market import MarketAnalyzer
from analyzer.market_sentiment import get_sentiment_analyzer
from analyzer.market_regime import MarketRegimeDetector
from utils.trading_calendar import is_trading_day


# 每阶段最多发送的高亮图表数
MAX_CHARTS_PER_PHASE = 3


def _analyze_all_stocks(codes, config, manager, tech_analyzer, engine, ai_advisor):
    """分析所有自选股，返回结果列表和评分映射"""
    all_results = []
    ai_available = ai_advisor.is_available
    current_scores = {}

    for code in codes:
        try:
            code = code.strip().zfill(6)
            quote = manager.get_quote(code)
            hist = manager.get_history(code, config.HISTORY_DAYS)
            if hist is None or hist.empty:
                print(f"  ✗ {code}: 无法获取数据")
                continue

            name = resolve_stock_name(code, quote)
            tech_result = tech_analyzer.analyze(hist, code=code, name=name)

            # 策略分析
            signals = []
            if engine:
                try:
                    adjusted_score, signals = engine.get_enhanced_score(tech_result)
                    tech_result.buy_score = adjusted_score
                    if adjusted_score >= 60:
                        tech_result.operation = "逢低买入"
                    elif adjusted_score >= 45:
                        tech_result.operation = "持有观望"
                    else:
                        tech_result.operation = "考虑卖出"
                except Exception:
                    pass

            # AI 分析
            ai_advice = None
            if ai_available:
                try:
                    ai_advice = ai_advisor.analyze(tech_result)
                except Exception as e:
                    print(f"    AI 分析 {code} 失败: {e}")

            # 生成图表路径（但不立刻发送）
            chart_path = ""
            try:
                gen = ChartGenerator()
                chart_path = gen.plot_kline_with_indicators(
                    hist, code=code, name=name,
                    buy_score=tech_result.buy_score,
                    operation=tech_result.operation,
                )
            except Exception:
                pass

            all_results.append({
                'code': code,
                'tech': tech_result,
                'quote': quote,
                'ai_advice': ai_advice,
                'signals': signals,
                'chart_path': chart_path,
            })
            current_scores[code] = tech_result.buy_score
            print(f"  ✓ {code} {name}: 评分={tech_result.buy_score} 操作={tech_result.operation}")

        except Exception as e:
            print(f"  ✗ {code}: 分析失败 - {e}")

    return all_results, current_scores


def run_analysis(phase: str = "full"):
    """
    执行分析并发送紧凑通知

    Args:
        phase: 分析阶段
            - pre_market: 盘前分析 (09:20)
            - mid_day: 午盘分析 (12:30)
            - after_close: 收市分析 (17:00)
            - full: 完整分析
    """
    config = Config.get()
    notifier = TelegramNotifier()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始 {phase} 分析...")

    if not is_trading_day():
        msg = "📅 今天不是交易日，跳过分析"
        print(msg)
        notifier.send_message(msg)
        return

    codes = config.WATCH_LIST
    if not codes:
        msg = "⚠ 未配置自选股 (WATCH_LIST)"
        notifier.send_message(msg)
        return

    # ===== 1. 获取市场情绪（但不单独发送，稍后追加到仪表盘） =====
    sentiment = None
    try:
        sentiment = get_sentiment_analyzer().get_sentiment()
        print("  ✓ 市场情绪已获取")
    except Exception as e:
        print(f"  市场情绪失败: {e}")

    # ===== 2. 获取历史评分（用于检测突变） =====
    prev_scores = get_previous_scores(phase)

    # ===== 2.5 检测市场状态（牛/熊/震荡/反弹/回调） =====
    regime_result = None
    try:
        regime_detector = MarketRegimeDetector()
        regime_result = regime_detector.detect()
        print(f"  ✓ 市场状态: {regime_result.regime.value} (信心{regime_result.confidence:.0%})")
    except Exception as e:
        print(f"  市场状态检测失败: {e}")

    # ===== 3. 分析所有自选股 =====
    manager = DataFetcherManager()
    manager.register_sources(config.DATA_SOURCES)
    tech_analyzer = TechnicalAnalyzer()

    try:
        engine = get_strategy_engine()
    except Exception:
        engine = None

    ai_advisor = AIAdvisor()

    all_results, current_scores = _analyze_all_stocks(
        codes, config, manager, tech_analyzer, engine, ai_advisor,
    )

    if not all_results:
        notifier.send_message("⚠ 未能分析任何股票")
        return

    # ===== 3.5 根据市场状态调整评分 =====
    if regime_result and regime_result.score_adjust != 0:
        for r in all_results:
            tech = r['tech']
            original = tech.buy_score
            tech.buy_score = max(0, min(100, original + regime_result.score_adjust))
            if tech.buy_score != original:
                print(f"    {tech.code}: 评分 {original}→{tech.buy_score} (市场状态调整{regime_result.score_adjust:+d})")
            # 更新 operation
            if tech.buy_score >= 60:
                tech.operation = "逢低买入"
            elif tech.buy_score >= 45:
                tech.operation = "持有观望"
            else:
                tech.operation = "考虑卖出"
        # 重新计算 current_scores
        current_scores = {r['code']: r['tech'].buy_score for r in all_results}

    # ===== 4. 计算评分变化 =====
    score_deltas = get_score_delta(current_scores, prev_scores)

    # ===== 5. 发送紧凑仪表盘（第 1 条消息） =====
    dashboard_msg = notifier.format_compact_dashboard(
        all_results, phase, sentiment=sentiment, score_deltas=score_deltas,
        regime_result=regime_result,
    )
    notifier.send_message(dashboard_msg)
    print("  ✓ 仪表盘已发送")

    # ===== 6. 识别高亮股票 =====
    highlights = notifier.format_stock_highlights(
        all_results, score_deltas=score_deltas, prev_scores=prev_scores,
    )

    # mid_day 阶段：只有评分有变化时才发高亮
    if phase == "mid_day" and not highlights:
        # 保存当前评分并结束
        save_scores(phase, current_scores)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 午盘分析完成（无高亮），共 {len(all_results)}/{len(codes)} 只")
        return

    # ===== 7. 发送高亮报告（第 2 条消息，最多 MAX_CHARTS_PER_PHASE 张图） =====
    if highlights:
        # 合并所有高亮报告为一条消息
        highlight_parts = []
        for i, h in enumerate(highlights):
            highlight_parts.append(notifier.format_highlight_report(h))

        # 分隔各只股票
        highlight_msg = "\n\n".join(highlight_parts)

        # 如果消息太长，拆分发送
        for chunk in notifier.split_message(highlight_msg):
            notifier.send_message(chunk)
        print(f"  ✓ 高亮报告已发送 ({len(highlights)} 只)")

        # 发送高亮股票的图表（最多 MAX_CHARTS_PER_PHASE 张）
        charts_sent = 0
        for h in highlights:
            if charts_sent >= MAX_CHARTS_PER_PHASE:
                break
            chart_path = h.get("chart_path") or ""
            if chart_path and os.path.exists(chart_path):
                tech = h["tech"]
                score_emoji = "🟢" if tech.buy_score >= 60 else "🟡" if tech.buy_score >= 40 else "🔴"
                caption = (
                    f"{h['name']}({h['code']}) {tech.current_price:.2f} "
                    f"{score_emoji}{tech.buy_score}分 {tech.operation}"
                )
                notifier.send_photo(chart_path, caption=caption)
                charts_sent += 1
        if charts_sent:
            print(f"  ✓ 已发送 {charts_sent} 张图表")

    # ===== 8. after_close 阶段：追加 Top Picks 详情 =====
    if phase == "after_close" and highlights:
        # 筛选评分最高的 2 只作为 Top Picks
        top_picks = sorted(highlights, key=lambda x: x["tech"].buy_score, reverse=True)[:2]
        if len(top_picks) >= 1:
            pick = top_picks[0]
            tech = pick["tech"]
            ai_advice = pick.get("ai_advice")
            name = pick["name"]
            code = pick["code"]
            quote = pick.get("quote")
            change_pct = quote.change_pct if quote else 0

            lines = []
            lines.append(f"<b>⭐ 今日精选: {name}({code})</b>")
            lines.append(f"  评分 {tech.buy_score}/100 | {change_pct:+.2f}%")
            lines.append(f"  趋势: {tech.trend_status.value} | MACD: {tech.macd_status.value}")
            lines.append(f"  RSI: {tech.rsi6:.0f} | 量比: {tech.volume_ratio:.2f}")

            if ai_advice:
                if hasattr(ai_advice, "analysis_detail") and ai_advice.analysis_detail:
                    lines.append(f"  🤖 {ai_advice.analysis_detail[:200]}")
                if ai_advice.risk_warnings:
                    lines.append(f"  ⚠️ {' | '.join(ai_advice.risk_warnings[:2])}")

            notifier.send_message("\n".join(lines))
            print("  ✓ Top Picks 已发送")

    # ===== 9. 保存当前评分 =====
    save_scores(phase, current_scores)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {phase} 分析完成，共 {len(all_results)}/{len(codes)} 只股票")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "full"
    run_analysis(phase)
