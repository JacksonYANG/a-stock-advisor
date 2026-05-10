# A股项目增强V3：龙虎榜+板块资金+融资融券+选股报告+Web仪表盘

> **For subagents:** Implement all 5 features in parallel using delegate_task.

---

## 模块一：龙虎榜追踪器

### Task 1.1: 创建龙虎榜数据模块

**File:** `data_provider/dragon_tiger.py`

```python
#!/usr/bin/env python3
"""
龙虎榜数据追踪模块
通过 Tushare 获取龙虎榜数据，跟踪游资和机构席位动向
Tushare免费接口: top_list (龙虎榜)
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
class DragonTigerRecord:
    """龙虎榜记录"""
    date: str = ""
    code: str = ""
    name: str = ""
    close_price: float = 0.0
    change_pct: float = 0.0
    turnover_rate: float = 0.0       # 换手率
    amount: float = 0.0               # 成交额(万)
    reason: str = ""                  # 上榜原因
    # 席位数据
    buy_seats: List[Dict] = None      # 买入席位 [{name, amount}]
    sell_seats: List[Dict] = None     # 卖出席位
    net_amount: float = 0.0           # 净额(万)
    # 机构专用
    institutional_net: float = 0.0    # 机构净买入

    def __post_init__(self):
        if self.buy_seats is None:
            self.buy_seats = []
        if self.sell_seats is None:
            self.sell_seats = []


class DragonTigerFetcher:
    """龙虎榜数据获取器"""

    def __init__(self, token: str = ""):
        self.token = token
        self._pro = None

    def _get_pro(self):
        if not HAS_TUSHARE:
            return None
        if self._pro is None:
            from config import Config
            config = Config.get()
            token = self.token or config.TUSHARE_TOKEN
            if token:
                ts.set_token(token)
                self._pro = ts.pro_api()
        return self._pro

    def get_top_list(self, date: Optional[str] = None, limit: int = 100) -> List[DragonTigerRecord]:
        """
        获取龙虎榜数据
        date: 交易日期 YYYYMMDD，默认今天
        """
        pro = self._get_pro()
        if pro is None:
            return []

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            df = pro.top_list(trade_date=date)
            if df is None or df.empty:
                return []

            results = []
            for _, row in df.iterrows():
                record = DragonTigerRecord(
                    date=str(row.get("trade_date", "")),
                    code=str(row.get("ts_code", "").replace(".SH", "").replace(".SZ", "")),
                    name=str(row.get("name", "")),
                    close_price=float(row.get("close", 0)),
                    change_pct=float(row.get("pct_change", 0)),
                    turnover_rate=float(row.get("turnover_rate", 0)),
                    amount=float(row.get("amount", 0)) / 1e4,  # 转换为万
                    reason=str(row.get("reason", "")),
                )

                # 解析席位数据
                buy_seats = []
                sell_seats = []
                institutional_net = 0.0

                # 从reason和席位信息中提取
                for col in ["buy_seats", "sell_seats"]:
                    if col in row and pd.notna(row[col]):
                        seats_str = str(row[col])
                        # 席位格式: "营业部A(1000万);营业部B(800万)"
                        for seat in seats_str.split(";"):
                            if seat.strip():
                                parts = seat.rsplit("(", 1)
                                if len(parts) == 2:
                                    seat_name = parts[0].strip()
                                    amount_str = parts[1].replace("万)", "").replace("亿)", "")
                                    try:
                                        amount = float(amount_str)
                                        if "亿" in seat:
                                            amount *= 10000
                                        seat_data = {"name": seat_name, "amount": amount}
                                        if "buy" in col:
                                            buy_seats.append(seat_data)
                                        else:
                                            sell_seats.append(seat_data)
                                    except:
                                        pass

                # 机构净买入
                if "institutional" in df.columns and pd.notna(row.get("institutional")):
                    institutional_net = float(row.get("institutional", 0)) / 1e4

                record.buy_seats = buy_seats
                record.sell_seats = sell_seats
                record.net_amount = sum(s["amount"] for s in buy_seats) - sum(s["amount"] for s in sell_seats)
                record.institutional_net = institutional_net
                results.append(record)

            return results
        except Exception:
            return []

    def get_history(self, days: int = 5) -> Dict[str, List[DragonTigerRecord]]:
        """获取最近N天龙虎榜"""
        results = {}
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            records = self.get_top_list(date_str)
            if records:
                results[date_str] = records

        return results

    def get_hot_seats(self, days: int = 30) -> List[Dict[str, Any]]:
        """统计最近N天最活跃席位"""
        all_records = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            records = self.get_top_list(date_str)
            all_records.extend(records)

        # 统计席位
        seat_stats: Dict[str, Dict] = {}
        for record in all_records:
            for seat in record.buy_seats:
                name = seat["name"]
                if name not in seat_stats:
                    seat_stats[name] = {"name": name, "appear_count": 0, "total_buy": 0.0, "total_sell": 0.0}
                seat_stats[name]["appear_count"] += 1
                seat_stats[name]["total_buy"] += seat["amount"]

            for seat in record.sell_seats:
                name = seat["name"]
                if name not in seat_stats:
                    seat_stats[name] = {"name": name, "appear_count": 0, "total_buy": 0.0, "total_sell": 0.0}
                seat_stats[name]["appear_count"] += 1
                seat_stats[name]["total_sell"] += seat["amount"]

        # 排序
        sorted_seats = sorted(seat_stats.values(), key=lambda x: x["appear_count"], reverse=True)
        for s in sorted_seats:
            s["net"] = s["total_buy"] - s["total_sell"]

        return sorted_seats


_dragon_fetcher = None


def get_dragon_tiger_fetcher(token: str = "") -> DragonTigerFetcher:
    global _dragon_fetcher
    if _dragon_fetcher is None:
        _dragon_fetcher = DragonTigerFetcher(token)
    return _dragon_fetcher
```

