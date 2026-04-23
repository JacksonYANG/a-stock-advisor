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
    """回测策略基类"""

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
        """对单只股票运行单个策略回测"""
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(commission=0.001)

        # 加载数据
        from data_provider.base import DataFetcherManager
        from config import Config

        config = Config.get()
        manager = DataFetcherManager()
        manager.register_sources(config.DATA_SOURCES)

        stock_code_norm = stock_code.strip().zfill(6)
        df = manager.get_history(stock_code_norm, interval)

        if df is None or df.empty:
            console.print(f"[yellow]无法获取 {stock_code} 数据[/yellow]")
            return None

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

        if len(df) < 20:
            console.print(f"[yellow]{stock_code} 数据不足[/yellow]")
            return None

        df = df.reset_index(drop=True)

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

        strategy = self._create_strategy(strategy_name, strategy_yaml)
        if strategy is None:
            return None

        cerebro.addstrategy(strategy)

        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        results = cerebro.run()

        if not results:
            return None

        strat = results[0]

        try:
            drawdown = strat.analyzers.drawdown.get_analysis()
            sharpe = strat.analyzers.sharpe.get_analysis()
            returns = strat.analyzers.returns.get_analysis()
            trades = strat.analyzers.trades.get_analysis()

            total_return = returns.get("rtot", 0) * 100
            max_dd = drawdown.get("max", {}).get("drawdown", 0)
            sharpe_ratio = sharpe.get("sharperatio", 0) or 0.0

            total_trades = trades.get("total", {}).get("total", 0)
            winning = trades.get("won", {}).get("total", 0)
            losing = trades.get("lost", {}).get("total", 0)

            win_rate = winning / total_trades * 100 if total_trades > 0 else 0

            avg_win = trades.get("won", {}).get("pnl", {}).get("avg", 0)
            avg_loss = abs(trades.get("lost", {}).get("pnl", {}).get("avg", 0))
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

            all_trades = getattr(strat, "trades", [])
            if all_trades:
                total_days = sum(int(t["holding_days"]) for t in all_trades)
                avg_days = total_days / len(all_trades) if all_trades else 0
            else:
                avg_days = 0

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            years = (end_dt - start_dt).days / 365.0
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

        strategy_code = f"""
class _BacktestStrategy_{name.replace(' ', '_').replace('-', '_')}(BacktestStrategy):
    def __init__(self):
        super().__init__()
        self.entry_conditions = {entry_conditions}
        self.exit_conditions = {exit_conditions}

    def next(self):
        if self.entry_price is None:
            if self._check_entry_conditions():
                self.buy()
        else:
            if self._check_exit_conditions():
                self.sell()

    def _check_entry_conditions(self):
        return False

    def _check_exit_conditions(self):
        return False
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
        table = Table(title="回测结果汇总", show_header=True, header_style="bold magenta")
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


_backtest_engine = None


def get_backtest_engine(initial_cash: float = 100000.0) -> BacktestEngine:
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine(initial_cash)
    return _backtest_engine
