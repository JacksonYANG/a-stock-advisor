#!/usr/bin/env python3
"""
北向资金追踪模块
通过 Tushare 沪深港通数据追踪外资动向
Tushare免费积分接口: hsgt_top10 (沪深港通TOP10)
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
class NorthMoneyData:
    """北向资金数据"""
    date: str = ""
    hgt_shanghai: float = 0.0   # 沪股通净买入
    sgt_shenzhen: float = 0.0   # 深股通净买入
    total: float = 0.0          # 合计净买入
    top_stocks: List[Dict] = None

    def __post_init__(self):
        if self.top_stocks is None:
            self.top_stocks = []


class NorthMoneyFetcher:
    """北向资金获取器"""

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

    def get_daily(self, date: Optional[str] = None) -> Optional[NorthMoneyData]:
        """获取每日北向资金流向"""
        pro = self._get_pro()
        if pro is None:
            return None

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            df_sh = pro.hsgt_top10(symbol="SH", start_date=date, end_date=date)
            df_sz = pro.hsgt_top10(symbol="SZ", start_date=date, end_date=date)

            hgt_buy = 0.0
            sgt_buy = 0.0
            top_stocks = []

            if df_sh is not None and not df_sh.empty:
                hgt_buy = float(df_sh["buy_amount"].sum() - df_sh["sell_amount"].sum()) / 1e8

            if df_sz is not None and not df_sz.empty:
                sgt_buy = float(df_sz["buy_amount"].sum() - df_sz["sell_amount"].sum()) / 1e8

            for df in [df_sh, df_sz]:
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        ts_code = str(row.get("ts_code", ""))
                        top_stocks.append({
                            "code": ts_code.replace(".SH", "").replace(".SZ", ""),
                            "name": row.get("name", ""),
                            "buy_amount": float(row.get("buy_amount", 0)) / 1e8,
                            "sell_amount": float(row.get("sell_amount", 0)) / 1e8,
                            "net_amount": float(row.get("net_amount", 0)) / 1e8,
                        })

            return NorthMoneyData(
                date=date,
                hgt_shanghai=hgt_buy,
                sgt_shenzhen=sgt_buy,
                total=hgt_buy + sgt_buy,
                top_stocks=top_stocks,
            )
        except Exception:
            return None

    def get_history(self, days: int = 5) -> List[NorthMoneyData]:
        """获取最近N天北向资金历史"""
        results = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            data = self.get_daily(date_str)
            if data:
                results.append(data)

        return results


_north_fetcher = None


def get_north_money_fetcher(token: str = "") -> NorthMoneyFetcher:
    global _north_fetcher
    if _north_fetcher is None:
        _north_fetcher = NorthMoneyFetcher(token)
    return _north_fetcher