#!/usr/bin/env python3
"""
模拟交易模块
Paper Trading - 模拟实盘交易信号，记录但不实际执行
用于验证策略的实际表现
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class PaperTrade:
    """模拟交易记录"""
    id: int = 0
    code: str = ""
    name: str = ""
    action: str = ""        # BUY / SELL
    price: float = 0.0
    shares: int = 0
    strategy: str = ""
    signal_strength: float = 0.0
    reason: str = ""
    timestamp: str = ""
    # 跟踪
    current_price: float = 0.0
    pnl: float = 0.0        # 浮动盈亏
    pnl_pct: float = 0.0    # 盈亏%
    status: str = "OPEN"     # OPEN / CLOSED


class PaperTradingEngine:
    """模拟交易引擎"""

    def __init__(self, data_file: str = "data/paper_trades.json"):
        self.data_file = data_file
        self.trades: List[PaperTrade] = []
        self._load()

    def _load(self):
        """加载模拟交易"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.trades = []
                for d in data:
                    self.trades.append(PaperTrade(**d))
            except:
                self.trades = []

    def _save(self):
        """保存模拟交易"""
        os.makedirs(os.path.dirname(self.data_file) or ".", exist_ok=True)
        data = []
        for t in self.trades:
            data.append({
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "action": t.action,
                "price": t.price,
                "shares": t.shares,
                "strategy": t.strategy,
                "signal_strength": t.signal_strength,
                "reason": t.reason,
                "timestamp": t.timestamp,
                "current_price": t.current_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "status": t.status,
            })
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def buy(self, code: str, name: str, price: float, shares: int = 100,
            strategy: str = "", strength: float = 0.0, reason: str = "") -> PaperTrade:
        """模拟买入"""
        trade = PaperTrade(
            id=len(self.trades) + 1,
            code=code,
            name=name,
            action="BUY",
            price=price,
            shares=shares,
            strategy=strategy,
            signal_strength=strength,
            reason=reason,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            current_price=price,
            status="OPEN",
        )
        self.trades.append(trade)
        self._save()
        return trade

    def sell(self, code: str, price: float) -> Optional[PaperTrade]:
        """模拟卖出"""
        # 找到最近的未平仓买入
        for trade in reversed(self.trades):
            if trade.code == code and trade.action == "BUY" and trade.status == "OPEN":
                trade.status = "CLOSED"
                trade.current_price = price
                trade.pnl = (price - trade.price) * trade.shares
                trade.pnl_pct = (price - trade.price) / trade.price * 100
                self._save()

                # 记录卖出
                sell_trade = PaperTrade(
                    id=len(self.trades) + 1,
                    code=code,
                    name=trade.name,
                    action="SELL",
                    price=price,
                    shares=trade.shares,
                    strategy=trade.strategy,
                    reason="平仓",
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_price=price,
                    pnl=trade.pnl,
                    pnl_pct=trade.pnl_pct,
                    status="CLOSED",
                )
                self.trades.append(sell_trade)
                self._save()
                return sell_trade
        return None

    def update_prices(self):
        """更新所有持仓的当前价格"""
        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        for trade in self.trades:
            if trade.status == "OPEN" and trade.action == "BUY":
                try:
                    quote = manager.get_quote(trade.code)
                    if quote:
                        trade.current_price = quote.price
                        trade.pnl = (quote.price - trade.price) * trade.shares
                        trade.pnl_pct = (quote.price - trade.price) / trade.price * 100
                except:
                    pass
        self._save()

    def get_open_positions(self) -> List[PaperTrade]:
        """获取未平仓"""
        return [t for t in self.trades if t.status == "OPEN" and t.action == "BUY"]

    def get_summary(self) -> Dict[str, Any]:
        """获取模拟交易统计"""
        open_trades = [t for t in self.trades if t.status == "OPEN" and t.action == "BUY"]
        closed_trades = [t for t in self.trades if t.status == "CLOSED" and t.action == "SELL"]

        total_pnl = sum(t.pnl for t in closed_trades)
        win_count = sum(1 for t in closed_trades if t.pnl > 0)
        total_closed = len(closed_trades)
        win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0

        return {
            "total_trades": len(self.trades),
            "open_positions": len(open_trades),
            "closed_trades": total_closed,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "win_count": win_count,
        }


_paper_engine = None


def get_paper_engine() -> PaperTradingEngine:
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = PaperTradingEngine()
    return _paper_engine
