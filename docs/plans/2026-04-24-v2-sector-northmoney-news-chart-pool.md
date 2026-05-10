# A股项目增强V2：板块分析+北向资金+舆情+回测图表+股票池

> **For Hermes:** Use subagent-driven-development skill to implement all 5 features.

**Goal:** 为A股项目添加5大核心能力

**Tech Stack:** matplotlib, baostock, akshare, tushare, pandas

---

## 模块一：板块/题材联动分析

### Task 1.1: 创建板块数据获取模块

**Files:**
- Create: `data_provider/sector.py`

```python
#!/usr/bin/env python3
"""
板块/行业数据获取模块
基于 baostock + akshare 获取板块涨跌/资金流/联动效应
"""

import baostock as bs
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SectorData:
    """板块数据结构"""
    industry: str = ""
    stock_count: int = 0
    avg_change: float = 0.0    # 平均涨跌幅 %
    up_count: int = 0         # 上涨家数
    down_count: int = 0       # 下跌家数
    limit_up_count: int = 0    # 涨停家数
    lead_stock: str = ""       # 龙头股
    lead_change: float = 0.0   # 龙头涨幅


class SectorFetcher:
    """板块数据获取器"""

    def __init__(self):
        self._logged_in = False

    def _login(self):
        if not self._logged_in:
            bs.login()
            self._logged_in = True

    def _logout(self):
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def _normalize_code(self, code: str) -> str:
        code = code.strip().zfill(6)
        if code.startswith(("6", "5", "9")):
            return f"sh.{code}"
        elif code.startswith(("0", "3")):
            return f"sz.{code}"
        elif code.startswith(("4", "8")):
            return f"bj.{code}"
        return f"sz.{code}"

    def get_stock_industry(self, code: str) -> str:
        """获取个股所属行业"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            rs = bs.query_stock_industry(bs_code)
            while rs.next():
                return rs.get_row_data()[2] or ""
        finally:
            self._logout()
        return ""

    def get_all_sectors(self) -> List[Dict[str, Any]]:
        """获取所有行业板块数据"""
        self._login()
        try:
            # 获取所有股票的行业信息
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            stocks = []
            while rs.next():
                stocks.append(rs.get_row_data())
        finally:
            self._logout()

        # 按行业分组
        industry_stocks: Dict[str, List] = {}
        for stock in stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                industry = self.get_stock_industry(code)
                if industry:
                    if industry not in industry_stocks:
                        industry_stocks[industry] = []
                    industry_stocks[industry].append({
                        "code": code,
                        "name": stock[2] if len(stock) > 2 else "",
                    })
            except:
                continue

        # 获取每个行业的涨跌情况
        results = []
        for industry, stock_list in industry_stocks.items():
            if not stock_list:
                continue

            try:
                changes = []
                lead_stock = ""
                lead_change = -999.0
                limit_up = 0

                for s in stock_list[:20]:  # 最多检查20只
                    try:
                        from data_provider.base import DataFetcherManager
                        mgr = DataFetcherManager()
                        mgr.register_sources(["baostock"])
                        quote = mgr.get_quote(s["code"])
                        if quote:
                            changes.append(quote.change_pct)
                            if quote.change_pct > lead_change:
                                lead_change = quote.change_pct
                                lead_stock = s["name"]
                            if quote.change_pct >= 9.5:
                                limit_up += 1
                    except:
                        continue

                if changes:
                    results.append({
                        "industry": industry,
                        "stock_count": len(stock_list),
                        "avg_change": sum(changes) / len(changes),
                        "up_count": sum(1 for c in changes if c > 0),
                        "down_count": sum(1 for c in changes if c < 0),
                        "limit_up_count": limit_up,
                        "lead_stock": lead_stock,
                        "lead_change": lead_change,
                    })
            except:
                continue

        # 按平均涨幅排序
        results.sort(key=lambda x: x["avg_change"], reverse=True)
        return results

    def get_sector_stocks(self, industry: str) -> List[Dict[str, Any]]:
        """获取某行业所有成分股"""
        self._login()
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            all_stocks = []
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        results = []
        for stock in all_stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                ind = self.get_stock_industry(code)
                if ind == industry:
                    results.append({
                        "code": code,
                        "name": stock[2] if len(stock) > 2 else "",
                    })
            except:
                continue
        return results


_sector_fetcher = None


def get_sector_fetcher() -> SectorFetcher:
    global _sector_fetcher
    if _sector_fetcher is None:
        _sector_fetcher = SectorFetcher()
    return _sector_fetcher
```

