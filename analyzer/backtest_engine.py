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
    """回测策略基类 - 包含常用指标"""

    params = (
        ("entry_checks", []),   # list of callables for entry
        ("exit_checks", []),    # list of callables for exit
    )

    def __init__(self):
        self.order = None
        self.entry_price = None
        self.entry_date = None
        self.trades = []  # 交易记录

        # ── 常用指标 ──
        # Moving averages
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma60 = bt.indicators.SMA(self.data.close, period=60)

        # RSI
        self.rsi6 = bt.indicators.RSI(self.data.close, period=6)
        self.rsi14 = bt.indicators.RSI(self.data.close, period=14)

        # MACD (standard 12/26/9)
        self.macd = bt.indicators.MACD(self.data.close)

        # Bollinger Bands (20, 2)
        self.boll = bt.indicators.BollingerBands(self.data.close, period=20)

        # Volume moving average
        self.vol_ma5 = bt.indicators.SMA(self.data.volume, period=5)
        self.vol_ma20 = bt.indicators.SMA(self.data.volume, period=20)

        # Crossover signals (pre-computed for easy use)
        self.ma5_cross_ma10 = bt.indicators.CrossOver(self.ma5, self.ma10)
        self.ma10_cross_ma20 = bt.indicators.CrossOver(self.ma10, self.ma20)
        self.macd_cross_signal = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

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
        # Default: use param-based checks
        if self.entry_price is None and not self.position:
            if self._check_entry():
                self.buy()
        else:
            if self._check_exit():
                self.sell()

    def _check_entry(self):
        """Run all entry condition checkers; ANY match triggers entry."""
        for fn in self.p.entry_checks:
            try:
                if fn(self):
                    return True
            except Exception:
                pass
        return False

    def _check_exit(self):
        """Run all exit condition checkers; ANY match triggers exit."""
        for fn in self.p.exit_checks:
            try:
                if fn(self):
                    return True
            except Exception:
                pass
        return False


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

        # Ensure 'date' is the datetime index for PandasData
        if "date" in df.columns:
            df = df.set_index("date")
        elif "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"}).set_index("date")

        # Use column names instead of integer positions for robustness
        data = bt.feeds.PandasData(
            dataname=df,
            datetime=None,     # use index
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
        )

        cerebro.adddata(data)

        result = self._create_strategy(strategy_name, strategy_yaml)
        if result is None:
            return None

        strategy_cls, entry_fns, exit_fns = result
        cerebro.addstrategy(
            strategy_cls,
            entry_checks=entry_fns,
            exit_checks=exit_fns,
        )

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

    def run(self, stock_code, strategy_name, strategy_yaml, start_date, end_date, **kwargs):
        """Alias for run_backtest() — convenience wrapper."""
        return self.run_backtest(
            stock_code=stock_code,
            strategy_name=strategy_name,
            strategy_yaml=strategy_yaml,
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )

    # ── 关键词 → 条件检查函数映射 ──
    # 每个函数接受 strategy 实例 (s)，返回 bool
    _COND_ENTRY = {
        # MA 金叉（短线上穿）
        "金叉": lambda s: s.ma5_cross_ma10[0] > 0,
        "上穿": lambda s: s.ma5_cross_ma10[0] > 0,
        "MACD金叉": lambda s: s.macd_cross_signal[0] > 0,
        "MACD金": lambda s: s.macd_cross_signal[0] > 0,
        "RSI超卖": lambda s: s.rsi6[0] < 30,
        "RSI<": lambda s: s.rsi6[0] < 30,
        "放量": lambda s: s.data.volume[0] > s.vol_ma5[0] * 1.5,
        "量比": lambda s: s.data.volume[0] > s.vol_ma5[0] * 1.2,
        "涨停": lambda s: (s.data.close[0] - s.data.close[-1]) / s.data.close[-1] > 0.09,
        "突破": lambda s: s.data.close[0] > bt.indicators.Highest(s.data.high, period=20)[0],
        "趋势向上": lambda s: s.data.close[0] > s.ma20[0] and s.ma5[0] > s.ma10[0],
        "多头": lambda s: s.ma5[0] > s.ma10[0] > s.ma20[0],
        "站上MA": lambda s: s.data.close[0] > s.ma5[0],
        "布林下轨": lambda s: s.data.close[0] <= s.boll.lines.bot[0],
        "缩量回调": lambda s: s.data.volume[0] < s.vol_ma5[0] * 0.7 and s.data.close[0] < s.data.close[-1],
        "回调MA": lambda s: abs(s.data.close[0] - s.ma10[0]) / s.ma10[0] < 0.02,
        "回调MA20": lambda s: abs(s.data.close[0] - s.ma20[0]) / s.ma20[0] < 0.02,
        "阳线": lambda s: s.data.close[0] > s.data.open[0],
        "企稳": lambda s: s.data.close[0] > s.data.open[0] and s.data.close[0] > s.ma5[0],
        "底背离": lambda s: s.rsi6[0] < 35,
    }

    _COND_EXIT = {
        # MA 死叉（短线下穿）
        "死叉": lambda s: s.ma5_cross_ma10[0] < 0,
        "下穿": lambda s: s.ma5_cross_ma10[0] < 0,
        "MACD死叉": lambda s: s.macd_cross_signal[0] < 0,
        "MACD死": lambda s: s.macd_cross_signal[0] < 0,
        "RSI超买": lambda s: s.rsi6[0] > 70,
        "RSI>": lambda s: s.rsi6[0] > 70,
        "缩量": lambda s: s.data.volume[0] < s.vol_ma5[0] * 0.5,
        "跌破": lambda s: s.data.close[0] < s.ma20[0],
        "跌破MA": lambda s: s.data.close[0] < s.ma5[0],
        "趋势向下": lambda s: s.data.close[0] < s.ma20[0],
        "空头": lambda s: s.ma5[0] < s.ma10[0] < s.ma20[0],
        "布林上轨": lambda s: s.data.close[0] >= s.boll.lines.top[0],
        "放量滞涨": lambda s: s.data.volume[0] > s.vol_ma5[0] * 1.5
                             and (s.data.close[0] - s.data.close[-1]) / s.data.close[-1] < 0.01,
        "长上影": lambda s: s.data.high[0] - max(s.data.open[0], s.data.close[0])
                            > abs(s.data.close[0] - s.data.open[0]),
        "大阴线": lambda s: (s.data.close[0] - s.data.open[0]) / s.data.open[0] < -0.03,
        "跌停": lambda s: (s.data.close[0] - s.data.close[-1]) / s.data.close[-1] < -0.09,
    }

    @staticmethod
    def _match_conditions(condition_list, cond_map):
        """从 YAML 条件列表中匹配出可识别的检查函数。

        condition_list 可能是:
          - list[str]  →  ["MA5 上穿 MA10", "放量"]
          - dict       →  {sub_key: [str, ...], ...}  (嵌套子条件)
          - str        →  单条条件
        返回匹配到的函数列表。
        """
        matched = []

        def _flatten(items):
            """递归展平嵌套条件"""
            if isinstance(items, str):
                yield items
            elif isinstance(items, list):
                for item in items:
                    yield from _flatten(item)
            elif isinstance(items, dict):
                for val in items.values():
                    yield from _flatten(val)

        for cond_str in _flatten(condition_list):
            if not isinstance(cond_str, str) or not cond_str.strip():
                continue
            cond_str = cond_str.strip()
            # 尝试按关键词匹配（优先匹配更长的关键词）
            for keyword in sorted(cond_map.keys(), key=len, reverse=True):
                if keyword in cond_str:
                    matched.append(cond_map[keyword])
                    break  # 一条条件只匹配一个关键词

        return matched

    def _create_strategy(self, name: str, yaml_config: dict):
        """从YAML配置创建backtrader策略类（直接返回 BacktestStrategy 即可）"""
        raw_entry = yaml_config.get("entry_conditions", [])
        raw_exit = yaml_config.get("exit_conditions", [])

        entry_fns = self._match_conditions(raw_entry, self._COND_ENTRY)
        exit_fns = self._match_conditions(raw_exit, self._COND_EXIT)

        # 默认保底：如果完全没有匹配到入场条件，使用简单的MA金叉
        if not entry_fns:
            entry_fns = [lambda s: s.ma5_cross_ma10[0] > 0]
        if not exit_fns:
            exit_fns = [lambda s: s.ma5_cross_ma10[0] < 0]

        # 直接把函数列表塞进 params——无需 exec / 动态类
        return BacktestStrategy, entry_fns, exit_fns

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

    def plot_backtest_result(self, results: Dict[str, BacktestResult], save_path: Optional[str] = None):
        """
        绘制回测结果图表
        - 年化收益柱状图
        - 关键指标对比
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # 中文字体设置
        try:
            plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
        except:
            pass

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        names = list(results.keys())
        annualized = [r.annualized_return for r in results.values()]
        colors = ["#2ecc71" if x >= 0 else "#e74c3c" for x in annualized]

        # 子图1: 年化收益对比
        axes[0].barh(names, annualized, color=colors, alpha=0.8)
        axes[0].set_xlabel("Annualized Return (%)", fontsize=11)
        axes[0].set_title("Strategy Annualized Returns", fontsize=13, fontweight="bold")
        axes[0].axvline(x=0, color="black", linewidth=0.5)
        for i, v in enumerate(annualized):
            axes[0].text(v + 0.5, i, f"{v:.1f}%", va="center", fontsize=9)

        # 子图2: 关键指标对比
        metrics_data = {}
        for name in names:
            r = results[name]
            metrics_data[name] = {
                "win_rate": r.win_rate,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio * 10,  # 缩放以便可视化
            }

        x = range(len(names))
        width = 0.25
        metric_names = ["win_rate", "max_drawdown", "sharpe_ratio"]
        metric_labels = ["Win Rate (%)", "Max Drawdown (%)", "Sharpe×10"]
        bar_colors = ["#3498db", "#e74c3c", "#f39c12"]

        for i, (m, l, c) in enumerate(zip(metric_names, metric_labels, bar_colors)):
            values = [metrics_data[n][m] for n in names]
            axes[1].bar([xi + width * i for xi in x], values, width, label=l, color=c, alpha=0.8)

        axes[1].set_xticks([xi + width for xi in x])
        axes[1].set_xticklabels(names, rotation=35, ha="right", fontsize=9)
        axes[1].legend(fontsize=9)
        axes[1].set_title("Key Metrics Comparison", fontsize=13, fontweight="bold")

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
        else:
            plt.savefig("reports/backtest_result.png", dpi=150, bbox_inches="tight")

        plt.close()
        return save_path or "reports/backtest_result.png"


_backtest_engine = None


def get_backtest_engine(initial_cash: float = 100000.0) -> BacktestEngine:
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine(initial_cash)
    return _backtest_engine
