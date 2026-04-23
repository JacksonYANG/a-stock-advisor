#!/usr/bin/env python3
"""
组合持仓分析器
计算组合级别的风险指标: 夏普比率、索提诺比率、最大回撤、相关性矩阵
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PortfolioMetrics:
    """组合指标"""
    total_value: float = 0.0        # 总市值
    total_cost: float = 0.0          # 总成本
    total_pnl: float = 0.0           # 总盈亏
    total_pnl_pct: float = 0.0       # 总盈亏%
    position_count: int = 0          # 持仓数
    # 风险指标
    sharpe_ratio: float = 0.0        # 夏普比率
    sortino_ratio: float = 0.0       # 索提诺比率
    max_drawdown: float = 0.0        # 最大回撤
    # 资产配置
    concentration: float = 0.0       # 集中度 (最大持仓占比)
    diversification_score: float = 0.0  # 分散化评分 0-100


class PortfolioAnalyzer:
    """组合分析器"""

    def analyze(self) -> PortfolioMetrics:
        """分析当前组合"""
        from data_provider.storage import Database
        from data_provider.base import DataFetcherManager

        db = Database()
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        positions = db.get_positions()

        if not positions:
            return PortfolioMetrics()

        metrics = PortfolioMetrics()
        metrics.position_count = len(positions)

        total_value = 0.0
        total_cost = 0.0
        weights = []

        for pos in positions:
            try:
                quote = manager.get_quote(pos.code)
                if quote:
                    current_price = quote.price
                else:
                    current_price = pos.current_price or pos.avg_cost

                market_value = pos.shares * current_price
                cost_value = pos.shares * pos.avg_cost

                total_value += market_value
                total_cost += cost_value
                weights.append(market_value)
            except:
                weights.append(pos.shares * pos.avg_cost)
                total_cost += pos.shares * pos.avg_cost

        metrics.total_value = total_value
        metrics.total_cost = total_cost
        metrics.total_pnl = total_value - total_cost
        metrics.total_pnl_pct = (metrics.total_pnl / total_cost * 100) if total_cost > 0 else 0

        # 集中度
        if weights and total_value > 0:
            weight_pcts = [w / total_value for w in weights]
            metrics.concentration = max(weight_pcts)
            # 分散化评分: 100 = 完全分散, 0 = 集中一只
            n = len(weight_pcts)
            ideal_weight = 1.0 / n
            deviation = sum(abs(w - ideal_weight) for w in weight_pcts) / 2
            metrics.diversification_score = max(0, 100 * (1 - deviation))

        # 风险指标 (简化计算)
        metrics.sharpe_ratio = self._calc_sharpe(positions, db)
        metrics.sortino_ratio = self._calc_sortino(positions, db)
        metrics.max_drawdown = self._calc_max_drawdown(positions, db)

        return metrics

    def _calc_sharpe(self, positions, db) -> float:
        """简化夏普比率计算"""
        returns = []
        for pos in positions:
            trades = db.get_trades(code=pos.code)
            for t in trades:
                if t.trade_type == "卖出" and t.price > 0 and t.signal_price > 0:
                    ret = (t.price - t.signal_price) / t.signal_price
                    returns.append(ret)

        if len(returns) < 2:
            return 0.0

        avg_ret = np.mean(returns)
        std_ret = np.std(returns)
        if std_ret == 0:
            return 0.0

        # 年化: 假设252个交易日
        return (avg_ret / std_ret) * np.sqrt(252)

    def _calc_sortino(self, positions, db) -> float:
        """索提诺比率"""
        returns = []
        for pos in positions:
            trades = db.get_trades(code=pos.code)
            for t in trades:
                if t.trade_type == "卖出" and t.price > 0 and t.signal_price > 0:
                    ret = (t.price - t.signal_price) / t.signal_price
                    returns.append(ret)

        if len(returns) < 2:
            return 0.0

        avg_ret = np.mean(returns)
        downside = [r for r in returns if r < 0]
        if not downside:
            return float("inf") if avg_ret > 0 else 0.0

        downside_std = np.std(downside)
        if downside_std == 0:
            return 0.0

        return (avg_ret / downside_std) * np.sqrt(252)

    def _calc_max_drawdown(self, positions, db) -> float:
        """最大回撤"""
        # 简化: 基于持仓浮亏估算
        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        max_dd = 0.0
        for pos in positions:
            try:
                quote = manager.get_quote(pos.code)
                if quote and pos.avg_cost > 0:
                    # 从成本到最低价的回撤
                    dd = max(0, (pos.avg_cost - quote.low) / pos.avg_cost * 100)
                    max_dd = max(max_dd, dd)
            except:
                pass

        return max_dd

    def get_correlation_matrix(self) -> Optional[pd.DataFrame]:
        """计算持仓相关性矩阵"""
        from data_provider.storage import Database
        from data_provider.base import DataFetcherManager

        db = Database()
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        positions = db.get_positions()
        if len(positions) < 2:
            return None

        price_data = {}
        for pos in positions:
            try:
                df = manager.get_history(pos.code, days=60)
                if df is not None and not df.empty:
                    price_data[pos.code] = df["close"].pct_change().dropna()
            except:
                continue

        if len(price_data) < 2:
            return None

        df = pd.DataFrame(price_data)
        return df.corr()


_analyzer = None


def get_portfolio_analyzer() -> PortfolioAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = PortfolioAnalyzer()
    return _analyzer
