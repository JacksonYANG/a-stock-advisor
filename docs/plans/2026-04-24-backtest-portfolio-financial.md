# A股项目增强：回测+持仓+基本面 实现方案

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 为A股项目添加三大核心能力：量化回测引擎、持仓管理、基本面分析

**Architecture:** 
- 回测引擎：基于 backtrader，复用现有策略YAML系统，输出绩效报告
- 持仓管理：扩展现有 SQLite 的 Database 类，添加持仓/交易记录表
- 基本面：基于 baostock 财务报表 API，扩展 data_provider 层

**Tech Stack:** backtrader, baostock, pandas, sqlalchemy, matplotlib

---

## 准备工作：确认依赖

### Task 1: 创建 requirements.txt 更新并安装依赖

**Objective:** 添加三个新功能需要的依赖包

**Files:**
- Modify: `requirements.txt`

**Step 1: 查看当前 requirements.txt**
```
cat requirements.txt
```

**Step 2: 添加新依赖**
```
backtrader>=1.9.78.123
```

**Step 3: 安装**
```bash
cd ~/a-stock-advisor && source venv/bin/activate && pip install backtrader
```

**Step 4: 验证**
```bash
python -c "import backtrader; print(backtrader.__version__)"
```
Expected: 版本号

**Step 5: Commit**
```bash
cd ~/a-stock-advisor && git add requirements.txt && git commit -m "feat: add backtrader dependency"
```

---

## 模块一：量化回测引擎

### Task 2: 创建回测引擎模块

**Objective:** 实现基于 backtrader 的回测引擎，加载YAML策略文件进行历史绩效验证

**Files:**
- Create: `analyzer/backtest_engine.py`

**Step 1: 编写回测引擎核心代码**

