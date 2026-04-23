#!/usr/bin/env python3
"""
龙虎榜数据追踪模块
通过 Tushare 获取龙虎榜数据，跟踪游资和机构席位动向
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
    turnover_rate: float = 0.0
    amount: float = 0.0
    reason: str = ""
    buy_seats: List[Dict] = None
    sell_seats: List[Dict] = None
    net_amount: float = 0.0
    institutional_net: float = 0.0

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
                    code=str(row.get("ts_code", "")).replace(".SH", "").replace(".SZ", ""),
                    name=str(row.get("name", "")),
                    close_price=float(row.get("close", 0)),
                    change_pct=float(row.get("pct_change", 0)),
                    turnover_rate=float(row.get("turnover_rate", 0)),
                    amount=float(row.get("amount", 0)) / 1e4,
                    reason=str(row.get("reason", "")),
                )
                record.net_amount = record.amount * (record.change_pct / 100)
                results.append(record)
            return results
        except Exception:
            return []

    def get_history(self, days: int = 5) -> Dict[str, List[DragonTigerRecord]]:
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
        all_records = []
        today = datetime.now()
        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            records = self.get_top_list(date_str)
            all_records.extend(records)

        seat_stats: Dict[str, Dict] = {}
        for record in all_records:
            for seat in record.buy_seats:
                name = seat["name"]
                if name not in seat_stats:
                    seat_stats[name] = {"name": name, "appear_count": 0, "total_buy": 0.0, "total_sell": 0.0}
                seat_stats[name]["appear_count"] += 1
                seat_stats[name]["total_buy"] += seat.get("amount", 0)

            for seat in record.sell_seats:
                name = seat["name"]
                if name not in seat_stats:
                    seat_stats[name] = {"name": name, "appear_count": 0, "total_buy": 0.0, "total_sell": 0.0}
                seat_stats[name]["appear_count"] += 1
                seat_stats[name]["total_sell"] += seat.get("amount", 0)

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