### Task 1.2: 添加 CLI 命令

**File:** `main.py` 添加命令

```python
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
            r.code,
            r.name,
            f"{r.close_price:.2f}",
            f"[{chg_color}]{r.change_pct:+.2f}%[/{chg_color}]",
            f"{r.turnover_rate:.2f}%",
            f"{r.amount:,.0f}",
            r.reason[:20],
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
        table.add_row(
            s["name"],
            str(s["appear_count"]),
            f"{s['total_buy']:,.0f}",
            f"{s['total_sell']:,.0f}",
            f"[{net_color}]{s['net']:+,.0f}[/{net_color}]",
        )

    console.print(table)
```

---

## 模块二：板块资金流向

### Task 2.1: 创建板块资金模块

**File:** `data_provider/sector_flow.py`

```python
#!/usr/bin/env python3
"""
板块资金流向模块
追踪各行业板块的资金净流入/流出
使用 baostock 行业分类 + 实时行情计算
"""

import baostock as bs
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SectorFlowData:
    """板块资金流向"""
    industry: str = ""
    stock_count: int = 0
    total_market_cap: float = 0.0     # 总市值(万)
    total_flow: float = 0.0           # 资金净流入(万)
    inflow_pct: float = 0.0           # 净流入占市值比
    avg_change: float = 0.0           # 平均涨跌幅


class SectorFlowFetcher:
    """板块资金流向获取器"""

    def __init__(self):
        self._logged_in = False
        self._industry_cache: Dict[str, str] = {}

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
        """获取个股所属行业（带缓存）"""
        if code in self._industry_cache:
            return self._industry_cache[code]

        self._login()
        try:
            bs_code = self._normalize_code(code)
            rs = bs.query_stock_industry(bs_code)
            while rs.next():
                industry = rs.get_row_data()[2] or ""
                self._industry_cache[code] = industry
                return industry
        finally:
            self._logout()
        return ""

    def get_all_sector_flows(self) -> List[SectorFlowData]:
        """获取所有板块资金流向"""
        self._login()

        # 获取所有股票
        all_stocks = []
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        # 按行业分组，同时获取行情
        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        industry_data: Dict[str, Dict] = {}

        for stock in all_stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                industry = self.get_stock_industry(code)

                if not industry:
                    continue

                if industry not in industry_data:
                    industry_data[industry] = {
                        "stocks": [],
                        "total_flow": 0.0,
                        "total_cap": 0.0,
                        "changes": [],
                    }

                # 获取行情计算资金流
                try:
                    quote = manager.get_quote(code)
                    if quote:
                        # 资金流估算: 成交额 * 涨跌幅符号 * 换手率因子
                        amount = getattr(quote, "amount", 0) or 0  # 成交额
                        change_pct = getattr(quote, "change_pct", 0) or 0

                        # 净流入估算 = 成交额 * (涨跌幅 / 100) 的方向
                        flow = amount * 1e4 * (change_pct / 100) if change_pct > 0 else amount * 1e4 * (change_pct / 100)
                        # 取绝对值作为资金进出量
                        flow_abs = abs(amount * 1e4 * change_pct / 100)

                        industry_data[industry]["total_flow"] += flow
                        industry_data[industry]["total_cap"] += getattr(quote, "market_cap", 0) or 0
                        industry_data[industry]["changes"].append(change_pct)
                        industry_data[industry]["stocks"].append(code)
                except:
                    continue
            except:
                continue

        # 构建结果
        results = []
        for industry, data in industry_data.items():
            if not data["stocks"]:
                continue

            avg_change = sum(data["changes"]) / len(data["changes"]) if data["changes"] else 0
            inflow_pct = (data["total_flow"] / data["total_cap"] * 100) if data["total_cap"] > 0 else 0

            results.append(SectorFlowData(
                industry=industry,
                stock_count=len(data["stocks"]),
                total_market_cap=data["total_cap"] / 1e4,  # 转为亿
                total_flow=data["total_flow"] / 1e4,       # 转为亿
                inflow_pct=inflow_pct,
                avg_change=avg_change,
            ))

        # 按资金净流入排序
        results.sort(key=lambda x: x.total_flow, reverse=True)
        return results


_sector_flow_fetcher = None


def get_sector_flow_fetcher() -> SectorFlowFetcher:
    global _sector_flow_fetcher
    if _sector_flow_fetcher is None:
        _sector_flow_fetcher = SectorFlowFetcher()
    return _sector_flow_fetcher
```