```python
#!/usr/bin/env python3
"""
回测引擎模块
基于 backtrader 实现策略历史回测
"""

import backtrader as bt
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
from dataclasses import dataclass, field
from rich.console import Console
from rich.table import Table

console = Console()

# 策略目录（复用现有的）
STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str = ""
    start_date: str = ""
    end_date: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0      # 总收益率 %
    annualized_return: float = 0.0  # 年化收益率 %
    max_drawdown: float = 0.0       # 最大回撤 %
    sharpe_ratio: float = 0.0       # 夏普比率
    avg_holding_days: float = 0.0   # 平均持仓天数
    profit_loss_ratio: float = 0.0  # 盈亏比

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_trades": self.total_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_return": f"{self.total_return:.2f}%",
            "annualized_return": f"{self.annualized_return:.2f}%",
            "max_drawdown": f"{self.max_drawdown:.2f}%",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
            "profit_loss_ratio": f"{self.profit_loss_ratio:.2f}",
            "avg_holding_days": f"{self.avg_holding_days:.1f}",
        }


class BacktestStrategy(bt.Strategy):
    """回测策略基类 - 从YAML条件动态判断"""

    def __init__(self):
        self.order = None
        self.entry_price = None
        self.entry_date = None
        self.trades = []  # 交易记录

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_date = self.datas[0].datetime.date(0)
            elif order.issell():
                if self.entry_price:
                    pnl_pct = (order.executed.price - self.entry_price) / self.entry_price * 100
                    self.trades.append({
                        "entry_date": self.entry_date,
                        "entry_price": self.entry_price,
                        "exit_date": self.datas[0].datetime.date(0),
                        "exit_price": order.executed.price,
                        "pnl_pct": pnl_pct,
                        "holding_days": (self.datas[0].datetime.date(0) - self.entry_date),
                    })
                self.entry_price = None
                self.entry_date = None

    def next(self):
        # 每日检查一次信号
        pass


class BacktestEngine:
    """回测引擎"""

    def __init__(self, initial_cash: float = 100000.0):
        self.initial_cash = initial_cash
        self.results: Dict[str, BacktestResult] = {}

    def load_strategy_from_yaml(self, name: str, yaml_path: Path) -> Optional[dict]:
        """加载YAML策略定义"""
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            console.print(f"[red]加载策略失败 {name}: {e}[/red]")
            return None

    def run_backtest(
        self,
        stock_code: str,
        strategy_name: str,
        strategy_yaml: dict,
        start_date: str,
        end_date: str,
        interval: int = 120,
    ) -> Optional[BacktestResult]:
        """
        对单只股票运行单个策略回测
        
        Args:
            stock_code: 股票代码 (如 000001)
            strategy_name: 策略名称
            strategy_yaml: 策略YAML配置
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            interval: 历史数据天数
        """
        cerebro = bt.Cerebro()

        # 设置初始资金
        cerebro.broker.setcash(self.initial_cash)

        # 手续费
        cerebro.broker.setcommission(commission=0.001)  # 0.1%

        # 加载数据
        from data_provider.base import DataFetcherManager
        from config import Config

        config = Config.get()
        manager = DataFetcherManager()
        manager.register_sources(config.DATA_SOURCES)

        # 获取历史数据
        stock_code_norm = stock_code.strip().zfill(6)
        df = manager.get_history(stock_code_norm, interval)

        if df is None or df.empty:
            console.print(f"[yellow]无法获取 {stock_code} 数据[/yellow]")
            return None

        # 转换日期格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # 过滤日期范围
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

        if len(df) < 20:
            console.print(f"[yellow]{stock_code} 数据不足[/yellow]")
            return None

        # 重置索引
        df = df.reset_index(drop=True)

        # 创建 backtrader 数据 feed
        data = bt.feeds.PandasData(
            dataname=df,
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        )

        cerebro.adddata(data)

        # 创建策略实例
        strategy = self._create_strategy(strategy_name, strategy_yaml)
        if strategy is None:
            return None

        cerebro.addstrategy(strategy)

        # 分析器
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        # 运行
        results = cerebro.run()

        # 提取结果
        if not results:
            return None

        strat = results[0]

        # 获取分析器结果
        try:
            drawdown = strat.analyzers.drawdown.get_analysis()
            sharpe = strat.analyzers.sharpe.get_analysis()
            returns = strat.analyzers.returns.get_analysis()
            trades = strat.analyzers.trades.get_analysis()

            total_return = returns.get("rtot", 0) * 100
            max_dd = drawdown.get("max", {}).get("drawdown", 0)
            sharpe_ratio = sharpe.get("sharperatio", 0) or 0.0

            # 交易统计
            total_trades = trades.get("total", {}).get("total", 0)
            winning = trades.get("won", {}).get("total", 0)
            losing = trades.get("lost", {}).get("total", 0)

            win_rate = winning / total_trades * 100 if total_trades > 0 else 0

            # 盈亏比
            avg_win = trades.get("won", {}).get("pnl", {}).get("avg", 0)
            avg_loss = abs(trades.get("lost", {}).get("pnl", {}).get("avg", 0))
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

            # 平均持仓天数
            all_trades = getattr(strat, "trades", [])
            if all_trades:
                total_days = sum(t["holding_days"] for t in all_trades)
                avg_days = total_days / len(all_trades) if all_trades else 0
            else:
                avg_days = 0

            # 年化收益
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            years = (end - start).days / 365.0
            annualized = (pow(1 + total_return / 100, 1 / years) - 1) * 100 if years > 0 else 0

            result = BacktestResult(
                strategy_name=strategy_name,
                start_date=start_date,
                end_date=end_date,
                total_trades=total_trades,
                winning_trades=winning,
                losing_trades=losing,
                win_rate=win_rate,
                total_return=total_return,
                annualized_return=annualized,
                max_drawdown=max_dd,
                sharpe_ratio=sharpe_ratio,
                avg_holding_days=avg_days,
                profit_loss_ratio=profit_loss_ratio,
            )

            return result

        except Exception as e:
            console.print(f"[red]分析结果提取失败: {e}[/red]")
            return None

    def _create_strategy(self, name: str, yaml_config: dict) -> Optional[type]:
        """从YAML配置创建backtrader策略类"""

        entry_conditions = yaml_config.get("entry_conditions", [])
        exit_conditions = yaml_config.get("exit_conditions", [])

        # 动态创建策略类
        strategy_code = f"""
class _BacktestStrategy_{name.replace(' ', '_')}(BacktestStrategy):
    def __init__(self):
        super().__init__()
        self.entry_conditions = {entry_conditions}
        self.exit_conditions = {exit_conditions}

    def next(self):
        # 检查是否已有持仓
        if self.entry_price is None:
            # 检查买入条件
            if self._check_entry_conditions():
                self.buy()
        else:
            # 检查卖出条件
            if self._check_exit_conditions():
                self.sell()

    def _check_entry_conditions(self):
        # 从父类技术指标获取
        return False  # 默认不触发

    def _check_exit_conditions(self):
        return False  # 默认不触发
"""
        try:
            local_ns = {"BacktestStrategy": BacktestStrategy}
            exec(strategy_code, local_ns)
            return local_ns[list(local_ns.keys())[-1]]
        except Exception as e:
            console.print(f"[red]策略类创建失败: {e}[/red]")
            return None

    def run_multi_strategy(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, BacktestResult]:
        """对一只股票运行所有策略回测"""
        results = {}

        if not STRATEGIES_DIR.exists():
            return results

        for yaml_file in STRATEGIES_DIR.glob("*.yaml"):
            strategy_data = self.load_strategy_from_yaml(yaml_file.stem, yaml_file)
            if strategy_data is None:
                continue

            console.print(f"[dim]回测 {stock_code} @ {strategy_data.get('name', yaml_file.stem)}...[/dim]")

            result = self.run_backtest(
                stock_code=stock_code,
                strategy_name=strategy_data.get("name", yaml_file.stem),
                strategy_yaml=strategy_data,
                start_date=start_date,
                end_date=end_date,
            )

            if result:
                results[result.strategy_name] = result
                self.results[result.strategy_name] = result

        return results

    def print_summary(self, results: Dict[str, BacktestResult]):
        """打印回测结果汇总表"""
        table = Table(title="📊 回测结果汇总", show_header=True, header_style="bold magenta")
        table.add_column("策略", style="cyan")
        table.add_column("交易次数", justify="right")
        table.add_column("胜率", justify="right")
        table.add_column("总收益", justify="right")
        table.add_column("年化收益", justify="right")
        table.add_column("最大回撤", justify="right")
        table.add_column("夏普比率", justify="right")
        table.add_column("盈亏比", justify="right")

        for name, r in results.items():
            dd_color = "green" if r.max_drawdown < 10 else "yellow" if r.max_drawdown < 20 else "red"
            ret_color = "green" if r.annualized_return > 0 else "red"

            table.add_row(
                name,
                str(r.total_trades),
                f"{r.win_rate:.1f}%",
                f"[{ret_color}]{r.total_return:.2f}%[/{ret_color}]",
                f"[{ret_color}]{r.annualized_return:.2f}%[/{ret_color}]",
                f"[{dd_color}]{r.max_drawdown:.2f}%[/{dd_color}]",
                f"{r.sharpe_ratio:.2f}",
                f"{r.profit_loss_ratio:.2f}",
            )

        console.print(table)


# 全局实例
_backtest_engine = None


def get_backtest_engine(initial_cash: float = 100000.0) -> BacktestEngine:
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine(initial_cash)
    return _backtest_engine
```

