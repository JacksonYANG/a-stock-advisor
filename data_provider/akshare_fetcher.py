"""
AkShare 数据源 - 备用方案 (Priority 1)
基于东方财富数据接口，通过 akshare 库获取
"""

import pandas as pd
from typing import Optional
from datetime import datetime, timedelta
from .base import BaseFetcher, StockQuote

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False


class AkshareFetcher(BaseFetcher):
    """AkShare 数据源"""

    @property
    def name(self) -> str:
        return "akshare"

    @property
    def priority(self) -> int:
        return 1

    def __init__(self):
        if not HAS_AKSHARE:
            raise ImportError("akshare 未安装，请运行: pip install akshare")

    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取实时行情"""
        try:
            code = self.normalize_code(code)
            full_code = self.get_market_prefix(code) + code

            # 使用 akshare 获取实时行情
            df = ak.stock_zh_a_spot_em()
            target = df[df["代码"] == code]

            if target.empty:
                return None

            row = target.iloc[0]
            return StockQuote(
                code=code,
                name=str(row.get("名称", "")),
                price=float(row.get("最新价", 0) or 0),
                change_pct=float(row.get("涨跌幅", 0) or 0),
                change_amt=float(row.get("涨跌额", 0) or 0),
                open=float(row.get("今开", 0) or 0),
                high=float(row.get("最高", 0) or 0),
                low=float(row.get("最低", 0) or 0),
                close=float(row.get("昨收", 0) or 0),
                volume=float(row.get("成交量", 0) or 0),
                amount=float(row.get("成交额", 0) or 0),
                turnover_rate=float(row.get("换手率", 0) or 0),
                pe_ratio=float(row.get("市盈率-动态", 0) or 0),
                pb_ratio=float(row.get("市净率", 0) or 0),
                total_mv=float(row.get("总市值", 0) or 0),
                circ_mv=float(row.get("流通市值", 0) or 0),
            )
        except Exception as e:
            raise RuntimeError(f"akshare 行情获取失败: {e}") from e

    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史K线数据"""
        try:
            code = self.normalize_code(code)

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",  # 前复权
            )

            if df is None or df.empty:
                return None

            # 标准化列名
            column_map = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover_rate",
            }
            df = df.rename(columns=column_map)

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)

            keep_cols = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"] if c in df.columns]
            df = df[keep_cols]

            return df.tail(days).reset_index(drop=True)

        except Exception as e:
            raise RuntimeError(f"akshare 历史数据获取失败: {e}") from e