### Task 2.2: 添加 CLI 命令

```python
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
            f.industry,
            str(f.stock_count),
            f"[{change_color}]{f.avg_change:+.2f}%[/{change_color}]",
            f"[{flow_color}]{f.total_flow:+,.2f}亿[/{flow_color}]",
            f"{f.inflow_pct:+.2f}%",
        )

    console.print(table)
```

---

## 模块三：融资融券数据

### Task 3.1: 创建融资融券模块

**File:** `data_provider/margin.py`

```python
#!/usr/bin/env python3
"""
融资融券数据模块
通过 Tushare 获取个股的融资融券数据
融资 = 做多力量，融券 = 做空力量
Tushare免费接口: margin_detail (融资融券明细)
"""

import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False


@dataclass
class MarginData:
    """融资融券数据"""
    date: str = ""
    code: str = ""
    name: str = ""
    close_price: float = 0.0
    # 融资数据
    margin_balance: float = 0.0    # 融资余额(万)
    margin_buy: float = 0.0         # 融资买入额(万)
    margin_repay: float = 0.0       # 融资偿还额(万)
    margin_net: float = 0.0         # 融资净买入(万)
    # 融券数据
    short_balance: float = 0.0       # 融券余额(万)
    short_sell: float = 0.0          # 融券卖出量
    short_cover: float = 0.0         # 融券偿还量
    short_net: float = 0.0           # 融券净卖出
    # 杠杆指标
    margin_ratio: float = 0.0       # 融资融券余额比


class MarginFetcher:
    """融资融券数据获取器"""

    def __init__(self, token: str = ""):
        self.token = token
        self._pro = None

    def _get_pro(self):
        if not HAS_TUSHARE:
            return None
        if self._pro is None:
            from config import Config
            config = Config.get()
            token = self.token or config.TUSHARE_TOKEN
            if token:
                ts.set_token(token)
                self._pro = ts.pro_api()
        return self._pro

    def get_daily(self, code: str, date: Optional[str] = None) -> Optional[MarginData]:
        """获取个股每日融资融券数据"""
        pro = self._get_pro()
        if pro is None:
            return None

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            # 转换代码格式
            ts_code = code.zfill(6)
            if ts_code.startswith(("6", "5", "9")):
                ts_code = f"{ts_code}.SH"
            else:
                ts_code = f"{ts_code}.SZ"

            df = pro.margin_detail(ts_code=ts_code, trade_date=date)
            if df is None or df.empty:
                return None

            row = df.iloc[0]
            return MarginData(
                date=str(row.get("trade_date", "")),
                code=code,
                name=str(row.get("name", "")),
                close_price=float(row.get("close", 0)),
                margin_balance=float(row.get("margin_balance", 0)) / 1e4,  # 转为万
                margin_buy=float(row.get("margin_buy", 0)) / 1e4,
                margin_repay=float(row.get("margin_repay", 0)) / 1e4,
                margin_net=float(row.get("net_buy_rate", 0)),
                short_balance=float(row.get("short_balance", 0)) / 1e4,
                short_sell=float(row.get("short_sell_amount", 0)),
                short_cover=float(row.get("short_cover_amount", 0)),
                short_net=float(row.get("net_short_position", 0)),
                margin_ratio=float(row.get("margin_balance", 0) / max(float(row.get("short_balance", 1)), 1)),
            )
        except Exception:
            return None

    def get_history(self, code: str, days: int = 10) -> List[MarginData]:
        """获取个股最近N天融资融券历史"""
        results = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            data = self.get_daily(code, date_str)
            if data:
                results.append(data)

        return results


_margin_fetcher = None


def get_margin_fetcher(token: str = "") -> MarginFetcher:
    global _margin_fetcher
    if _margin_fetcher is None:
        _margin_fetcher = MarginFetcher(token)
    return _margin_fetcher
```

