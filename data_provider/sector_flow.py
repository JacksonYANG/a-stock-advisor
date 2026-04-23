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

from data_provider.industry import get_stock_industry


@dataclass
class SectorFlowData:
    """板块资金流向"""
    industry: str = ""
    stock_count: int = 0
    total_market_cap: float = 0.0     # 总市值(亿)
    total_flow: float = 0.0            # 资金净流入(亿)
    inflow_pct: float = 0.0            # 净流入占市值比
    avg_change: float = 0.0            # 平均涨跌幅


class SectorFlowFetcher:
    """板块资金流向获取器"""

    def get_all_sector_flows(self) -> List[SectorFlowData]:
        """获取所有板块资金流向"""
        self._login()

        all_stocks = []
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        industry_data: Dict[str, Dict] = {}

        for stock in all_stocks:
            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]
                industry = get_stock_industry(code)

                if not industry:
                    continue

                if industry not in industry_data:
                    industry_data[industry] = {
                        "stocks": [],
                        "total_flow": 0.0,
                        "total_cap": 0.0,
                        "changes": [],
                    }

                try:
                    quote = manager.get_quote(code)
                    if quote:
                        amount = getattr(quote, "amount", 0) or 0
                        change_pct = getattr(quote, "change_pct", 0) or 0
                        market_cap = getattr(quote, "market_cap", 0) or 0

                        # 净流入估算
                        flow = amount * 1e4 * change_pct / 100

                        industry_data[industry]["total_flow"] += flow
                        industry_data[industry]["total_cap"] += market_cap
                        industry_data[industry]["changes"].append(change_pct)
                        industry_data[industry]["stocks"].append(code)
                except:
                    continue
            except:
                continue

        results = []
        for industry, data in industry_data.items():
            if not data["stocks"]:
                continue

            avg_change = sum(data["changes"]) / len(data["changes"]) if data["changes"] else 0
            total_cap_b = data["total_cap"] / 1e8  # 转为亿
            inflow_pct = (data["total_flow"] / 1e8 / total_cap_b * 100) if total_cap_b > 0 else 0

            results.append(SectorFlowData(
                industry=industry,
                stock_count=len(data["stocks"]),
                total_market_cap=total_cap_b,
                total_flow=data["total_flow"] / 1e8,
                inflow_pct=inflow_pct,
                avg_change=avg_change,
            ))

        results.sort(key=lambda x: x.total_flow, reverse=True)
        return results


_sector_flow_fetcher = None


def get_sector_flow_fetcher() -> SectorFlowFetcher:
    global _sector_flow_fetcher
    if _sector_flow_fetcher is None:
        _sector_flow_fetcher = SectorFlowFetcher()
    return _sector_flow_fetcher