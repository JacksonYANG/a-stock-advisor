"""
efinance 数据源 - 基于东方财富 (Priority 0)
实时行情 + 历史K线，免费无限制
"""

import pandas as pd
from typing import Optional
from datetime import datetime, timedelta
from .base import BaseFetcher, StockQuote

try:
    import efinance as ef
    HAS_EFINANCE = True
except ImportError:
    HAS_EFINANCE = False


class EfinanceFetcher(BaseFetcher):
    """东方财富数据源 - efinance 库"""

    @property
    def name(self) -> str:
        return "efinance"

    @property
    def priority(self) -> int:
        return 0

    def __init__(self):
        if not HAS_EFINANCE:
            raise ImportError("efinance 未安装，请运行: pip install efinance")

    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取实时行情"""
        try:
            code = self.normalize_code(code)
            full_code = self.get_market_prefix(code) + code
            df = ef.stock.get_realtime_quotes()

            # 筛选目标股票
            target = df[df["股票代码"] == code]
            if target.empty:
                target = df[df["股票代码"] == full_code]
            if target.empty:
                return None

            row = target.iloc[0]
            return StockQuote(
                code=code,
                name=str(row.get("股票名称", "")),
                price=float(row.get("最新价", 0)),
                change_pct=float(row.get("涨跌幅", 0)),
                change_amt=float(row.get("涨跌额", 0)),
                open=float(row.get("今开", 0)),
                high=float(row.get("最高", 0)),
                low=float(row.get("最低", 0)),
                close=float(row.get("昨收", 0)),
                volume=float(row.get("成交量", 0)),
                amount=float(row.get("成交额", 0)),
                turnover_rate=float(row.get("换手率", 0)),
            )
        except Exception as e:
            raise RuntimeError(f"efinance 行情获取失败: {e}") from e

    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史K线数据"""
        try:
            code = self.normalize_code(code)
            full_code = self.get_market_prefix(code) + code

            # 计算日期范围
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

            df = ef.stock.get_quote_history(
                code,
                beg=start_date,
                end=end_date,
                klt=101,  # 日K线
                fqt=1,    # 前复权
            )

            if df is None or df.empty:
                return None

            # 标准化列名
            column_map = {
                "股票代码": "code",
                "股票名称": "name",
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

            # 确保日期列
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)

            # 只保留需要的列
            keep_cols = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"] if c in df.columns]
            df = df[keep_cols]

            return df.tail(days).reset_index(drop=True)

        except Exception as e:
            raise RuntimeError(f"efinance 历史数据获取失败: {e}") from e