### Task 3.2: 添加 CLI 命令

```python
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
        f"融券余额/融资余额: {latest.margin_ratio:.2f}x",
        title=f"{latest.name}",
        border_style="cyan",
    ))

    table = Table(title=f"近{len(history)}日融资融券", show_header=True, header_style="bold magenta")
    table.add_column("日期", style="cyan")
    table.add_column("收盘价", justify="right")
    table.add_column("融资余额(万)", justify="right", style="green")
    table.add_column("融资买入(万)", justify="right")
    table.add_column("融券余额(万)", justify="right", style="red")
    table.add_column("融券余额/融资", justify="right")

    for d in history:
        table.add_row(
            d.date,
            f"{d.close_price:.2f}",
            f"{d.margin_balance:,.0f}",
            f"{d.margin_buy:,.0f}",
            f"{d.short_balance:,.0f}",
            f"{d.margin_ratio:.2f}",
        )

    console.print(table)
```

---

## 模块四：智能选股报告

### Task 4.1: 创建选股报告模块

**File:** `analyzer/stock_picker.py`

```python
#!/usr/bin/env python3
"""
智能选股报告生成器
基于多维度分析，生成每日推荐股票池报告
综合: 技术面 + 资金面 + 情绪面 + 板块联动
"""

import pandas as pd
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from rich.console import Console

console = Console()


@dataclass
class PickRecommendation:
    """选股推荐"""
    code: str = ""
    name: str = ""
    score: float = 0.0          # 综合评分 0-100
    tags: List[str] = None       # 标签: ["突破", "游资买入", "板块龙头"]
    entry_price: float = 0.0     # 建议买入价
    stop_loss: float = 0.0       # 止损价
    target_price: float = 0.0   # 目标价
    position_pct: float = 20.0  # 建议仓位
    reasons: List[str] = None
    risk_level: str = "medium"   # low / medium / high

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.reasons is None:
            self.reasons = []


class StockPicker:
    """智能选股器"""

    def __init__(self):
        self.min_score = 60  # 最低入选分数

    def generate_daily_report(self, top_n: int = 10) -> Dict[str, Any]:
        """
        生成每日选股报告
        综合: 技术突破 + 资金流入 + 板块联动 + 情绪共振
        """
        from data_provider.base import DataFetcherManager
        from data_provider.sector import get_sector_fetcher

        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "market_summary": "",
            "recommendations": [],
            "hot_sectors": [],
            "risk_warnings": [],
        }

        # 1. 获取强势板块
        try:
            sector_fetcher = get_sector_fetcher()
            sectors = sector_fetcher.get_all_sectors()[:5]
            report["hot_sectors"] = [s["industry"] for s in sectors]
        except:
            pass

        # 2. 扫描自选股/热门股
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        from config import Config
        config = Config.get()
        watch_list = config.WATCH_LIST or []

        candidates = []
        for code in watch_list:
            try:
                quote = manager.get_quote(code)
                if not quote:
                    continue

                score = 0
                tags = []
                reasons = []

                # 涨幅评分
                if quote.change_pct >= 9.5:
                    score += 30
                    tags.append("涨停")
                    reasons.append("涨停封板")
                elif quote.change_pct >= 5:
                    score += 20
                    tags.append("强势")
                    reasons.append("涨幅超过5%")
                elif quote.change_pct > 0:
                    score += 10
                    reasons.append("上涨")

                # 放量评分
                if hasattr(quote, "volume_ratio") and quote.volume_ratio > 2:
                    score += 15
                    tags.append("放量")
                    reasons.append(f"量比{quote.volume_ratio:.1f}x")
                elif hasattr(quote, "volume_ratio") and quote.volume_ratio > 1.5:
                    score += 8
                    tags.append("温和放量")

                # 价格位置
                if hasattr(quote, "position_type"):
                    if quote.position_type == "high":
                        score += 10
                        tags.append("高位")
                        reasons.append("处于高位")
                    elif quote.position_type == "low":
                        score += 5
                        reasons.append("低位")

                if score >= self.min_score:
                    # 计算止损/目标
                    entry = quote.current_price
                    stop_loss = entry * 0.97  # 3%止损
                    target = entry * 1.05     # 5%目标

                    candidates.append(PickRecommendation(
                        code=code,
                        name=quote.name,
                        score=score,
                        tags=tags,
                        entry_price=entry,
                        stop_loss=stop_loss,
                        target_price=target,
                        reasons=reasons,
                        risk_level="high" if "涨停" in tags else "medium",
                    ))
            except:
                continue

        # 按评分排序
        candidates.sort(key=lambda x: x.score, reverse=True)
        report["recommendations"] = candidates[:top_n]

        return report

    def print_report(self, report: Dict[str, Any]):
        """打印选股报告"""
        console.print(f"\n[bold cyan]🎯 每日智能选股报告 — {report['date']}[/bold cyan]\n")

        # 热门板块
        if report["hot_sectors"]:
            console.print(f"[bold]🔥 强势板块[/bold]: {' | '.join(report['hot_sectors'])}")

        # 推荐股票
        if not report["recommendations"]:
            console.print("[yellow]今日暂无符合条件的股票[/yellow]")
            return

        table = Table(title=f"推荐股票 (共{len(report['recommendations'])}只)", show_header=True, header_style="bold magenta")
        table.add_column("代码", style="cyan")
        table.add_column("名称")
        table.add_column("评分", justify="right")
        table.add_column("标签")
        table.add_column("建议价", justify="right")
        table.add_column("止损价", justify="right")
        table.add_column("仓位", justify="right")
        table.add_column("推荐理由")

        for r in report["recommendations"]:
            risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(r.risk_level, "dim")
            tags_str = "/".join(r.tags)
            reasons_str = "; ".join(r.reasons[:2])

            table.add_row(
                r.code,
                r.name,
                f"[bold]{r.score:.0f}[/bold]",
                f"[{risk_color}]{tags_str}[/{risk_color}]",
                f"{r.entry_price:.2f}",
                f"{r.stop_loss:.2f}",
                f"{r.position_pct:.0f}%",
                reasons_str,
            )

        console.print(table)


_picker = None


def get_stock_picker() -> StockPicker:
    global _picker
    if _picker is None:
        _picker = StockPicker()
    return _picker
```

