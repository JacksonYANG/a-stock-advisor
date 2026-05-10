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
    from data_provider.stock_names import resolve_stock_name
    name = resolve_stock_name(code, quote, hist)
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
        # 生成图表
        try:
            chart_path = engine.plot_backtest_result(results)
            console.print(f"[green]✓ 回测图表已保存: {chart_path}[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ 图表生成失败: {e}[/yellow]")
    else:
        console.print("[yellow]未获得回测结果[/yellow]")


# ==================== 持仓管理 ====================

@cli.group()
def portfolio():
    """💼 持仓管理"""
    pass


@portfolio.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--shares", "-n", type=float, required=True, help="持股数量")
@click.option("--avg-cost", "-c", type=float, required=True, help="平均成本")
@click.option("--name", help="股票名称（可选）")
@click.option("--notes", help="备注")
def add(stock, shares, avg_cost, name, notes):
    """➕ 添加持仓"""
    code = stock.strip().zfill(6)
    if not name:
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()
        mgr.register_sources(["baostock"])
        quote = mgr.get_quote(code)
        name = quote.name if quote else code

    db = Database()
    db.save_position(code, name, shares, avg_cost, notes or "")
    console.print(f"[green]✓ 已添加持仓: {code} {name} {shares}股 成本 {avg_cost}[/green]")


