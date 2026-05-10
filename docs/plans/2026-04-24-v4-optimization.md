# A股项目增强V4：问题修复 + 深度优化

> **For subagents:** Implement all 10 optimization items.

---

## 模块一：问题修复

### Task 1.1: 扩展 StockQuote 数据类

**File:** `data_provider/base.py`

找到现有的 `StockQuote` dataclass，替换为扩展版本：

```python
@dataclass
class StockQuote:
    """实时行情数据"""
    code: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0    # 涨跌幅(%)
    change_amt: float = 0.0    # 涨跌额
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0        # 成交量(手)
    amount: float = 0.0        # 成交额(元)
    turnover_rate: float = 0.0  # 换手率(%)
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    total_mv: float = 0.0     # 总市值(元)
    circ_mv: float = 0.0       # 流通市值(元)
    # 扩展字段 (用于选股/回测)
    market_cap: float = 0.0     # 总市值(元) - alias方便用
    volume_ratio: float = 0.0   # 量比
    position_type: str = ""     # price_position: "high"/"medium"/"low"
    amplitude: float = 0.0      # 振幅(%)
    hand_rate: float = 0.0     # 换手率 (同turnover_rate)

    def __post_init__(self):
        if self.market_cap == 0.0:
            self.market_cap = self.total_mv
```

### Task 1.2: 修复 baostock_fetcher 返回字段

**File:** `data_provider/baostock_fetcher.py`

Read the file, find how `StockQuote` is populated, ensure `market_cap`, `volume_ratio`, `position_type`, and `amplitude` are set from baostock data.

For baostock `query_history_k_data_plus`, you need to call `query_stock_basic` separately to get `circ_mv` and `total_mv`.

Also ensure `market_cap` is set on the returned StockQuote.

---

## 模块二：新增功能

### Task 2.1: 添加 AI 分析 CLI 命令

**File:** `main.py`

Add before `setup_telegram`:

```python
@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--strategy", default="综合", help="策略类型")
def ai(stock, strategy):
    """🤖 AI 智能分析"""
    from analyzer.ai_advisor import get_ai_advisor

    code = stock.strip().zfill(6)
    console.print(f"[bold cyan]🤖 AI 分析中: {code}[/bold cyan]")

    advisor = get_ai_advisor()
    advice = advisor.analyze(code, strategy)

    if not advice or not advice.summary:
        console.print("[yellow]AI 分析失败，请检查 LLM 配置[/yellow]")
        return

    console.print(Panel(
        f"[bold]{advice.summary}[/bold]\n\n"
        f"操作建议: [bold]{advice.operation}[/bold]\n"
        f"建议买入价: {advice.entry_price:.2f}\n"
        f"止损价: [red]{advice.stop_loss:.2f}[/red]\n"
        f"目标价: [green]{advice.target_price:.2f}[/green]\n"
        f"风险等级: {advice.risk_level}\n\n"
        f"关键因素:\n" + "\n".join(f"  • {f}" for f in advice.key_factors[:5]) + "\n\n"
        f"风险提示:\n" + "\n".join(f"  ⚠️ {r}" for r in advice.risk_warnings[:3]),
        title=f"{code} AI 分析报告",
        border_style="cyan",
    ))
```

### Task 2.2: 添加持仓均价重算命令

**File:** `main.py` portfolio 子命令

Add new command to the `portfolio` group:

```python
@portfolio.command()
@click.option("--stock", "-s", required=True, help="股票代码")
def avg_cost(stock):
    """📐 计算持仓均价（含手续费）"""
    from data_provider.storage import Database
    from config import Config

    code = stock.strip().zfill(6)
    db = Database()
    positions = db.get_positions()
    pos = next((p for p in positions if p.code == code), None)

    if not pos:
        console.print(f"[yellow]未找到持仓: {code}[/yellow]")
        return

    # 重新计算平均成本
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
```

### Task 2.3: 添加多股票回测排名命令

**File:** `main.py`

Add new command:

```python
@cli.command()
@click.option("--stocks", "-s", help="股票代码（逗号分隔，留空则使用自选股）")
@click.option("--start", default="2025-01-01", help="回测开始日期")
@click.option("--strategy", default="ma_cross", help="策略名称")
def backtest_rank(stocks, start, strategy):
    """🏆 多股票回测排名"""
    from analyzer.backtest_engine import get_backtest_engine
    from config import Config

    config = Config.get()
    stock_list = []
    if stocks:
        stock_list = [c.strip().zfill(6) for c in stocks.split(",") if c.strip()]
    else:
        stock_list = config.WATCH_LIST[:10]  # 最多10个

    if not stock_list:
        console.print("[yellow]未指定股票[/yellow]")
        return

    engine = get_backtest_engine()
    results = {}

    console.print(f"[bold cyan]🏆 多股票回测中 ({len(stock_list)} 只)...[/bold cyan]")

    for code in stock_list:
        try:
            result = engine.run(code, start, strategy)
            results[code] = result
        except Exception as e:
            continue

    if not results:
        console.print("[yellow]所有股票回测均失败[/yellow]")
        return

    # 按年化收益排序
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
            f"[red]{r.max_drawdown:.2f}%[red]",
            f"{r.sharpe_ratio:.2f}",
        )

    console.print(table)

    # 生成图表
    try:
        chart_path = engine.plot_backtest_result(results)
        console.print(f"[green]✓ 回测图表已保存: {chart_path}[/green]")
    except:
        pass
```

### Task 2.4: 添加智能选股 CLI（基于 smart_screener）