### Task 4.2: 添加 CLI 命令

```python
@cli.command()
@click.option("--top", "-n", type=int, default=10, help="推荐股票数量")
def pick(top):
    """🎯 智能选股报告"""
    from analyzer.stock_picker import get_stock_picker

    console.print(f"[bold cyan]🎯 智能选股中...[/bold cyan]")

    picker = get_stock_picker()
    report = picker.generate_daily_report(top_n=top)
    picker.print_report(report)
```

---

## 模块五：Web仪表盘

### Task 5.1: 创建Web仪表盘

**File:** `web_dashboard.py` (项目根目录)

```python
#!/usr/bin/env python3
"""
A股分析系统 Web 控制台
基于 Flask + 实时数据，提供可视化仪表盘
"""

import os
import json
from datetime import datetime
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.template_folder = "templates"

# 确保reports目录存在
os.makedirs("reports/charts", exist_ok=True)


@app.route("/")
def index():
    """仪表盘主页"""
    return render_template("dashboard.html")


@app.route("/api/market")
def api_market():
    """市场总览API"""
    try:
        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        # 上证指数
        sh = manager.get_quote("000001")
        # 创业板
        cy = manager.get_quote("399006")

        return jsonify({
            "success": True,
            "data": {
                "shanghai": {
                    "price": sh.current_price if sh else 0,
                    "change": sh.change_pct if sh else 0,
                },
                "chengye": {
                    "price": cy.current_price if cy else 0,
                    "change": cy.change_pct if cy else 0,
                },
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/sector")
def api_sector():
    """板块数据API"""
    try:
        from data_provider.sector import get_sector_fetcher
        fetcher = get_sector_fetcher()
        sectors = fetcher.get_all_sectors()[:10]
        return jsonify({"success": True, "data": sectors})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/portfolio")
def api_portfolio():
    """持仓数据API"""
    try:
        from data_provider.storage import Database
        db = Database()
        positions = db.get_positions()
        return jsonify({
            "success": True,
            "data": [
                {
                    "code": p.code,
                    "name": p.name,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "floating_pnl": p.floating_pnl,
                }
                for p in positions
            ]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """回测API"""
    try:
        data = request.json
        code = data.get("code", "000001")
        start = data.get("start", "2025-01-01")

        from analyzer.backtest_engine import get_backtest_engine
        engine = get_backtest_engine()
        result = engine.run(code, start)

        return jsonify({
            "success": True,
            "data": {
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "win_rate": result.win_rate,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    print("🌐 启动 Web 控制台: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
```