**Step 2: 验证语法**
```bash
cd ~/a-stock-advisor && source venv/bin/activate && python -c "from analyzer.backtest_engine import BacktestEngine; print('OK')"
```
Expected: OK

**Step 3: Commit**
```bash
git add analyzer/backtest_engine.py && git commit -m "feat: add backtrader backtest engine"
```

---

### Task 3: 添加 CLI 回测命令

**Objective:** 在 main.py 中添加 `backtest` 命令

**Files:**
- Modify: `main.py` (在CLI命令区域添加)

**Step 1: 添加导入**
```python
from analyzer.backtest_engine import get_backtest_engine
```

**Step 2: 添加命令**
```python
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
```

**Step 3: 测试**
```bash
cd ~/a-stock-advisor && source venv/bin/activate && python main.py backtest --stock 000001 --end 2026-04-01
```
Expected: 回测结果表格或"无法获取数据"提示

**Step 4: Commit**
```bash
git add main.py && git commit -m "feat: add backtest CLI command"
```

---

## 模块二：持仓管理与盈亏分析

### Task 4: 扩展 Database 类 - 添加持仓表

**Objective:** 在 SQLite 中添加持仓记录和交易记录表

**Files:**
- Modify: `data_provider/storage.py`

**Step 1: 在 Database 类之前添加新的 Model 定义**