**File:** `main.py`

```python
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
```

### Task 2.5: 邮件/企微发送命令

**File:** `main.py`

```python
@cli.command()
@click.option("--to", "-t", required=True, help="收件人邮箱")
@click.option("--subject", "-s", default="A股分析报告", help="邮件主题")
@click.option("--content", "-c", required=True, help="邮件内容")
def send_email(to, subject, content):
    """📧 发送邮件"""
    from analyzer.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier()
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
    from analyzer.telegram_notifier import TelegramNotifier

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
```

### Task 2.6: 添加配置查看命令

**File:** `main.py`

```python
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
        console.print(f"\n[bold]自选股列表[/bold]: {', '.join(config.WATCH_LIST[:10])}" +
                     (f" ... (共{len(config.WATCH_LIST)}只)" if len(config.WATCH_LIST) > 10 else ""))
```

### Task 2.7: 添加回测结果导出命令

**File:** `main.py`

```python
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
```

### Task 2.8: 添加恐慌/贪婪指数命令

**File:** `main.py`

```python
@cli.command()
def fear_greed():
    """🌡️ 市场恐慌贪婪指数"""
    from analyzer.market_sentiment import get_sentiment_analyzer

    console.print(f"[bold cyan]🌡️ 市场情绪温度计[/bold cyan]")

    analyzer = get_sentiment_analyzer()
    sentiment = analyzer.get_sentiment()

    if not sentiment:
        console.print("[yellow]无法获取市场情绪数据[/yellow]")
        return

    # 计算恐慌/贪婪指数 (基于涨跌停家数比)
    up_limit = getattr(sentiment, "up_limit_count", 0)
    down_limit = getattr(sentiment, "down_limit_count", 0)

    if up_limit + down_limit == 0:
        index = 50
    else:
        # 公式: (涨停/(涨停+跌停)) * 100，>50贪婪，<50恐慌
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

    console.print(Panel(
        f"[bold]{emoji} {level}[/bold]\n\n"
        f"恐慌/贪婪指数: [bold {color}]{index:.1f}[/bold {color}]\n\n"
        f"涨停家数: [green]{up_limit}[/green]\n"
        f"跌停家数: [red]{down_limit}[/red]\n"
        f"上涨家数: {getattr(sentiment, 'up_count', 'N/A')}\n"
        f"下跌家数: {getattr(sentiment, 'down_count', 'N/A')}",
        title="市场情绪",
        border_style="cyan",
    ))
```

### Task 2.9: 抽取板块数据获取到公共模块

**Problem:** `sector.py` 和 `sector_flow.py` 都有 `get_stock_industry()` 方法，代码重复。

**File:** 创建 `data_provider/industry.py`

```python
#!/usr/bin/env python3
"""
行业分类数据获取模块（公共模块）
被 sector.py 和 sector_flow.py 共用
"""

import baostock as bs
from typing import Dict, Optional


_industry_cache: Dict[str, str] = {}
_logged_in = False


def _login():
    global _logged_in
    if not _logged_in:
        bs.login()
        _logged_in = True


def _logout():
    global _logged_in
    if _logged_in:
        bs.logout()
        _logged_in = False


def get_stock_industry(code: str) -> str:
    """获取个股所属行业（带缓存）"""
    if code in _industry_cache:
        return _industry_cache[code]

    code = code.strip().zfill(6)
    if code.startswith(("6", "5", "9")):
        bs_code = f"sh.{code}"
    elif code.startswith(("0", "3")):
        bs_code = f"sz.{code}"
    elif code.startswith(("4", "8")):
        bs_code = f"bj.{code}"
    else:
        bs_code = f"sz.{code}"

    _login()
    try:
        rs = bs.query_stock_industry(bs_code)
        while rs.next():
            industry = rs.get_row_data()[2] or ""
            _industry_cache[code] = industry
            return industry
    finally:
        _logout()

    return ""


def clear_cache():
    """清除行业缓存"""
    global _industry_cache
    _industry_cache = {}
```

Then modify `sector.py` and `sector_flow.py` to import from `industry.py` instead of having their own implementations.

### Task 2.10: 盘中异动智能推送（扩展 monitor）

**File:** `run_monitoring.py`

Add a function to automatically send alerts to Telegram when異動 is detected. The existing `AlertSystem` already has this capability, but the monitoring script should auto-detect and send Telegram alerts for major moves (limit up, limit down, unusual volume).

---

## 文件变更汇总

| 操作 | 文件 |
|------|------|
| Modify | `data_provider/base.py` — 扩展 StockQuote |
| Modify | `data_provider/baostock_fetcher.py` — 补充 market_cap 等字段 |
| Create | `data_provider/industry.py` — 抽取公共行业获取方法 |
| Modify | `data_provider/sector.py` — 使用 industry.py |
| Modify | `data_provider/sector_flow.py` — 使用 industry.py |
| Modify | `main.py` — 新增 8 个命令 |
| Modify | `run_monitoring.py` — 增强自动推送 |

## 新增CLI命令

```
ai              🤖 AI 智能分析（新增）
portfolio avg-cost 📐 持仓均价重算（新增）
backtest-rank   🏆 多股票回测排名（新增）
screen-stocks   🔍 智能综合选股（新增）
send-email      📧 发送邮件（新增）
send-wx         💬 发送企微消息（新增）
config-show     ⚙️ 查看当前配置（新增）
backtest-export 📤 导出回测结果（新增）
fear-greed      🌡️ 恐慌贪婪指数（新增）
```
