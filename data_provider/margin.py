#!/usr/bin/env python3
"""
融资融券数据模块
通过 Tushare 获取个股的融资融券数据
融资 = 做多力量，融券 = 做空力量
Tushare免费接口: margin_detail
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
class MarginData:
    """融资融券数据"""
    date: str = ""
    code: str = ""
    name: str = ""
    close_price: float = 0.0
    margin_balance: float = 0.0    # 融资余额(万)
    margin_buy: float = 0.0         # 融资买入额(万)
    margin_repay: float = 0.0       # 融资偿还额(万)
    margin_net: float = 0.0         # 融资净买入(万)
    short_balance: float = 0.0       # 融券余额(万)
    short_sell: float = 0.0          # 融券卖出量
    short_cover: float = 0.0        # 融券偿还量
    short_net: float = 0.0           # 融券净卖出
    margin_ratio: float = 0.0       # 融资融券余额比


class MarginFetcher:
    """融资融券数据获取器"""

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

    def get_daily(self, code: str, date: Optional[str] = None) -> Optional[MarginData]:
        """获取个股每日融资融券数据"""
        pro = self._get_pro()
        if pro is None:
            return None

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            ts_code = code.zfill(6)
            if ts_code.startswith(("6", "5", "9")):
                ts_code = f"{ts_code}.SH"
            else:
                ts_code = f"{ts_code}.SZ"

            df = pro.margin_detail(ts_code=ts_code, trade_date=date)
            if df is None or df.empty:
                return None

            row = df.iloc[0]
            margin_balance = float(row.get("margin_balance", 0)) / 1e4
            short_balance = float(row.get("short_balance", 0)) / 1e4

            return MarginData(
                date=str(row.get("trade_date", "")),
                code=code,
                name=str(row.get("name", "")),
                close_price=float(row.get("close", 0)),
                margin_balance=margin_balance,
                margin_buy=float(row.get("margin_buy", 0)) / 1e4,
                margin_repay=float(row.get("margin_repay", 0)) / 1e4,
                short_balance=short_balance,
                short_sell=float(row.get("short_sell_amount", 0)),
                short_cover=float(row.get("short_cover_amount", 0)),
                margin_ratio=margin_balance / max(short_balance, 1),
            )
        except Exception:
            return None

    def get_history(self, code: str, days: int = 10) -> List[MarginData]:
        """获取个股最近N天融资融券历史"""
        results = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            data = self.get_daily(code, date_str)
            if data:
                results.append(data)

        return results


_margin_fetcher = None


def get_margin_fetcher(token: str = "") -> MarginFetcher:
    global _margin_fetcher
    if _margin_fetcher is None:
        _margin_fetcher = MarginFetcher(token)
    return _margin_fetcher