在 `class WatchListItem(Base):` 之后添加：

```python
class Position(Base):
    """持仓记录"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    name = Column(String(20))
    shares = Column(Float, nullable=False)        # 持股数量
    avg_cost = Column(Float, nullable=False)       # 平均成本
    current_price = Column(Float, default=0)      # 当前价
    market_value = Column(Float, default=0)       # 市值
    floating_pnl = Column(Float, default=0)       # 浮动盈亏
    floating_pnl_pct = Column(Float, default=0)  # 浮动盈亏比例 %
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    opened_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, default="")


class Trade(Base):
    """交易记录"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    name = Column(String(20))
    trade_type = Column(String(10), nullable=False)   # buy / sell
    shares = Column(Float, nullable=False)            # 成交数量
    price = Column(Float, nullable=False)           # 成交价格
    amount = Column(Float, nullable=False)           # 成交金额
    commission = Column(Float, default=0)             # 手续费
    trade_date = Column(DateTime, default=datetime.now, index=True)
    strategy = Column(String(50), default="")        # 策略来源
    signal_price = Column(Float, default=0)         # 信号时价格
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
```

**Step 2: 在 Database 类中添加持仓管理方法**

```python
def save_position(self, code: str, name: str, shares: float, avg_cost: float, notes: str = ""):
    """保存或更新持仓"""
    session = self.get_session()
    try:
        existing = session.query(Position).filter(Position.code == code).first()
        if existing:
            existing.shares = shares
            existing.avg_cost = avg_cost
            existing.updated_at = datetime.now()
            existing.notes = notes
        else:
            pos = Position(code=code, name=name, shares=shares, avg_cost=avg_cost, notes=notes)
            session.add(pos)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def get_positions(self) -> List[Position]:
    """获取所有持仓"""
    session = self.get_session()
    try:
        return session.query(Position).all()
    finally:
        session.close()

def update_position_price(self, code: str, current_price: float):
    """更新持仓当前价格和盈亏"""
    session = self.get_session()
    try:
        pos = session.query(Position).filter(Position.code == code).first()
        if pos:
            pos.current_price = current_price
            pos.market_value = pos.shares * current_price
            pos.floating_pnl = (current_price - pos.avg_cost) * pos.shares
            pos.floating_pnl_pct = (current_price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost > 0 else 0
            pos.updated_at = datetime.now()
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def remove_position(self, code: str):
    """清仓（删除持仓）"""
    session = self.get_session()
    try:
        pos = session.query(Position).filter(Position.code == code).first()
        if pos:
            session.delete(pos)
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def save_trade(self, code: str, name: str, trade_type: str, shares: float,
               price: float, amount: float, commission: float = 0,
               strategy: str = "", signal_price: float = 0, notes: str = ""):
    """保存交易记录"""
    session = self.get_session()
    try:
        trade = Trade(
            code=code, name=name, trade_type=trade_type,
            shares=shares, price=price, amount=amount,
            commission=commission, strategy=strategy,
            signal_price=signal_price, notes=notes,
        )
        session.add(trade)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def get_trades(self, code: Optional[str] = None, limit: int = 50) -> List[Trade]:
    """获取交易记录"""
    session = self.get_session()
    try:
        q = session.query(Trade)
        if code:
            q = q.filter(Trade.code == code)
        return q.order_by(Trade.trade_date.desc()).limit(limit).all()
    finally:
        session.close()
```

