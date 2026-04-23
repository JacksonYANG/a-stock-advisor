#!/usr/bin/env python3
"""
A股交易决策辅助系统 - 主入口
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from config import Config
from data_provider.base import DataFetcherManager
from analyzer.technical import TechnicalAnalyzer, TechnicalResult
from analyzer.market import MarketAnalyzer
from analyzer.ai_advisor import AIAdvisor
from analyzer.visualization import ChartGenerator
from analyzer.strategy_engine import get_strategy_engine
from analyzer.telegram_notifier import get_notifier
from analyzer.backtest_engine import get_backtest_engine
from data_provider.storage import Database
from utils.trading_calendar import is_trading_day, get_last_trading_day
from utils.formatting import format_number, format_percent, format_volume, format_amount, colorize_change

console = Console()


def get_data_manager() -> DataFetcherManager:
    """获取数据管理器"""
    config = Config.get()
    manager = DataFetcherManager()
    manager.register_sources(config.DATA_SOURCES)
    return manager


def analyze_single_stock(code: str, ai: bool = True, chart: bool = True) -> dict:
    """
    分析单只股票

    Returns:
        包含所有分析结果的字典
    """
    config = Config.get()
    manager = get_data_manager()
    tech_analyzer = TechnicalAnalyzer()
    db = Database()

    code = code.strip().zfill(6)
    console.print(f"\n[bold cyan]📡 正在获取 {code} 数据...[/bold cyan]")

    # 1. 获取实时行情
    quote = manager.get_quote(code)

    # 2. 获取历史数据
    hist = manager.get_history(code, config.HISTORY_DAYS)
    if hist is None or hist.empty:
        console.print(f"[red]✗ 无法获取 {code} 的历史数据[/red]")
        return None

    console.print(f"[green]✓ 获取到 {len(hist)} 天历史数据[/green]")

    # 3. 技术分析
    console.print("[dim]📊 正在进行技术分析...[/dim]")
    name = quote.name if quote else ""
    tech_result = tech_analyzer.analyze(hist, code=code, name=name)

    # 3.5 策略分析
    signals = []
    try:
        engine = get_strategy_engine()
        adjusted_score, signals = engine.get_enhanced_score(tech_result)
        if adjusted_score != tech_result.buy_score:
            console.print(f"[dim]📐 策略调整评分: {tech_result.buy_score} → {adjusted_score}[/dim]")
            tech_result.buy_score = adjusted_score
            # 重新计算操作建议
            if adjusted_score >= 75:
                tech_result.operation = "积极买入"
                tech_result.operation_reason = "多项技术指标+策略信号共振看多"
            elif adjusted_score >= 60:
                tech_result.operation = "逢低买入"
                tech_result.operation_reason = "技术面偏多，策略信号支持"
            elif adjusted_score >= 45:
                tech_result.operation = "持有观望"
                tech_result.operation_reason = "多空分歧较大，等待方向明确"
            elif adjusted_score >= 30:
                tech_result.operation = "减仓观望"
                tech_result.operation_reason = "技术面偏空，注意风控"
            else:
                tech_result.operation = "考虑卖出"
                tech_result.operation_reason = "多项技术指标+策略信号看空"
    except Exception as e:
        console.print(f"[yellow]⚠ 策略分析失败: {e}[/yellow]")

    # 4. AI 分析 (可选)
    ai_advice = None
    if ai:
        advisor = AIAdvisor()
        if advisor.is_available:
            console.print("[dim]🤖 正在进行 AI 分析...[/dim]")
            ai_advice = advisor.analyze(tech_result)

    # 5. 生成图表 (可选)
    chart_path = ""
    if chart:
        try:
            gen = ChartGenerator()
            chart_path = gen.plot_kline_with_indicators(
                hist, code=code, name=name,
                buy_score=tech_result.buy_score,
                operation=tech_result.operation,
            )
            console.print(f"[green]✓ 图表已保存: {chart_path}[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ 图表生成失败: {e}[/yellow]")

    # 6. 保存到数据库
    try:
        result_dict = {
            "code": code,
            "name": name,
            "current_price": tech_result.current_price,
            "change_pct": quote.change_pct if quote else 0,
            "trend_status": tech_result.trend_status.value,
            "macd_status": tech_result.macd_status.value,
            "rsi_status": tech_result.rsi_status.value,
            "rsi6": tech_result.rsi6,
            "rsi12": tech_result.rsi12,
            "rsi24": tech_result.rsi24,
            "ma5": tech_result.ma5,
            "ma10": tech_result.ma10,
            "ma60": tech_result.ma60,
            "buy_score": tech_result.buy_score,
            "operation": tech_result.operation,
            "operation_reason": tech_result.operation_reason,
        }
        db.save_analysis(result_dict)
    except Exception as e:
        console.print(f"[yellow]⚠ 保存数据库失败: {e}[/yellow]")

    # 7. 输出结果
    _display_result(tech_result, quote, ai_advice, chart_path)

    # 8. 策略信号输出
    if signals:
        console.print("\n[bold blue]📐 策略信号:[/bold blue]")
        for s in signals[:5]:
            console.print(f"  {s.to_summary()}")

    # 9. Telegram 通知
    try:
        notifier = get_notifier()
        if notifier:
            report = notifier.format_tech_report(tech_result, quote, ai_advice, signals)
            if notifier.send_message(report):
                console.print("[dim]✓ Telegram 通知已发送[/dim]")
            if chart_path:
                notifier.send_photo(chart_path, caption=f"{tech_result.code} {tech_result.name} K线图")
    except Exception as e:
        console.print(f"[yellow]⚠ Telegram 通知失败: {e}[/yellow]")

    return {
        "code": code,
        "quote": quote,
        "tech": tech_result,
        "ai_advice": ai_advice,
        "chart_path": chart_path,
        "signals": signals,
    }


def _display_result(tech: TechnicalResult, quote, ai_advice, chart_path: str):
    """美化输出分析结果"""
    # 行情摘要
    if quote:
        change_color = "red" if quote.change_pct > 0 else "green" if quote.change_pct < 0 else "white"
        console.print(Panel(
            f"[bold]{tech.code} {tech.name}[/bold]\n"
            f"当前价: [bold]{format_number(tech.current_price)}[/bold]  "
            f"涨跌幅: [{change_color}]{format_percent(quote.change_pct)}[/{change_color}]  "
            f"今开: {format_number(quote.open)}  "
            f"最高: {format_number(quote.high)}  "
            f"最低: {format_number(quote.low)}",
            title="💰 行情",
            border_style="cyan",
        ))

    # 技术指标表格
    table = Table(title="📊 技术指标", show_header=True, header_style="bold magenta")
    table.add_column("指标", style="cyan", width=15)
    table.add_column("数值", style="white", width=30)
    table.add_column("状态", style="yellow", width=15)

    table.add_row("均线趋势",
                  f"MA5={format_number(tech.ma5)} MA10={format_number(tech.ma10)} MA20={format_number(tech.ma20)} MA60={format_number(tech.ma60)}",
                  tech.trend_status.value)
    table.add_row("MACD",
                  f"DIF={tech.dif:.4f} DEA={tech.dea:.4f} BAR={tech.macd_bar:.4f}",
                  tech.macd_status.value)
    table.add_row("RSI",
                  f"RSI6={tech.rsi6:.1f} RSI12={tech.rsi12:.1f} RSI24={tech.rsi24:.1f}",
                  tech.rsi_status.value)
    table.add_row("KDJ",
                  f"K={tech.k_value:.1f} D={tech.d_value:.1f} J={tech.j_value:.1f}", "")
    table.add_row("布林带",
                  f"上={format_number(tech.boll_upper)} 中={format_number(tech.boll_middle)} 下={format_number(tech.boll_lower)}",
                  f"位置:{tech.boll_position:.0%}")
    table.add_row("成交量",
                  f"量比={tech.volume_ratio:.2f}",
                  tech.volume_status.value)
    table.add_row("乖离率",
                  f"BIAS5={tech.bias5:.2f}% BIAS10={tech.bias10:.2f}%", "")

    console.print(table)

    # 综合评分
    score_color = "green" if tech.buy_score >= 60 else "yellow" if tech.buy_score >= 40 else "red"
    op_color = "green" if "买入" in tech.operation else "red" if "卖出" in tech.operation else "yellow"

    console.print(Panel(
        f"综合评分: [bold {score_color}]{tech.buy_score}/100[/bold {score_color}]\n"
        f"操作建议: [bold {op_color}]{tech.operation}[/bold {op_color}] - {tech.operation_reason}\n\n"
        f"📍 支撑位: {', '.join(format_number(x) for x in tech.support_levels)}\n"
        f"🔴 压力位: {', '.join(format_number(x) for x in tech.resistance_levels)}",
        title="🎯 决策建议",
        border_style=score_color,
    ))

    # 看多/风险因素
    if tech.score_reasons:
        console.print("\n[bold green]✅ 看多因素:[/bold green]")
        for r in tech.score_reasons:
            console.print(f"  • {r}")

    if tech.risk_warnings:
        console.print("\n[bold red]⚠️ 风险提示:[/bold red]")
        for r in tech.risk_warnings:
            console.print(f"  • {r}")

    # AI 分析
    if ai_advice:
        console.print(Panel(
            f"[bold]{ai_advice.summary}[/bold]\n\n"
            f"操作: {ai_advice.operation}  |  风险: {ai_advice.risk_level}\n"
            f"建议买入: {format_number(ai_advice.entry_price)}  |  "
            f"止损: {format_number(ai_advice.stop_loss)}  |  "
            f"目标: {format_number(ai_advice.target_price)}\n"
            + (f"\n策略: {ai_advice.strategy}" if ai_advice.strategy else ""),
            title="🤖 AI 分析",
            border_style="blue",
        ))

    # 图表路径
    if chart_path:
        console.print(f"\n[dim]📈 K线图: {chart_path}[/dim]")


# ==================== CLI 命令 ====================

@click.group()
@click.option("--debug", is_flag=True, help="调试模式")
def cli(debug):
    """📈 A股交易决策辅助系统"""
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)


@cli.command()
@click.option("--stock", "-s", help="单只股票代码")
@click.option("--stocks", "-S", help="多只股票代码，逗号分隔")
@click.option("--no-ai", is_flag=True, help="不使用AI分析")
@click.option("--no-chart", is_flag=True, help="不生成图表")
@click.option("--watchlist", "-w", is_flag=True, help="分析自选股列表")
def analyze(stock, stocks, no_ai, no_chart, watchlist):
    """📊 分析股票"""
    console.print(Panel.fit(
        "[bold]📈 A股交易决策辅助系统[/bold]",
        border_style="cyan",
    ))

    config = Config.get()
    codes = []

    if stock:
        codes.append(stock)
    if stocks:
        codes.extend(s.strip() for s in stocks.split(",") if s.strip())
    if watchlist:
        codes.extend(config.WATCH_LIST)

    if not codes:
        console.print("[yellow]请指定要分析的股票: --stock 000001 或 --watchlist[/yellow]")
        return

    results = []
    for code in codes:
        try:
            result = analyze_single_stock(code, ai=not no_ai, chart=not no_chart)
            if result:
                results.append(result)
        except Exception as e:
            console.print(f"[red]✗ 分析 {code} 失败: {e}[/red]")

    # 汇总表
    if len(results) > 1:
        console.print("\n")
        summary_table = Table(title="📊 分析汇总", show_header=True, header_style="bold magenta")
        summary_table.add_column("代码", style="cyan")
        summary_table.add_column("名称")
        summary_table.add_column("价格")
        summary_table.add_column("涨跌幅")
        summary_table.add_column("趋势")
        summary_table.add_column("评分", justify="center")
        summary_table.add_column("操作", style="bold")

        for r in results:
            q = r.get("quote")
            t = r.get("tech")
            if q and t:
                score_color = "green" if t.buy_score >= 60 else "yellow" if t.buy_score >= 40 else "red"
                op_color = "green" if "买入" in t.operation else "red" if "卖出" in t.operation else "yellow"
                summary_table.add_row(
                    t.code,
                    t.name,
                    format_number(t.current_price),
                    colorize_change(q.change_pct),
                    t.trend_status.value,
                    f"[{score_color}]{t.buy_score}[/{score_color}]",
                    f"[{op_color}]{t.operation}[/{op_color}]",
                )

        console.print(summary_table)


@cli.command()
def market():
    """📋 市场总览"""
    console.print(Panel.fit(
        "[bold]📋 A股市场总览[/bold]",
        border_style="cyan",
    ))

    analyzer = MarketAnalyzer()
    overview = analyzer.get_overview()

    # 输出文字版
    console.print(overview.to_summary())

    # 生成图表
    try:
        gen = ChartGenerator()
        chart_path = gen.plot_market_overview(overview)
        console.print(f"\n[green]✓ 市场总览图: {chart_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠ 市场图表生成失败: {e}[/yellow]")


@cli.command()
@click.option("--time", "-t", default="15:30", help="定时执行时间 (HH:MM)")
@click.option("--stocks", "-S", help="分析的股票列表，逗号分隔")
def schedule(time, stocks):
    """⏰ 定时分析"""
    import schedule as sched

    config = Config.get()
    codes = [s.strip() for s in stocks.split(",") if s.strip()] if stocks else config.WATCH_LIST

    if not codes:
        console.print("[yellow]请设置自选股列表 (WATCH_LIST) 或通过 --stocks 指定[/yellow]")
        return

    def job():
        console.print(f"\n[bold cyan]⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} 定时分析开始[/bold cyan]")
        if not is_trading_day():
            console.print("[yellow]今天不是交易日，跳过[/yellow]")
            return

        for code in codes:
            try:
                analyze_single_stock(code)
            except Exception as e:
                console.print(f"[red]✗ {code} 分析失败: {e}[/red]")

    sched.every().day.at(time).do(job)

    console.print(f"[green]✓ 定时任务已设置: 每天 {time}[/green]")
    console.print(f"[dim]分析股票: {', '.join(codes)}[/dim]")
    console.print("[dim]按 Ctrl+C 退出[/dim]")

    while True:
        sched.run_pending()
        import time
        time.sleep(60)


@cli.command()
@click.option("--port", "-p", default=8080, help="端口号")
def serve(port):
    """🌐 启动 Web 服务 (预留)"""
    console.print(f"[yellow]Web 服务正在开发中，当前请使用 CLI 模式[/yellow]")
    console.print(f"[dim]可通过 cronjob + CLI 实现定时分析[/dim]")


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--start", default=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"), help="开始日期 YYYY-MM-DD")
@click.option("--end", default=datetime.now().strftime("%Y-%m-%d"), help="结束日期 YYYY-MM-DD")
@click.option("--cash", default=100000.0, help="初始资金")
def backtest(stock, start, end, cash):
    """🔁 策略回测"""
    console.print(Panel.fit(
        f"[bold]🔁 策略回测: {stock}[/bold]\n"
        f"日期范围: {start} ~ {end} | 初始资金: {cash:,.0f}",
        border_style="cyan",
    ))

    engine = get_backtest_engine(initial_cash=cash)
    results = engine.run_multi_strategy(stock, start, end)

    if results:
        engine.print_summary(results)
    else:
        console.print("[yellow]未获得回测结果[/yellow]")


@cli.command()
def setup_telegram():
    """🤖 配置 Telegram Bot"""
    from analyzer.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        console.print("[red]✗ 请先在 .env 中配置 TELEGRAM_BOT_TOKEN[/red]")
        return

    # 获取 Bot 信息
    bot_info = notifier.get_bot_info()
    if bot_info:
        console.print(f"[green]✓ Bot: @{bot_info.get('username', '')} ({bot_info.get('first_name', '')})[/green]")
    else:
        console.print("[red]✗ Bot Token 无效[/red]")
        return

    # 查找 Chat ID
    console.print("\n[cyan]请先给 Bot 发送一条消息（任意内容），然后按回车继续...[/cyan]")
    input()

    chat_id = notifier.find_chat_id()
    if chat_id:
        console.print(f"[green]✓ 找到 Chat ID: {chat_id}[/green]")

        # 保存到 .env
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            content = env_path.read_text()
            if "TELEGRAM_CHAT_ID=" in content:
                # 更新已有的
                import re
                content = re.sub(
                    r"TELEGRAM_CHAT_ID=.*",
                    f"TELEGRAM_CHAT_ID={chat_id}",
                    content
                )
            else:
                content += f"\nTELEGRAM_CHAT_ID={chat_id}\n"
            env_path.write_text(content)
            console.print(f"[green]✓ Chat ID 已保存到 .env[/green]")

        # 测试发送
        if notifier.send_message("✅ A股分析系统 Telegram 通知配置成功！", chat_id=chat_id):
            console.print("[green]✓ 测试消息发送成功！[/green]")
        else:
            console.print("[red]✗ 测试消息发送失败[/red]")
    else:
        console.print("[yellow]⚠ 未找到消息记录，请确认已给 Bot 发送过消息[/yellow]")


@cli.command()
def list_strategies():
    """📋 列出所有策略"""
    engine = get_strategy_engine()
    if not engine.strategies:
        console.print("[yellow]没有找到策略文件[/yellow]")
        return

    table = Table(title="📐 交易策略列表", show_header=True, header_style="bold magenta")
    table.add_column("策略名称", style="cyan", width=25)
    table.add_column("时间框架", width=15)
    table.add_column("适合市场", width=15)

    for name, data in engine.strategies.items():
        table.add_row(
            name,
            data.get("timeframe", ""),
            data.get("suitable_market", ""),
        )

    console.print(table)


if __name__ == "__main__":
    cli()