### Task 5.2: 创建HTML模板

**File:** `templates/dashboard.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股分析系统 - 控制台</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
        body { background: #0f1419; color: #e7e9ea; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
        .card { background: #192734; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
        .metric { font-size: 2rem; font-weight: bold; }
        .positive { color: #00ba7c; }
        .negative { color: #ff4444; }
        .tab { padding: 8px 16px; cursor: pointer; border-radius: 6px; }
        .tab.active { background: #22303c; }
        #sectorChart, #portfolioChart { height: 300px; }
    </style>
</head>
<body>
    <div class="max-w-7xl mx-auto p-4">
        <header class="flex justify-between items-center mb-6">
            <h1 class="text-2xl font-bold">📈 A股分析系统</h1>
            <span class="text-gray-400" id="clock"></span>
        </header>

        <!-- 市场概览 -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="card">
                <div class="text-gray-400 text-sm">上证指数</div>
                <div class="metric" id="sh-price">--</div>
                <div class="text-sm" id="sh-change">--</div>
            </div>
            <div class="card">
                <div class="text-gray-400 text-sm">深证成指</div>
                <div class="metric" id="sz-price">--</div>
                <div class="text-sm" id="sz-change">--</div>
            </div>
            <div class="card">
                <div class="text-gray-400 text-sm">创业板</div>
                <div class="metric" id="cy-price">--</div>
                <div class="text-sm" id="cy-change">--</div>
            </div>
            <div class="card">
                <div class="text-gray-400 text-sm">沪深港通北向</div>
                <div class="metric positive" id="north-money">--</div>
                <div class="text-sm text-gray-400">亿</div>
            </div>
        </div>

        <!-- 标签页 -->
        <div class="flex gap-2 mb-4">
            <div class="tab active" onclick="showTab('sector')">🏭 板块</div>
            <div class="tab" onclick="showTab('portfolio')">💼 持仓</div>
            <div class="tab" onclick="showTab('backtest')">🔁 回测</div>
        </div>

        <!-- 板块Tab -->
        <div id="tab-sector" class="card">
            <h2 class="text-lg font-bold mb-4">板块涨跌排行</h2>
            <div id="sectorChart"></div>
        </div>

        <!-- 持仓Tab -->
        <div id="tab-portfolio" class="card" style="display:none">
            <h2 class="text-lg font-bold mb-4">我的持仓</h2>
            <table class="w-full text-left">
                <thead><tr class="text-gray-400"><th>代码</th><th>名称</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>浮动盈亏</th></tr></thead>
                <tbody id="portfolio-body"></tbody>
            </table>
        </div>

        <!-- 回测Tab -->
        <div id="tab-backtest" class="card" style="display:none">
            <h2 class="text-lg font-bold mb-4">策略回测</h2>
            <div class="flex gap-4 mb-4">
                <input type="text" id="bt-code" placeholder="股票代码" value="000001" class="bg-gray-800 text-white px-3 py-2 rounded">
                <button onclick="runBacktest()" class="bg-blue-600 px-4 py-2 rounded hover:bg-blue-700">运行回测</button>
            </div>
            <div id="bt-results" class="grid grid-cols-4 gap-4"></div>
        </div>
    </div>

    <script>
        // 时钟
        function updateClock() {
            document.getElementById('clock').textContent = new Date().toLocaleString('zh-CN');
        }
        setInterval(updateClock, 1000);
        updateClock();

        // 加载市场数据
        async function loadMarket() {
            try {
                const res = await fetch('/api/market');
                const json = await res.json();
                if (json.success) {
                    const sh = json.data.shanghai;
                    document.getElementById('sh-price').textContent = sh.price.toFixed(2);
                    document.getElementById('sh-change').textContent = (sh.change >= 0 ? '+' : '') + sh.change.toFixed(2) + '%';
                    document.getElementById('sh-change').className = sh.change >= 0 ? 'text-sm positive' : 'text-sm negative';
                }
            } catch(e) { console.log(e); }
        }

        // 板块图表
        async function loadSectorChart() {
            try {
                const res = await fetch('/api/sector');
                const json = await res.json();
                if (json.success) {
                    const chart = echarts.init(document.getElementById('sectorChart'));
                    chart.setOption({
                        yAxis: { type: 'category', data: json.data.map(s => s.industry), axisLabel: { color: '#e7e9ea' } },
                        xAxis: { type: 'value', axisLabel: { color: '#e7e9ea' } },
                        series: [{ type: 'bar', data: json.data.map(s => ({ value: s.avg_change, itemStyle: { color: s.avg_change >= 0 ? '#00ba7c' : '#ff4444' } })) }],
                        tooltip: { trigger: 'axis' },
                    });
                }
            } catch(e) { console.log(e); }
        }

        // 持仓
        async function loadPortfolio() {
            try {
                const res = await fetch('/api/portfolio');
                const json = await res.json();
                if (json.success) {
                    const tbody = document.getElementById('portfolio-body');
                    tbody.innerHTML = json.data.map(p => `
                        <tr class="border-t border-gray-700">
                            <td>${p.code}</td><td>${p.name}</td><td>${p.shares}</td>
                            <td>${p.avg_cost.toFixed(2)}</td><td>${p.current_price.toFixed(2)}</td>
                            <td>${p.market_value.toFixed(2)}</td>
                            <td class="${p.floating_pnl >= 0 ? 'positive' : 'negative'}">${p.floating_pnl >= 0 ? '+' : ''}${p.floating_pnl.toFixed(2)}</td>
                        </tr>`).join('');
                }
            } catch(e) { console.log(e); }
        }

        function runBacktest() {
            const code = document.getElementById('bt-code').value;
            fetch('/api/backtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) })
                .then(r => r.json())
                .then(json => {
                    if (json.success) {
                        const d = json.data;
                        document.getElementById('bt-results').innerHTML = `
                            <div class="bg-gray-800 p-4 rounded"><div class="text-gray-400">总收益</div><div class="metric ${d.total_return>=0?'positive':'negative'}">${d.total_return.toFixed(1)}%</div></div>
                            <div class="bg-gray-800 p-4 rounded"><div class="text-gray-400">年化收益</div><div class="metric ${d.annualized_return>=0?'positive':'negative'}">${d.annualized_return.toFixed(1)}%</div></div>
                            <div class="bg-gray-800 p-4 rounded"><div class="text-gray-400">胜率</div><div class="metric">${d.win_rate.toFixed(1)}%</div></div>
                            <div class="bg-gray-800 p-4 rounded"><div class="text-gray-400">最大回撤</div><div class="metric negative">${d.max_drawdown.toFixed(1)}%</div></div>`;
                    }
                });
        }

        function showTab(name) {
            document.querySelectorAll('[id^=tab-]').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-' + name).style.display = 'block';
            event.target.classList.add('active');
        }

        loadMarket();
        loadSectorChart();
        loadPortfolio();
        setInterval(loadMarket, 30000);
    </script>
</body>
</html>
```

---

## 文件变更汇总

| 文件 | 操作 |
|------|------|
| `data_provider/dragon_tiger.py` | Create - 龙虎榜数据 |
| `data_provider/sector_flow.py` | Create - 板块资金流向 |
| `data_provider/margin.py` | Create - 融资融券 |
| `analyzer/stock_picker.py` | Create - 智能选股报告 |
| `web_dashboard.py` | Create - Flask Web仪表盘 |
| `templates/dashboard.html` | Create - 仪表盘HTML模板 |
| `main.py` | Modify - 添加5个新CLI命令 |

## 新增CLI命令

```
dragon-tiger    🐉 龙虎榜追踪
hot-seats       🔥 热门游资席位
sector-flow     💧 板块资金流向
margin          📊 融资融券数据
pick            🎯 智能选股报告
```

## 运行Web仪表盘

```bash
cd ~/a-stock-advisor
source venv/bin/activate
pip install flask -q
python web_dashboard.py
# 打开浏览器: http://localhost:5000
```