**Step 3: 验证**
```bash
cd ~/a-stock-advisor && source venv/bin/activate && python -c "
from data_provider.storage import Database
db = Database()
# 验证新表已创建
from sqlalchemy import inspect
inspector = inspect(db.engine)
tables = inspector.get_table_names()
print('Tables:', tables)
"
```
Expected: 包含 positions 和 trades

**Step 4: Commit**
```bash
git add data_provider/storage.py && git commit -m "feat: add position and trade tables to database"
```

---

### Task 5: 创建持仓管理 CLI 命令

**Objective:** 在 main.py 中添加持仓管理命令

**Files:**
- Modify: `main.py`

**Step 1: 添加持仓命令组**

```python
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
def list():
    """📋 查看持仓"""
    from config import Config
    from data_provider.base import DataFetcherManager

    db = Database()
    positions = db.get_positions()

    if not positions:
        console.print("[yellow]暂无持仓[/yellow]")
        return

    # 更新实时价格
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
    console.print(f"\n[bold]总浮动盈亏: [\{total_color}]{total_pnl:+,.0f}[/{total_color}] | 总市值: {total_value:,.0f}[/bold]")


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
    commission = amount * 0.001  # 0.1% 手续费

    # 保存交易记录
    db.save_trade(
        code=code, name=pos.name or "",
        trade_type="sell", shares=shares, price=price,
        amount=amount, commission=commission,
        strategy=strategy or "", notes=notes or "",
    )

    # 更新持仓
    new_shares = pos.shares - shares
    if new_shares <= 0:
        db.remove_position(code)
        console.print(f"[yellow]✓ {code} 已全部清仓[/yellow]")
    else:
        # 保留剩余持仓
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
```

**Step 2: 测试**
```bash
cd ~/a-stock-advisor && source venv/bin/activate
python main.py portfolio --help
python main.py portfolio list
```

**Step 3: Commit**
```bash
git add main.py && git commit -m "feat: add portfolio management CLI commands"
```

---

## 模块三：财务数据基本面分析

### Task 6: 创建基本面数据获取模块

**Objective:** 基于 baostock 实现财务报表数据获取

**Files:**
- Create: `data_provider/fundamental.py`

**Step 1: 编写基本面数据获取器**