**Verify:** `cd ~/a-stock-advisor && source venv/bin/activate && python -c "from data_provider.sector import SectorFetcher; print('OK')"`

---

### Task 1.2: 添加 CLI 命令

**Files:**
- Modify: `main.py` 添加 `sector` 命令

```python
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
            f"{s['lead_change']:+.2f}%" if s['lead_change'] != -999.0 else "N/A",
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
```

---

## 模块二：北向资金追踪

### Task 2.1: 创建北向资金模块

**Files:**
- Create: `data_provider/north_money.py`

```python
#!/usr/bin/env python3
"""
北向资金追踪模块
通过 Tushare 沪深港通数据追踪外资动向
Tushare免费积分接口: hsgt_top10 (沪深港通TOP10)
"""

import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False


@dataclass
class NorthMoneyData:
    """北向资金数据"""
    date: str = ""
    hgt_shanghai: float = 0.0   # 沪股通净买入
    sgt_shenzhen: float = 0.0   # 深股通净买入
    total: float = 0.0          # 合计净买入
    # 个股数据
    top_stocks: List[Dict] = None  # [{code, name, buy_amount, reason}]

    def __post_init__(self):
        if self.top_stocks is None:
            self.top_stocks = []


class NorthMoneyFetcher:
    """北向资金获取器"""

    def __init__(self, token: str = ""):
        self.token = token
        self._pro = None

    def _get_pro(self):
        if not HAS_TUSHARE:
            return None
        if self._pro is None:
            import os
            from config import Config
            config = Config.get()
            token = self.token or config.TUSHARE_TOKEN
            if token:
                ts.set_token(token)
                self._pro = ts.pro_api()
        return self._pro

    def get_daily(self, date: Optional[str] = None) -> Optional[NorthMoneyData]:
        """获取每日北向资金流向"""
        pro = self._get_pro()
        if pro is None:
            return None

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            # 沪股通 + 深股通 十大成交
            df_sh = pro.hsgt_top10(symbol="SH", start_date=date, end_date=date)
            df_sz = pro.hsgt_top10(symbol="SZ", start_date=date, end_date=date)

            hgt_buy = 0.0
            sgt_buy = 0.0
            top_stocks = []

            if df_sh is not None and not df_sh.empty:
                # 沪股通买入
                hgt_buy = float(df_sh["buy_amount"].sum() - df_sh["sell_amount"].sum()) / 1e8

            if df_sz is not None and not df_sz.empty:
                sgt_buy = float(df_sz["buy_amount"].sum() - df_sz["sell_amount"].sum()) / 1e8

            # 合成个股TOP10
            for df in [df_sh, df_sz]:
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        top_stocks.append({
                            "code": row.get("ts_code", "").replace(".SH", "").replace(".SZ", ""),
                            "name": row.get("name", ""),
                            "buy_amount": float(row.get("buy_amount", 0)) / 1e8,
                            "sell_amount": float(row.get("sell_amount", 0)) / 1e8,
                            "net_amount": float(row.get("net_amount", 0)) / 1e8,
                        })

            return NorthMoneyData(
                date=date,
                hgt_shanghai=hgt_buy,
                sgt_shenzhen=sgt_buy,
                total=hgt_buy + sgt_buy,
                top_stocks=top_stocks,
            )
        except Exception as e:
            return None

    def get_history(self, days: int = 5) -> List[NorthMoneyData]:
        """获取最近N天北向资金历史"""
        results = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            data = self.get_daily(date_str)
            if data:
                results.append(data)

        return results


_north_fetcher = None


def get_north_money_fetcher(token: str = "") -> NorthMoneyFetcher:
    global _north_fetcher
    if _north_fetcher is None:
        _north_fetcher = NorthMoneyFetcher(token)
    return _north_fetcher
```

---

### Task 2.2: 添加 CLI 命令

**Files:**
- Modify: `main.py` 添加 `north_money` 命令