@portfolio.command()
def list_cmd():
    """📋 查看持仓"""
    from config import Config
    from data_provider.base import DataFetcherManager

    db = Database()
    positions = db.get_positions()

    if not positions:
        console.print("[yellow]暂无持仓[/yellow]")
        return

    config = Config.get()
    manager = DataFetcherManager()
    manager.register_sources(config.DATA_SOURCES)

    table = Table(title="💼 持仓列表", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("持股", justify="right")
    table.add_column("成本", justify="right")
    table.add_column("现价", justify="right")
    table.add_column("市值", justify="right")
    table.add_column("浮动盈亏", justify="right")
    table.add_column("盈亏%", justify="right")

    total_pnl = 0
    total_value = 0

    for pos in positions:
        try:
            quote = manager.get_quote(pos.code)
            if quote:
                db.update_position_price(pos.code, quote.current_price)
                pos.current_price = quote.current_price
                pos.market_value = pos.shares * quote.current_price
                pos.floating_pnl = (quote.current_price - pos.avg_cost) * pos.shares
                pos.floating_pnl_pct = (quote.current_price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost > 0 else 0
        except:
            pass

        pnl_color = "green" if pos.floating_pnl >= 0 else "red"
        pnl_pct_color = "green" if pos.floating_pnl_pct >= 0 else "red"

        table.add_row(
            pos.code,
            pos.name or "",
            f"{pos.shares:.0f}",
            f"{pos.avg_cost:.2f}",
            f"{pos.current_price:.2f}",
            f"{pos.market_value:,.0f}",
            f"[{pnl_color}]{pos.floating_pnl:+,.0f}[/{pnl_color}]",
            f"[{pnl_pct_color}]{pos.floating_pnl_pct:+.1f}%[/{pnl_pct_color}]",
        )
        total_pnl += pos.floating_pnl
        total_value += pos.market_value

    console.print(table)
    total_color = "green" if total_pnl >= 0 else "red"
    console.print(f"\n[bold]总浮动盈亏: [{total_color}]{total_pnl:+,.0f}[/{total_color}] | 总市值: {total_value:,.0f}[/bold]")


@portfolio.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--shares", "-n", type=float, required=True, help="卖出数量")
@click.option("--price", "-p", type=float, required=True, help="卖出价格")
@click.option("--strategy", help="策略来源")
@click.option("--notes", help="备注")
def sell(stock, shares, price, strategy, notes):
    """🔴 卖出股票"""
    code = stock.strip().zfill(6)
    db = Database()
    positions = db.get_positions()
    pos = next((p for p in positions if p.code == code), None)

    if not pos:
        console.print(f"[red]没有找到 {code} 的持仓[/red]")
        return

    amount = shares * price
    commission = amount * 0.001

    db.save_trade(
        code=code, name=pos.name or "",
        trade_type="sell", shares=shares, price=price,
        amount=amount, commission=commission,
        strategy=strategy or "", notes=notes or "",
    )

    new_shares = pos.shares - shares
    if new_shares <= 0:
        db.remove_position(code)
        console.print(f"[yellow]✓ {code} 已全部清仓[/yellow]")
    else:
        console.print(f"[green]✓ 卖出 {code}: {shares}股 @ {price}[/green]")

    console.print(f"[dim]手续费: {commission:.2f} | 实际收款: {amount - commission:.2f}[/dim]")


@portfolio.command()
@click.option("--stock", "-s", required=True, help="股票代码")
def remove(stock):
    """🗑️ 删除持仓（清仓）"""
    code = stock.strip().zfill(6)
    db = Database()
    db.remove_position(code)
    console.print(f"[green]✓ 已删除持仓 {code}[/green]")


@portfolio.command()
@click.option("--stock", "-s", required=True, help="股票代码")
def avg_cost(stock):
    """📐 计算持仓均价（含手续费）"""
    from data_provider.storage import Database

    code = stock.strip().zfill(6)
    db = Database()
    positions = db.get_positions()
    pos = next((p for p in positions if p.code == code), None)

    if not pos:
        console.print(f"[yellow]未找到持仓: {code}[/yellow]")
        return

    trades = db.get_trades(code=code)
    if not trades:
        console.print(f"[yellow]未找到交易记录: {code}[/yellow]")
        return

    total_shares = 0
    total_cost = 0.0

    for t in trades:
        if t.trade_type == "买入":
            total_shares += t.shares
            total_cost += t.shares * t.price + t.commission
        elif t.trade_type == "卖出":
            total_shares -= t.shares
            total_cost -= t.shares * t.price - t.commission

    if total_shares <= 0:
        console.print(f"[yellow]{code} 已清仓[/yellow]")
        return

    avg_price = total_cost / total_shares
    console.print(f"[bold]📐 {code} 均价重算结果[/bold]")
    console.print(f"  总股数: {total_shares}")
    console.print(f"  总成本: {total_cost:.2f}")
    console.print(f"  均价: [green]{avg_price:.3f}[/green]")
    console.print(f"  当前持仓均价: {pos.avg_cost:.3f}")


# ==================== 基本面分析 ====================

@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--year", "-y", type=int, help="年份 (默认去年)")
def financial(stock, year):
    """📊 基本面分析"""
    from data_provider.fundamental import get_fundamental_fetcher

    code = stock.strip().zfill(6)
    fetcher = get_fundamental_fetcher()

    console.print(f"\n[bold cyan]📊 基本面数据: {code}[/bold cyan]")

    # 综合财务数据
    data = fetcher.get_financial_data(code, year=year)
    if data:
        console.print(Panel(
            f"[bold]{data.name} ({data.code})[/bold]\n\n"
            f"净资产收益率 (ROE): [green]{data.roe:.2f}%[/green]\n"
            f"毛利率: {data.gross_margin:.2f}%  |  净利率: {data.net_margin:.2f}%\n"
            f"净利润增速: {data.profit_growth:+.2f}%  |  营收增速: {data.revenue_growth:+.2f}%\n"
            f"每股收益 (TTM): {data.eps:.4f}",
            title="财务质量",
            border_style="cyan",
        ))

        # 财务评分
        score = 0
        reasons = []
        if data.roe > 15:
            score += 30
            reasons.append("ROE>15%，盈利能力优秀")
        elif data.roe > 8:
            score += 15
            reasons.append("ROE>8%，盈利能力良好")
        elif data.roe > 0:
            score += 5
            reasons.append("ROE>0，盈利但偏低")

        if data.profit_growth > 20:
            score += 25
            reasons.append("净利润增速>20%，成长性强")
        elif data.profit_growth > 0:
            score += 10
            reasons.append("净利润正增长")

        if data.gross_margin > 30:
            score += 20
            reasons.append("毛利率>30%，定价能力强")
        elif data.gross_margin > 0:
            score += 10

        if data.net_margin > 10:
            score += 15
            reasons.append("净利率>10%，盈利质量高")
        elif data.net_margin > 0:
            score += 5

        if data.profit_growth < -20:
            score -= 20
            reasons.append("⚠️ 净利润大幅下滑，风险警示")

        score = max(0, min(100, score))

        if score >= 70:
            label = "[green]优秀[/green]"
        elif score >= 50:
            label = "[yellow]良好[/yellow]"
        elif score >= 30:
            label = "[yellow]一般[/yellow]"
        else:
            label = "[red]较差[/red]"

        console.print(Panel(
            f"基本面评分: {label}  ({score}/100)\n\n" + "\n".join(f"• {r}" for r in reasons),
            title="财务评分",
            border_style="cyan",
        ))
    else:
        console.print("[yellow]无法获取基本面数据[/yellow]")


@cli.command()
@click.option("--roe-min", type=float, help="ROE下限 (%)")
@click.option("--profit-growth-min", type=float, help="净利润增速下限 (%)")
@click.option("--net-margin-min", type=float, help="净利率下限 (%)")
@click.option("--gross-margin-min", type=float, help="毛利率下限 (%)")
@click.option("--limit", "-n", type=int, default=20, help="返回数量")
def screen(roe_min, profit_growth_min, net_margin_min, gross_margin_min, limit):
    """🔍 财务筛选"""
    from data_provider.fundamental import get_fundamental_fetcher

    console.print(f"[bold cyan]🔍 财务筛选[/bold cyan]")
    conditions = []
    if roe_min:
        conditions.append(f"ROE ≥ {roe_min}%")
    if profit_growth_min:
        conditions.append(f"净利润增速 ≥ {profit_growth_min}%")
    if net_margin_min:
        conditions.append(f"净利率 ≥ {net_margin_min}%")
    if gross_margin_min:
        conditions.append(f"毛利率 ≥ {gross_margin_min}%")

    if conditions:
        console.print("条件: " + " | ".join(conditions))
    else:
        console.print("[yellow]未设置筛选条件，返回示例数据[/yellow]")

    fetcher = get_fundamental_fetcher()

    # 使用默认筛选或传入的条件
    results = fetcher.screen_stocks(
        roe_min=roe_min,
        profit_growth_min=profit_growth_min,
        net_margin_min=net_margin_min,
        gross_margin_min=gross_margin_min,
        limit=limit,
    )

    if not results:
        console.print("[yellow]未找到符合条件的股票[/yellow]")
        return

    table = Table(title=f"筛选结果 ({len(results)}只)", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("ROE%", justify="right")
    table.add_column("净利率%", justify="right")
    table.add_column("毛利率%", justify="right")
    table.add_column("净利润增速%", justify="right")
    table.add_column("行业", style="dim")

    for r in results:
        table.add_row(
            r["code"],
            r["name"],
            f"{r['roe']:.1f}" if r['roe'] else "N/A",
            f"{r['net_margin']:.1f}" if r['net_margin'] else "N/A",
            f"{r['gross_margin']:.1f}" if r['gross_margin'] else "N/A",
            f"{r['profit_growth']:+.1f}" if r['profit_growth'] else "N/A",
            r.get("industry", ""),
        )

    console.print(table)


@cli.command()
@click.option("--top", "-n", type=int, default=20, help="显示前N个板块")
def sector(top):
    """🏭 板块涨跌排行"""
    from data_provider.sector import get_sector_fetcher

    console.print(f"[bold cyan]🏭 行业板块涨跌排行[/bold cyan]")

    fetcher = get_sector_fetcher()
    sectors = fetcher.get_all_sectors()

    if not sectors:
        console.print("[yellow]无法获取板块数据[/yellow]")
        return

    table = Table(title=f"板块涨跌 (前{min(top, len(sectors))}名)", show_header=True, header_style="bold magenta")
    table.add_column("行业", style="cyan")
    table.add_column("股票数", justify="right")
    table.add_column("平均涨跌", justify="right")
    table.add_column("上涨", justify="right", style="green")
    table.add_column("下跌", justify="right", style="red")
    table.add_column("涨停", justify="right", style="red")
    table.add_column("龙头", style="yellow")
    table.add_column("龙头涨幅", justify="right")

    for s in sectors[:top]:
        change_color = "green" if s["avg_change"] > 0 else "red"
        table.add_row(
            s["industry"],
            str(s["stock_count"]),
            f"[{change_color}]{s['avg_change']:+.2f}%[/{change_color}]",
            str(s["up_count"]),
            str(s["down_count"]),
            str(s["limit_up_count"]),
            s["lead_stock"],
            f"{s['lead_change']:+.2f}%" if s["lead_change"] != -999.0 else "N/A",
        )

    console.print(table)


@cli.command()
@click.option("--industry", "-i", required=True, help="行业名称")
def sector_stocks(industry):
    """📋 查看板块成分股"""
    from data_provider.sector import get_sector_fetcher
    from data_provider.base import DataFetcherManager

    fetcher = get_sector_fetcher()
    stocks = fetcher.get_sector_stocks(industry)

    if not stocks:
        console.print(f"[yellow]未找到行业: {industry}[/yellow]")
        return

    manager = DataFetcherManager()
    manager.register_sources(["baostock"])

    table = Table(title=f"{industry} 成分股", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("现价", justify="right")
    table.add_column("涨跌幅", justify="right")

    for s in stocks:
        try:
            quote = manager.get_quote(s["code"])
            if quote:
                chg = quote.change_pct
                color = "green" if chg > 0 else "red" if chg < 0 else "white"
                table.add_row(s["code"], s["name"], f"{quote.current_price:.2f}", f"[{color}]{chg:+.2f}%[/{color}]")
            else:
                table.add_row(s["code"], s["name"], "N/A", "N/A")
        except:
            table.add_row(s["code"], s["name"], "N/A", "N/A")

    console.print(table)


@cli.command()
@click.option("--days", "-d", type=int, default=5, help="历史天数")
def north_money(days):
    """💰 北向资金追踪"""
    from data_provider.north_money import get_north_money_fetcher

    console.print(f"[bold cyan]💰 沪深港通北向资金[/bold cyan]")

    fetcher = get_north_money_fetcher()
    history = fetcher.get_history(days)

    if not history:
        console.print("[yellow]无法获取北向资金数据（需配置Tushare Token）[/yellow]")
        return

    latest = history[0]
    console.print(Panel(
        f"[bold]日期: {latest.date}[/bold]\n\n"
        f"沪股通净买入: [green]{latest.hgt_shanghai:+,+.2f}亿[/green]\n"
        f"深股通净买入: [green]{latest.sgt_shenzhen:+,+.2f}亿[/green]\n"
        f"合计净买入:  [bold green]{latest.total:+,+.2f}亿[/bold green]",
        title="今日北向资金",
        border_style="cyan",
    ))

    table = Table(title=f"近{len(history)}日北向资金趋势", show_header=True, header_style="bold magenta")
    table.add_column("日期", style="cyan")
    table.add_column("沪股通(亿)", justify="right")
    table.add_column("深股通(亿)", justify="right")
    table.add_column("合计(亿)", justify="right")

    for d in history:
        color = "green" if d.total > 0 else "red"
        table.add_row(
            d.date,
            f"{d.hgt_shanghai:+,+.2f}",
            f"{d.sgt_shenzhen:+,+.2f}",
            f"[{color}]{d.total:+,+.2f}[/{color}]",
        )

    console.print(table)

    if latest.top_stocks:
        top10 = sorted(latest.top_stocks, key=lambda x: x.get("net_amount", 0), reverse=True)[:10]
        t = Table(title="北向资金个股TOP10", show_header=True, header_style="bold magenta")
        t.add_column("代码", style="cyan")
        t.add_column("名称")
        t.add_column("净买入(亿)", justify="right", style="green")
        t.add_column("买入(亿)", justify="right")
        t.add_column("卖出(亿)", justify="right")

        for s in top10:
            t.add_row(
                s.get("code", ""),
                s.get("name", ""),
                f"{s.get('net_amount', 0):+,+.3f}",
                f"{s.get('buy_amount', 0):+.3f}",
                f"{s.get('sell_amount', 0):+.3f}",
            )
        console.print(t)


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--limit", "-n", type=int, default=10, help="新闻条数")
def news(stock, limit):
    """📰 个股新闻舆情"""
    from analyzer.sentiment import get_news_fetcher

    code = stock.strip().zfill(6)

    # 转换代码格式 (东方财富格式: sh.600519)
    if code.startswith(("6", "5", "9")):
        ef_code = f"sh.{code}"
    else:
        ef_code = f"sz.{code}"

    console.print(f"[bold cyan]📰 {code} 最新资讯[/bold cyan]")

    fetcher = get_news_fetcher()
    news_items = fetcher.get_stock_news(ef_code, limit)

    if not news_items:
        console.print("[yellow]未找到相关新闻[/yellow]")
        return

    table = Table(title=f"新闻列表 ({len(news_items)}条)", show_header=True, header_style="bold magenta")
    table.add_column("情感", width=8)
    table.add_column("时间", width=12)
    table.add_column("标题")

    for item in news_items:
        if item.sentiment == "positive":
            emoji = "✅"
            color = "green"
        elif item.sentiment == "negative":
            emoji = "⚠️"
            color = "red"
        else:
            emoji = "➖"
            color = "dim"

        table.add_row(
            emoji,
            item.publish_time[:10] if item.publish_time else "",
            f"[{color}]{item.title[:60]}[/{color}]" + ("..." if len(item.title) > 60 else ""),
        )

    console.print(table)


@cli.group()
def pool():
    """📦 股票池管理"""
    pass


@pool.command()
@click.option("--name", "-n", required=True, help="股票池名称")
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--notes", help="备注")
def add(name, stock, notes):
    """➕ 添加股票到股票池"""
    code = stock.strip().zfill(6)
    db = Database()
    db.save_stock_pool(name, code, notes or "")
    console.print(f"[green]✓ 已添加 {code} 到股票池 '{name}'[/green]")


@pool.command()
def list_pools():
    """📋 列出所有股票池"""
    db = Database()
    pools = db.get_stock_pools()

    if not pools:
        console.print("[yellow]暂无股票池[/yellow]")
        return

    for p in pools:
        stocks = db.get_pool_stocks(p)
        console.print(f"[cyan]{p}[/cyan] ({len(stocks)}只)")


@pool.command()
@click.option("--name", "-n", required=True, help="股票池名称")
def list_stocks(name):
    """📋 查看股票池成分股"""
    from data_provider.base import DataFetcherManager

    db = Database()
    stocks = db.get_pool_stocks(name)

    if not stocks:
        console.print(f"[yellow]股票池 '{name}' 为空[/yellow]")
        return

    manager = DataFetcherManager()
    manager.register_sources(["baostock"])

    table = Table(title=f"📦 {name} 成分股", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("现价", justify="right")
    table.add_column("涨跌幅", justify="right")
    table.add_column("备注")

    for s in stocks:
        try:
            quote = manager.get_quote(s.code)
            if quote:
                chg = quote.change_pct
                color = "green" if chg > 0 else "red" if chg < 0 else "white"
                table.add_row(s.code, s.name or quote.name, f"{quote.current_price:.2f}",
                            f"[{color}]{chg:+.2f}%[/{color}]", s.notes or "")
            else:
                table.add_row(s.code, s.name or "", "N/A", "N/A", s.notes or "")
        except:
            table.add_row(s.code, s.name or "", "N/A", "N/A", s.notes or "")

    console.print(table)


@pool.command()
@click.option("--name", "-n", required=True, help="股票池名称")
@click.option("--stock", "-s", required=True, help="股票代码")
def remove(name, stock):
    """➖ 从股票池移除"""
    code = stock.strip().zfill(6)
    db = Database()
    db.remove_pool_stock(name, code)
    console.print(f"[green]✓ 已从 '{name}' 移除 {code}[/green]")


@pool.command()
@click.option("--name", "-n", required=True, help="股票池名称")
def delete(name):
    """🗑️ 删除股票池"""
    db = Database()
    db.delete_pool(name)
    console.print(f"[green]✓ 已删除股票池 '{name}'[/green]")


@cli.command()
@click.option("--date", "-d", help="交易日期 YYYYMMDD")
@click.option("--top", "-n", type=int, default=30, help="显示条数")
def dragon_tiger(date, top):
    """🐉 龙虎榜追踪"""
    from data_provider.dragon_tiger import get_dragon_tiger_fetcher

    console.print(f"[bold cyan]🐉 龙虎榜数据[/bold cyan]")

    fetcher = get_dragon_tiger_fetcher()
    records = fetcher.get_top_list(date) if date else fetcher.get_top_list()

    if not records:
        console.print("[yellow]未获取到龙虎榜数据（需配置Tushare Token）[/yellow]")
        return

    console.print(Panel(f"[bold]上榜股票数: {len(records)}[/bold]", title="今日龙虎榜", border_style="cyan"))

    table = Table(title=f"龙虎榜 (前{min(top, len(records))}名)", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("收盘价", justify="right")
    table.add_column("涨跌幅", justify="right")
    table.add_column("换手率", justify="right")
    table.add_column("成交额(万)", justify="right")
    table.add_column("上榜原因")

    for r in records[:top]:
        chg_color = "green" if r.change_pct > 0 else "red"
        table.add_row(
            r.code, r.name, f"{r.close_price:.2f}",
            f"[{chg_color}]{r.change_pct:+.2f}%[/{chg_color}]",
            f"{r.turnover_rate:.2f}%", f"{r.amount:,.0f}", r.reason[:25],
        )
    console.print(table)


@cli.command()
@click.option("--days", "-d", type=int, default=30, help="统计天数")
@click.option("--top", "-n", type=int, default=20, help="显示席位数")
def hot_seats(days, top):
    """🔥 热门游资席位排行"""
    from data_provider.dragon_tiger import get_dragon_tiger_fetcher

    console.print(f"[bold cyan]🔥 近{days}天最活跃游资席位[/bold cyan]")

    fetcher = get_dragon_tiger_fetcher()
    seats = fetcher.get_hot_seats(days)

    if not seats:
        console.print("[yellow]未获取到席位数据[/yellow]")
        return

    table = Table(title=f"热门席位 (前{top}名)", show_header=True, header_style="bold magenta")
    table.add_column("席位名称", style="cyan")
    table.add_column("上榜次数", justify="right")
    table.add_column("买入总额(万)", justify="right", style="green")
    table.add_column("卖出总额(万)", justify="right", style="red")
    table.add_column("净额(万)", justify="right")

    for s in seats[:top]:
        net_color = "green" if s["net"] > 0 else "red" if s["net"] < 0 else "dim"
        table.add_row(s["name"], str(s["appear_count"]),
                     f"{s['total_buy']:,.0f}", f"{s['total_sell']:,.0f}",
                     f"[{net_color}]{s['net']:+,.0f}[/{net_color}]")
    console.print(table)


@cli.command()
@click.option("--top", "-n", type=int, default=20, help="显示前N个板块")
def sector_flow(top):
    """💧 板块资金流向"""
    from data_provider.sector_flow import get_sector_flow_fetcher

    console.print(f"[bold cyan]💧 行业板块资金流向[/bold cyan]")

    fetcher = get_sector_flow_fetcher()
    flows = fetcher.get_all_sector_flows()

    if not flows:
        console.print("[yellow]无法获取板块资金数据[/yellow]")
        return

    table = Table(title=f"板块资金流向 (前{top}名)", show_header=True, header_style="bold magenta")
    table.add_column("行业", style="cyan")
    table.add_column("股票数", justify="right")
    table.add_column("平均涨跌", justify="right")
    table.add_column("资金净流入(亿)", justify="right")
    table.add_column("净流入占市值比", justify="right")

    for f in flows[:top]:
        change_color = "green" if f.avg_change > 0 else "red"
        flow_color = "green" if f.total_flow > 0 else "red"
        table.add_row(
            f.industry, str(f.stock_count),
            f"[{change_color}]{f.avg_change:+.2f}%[/{change_color}]",
            f"[{flow_color}]{f.total_flow:+,.2f}亿[/{flow_color}]",
            f"{f.inflow_pct:+.3f}%",
        )
    console.print(table)


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--days", "-d", type=int, default=10, help="历史天数")
def margin(stock, days):
    """📊 融资融券数据"""
    from data_provider.margin import get_margin_fetcher

    code = stock.strip().zfill(6)
    console.print(f"[bold cyan]📊 {code} 融资融券数据[/bold cyan]")

    fetcher = get_margin_fetcher()
    history = fetcher.get_history(code, days)

    if not history:
        console.print("[yellow]未获取到融资融券数据（需配置Tushare Token）[/yellow]")
        return

    latest = history[0]

    console.print(Panel(
        f"[bold]日期: {latest.date}[/bold]\n\n"
        f"融资余额: [green]{latest.margin_balance:,.0f}万[/green]\n"
        f"融资买入: {latest.margin_buy:,.0f}万\n"
        f"融券余额: [red]{latest.short_balance:,.0f}万[/red]\n"
        f"融资/融券比: {latest.margin_ratio:.2f}x",
        title=f"{latest.name}",
        border_style="cyan",
    ))

    table = Table(title=f"近{len(history)}日融资融券", show_header=True, header_style="bold magenta")
    table.add_column("日期", style="cyan")
    table.add_column("收盘价", justify="right")
    table.add_column("融资余额(万)", justify="right", style="green")
    table.add_column("融资买入(万)", justify="right")
    table.add_column("融券余额(万)", justify="right", style="red")
    table.add_column("比值", justify="right")

    for d in history:
        table.add_row(
            d.date, f"{d.close_price:.2f}",
            f"{d.margin_balance:,.0f}", f"{d.margin_buy:,.0f}",
            f"{d.short_balance:,.0f}", f"{d.margin_ratio:.2f}",
        )
    console.print(table)


@cli.command()
@click.option("--top", "-n", type=int, default=10, help="推荐股票数量")
def pick(top):
    """🎯 智能选股报告"""
    from analyzer.stock_picker import get_stock_picker

    console.print(f"[bold cyan]🎯 智能选股中...[/bold cyan]")

    picker = get_stock_picker()
    report = picker.generate_daily_report(top_n=top)
    picker.print_report(report)


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--strategy", default="综合", help="策略类型")
def ai(stock, strategy):
    """🤖 AI 智能分析"""
    from analyzer.ai_advisor import AIAdvisor

    code = stock.strip().zfill(6)
    console.print(f"[bold cyan]🤖 AI 分析中: {code}[/bold cyan]")

    advisor = AIAdvisor()
    if not advisor.is_available:
        console.print("[yellow]AI 分析未配置，请设置 LLM_PROVIDER 和 LLM_API_KEY[/yellow]")
        return

    advice = advisor.analyze_by_code(code, strategy)

    if not advice or not advice.summary:
        console.print("[yellow]AI 分析失败，请检查 LLM 配置[/yellow]")
        return

    from rich.panel import Panel
    key_factors = "\n".join(f"  • {f}" for f in (advice.key_factors or [])[:5])
    risk_warnings = "\n".join(f"  ⚠️ {r}" for r in (advice.risk_warnings or [])[:3])

    console.print(Panel(
        f"[bold]{advice.summary}[/bold]\n\n"
        f"操作建议: [bold]{advice.operation}[/bold]\n"
        f"建议买入价: {advice.entry_price:.2f}\n"
        f"止损价: [red]{advice.stop_loss:.2f}[/red]\n"
        f"目标价: [green]{advice.target_price:.2f}[/green]\n"
        f"风险等级: {advice.risk_level}\n\n"
        f"关键因素:\n{key_factors}\n\n"
        f"风险提示:\n{risk_warnings}",
        title=f"{code} AI 分析报告",
        border_style="cyan",
    ))


@cli.command()
@click.option("--stocks", "-s", help="股票代码（逗号分隔，留空则使用自选股）")
@click.option("--start", default="2025-01-01", help="回测开始日期")
@click.option("--strategy", default="ma_cross", help="策略名称")
def backtest_rank(stocks, start, strategy):
    """🏆 多股票回测排名"""
    from analyzer.backtest_engine import get_backtest_engine
    from config import Config
    from datetime import datetime

    config = Config.get()
    stock_list = []
    if stocks:
        stock_list = [c.strip().zfill(6) for c in stocks.split(",") if c.strip()]
    else:
        stock_list = config.WATCH_LIST[:10]

    if not stock_list:
        console.print("[yellow]未指定股票[/yellow]")
        return

    engine = get_backtest_engine()
    results = {}

    console.print(f"[bold cyan]🏆 多股票回测中 ({len(stock_list)} 只)...[/bold cyan]")

    end_date = datetime.now().strftime("%Y-%m-%d")

    for code in stock_list:
        try:
            all_results = engine.run_multi_strategy(code, start, end_date)
            if strategy in all_results:
                results[code] = all_results[strategy]
            elif all_results:
                # 使用第一个可用策略的结果
                results[code] = next(iter(all_results.values()))
        except Exception:
            continue

    if not results:
        console.print("[yellow]所有股票回测均失败[/yellow]")
        return

    sorted_results = sorted(results.items(), key=lambda x: x[1].annualized_return, reverse=True)

    table = Table(title=f"回测排名 ({strategy})", show_header=True, header_style="bold magenta")
    table.add_column("排名", justify="right")
    table.add_column("代码", style="cyan")
    table.add_column("年化收益", justify="right")
    table.add_column("总收益", justify="right")
    table.add_column("胜率", justify="right")
    table.add_column("最大回撤", justify="right")
    table.add_column("夏普比率", justify="right")

    for i, (code, r) in enumerate(sorted_results, 1):
        ann_color = "green" if r.annualized_return > 0 else "red"
        table.add_row(
            str(i), code,
            f"[{ann_color}]{r.annualized_return:+.2f}%[/{ann_color}]",
            f"{r.total_return:+.2f}%",
            f"{r.win_rate:.1f}%",
            f"[red]{r.max_drawdown:.2f}%[/red]",
            f"{r.sharpe_ratio:.2f}",
        )

    console.print(table)

    try:
        chart_path = engine.plot_backtest_result(results)
        console.print(f"[green]✓ 回测图表已保存: {chart_path}[/green]")
    except:
        pass


@cli.command()
@click.option("--min-score", type=int, default=60, help="最低评分")
@click.option("--top", "-n", type=int, default=20, help="显示数量")
@click.option("--sector", help="限定行业")
def screen_stocks(min_score, top, sector):
    """🔍 智能综合选股"""
    from analyzer.smart_screener import get_smart_screener

    console.print(f"[bold cyan]🔍 智能选股中 (最低评分{min_score})...[/bold cyan]")

    screener = get_smart_screener()
    results = screener.screen_stocks(min_score=min_score, top_n=top, sector=sector)

    if not results:
        console.print("[yellow]未筛选出符合条件股票[/yellow]")
        return

    table = Table(title=f"选股结果 ({len(results)}只)", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("评分", justify="right")
    table.add_column("涨跌幅", justify="right")
    table.add_column("匹配原因")

    for r in results:
        chg_color = "green" if r.change_pct > 0 else "red"
        reasons = " | ".join(r.match_reasons[:2])
        table.add_row(r.code, r.name, f"[bold]{r.score:.0f}[/bold]",
                    f"[{chg_color}]{r.change_pct:+.2f}%[/{chg_color}]", reasons[:40])

    console.print(table)


@cli.command()
@click.option("--to", "-t", required=True, help="收件人邮箱")
@click.option("--subject", "-s", default="A股分析报告", help="邮件主题")
@click.option("--content", "-c", required=True, help="邮件内容")
def send_email(to, subject, content):
    """📧 发送邮件"""
    from config import Config

    config = Config.get()

    if not config.SMTP_HOST or not config.SMTP_USER:
        console.print("[yellow]邮件配置不完整，请检查 .env SMTP 配置[/yellow]")
        return

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg["From"] = config.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(content, "html", "utf-8"))

        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, [to], msg.as_string())

        console.print(f"[green]✓ 邮件已发送至 {to}[/green]")
    except Exception as e:
        console.print(f"[red]✗ 邮件发送失败: {e}[/red]")


@cli.command()
@click.option("--msg", "-m", required=True, help="发送内容")
def send_wx(msg):
    """💬 发送企业微信消息"""
    from config import Config

    config = Config.get()

    if not config.WECHAT_WEBHOOK_URL:
        console.print("[yellow]企业微信 Webhook 未配置[/yellow]")
        return

    try:
        import requests
        payload = {"msgtype": "text", "text": {"content": msg}}
        resp = requests.post(config.WECHAT_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            console.print("[green]✓ 消息已发送[/green]")
        else:
            console.print(f"[red]✗ 发送失败: {resp.status_code}[/red]")
    except Exception as e:
        console.print(f"[red]✗ 发送失败: {e}[/red]")


@cli.command()
def config_show():
    """⚙️ 查看当前配置"""
    from config import Config

    config = Config.get()

    info = [
        ["数据源", ", ".join(config.DATA_SOURCES)],
        ["Tushare Token", "✓ 已配置" if config.TUSHARE_TOKEN else "✗ 未配置"],
        ["LLM Provider", config.LLM_PROVIDER or "未配置"],
        ["LLM Model", config.LLM_MODEL or "默认"],
        ["自选股数量", str(len(config.WATCH_LIST))],
        ["Telegram Bot", "✓ 已配置" if config.TELEGRAM_BOT_TOKEN else "✗ 未配置"],
        ["企微 Webhook", "✓ 已配置" if config.WECHAT_WEBHOOK_URL else "✗ 未配置"],
        ["SMTP 邮件", "✓ 已配置" if config.SMTP_HOST else "✗ 未配置"],
    ]

    table = Table(title="⚙️ 当前配置", show_header=False, header_style="bold magenta")
    table.add_column("配置项", style="cyan")
    table.add_column("值")

    for item in info:
        table.add_row(item[0], item[1])

    console.print(table)

    if config.WATCH_LIST:
        shown = ", ".join(config.WATCH_LIST[:10])
        extra = f" ... (共{len(config.WATCH_LIST)}只)" if len(config.WATCH_LIST) > 10 else ""
        console.print(f"\n[bold]自选股[/bold]: {shown}{extra}")


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--start", default="2025-01-01", help="回测开始日期")
@click.option("--format", "-f", type=click.Choice(["json", "csv"]), default="json", help="导出格式")
@click.option("--output", "-o", help="输出文件路径")
def backtest_export(stock, start, format, output):
    """📤 导出回测结果"""
    from analyzer.backtest_engine import get_backtest_engine
    import json
    import csv
    import os
    from datetime import datetime

    code = stock.strip().zfill(6)
    engine = get_backtest_engine()
    result = engine.run(code, start)

    if not output:
        output = f"reports/backtest_{code}_{start}.{format}"

    os.makedirs(os.path.dirname(output) or "reports", exist_ok=True)

    if format == "json":
        data = {
            "code": code,
            "start": start,
            "end": datetime.now().strftime("%Y-%m-%d"),
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_loss_ratio": result.profit_loss_ratio,
            "avg_holding_days": result.avg_holding_days,
            "trade_count": result.trade_count,
        }
        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["指标", "值"])
            writer.writerow(["代码", code])
            writer.writerow(["开始日期", start])
            writer.writerow(["结束日期", datetime.now().strftime("%Y-%m-%d")])
            writer.writerow(["总收益", f"{result.total_return:.2f}%"])
            writer.writerow(["年化收益", f"{result.annualized_return:.2f}%"])
            writer.writerow(["胜率", f"{result.win_rate:.1f}%"])
            writer.writerow(["最大回撤", f"{result.max_drawdown:.2f}%"])
            writer.writerow(["夏普比率", f"{result.sharpe_ratio:.2f}"])

    console.print(f"[green]✓ 已导出: {output}[/green]")


@cli.command()
def fear_greed():
    """🌡️ 市场恐慌贪婪指数"""
    from analyzer.market_sentiment import get_sentiment_analyzer
    from rich.panel import Panel

    console.print(f"[bold cyan]🌡️ 市场情绪温度计[/bold cyan]")

    analyzer = get_sentiment_analyzer()
    sentiment = analyzer.get_sentiment()

    if not sentiment:
        console.print("[yellow]无法获取市场情绪数据[/yellow]")
        return

    up_limit = getattr(sentiment, "up_limit_count", 0)
    down_limit = getattr(sentiment, "down_limit_count", 0)

    if up_limit + down_limit == 0:
        index = 50.0
    else:
        index = up_limit / (up_limit + down_limit) * 100

    if index >= 75:
        level = "极度贪婪"
        color = "bright_red"
        emoji = "🔥"
    elif index >= 60:
        level = "贪婪"
        color = "red"
        emoji = "😰"
    elif index >= 40:
        level = "中性"
        color = "yellow"
        emoji = "😐"
    elif index >= 25:
        level = "恐慌"
        color = "cyan"
        emoji = "😨"
    else:
        level = "极度恐慌"
        color = "bright_cyan"
        emoji = "🥶"

    up_count = getattr(sentiment, "up_count", "N/A")
    down_count = getattr(sentiment, "down_count", "N/A")

    console.print(Panel(
        f"[bold]{emoji} {level}[/bold]\n\n"
        f"恐慌/贪婪指数: [bold {color}]{index:.1f}[/bold {color}]\n\n"
        f"涨停家数: [green]{up_limit}[/green]\n"
        f"跌停家数: [red]{down_limit}[/red]\n"
        f"上涨家数: {up_count}\n"
        f"下跌家数: {down_count}",
        title="市场情绪",
        border_style="cyan",
    ))


@cli.command()
@click.option("--date", "-d", help="交易日期 YYYYMMDD")
def hot_money(date):
    """🎰 游资动向追踪"""
    from data_provider.hot_money_tracker import get_hot_money_tracker

    console.print(f"[bold cyan]🎰 今日游资动向[/bold cyan]")

    tracker = get_hot_money_tracker()
    activities = tracker.get_daily_activities(date)

    if not activities:
        console.print("[yellow]未获取到游资活动数据（需安装akshare且市场有龙虎榜数据）[/yellow]")
        return

    # 按游资组汇总
    summary = tracker.get_group_summary(date)

    if summary:
        table = Table(title="游资动向汇总", show_header=True, header_style="bold magenta")
        table.add_column("游资", style="cyan")
        table.add_column("风格")
        table.add_column("净买入(万)", justify="right")
        table.add_column("买入(万)", justify="right")
        table.add_column("卖出(万)", justify="right")
        table.add_column("参与股票数", justify="right")
        table.add_column("活跃席位")

        for s in summary:
            net_color = "green" if s["net_total"] > 0 else "red"
            table.add_row(
                s["group_name"],
                s["style"][:15],
                f"[{net_color}]{s['net_total']:+,.0f}[/{net_color}]",
                f"{s['buy_total']:,.0f}",
                f"{s['sell_total']:,.0f}",
                str(s["stock_count"]),
                "; ".join(s["seats"][:2]),
            )
        console.print(table)

    # 明细
    table2 = Table(title="游资操作明细", show_header=True, header_style="bold magenta")
    table2.add_column("游资", style="cyan")
    table2.add_column("股票")
    table2.add_column("买入(万)", justify="right")
    table2.add_column("卖出(万)", justify="right")
    table2.add_column("净额(万)", justify="right")

    for a in activities[:20]:
        net_color = "green" if a.net_amount > 0 else "red"
        table2.add_row(
            a.group_name,
            f"{a.stock_name}({a.stock_code})",
            f"{a.buy_amount:,.0f}",
            f"{a.sell_amount:,.0f}",
            f"[{net_color}]{a.net_amount:+,.0f}[/{net_color}]",
        )
    console.print(table2)


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--days", "-d", type=int, default=30, help="追踪天数")
def track_hot_money(stock, days):
    """🔍 追踪个股游资参与"""
    from data_provider.hot_money_tracker import get_hot_money_tracker

    code = stock.strip().zfill(6)
    console.print(f"[bold cyan]🔍 {code} 近{days}天游资参与[/bold cyan]")

    tracker = get_hot_money_tracker()
    activities = tracker.track_stock(code, days)

    if not activities:
        console.print("[yellow]未发现游资参与记录[/yellow]")
        return

    table = Table(title=f"游资参与明细", show_header=True, header_style="bold magenta")
    table.add_column("日期", style="cyan")
    table.add_column("游资")
    table.add_column("席位")
    table.add_column("买入(万)", justify="right")
    table.add_column("卖出(万)", justify="right")
    table.add_column("净额(万)", justify="right")

    for a in activities:
        net_color = "green" if a.net_amount > 0 else "red"
        table.add_row(
            a.date, a.group_name, a.seat_name[:15],
            f"{a.buy_amount:,.0f}", f"{a.sell_amount:,.0f}",
            f"[{net_color}]{a.net_amount:+,.0f}[/{net_color}]",
        )
    console.print(table)


@cli.command()
def hot_money_groups():
    """📋 查看已知游资席位"""
    from data_provider.hot_money_tracker import get_hot_money_tracker

    console.print(f"[bold cyan]📋 已知游资席位注册表[/bold cyan]")

    tracker = get_hot_money_tracker()
    groups = tracker.list_known_groups()

    if not groups:
        console.print("[yellow]无游资席位数据，请检查 data/seat_registry.yaml[/yellow]")
        return

    table = Table(title="游资席位注册表", show_header=True, header_style="bold magenta")
    table.add_column("游资名称", style="cyan")
    table.add_column("别名")
    table.add_column("席位数", justify="right")
    table.add_column("风格")
    table.add_column("席位列表")

    for g in groups:
        table.add_row(
            g["name"],
            "/".join(g["aliases"][:2]),
            str(g["seat_count"]),
            g["style"][:20],
            "\n".join(g["seats"][:3]),
        )
    console.print(table)


@cli.command()
def report():
    """📄 生成PDF分析报告"""
    from analyzer.report_generator import get_report_generator

    console.print(f"[bold cyan]📄 生成分析报告中...[/bold cyan]")

    gen = get_report_generator()
    filepath = gen.generate_daily_report()

    if filepath:
        console.print(f"[green]✓ 报告已生成: {filepath}[/green]")
    else:
        console.print("[yellow]报告生成失败（需安装 fpdf2: pip install fpdf2）[/yellow]")


@cli.command()
def portfolio_analysis():
    """📈 组合持仓分析"""
    from analyzer.portfolio_analyzer import get_portfolio_analyzer
    from rich.panel import Panel

    console.print(f"[bold cyan]📈 组合分析中...[/bold cyan]")

    analyzer = get_portfolio_analyzer()
    metrics = analyzer.analyze()

    if metrics.position_count == 0:
        console.print("[yellow]当前无持仓[/yellow]")
        return

    pnl_color = "green" if metrics.total_pnl >= 0 else "red"

    console.print(Panel(
        f"[bold]持仓数量: {metrics.position_count}[/bold]\n\n"
        f"总市值: {metrics.total_value:,.2f}\n"
        f"总成本: {metrics.total_cost:,.2f}\n"
        f"总盈亏: [{pnl_color}]{metrics.total_pnl:+,.2f}[/{pnl_color}] ({metrics.total_pnl_pct:+.2f}%)\n\n"
        f"夏普比率: {metrics.sharpe_ratio:.2f}\n"
        f"索提诺比率: {metrics.sortino_ratio:.2f}\n"
        f"最大回撤: [red]{metrics.max_drawdown:.2f}%[/red]\n"
        f"集中度: {metrics.concentration:.1%}\n"
        f"分散化评分: {metrics.diversification_score:.0f}/100",
        title="Portfolio Analysis",
        border_style="cyan",
    ))

    # 相关性矩阵
    corr = analyzer.get_correlation_matrix()
    if corr is not None and not corr.empty:
        console.print(f"\n[bold]相关性矩阵[/bold]")
        console.print(str(corr.round(2)))


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--fast-max", type=int, default=20, help="快线最大周期")
@click.option("--slow-max", type=int, default=60, help="慢线最大周期")
def optimize(stock, fast_max, slow_max):
    """⚡ 策略参数优化"""
    from analyzer.strategy_optimizer import get_strategy_optimizer

    code = stock.strip().zfill(6)
    console.print(f"[bold cyan]⚡ 优化 {code} MA交叉策略参数...[/bold cyan]")

    optimizer = get_strategy_optimizer()
    result = optimizer.optimize_ma_cross(
        code,
        fast_range=range(5, fast_max + 1, 5),
        slow_range=range(20, slow_max + 1, 10),
    )

    if not result.all_results:
        console.print("[yellow]优化失败[/yellow]")
        return

    console.print(Panel(
        f"最优参数: MA{result.best_params.get('fast', '')}/{result.best_params.get('slow', '')}\n"
        f"预期收益: [green]{result.best_return:+.2f}%[/green]\n"
        f"夏普比率: {result.best_sharpe:.2f}\n"
        f"最大回撤: [red]{result.best_drawdown:.2f}%[/red]",
        title="Optimization Result",
        border_style="cyan",
    ))

    # Top 10 参数组合
    table = Table(title="参数组合排名 (Top 10)", show_header=True, header_style="bold magenta")
    table.add_column("排名", justify="right")
    table.add_column("快线", justify="right")
    table.add_column("慢线", justify="right")
    table.add_column("收益%", justify="right")
    table.add_column("夏普", justify="right")
    table.add_column("回撤%", justify="right")

    for i, r in enumerate(result.all_results, 1):
        ret_color = "green" if r["total_return"] > 0 else "red"
        table.add_row(
            str(i), str(r["fast"]), str(r["slow"]),
            f"[{ret_color}]{r['total_return']:+.2f}[/{ret_color}]",
            f"{r['sharpe']:.2f}",
            f"[red]{r['max_drawdown']:.2f}[/red]",
        )
    console.print(table)


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--action", "-a", required=True, type=click.Choice(["买入", "卖出", "观望"]), help="操作")
@click.option("--reason", "-r", default="", help="交易理由")
@click.option("--price", "-p", type=float, default=0, help="价格")
@click.option("--emotion", "-e", default="", help="情绪")
@click.option("--strategy", default="", help="策略")
def journal(stock, action, reason, price, emotion, strategy):
    """📝 记录交易日志"""
    from analyzer.trade_journal import save_journal
    from data_provider.storage import Database

    code = stock.strip().zfill(6)
    db = Database()
    save_journal(db, code, action, reason, price, emotion=emotion, strategy=strategy)
    console.print(f"[green]✓ 已记录: {code} {action}[/green]")


@cli.command()
@click.option("--stock", "-s", help="股票代码（留空查看全部）")
@click.option("--limit", "-n", type=int, default=20, help="显示条数")
def journal_list(stock, limit):
    """📋 查看交易日志"""
    from analyzer.trade_journal import get_journals
    from data_provider.storage import Database

    db = Database()
    journals = get_journals(db, code=stock or "", limit=limit)

    if not journals:
        console.print("[yellow]暂无交易日志[/yellow]")
        return

    table = Table(title="交易日志", show_header=True, header_style="bold magenta")
    table.add_column("时间", style="cyan")
    table.add_column("代码")
    table.add_column("操作")
    table.add_column("价格", justify="right")
    table.add_column("理由")
    table.add_column("情绪")

    for j in journals:
        action_color = "green" if j.action == "买入" else "red" if j.action == "卖出" else "yellow"
        table.add_row(
            str(j.created_at)[:16] if j.created_at else "",
            j.code,
            f"[{action_color}]{j.action}[/{action_color}]",
            f"{j.price:.2f}" if j.price else "",
            (j.reason or "")[:25],
            j.emotion or "",
        )
    console.print(table)


@cli.command()
@click.option("--date", "-d", help="日期 YYYY-MM-DD")
def breadth(date):
    """📊 市场宽度指标"""
    from analyzer.market_breadth import get_market_breadth
    from rich.panel import Panel

    console.print(f"[bold cyan]📊 市场宽度分析[/bold cyan]")

    mb = get_market_breadth()
    data = mb.get_breadth(date)

    if data.advance_count + data.decline_count == 0:
        console.print("[yellow]无法获取市场宽度数据[/yellow]")
        return

    breadth_color = "green" if data.breadth_pct > 60 else "red" if data.breadth_pct < 40 else "yellow"

    console.print(Panel(
        f"[bold]日期: {data.date}[/bold]\n\n"
        f"上涨家数: [green]{data.advance_count}[/green]\n"
        f"下跌家数: [red]{data.decline_count}[/red]\n"
        f"平盘家数: {data.flat_count}\n"
        f"涨停: [green]{data.up_limit}[/green] | 跌停: [red]{data.down_limit}[/red]\n\n"
        f"涨跌比: {data.ad_ratio:.2f}\n"
        f"市场宽度: [{breadth_color}]{data.breadth_pct:.1f}%[/{breadth_color}]",
        title="Market Breadth",
        border_style="cyan",
    ))


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--price", "-p", type=float, required=True, help="买入价格")
@click.option("--shares", type=int, default=100, help="股数")
@click.option("--strategy", default="", help="策略")
@click.option("--reason", "-r", default="", help="理由")
def paper_buy(stock, price, shares, strategy, reason):
    """🧪 模拟买入"""
    from analyzer.paper_trading import get_paper_engine
    from data_provider.base import DataFetcherManager

    code = stock.strip().zfill(6)
    manager = DataFetcherManager()
    manager.register_sources(["baostock"])

    name = ""
    try:
        quote = manager.get_quote(code)
        name = quote.name if quote else code
    except:
        name = code

    engine = get_paper_engine()
    trade = engine.buy(code, name, price, shares, strategy, reason=reason)
    console.print(f"[green]✓ 模拟买入: {code} {name} @ {price} x {shares}股[/green]")


@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--price", "-p", type=float, required=True, help="卖出价格")
def paper_sell(stock, price):
    """🧪 模拟卖出"""
    from analyzer.paper_trading import get_paper_engine

    code = stock.strip().zfill(6)
    engine = get_paper_engine()
    result = engine.sell(code, price)

    if result:
        pnl_color = "green" if result.pnl > 0 else "red"
        console.print(f"[green]✓ 模拟卖出: {code} @ {price}[/green]")
        console.print(f"  盈亏: [{pnl_color}]{result.pnl:+.2f} ({result.pnl_pct:+.2f}%)[/{pnl_color}]")
    else:
        console.print(f"[yellow]未找到 {code} 的未平仓买入[/yellow]")


@cli.command()
def paper_positions():
    """🧪 查看模拟持仓"""
    from analyzer.paper_trading import get_paper_engine

    engine = get_paper_engine()
    engine.update_prices()
    positions = engine.get_open_positions()
    summary = engine.get_summary()

    console.print(f"[bold cyan]🧪 模拟交易持仓[/bold cyan]")

    if not positions:
        console.print("[yellow]暂无模拟持仓[/yellow]")
        return

    table = Table(title="模拟持仓", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("买入价", justify="right")
    table.add_column("现价", justify="right")
    table.add_column("股数", justify="right")
    table.add_column("盈亏", justify="right")
    table.add_column("盈亏%", justify="right")
    table.add_column("策略")

    for p in positions:
        pnl_color = "green" if p.pnl > 0 else "red"
        table.add_row(
            p.code, p.name, f"{p.price:.2f}", f"{p.current_price:.2f}",
            str(p.shares),
            f"[{pnl_color}]{p.pnl:+,.2f}[/{pnl_color}]",
            f"[{pnl_color}]{p.pnl_pct:+.2f}%[/{pnl_color}]",
            p.strategy,
        )
    console.print(table)

    console.print(f"\n总盈亏: {summary['total_pnl']:+,.2f} | 胜率: {summary['win_rate']:.1f}%")


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