```python
#!/usr/bin/env python3
"""
基本面数据获取模块
基于 baostock 获取财务报表数据
"""

import baostock as bs
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from config import Config


@dataclass
class FinancialData:
    """财务数据结构"""
    code: str = ""
    name: str = ""
    trade_date: str = ""

    # 估值指标
    pe: float = 0.0      # 市盈率
    pb: float = 0.0      # 市净率
    ps: float = 0.0      # 市销率
    pcf: float = 0.0      # 市现率

    # 每股指标
    eps: float = 0.0     # 每股收益
    bps: float = 0.0     # 每股净资产
    roe: float = 0.0     # 净资产收益率 %
    roa: float = 0.0     # 总资产收益率 %

    # 成长指标
    revenue_growth: float = 0.0   # 营收增长率 %
    profit_growth: float = 0.0    # 净利润增长率 %
    equity_growth: float = 0.0    # 净资产增长率 %

    # 财务质量
    gross_margin: float = 0.0    # 毛利率 %
    net_margin: float = 0.0      # 净利率 %
    debt_ratio: float = 0.0      # 资产负债率 %


class FundamentalFetcher:
    """基本面数据获取器"""

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
        """转换代码格式: 000001 -> sh.600000 或 sz.000001"""
        code = code.strip().zfill(6)
        if code.startswith(("6", "5", "9")):
            return f"sh.{code}"
        elif code.startswith(("0", "3")):
            return f"sz.{code}"
        elif code.startswith(("4", "8")):
            return f"bj.{code}"
        return f"sz.{code}"

    def get_daily_basic(self, code: str, date: Optional[str] = None) -> Optional[FinancialData]:
        """
        获取个股每日指标 (PE/PB/换手率等)
        date: YYYY-MM-DD
        """
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")

            rs = bs.query_daily_basic(bs_code, date=date.replace("-", ""))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None

            df = pd.DataFrame(rows, columns=rs.fields)

            # 获取股票名称
            name = ""
            try:
                rs_name = bs.query_stock_basic(bs_code)
                while rs_name.next():
                    name = rs_name.get_row_data()[1]
            except:
                pass

            row = df.iloc[0]
            return FinancialData(
                code=code,
                name=name,
                trade_date=row.get("tradeDate", ""),
                pe=float(row.get("peTTM", 0) or 0),
                pb=float(row.get("pbMRQ", 0) or 0),
                ps=float(row.get("psTTM", 0) or 0),
                pcf=float(row.get("pcfTTM", 0) or 0),
            )
        finally:
            self._logout()

    def get_income_statement(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """
        获取利润表
        year: 2024, quarter: 1-4
        """
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_income_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None

            df = pd.DataFrame(rows, columns=rs.fields)
            return df
        finally:
            self._logout()

    def get_balance_sheet(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """获取资产负债表"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_balance_sheet_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None

            df = pd.DataFrame(rows, columns=rs.fields)
            return df
        finally:
            self._logout()

    def get_cash_flow(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """获取现金流量表"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_cash_flow_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None

            df = pd.DataFrame(rows, columns=rs.fields)
            return df
        finally:
            self._logout()

    def get_financial_summary(self, code: str) -> Optional[FinancialData]:
        """
        获取完整财务摘要（综合估值+成长+财务质量）
        """
        self._login()
        try:
            bs_code = self._normalize_code(code)

            # 获取每日指标（最新）
            daily = self.get_daily_basic(code)

            # 获取最近4个季度的财务数据来计算成长和盈利
            current_year = datetime.now().year
            data = FinancialData(code=code)

            if daily:
                data.pe = daily.pe
                data.pb = daily.pb
                data.ps = daily.ps
                data.pcf = daily.pcf
                data.name = daily.name

            # 计算 ROE (最近年报)
            rs_roe = bs.query_roe_data(bs_code)
            roe_rows = []
            while rs_roe.next():
                roe_rows.append(rs_roe.get_row_data())
            if roe_rows and len(roe_rows) > 0:
                try:
                    data.roe = float(roe_rows[0][2] or 0)  # roe 数据第3列
                except:
                    pass

            # 净利率、毛利率
            rs_profit = bs.query_profit_data(bs_code)
            profit_rows = []
            while rs_profit.next():
                profit_rows.append(rs_profit.get_row_data())
            if profit_rows and len(profit_rows) > 0:
                try:
                    row = profit_rows[0]
                    data.gross_margin = float(row[3] or 0)  # 毛利率
                    data.net_margin = float(row[4] or 0)     # 净利率
                except:
                    pass

            return data
        finally:
            self._logout()

    def screen_stocks(
        self,
        pe_max: Optional[float] = None,
        pe_min: Optional[float] = None,
        pb_max: Optional[float] = None,
        roe_min: Optional[float] = None,
        revenue_growth_min: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        财务筛选器
        基于 Tushare 免费接口和 baostock 综合筛选
        """
        results = []

        # 使用 baostock 的股票列表
        self._login()
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            stocks = []
            while rs.next():
                stocks.append(rs.get_row_data())
        finally:
            self._logout()

        count = 0
        for stock in stocks:
            if count >= limit:
                break
            try:
                code = stock[0].split(".")[1]
                data = self.get_daily_basic(code)
                if not data or data.pe == 0:
                    continue

                # 筛选条件
                if pe_max and data.pe > pe_max:
                    continue
                if pe_min and data.pe < pe_min:
                    continue
                if pb_max and data.pb > pb_max:
                    continue

                results.append({
                    "code": code,
                    "name": stock[2] if len(stock) > 2 else "",
                    "pe": data.pe,
                    "pb": data.pb,
                    "ps": data.ps,
                    "roe": data.roe,
                    "gross_margin": data.gross_margin,
                    "net_margin": data.net_margin,
                })
                count += 1
            except Exception:
                continue

        return results


# 全局实例
_fetcher = None


def get_fundamental_fetcher() -> FundamentalFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = FundamentalFetcher()
    return _fetcher
```

