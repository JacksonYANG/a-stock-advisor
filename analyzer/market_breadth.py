#!/usr/bin/env python3
"""
市场宽度指标
ADL (Advance/Decline Line)
上涨/下跌家数比
涨停/跌停家数
"""

import baostock as bs
import pandas as pd
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BreadthData:
    """市场宽度数据"""
    date: str = ""
    advance_count: int = 0       # 上涨家数
    decline_count: int = 0       # 下跌家数
    flat_count: int = 0          # 平盘
    up_limit: int = 0            # 涨停
    down_limit: int = 0          # 跌停
    ad_ratio: float = 0.0        # 涨跌比
    adl: float = 0.0             # 腾落指数
    breadth_pct: float = 0.0     # 市场宽度% (上涨/(上涨+下跌))


class MarketBreadth:
    """市场宽度分析器"""

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

    def get_breadth(self, date: str = "") -> BreadthData:
        """获取市场宽度"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        self._login()
        all_stocks = []
        try:
            rs = bs.query_all_stock(day=date)
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        advance = 0
        decline = 0
        flat = 0
        up_limit = 0
        down_limit = 0

        for stock in all_stocks[:500]:  # 限制数量避免太慢
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]

                # 跳过指数和基金
                if code.startswith(("5", "1", "2")):
                    continue

                quote = manager.get_quote(code)
                if quote:
                    if quote.change_pct >= 9.5:
                        up_limit += 1
                        advance += 1
                    elif quote.change_pct > 0:
                        advance += 1
                    elif quote.change_pct <= -9.5:
                        down_limit += 1
                        decline += 1
                    elif quote.change_pct < 0:
                        decline += 1
                    else:
                        flat += 1
            except:
                continue

        total = advance + decline
        ad_ratio = advance / max(decline, 1)
        breadth_pct = (advance / total * 100) if total > 0 else 0

        return BreadthData(
            date=date,
            advance_count=advance,
            decline_count=decline,
            flat_count=flat,
            up_limit=up_limit,
            down_limit=down_limit,
            ad_ratio=ad_ratio,
            breadth_pct=breadth_pct,
        )


_breadth = None


def get_market_breadth() -> MarketBreadth:
    global _breadth
    if _breadth is None:
        _breadth = MarketBreadth()
    return _breadth
