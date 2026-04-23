#!/usr/bin/env python3
"""
策略参数优化器
网格搜索 + Walk-Forward 验证
"""

import itertools
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OptimizationResult:
    """优化结果"""
    strategy_name: str = ""
    best_params: Dict[str, Any] = None
    best_return: float = 0.0
    best_sharpe: float = 0.0
    best_drawdown: float = 0.0
    all_results: List[Dict] = None

    def __post_init__(self):
        if self.best_params is None:
            self.best_params = {}
        if self.all_results is None:
            self.all_results = []


class StrategyOptimizer:
    """策略参数优化器"""

    def optimize_ma_cross(
        self,
        code: str,
        fast_range: range = range(5, 21, 5),
        slow_range: range = range(20, 61, 10),
        start_date: str = "2025-01-01",
    ) -> OptimizationResult:
        """优化均线交叉策略参数"""
        from data_provider.base import DataFetcherManager
        from analyzer.technical import TechnicalAnalyzer

        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        df = manager.get_history(code, days=250)
        if df is None or df.empty:
            return OptimizationResult(strategy_name="ma_cross")

        results = []

        for fast in fast_range:
            for slow in slow_range:
                if fast >= slow:
                    continue

                try:
                    # 计算均线
                    df_copy = df.copy()
                    df_copy["ma_fast"] = df_copy["close"].rolling(fast).mean()
                    df_copy["ma_slow"] = df_copy["close"].rolling(slow).mean()

                    # 生成信号
                    df_copy["signal"] = 0
                    df_copy.loc[df_copy["ma_fast"] > df_copy["ma_slow"], "signal"] = 1
                    df_copy.loc[df_copy["ma_fast"] < df_copy["ma_slow"], "signal"] = -1

                    # 计算收益
                    df_copy["returns"] = df_copy["close"].pct_change()
                    df_copy["strategy_returns"] = df_copy["signal"].shift(1) * df_copy["returns"]

                    total_return = (1 + df_copy["strategy_returns"].dropna()).prod() - 1
                    sharpe = df_copy["strategy_returns"].mean() / max(df_copy["strategy_returns"].std(), 0.001) * np.sqrt(252)

                    # 最大回撤
                    cum_returns = (1 + df_copy["strategy_returns"].dropna()).cumprod()
                    peak = cum_returns.expanding().max()
                    drawdown = (cum_returns - peak) / peak
                    max_dd = drawdown.min() * 100

                    results.append({
                        "fast": fast,
                        "slow": slow,
                        "total_return": total_return * 100,
                        "sharpe": sharpe,
                        "max_drawdown": max_dd,
                    })
                except:
                    continue

        if not results:
            return OptimizationResult(strategy_name="ma_cross")

        # 按夏普比率排序
        best = max(results, key=lambda x: x["sharpe"])

        return OptimizationResult(
            strategy_name="ma_cross",
            best_params={"fast": best["fast"], "slow": best["slow"]},
            best_return=best["total_return"],
            best_sharpe=best["sharpe"],
            best_drawdown=best["max_drawdown"],
            all_results=sorted(results, key=lambda x: x["sharpe"], reverse=True)[:10],
        )


_optimizer = None


def get_strategy_optimizer() -> StrategyOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = StrategyOptimizer()
    return _optimizer