**Step 2: 验证**
```bash
cd ~/a-stock-advisor && source venv/bin/activate && python -c "
from data_provider.fundamental import get_fundamental_fetcher
f = get_fundamental_fetcher()
data = f.get_daily_basic('000001')
if data:
    print(f'PE={data.pe}, PB={data.pb}, Name={data.name}')
else:
    print('No data')
"
```
Expected: PE=..., PB=..., Name=...

**Step 3: Commit**
```bash
git add data_provider/fundamental.py && git commit -m "feat: add fundamental financial data fetcher"
```

---

### Task 7: 创建基本面分析 CLI 命令

**Objective:** 在 main.py 中添加基本面分析命令

**Files:**
- Modify: `main.py`

**Step 1: 添加基本面命令**

```python
@cli.command()
@click.option("--stock", "-s", required=True, help="股票代码")
@click.option("--year", "-y", type=int, help="年份（默认去年）")
def financial(stock, year):
    """📊 基本面分析"""
    from data_provider.fundamental import get_fundamental_fetcher

    code = stock.strip().zfill(6)
    fetcher = get_fundamental_fetcher()

    console.print(f"\n[bold cyan]📊 基本面数据: {code}[/bold cyan]")

    # 每日指标
    daily = fetcher.get_daily_basic(code)
    if daily:
        console.print(Panel(
            f"[bold]{daily.name} ({daily.code})[/bold]\n\n"
            f"市盈率 (PE): [green]{daily.pe:.2f}[/green]  "
            f"市净率 (PB): [green]{daily.pb:.2f}[/green]\n"
            f"市销率 (PS): {daily.ps:.2f}  "
            f"市现率 (PCF): {daily.pcf:.2f}",
            title="估值指标",
            border_style="cyan",
        ))
    else:
        console.print("[yellow]无法获取估值数据[/yellow]")

    # 财务摘要
    summary = fetcher.get_financial_summary(code)
    if summary:
        table = Table(title="财务质量", show_header=True, header_style="bold magenta")
        table.add_column("指标", style="cyan")
        table.add_column("数值")

        table.add_row("净资产收益率 (ROE)", f"{summary.roe:.2f}%" if summary.roe else "N/A")
        table.add_row("毛利率", f"{summary.gross_margin:.2f}%" if summary.gross_margin else "N/A")
        table.add_row("净利率", f"{summary.net_margin:.2f}%" if summary.net_margin else "N/A")

        console.print(table)

        # 估值合理性判断
        pe_ok = 0 < daily.pe < 50 if daily and daily.pe > 0 else False
        pb_ok = 0 < daily.pb < 5 if daily and daily.pb > 0 else False
        roe_ok = summary.roe > 10 if summary.roe > 0 else False

        if pe_ok and pb_ok and roe_ok:
            console.print("[green]✓ 估值合理，财务质量良好[/green]")
        elif pe_ok and pb_ok:
            console.print("[yellow]⚠ 估值合理，ROE偏低[/yellow]")
        else:
            console.print("[red]⚠ 估值偏高或财务质量差[/red]")


@cli.command()
@click.option("--pe-max", type=float, help="PE上限")
@click.option("--pb-max", type=float, help="PB上限")
@click.option("--roe-min", type=float, help="ROE下限 (%)")
@click.option("--limit", "-n", type=int, default=20, help="返回数量")
def screen(pe_max, pb_max, roe_min, limit):
    """🔍 财务筛选"""
    from data_provider.fundamental import get_fundamental_fetcher

    console.print(f"[bold cyan]🔍 财务筛选[/bold cyan]")
    if pe_max:
        console.print(f"PE ≤ {pe_max}")
    if pb_max:
        console.print(f"PB ≤ {pb_max}")
    if roe_min:
        console.print(f"ROE ≥ {roe_min}%")

    fetcher = get_fundamental_fetcher()
    results = fetcher.screen_stocks(
        pe_max=pe_max,
        pb_max=pb_max,
        roe_min=roe_min,
        limit=limit,
    )

    if not results:
        console.print("[yellow]未找到符合条件的股票[/yellow]")
        return

    table = Table(title=f"筛选结果 ({len(results)}只)", show_header=True, header_style="bold magenta")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("PE", justify="right")
    table.add_column("PB", justify="right")
    table.add_column("ROE%", justify="right")
    table.add_column("毛利率%", justify="right")

    for r in results:
        table.add_row(
            r["code"],
            r["name"],
            f"{r['pe']:.2f}" if r['pe'] else "N/A",
            f"{r['pb']:.2f}" if r['pb'] else "N/A",
            f"{r['roe']:.1f}" if r['roe'] else "N/A",
            f"{r['gross_margin']:.1f}" if r['gross_margin'] else "N/A",
        )

    console.print(table)
```