```python
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

    # 最近一天
    latest = history[0]
    console.print(Panel(
        f"[bold]日期: {latest.date}[/bold]\n\n"
        f"沪股通净买入: [green]{latest.hgt_shanghai:+,+.2f}亿[/green]\n"
        f"深股通净买入: [green]{latest.sgt_shenzhen:+,+.2f}亿[/green]\n"
        f"合计净买入:  [bold green]{latest.total:+,+.2f}亿[/bold green]",
        title="今日北向资金",
        border_style="cyan",
    ))

    # 历史趋势
    table = Table(title="近{}日北向资金趋势".format(len(history)), show_header=True, header_style="bold magenta")
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

    # 个股TOP10
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
```

---

## 模块三：新闻/公告舆情

### Task 3.1: 创建舆情模块

**Files:**
- Create: `analyzer/sentiment.py`

```python
#!/usr/bin/env python3
"""
舆情分析模块
基于网络爬虫获取个股新闻/公告，进行简单情感分析
"""

import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from bs4 import BeautifulSoup
import re


@dataclass
class NewsItem:
    """新闻条目"""
    title: str = ""
    url: str = ""
    publish_time: str = ""
    source: str = ""
    sentiment: str = ""  # positive / negative / neutral
    sentiment_score: float = 0.0  # -1 to 1


class NewsFetcher:
    """新闻获取器"""

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

    def get_stock_news(self, code: str, limit: int = 10) -> List[NewsItem]:
        """
        获取个股新闻
        使用东方财富个股资讯接口
        """
        results = []

        # 东方财富个股资讯接口
        url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size={limit}&page_index=1&ann_type=SHA%2CSZA&client_source=web&stock_list={code}"

        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("list", [])
                for item in items:
                    news = NewsItem(
                        title=item.get("title", ""),
                        url=item.get("art_url", ""),
                        publish_time=item.get("notice_date", ""),
                        source="东方财富",
                    )
                    news.sentiment, news.sentiment_score = self._analyze_sentiment(news.title)
                    results.append(news)
        except Exception:
            pass

        return results

    def _analyze_sentiment(self, text: str) -> tuple:
        """
        简单情感分析
        基于关键词打分
        """
        if not text:
            return "neutral", 0.0

        text_lower = text.lower()

        positive_words = ["增长", "盈利", "突破", "创新", "扩张", "合作", "中标", "业绩", "提升", "超额", "增持", "买入", "推荐", "买入"]
        negative_words = ["下降", "亏损", "风险", "减持", "卖出", "预警", "下调", "违规", "处罚", "诉讼", "暴跌", "破发", "ST"]

        score = 0.0
        for w in positive_words:
            if w in text_lower:
                score += 0.2
        for w in negative_words:
            if w in text_lower:
                score -= 0.2

        score = max(-1.0, min(1.0, score))

        if score > 0.1:
            sentiment = "positive"
        elif score < -0.1:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return sentiment, score


_news_fetcher = None


def get_news_fetcher() -> NewsFetcher:
    global _news_fetcher
    if _news_fetcher is None:
        _news_fetcher = NewsFetcher()
    return _news_fetcher
```

**Note:** 需要安装 `beautifulsoup4` 和 `lxml`:
```
pip install beautifulsoup4 lxml
```

---

### Task 3.2: 添加 CLI 命令

**Files:**
- Modify: `main.py` 添加 `news` 命令

```python
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
    # 使用东方财富接口需要股票代码
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
```

---

## 模块四：回测结果图表

### Task 4.1: 扩展回测引擎，添加图表生成

**Files:**
- Modify: `analyzer/backtest_engine.py` 添加权益曲线生成

在 BacktestEngine 类中添加:

```python
    def plot_backtest_result(self, results: Dict[str, BacktestResult], save_path: Optional[str] = None):
        """
        绘制回测结果图表
        - 权益曲线对比
        - 关键指标柱状图
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm

        # 中文字体
        try:
            plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
        except:
            pass

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        # 子图1: 年化收益对比
        names = list(results.keys())
        annualized = [r.annualized_return for r in results.values()]
        colors = ["green" if x >= 0 else "red" for x in annualized]

        axes[0].barh(names, annualized, color=colors, alpha=0.7)
        axes[0].set_xlabel("Annualized Return (%)")
        axes[0].set_title("Strategy Annualized Returns")
        axes[0].axvline(x=0, color="black", linewidth=0.5)
        for i, v in enumerate(annualized):
            axes[0].text(v + 0.5, i, f"{v:.1f}%", va="center", fontsize=8)

        # 子图2: 关键指标对比
        metrics = ["win_rate", "max_drawdown", "sharpe_ratio"]
        metric_labels = ["Win Rate (%)", "Max Drawdown (%)", "Sharpe Ratio"]
        x = range(len(names))
        width = 0.25

        for i, (m, l) in enumerate(zip(metrics, metric_labels)):
            values = [getattr(r, m) for r in results.values()]
            axes[1].bar([xi + width * i for xi in x], values, width, label=l)

        axes[1].set_xticks([xi + width for xi in x])
        axes[1].set_xticklabels(names, rotation=30, ha="right", fontsize=8)
        axes[1].legend(fontsize=8)
        axes[1].set_title("Key Metrics Comparison")

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
        else:
            plt.savefig("reports/backtest_result.png", dpi=150, bbox_inches="tight")

        plt.close()
        return save_path or "reports/backtest_result.png"
```

同时在 CLI 命令中调用:
```python
# 在 backtest 命令中添加:
if results:
    engine.print_summary(results)
    # 生成图表
    try:
        chart_path = engine.plot_backtest_result(results)
        console.print(f"[green]✓ 回测图表已保存: {chart_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠️ 图表生成失败: {e}[/yellow]")
```

---

## 模块五：多股票池管理

### Task 5.1: 扩展 Database，添加股票池表

**Files:**
- Modify: `data_provider/storage.py` 添加 StockPool 模型

```python
class StockPool(Base):
    """股票池"""
    __tablename__ = "stock_pools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)     # 股票池名称
    code = Column(String(10), nullable=False)     # 股票代码
    added_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, default="")
```

**添加方法到 Database 类:**
```python
    def save_stock_pool(self, pool_name: str, code: str, notes: str = ""):
        """添加股票到股票池"""
        session = self.get_session()
        try:
            existing = session.query(StockPool).filter(
                StockPool.name == pool_name,
                StockPool.code == code,
            ).first()
            if not existing:
                pool = StockPool(name=pool_name, code=code, notes=notes)
                session.add(pool)
            session.commit()
        finally:
            session.close()

    def get_stock_pools(self) -> List[str]:
        """获取所有股票池名称"""
        session = self.get_session()
        try:
            rows = session.query(StockPool.name).distinct().all()
            return [r[0] for r in rows]
        finally:
            session.close()

    def get_pool_stocks(self, pool_name: str) -> List[StockPool]:
        """获取股票池所有股票"""
        session = self.get_session()
        try:
            return session.query(StockPool).filter(StockPool.name == pool_name).all()
        finally:
            session.close()

    def remove_pool_stock(self, pool_name: str, code: str):
        """从股票池移除股票"""
        session = self.get_session()
        try:
            session.query(StockPool).filter(
                StockPool.name == pool_name,
                StockPool.code == code,
            ).delete()
            session.commit()
        finally:
            session.close()

    def delete_pool(self, pool_name: str):
        """删除整个股票池"""
        session = self.get_session()
        try:
            session.query(StockPool).filter(StockPool.name == pool_name).delete()
            session.commit()
        finally:
            session.close()
```

---

### Task 5.2: 添加 CLI 命令

**Files:**
- Modify: `main.py` 添加 `pool` 命令组

```python
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
```

---

## 依赖更新

**requirements.txt 添加:**
```
beautifulsoup4>=4.12
lxml>=4.9
```

---

## 文件变更汇总

| 文件 | 操作 |
|------|------|
| `data_provider/sector.py` | Create - 板块数据获取器 |
| `data_provider/north_money.py` | Create - 北向资金追踪 |
| `analyzer/sentiment.py` | Create - 新闻舆情 |
| `data_provider/storage.py` | Modify - 添加StockPool模型 |
| `analyzer/backtest_engine.py` | Modify - 添加图表生成 |
| `main.py` | Modify - 添加sector/north_money/news/pool CLI命令 |
| `requirements.txt` | Modify - 添加beautifulsoup4/lxml |
