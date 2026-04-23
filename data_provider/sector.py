#!/usr/bin/env python3
"""
板块/行业数据获取模块
基于 baostock + 获取板块涨跌/资金流/联动效应
"""

import baostock as bs
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

from data_provider.industry import get_stock_industry


@dataclass
class SectorData:
    """板块数据结构"""
    industry: str = ""
    stock_count: int = 0
    avg_change: float = 0.0
    up_count: int = 0
    down_count: int = 0
    limit_up_count: int = 0
    lead_stock: str = ""
    lead_change: float = 0.0


class SectorFetcher:
    """板块数据获取器"""

    def get_all_sectors(self) -> List[Dict[str, Any]]:
        """获取所有行业板块数据"""
        self._login()
        all_stocks = []
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        # 按行业分组
        industry_stocks: Dict[str, List] = {}
        for stock in all_stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                industry = get_stock_industry(code)
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
        from data_provider.base import DataFetcherManager

        for industry, stock_list in industry_stocks.items():
            if not stock_list:
                continue

            try:
                changes = []
                lead_stock = ""
                lead_change = -999.0
                limit_up = 0

                for s in stock_list[:20]:
                    try:
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

        results.sort(key=lambda x: x["avg_change"], reverse=True)
        return results

    def get_sector_stocks(self, industry: str) -> List[Dict[str, Any]]:
        """获取某行业所有成分股"""
        self._login()
        all_stocks = []
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        results = []
        for stock in all_stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                ind = get_stock_industry(code)
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