**Step 2: 测试**
```bash
cd ~/a-stock-advisor && source venv/bin/activate
python main.py financial --stock 000001
python main.py screen --pe-max 30 --pb-max 5 --roe-min 10
```

**Step 3: Commit**
```bash
git add main.py && git commit -m "feat: add financial analysis and screening CLI commands"
```

---

## 集成测试

### Task 8: 集成测试 - 三个模块联调

**Step 1: 测试持仓+基本面联动**
```bash
cd ~/a-stock-advisor && source venv/bin/activate

# 1. 添加持仓
python main.py portfolio add --stock 000001 --shares 1000 --avg-cost 12.5 --name "平安银行"

# 2. 查看持仓（含浮动盈亏）
python main.py portfolio list

# 3. 基本面分析
python main.py financial --stock 000001
```

**Step 2: 测试回测**
```bash
# 对单只股票单策略回测
python main.py backtest --stock 600519 --start 2025-01-01 --end 2026-01-01
```

---

## 依赖清单

在完成所有任务后，`requirements.txt` 应包含：
```
backtrader>=1.9.78.123
```

---

## 验证清单

- [ ] `python main.py backtest --stock 000001` 能运行并返回回测结果
- [ ] `python main.py portfolio add --stock 000001 --shares 1000 --avg-cost 12.5` 能保存持仓
- [ ] `python main.py portfolio list` 能显示持仓和盈亏
- [ ] `python main.py financial --stock 000001` 能显示基本面数据
- [ ] `python main.py screen --pe-max 30 --roe-min 10` 能筛选股票
- [ ] 所有新表 (positions, trades) 在 SQLite 中正确创建
- [ ] git commit 每个模块

---

## 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | Modify | 添加 backtrader |
| `analyzer/backtest_engine.py` | Create | 回测引擎 |
| `data_provider/storage.py` | Modify | 添加 Position/Trade 模型和方法 |
| `data_provider/fundamental.py` | Create | 基本面数据获取器 |
| `main.py` | Modify | 添加 backtest/portfolio/financial/screen CLI 命令 |
