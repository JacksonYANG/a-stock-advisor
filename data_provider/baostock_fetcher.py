"""
Baostock 数据源 (Priority 2)
最稳定的免费A股数据源，适合从海外访问
"""

import pandas as pd
from typing import Optional
from datetime import datetime, timedelta
from .base import BaseFetcher, StockQuote

try:
    import baostock as bs
    HAS_BAOSTOCK = True
except ImportError:
    HAS_BAOSTOCK = False


class BaostockFetcher(BaseFetcher):
    """Baostock 数据源"""

    @property
    def name(self) -> str:
        return "baostock"

    @property
    def priority(self) -> int:
        return 2

    def __init__(self):
        if not HAS_BAOSTOCK:
            raise ImportError("baostock 未安装，请运行: pip install baostock")

    def _get_full_code(self, code: str) -> str:
        """获取带市场前缀的代码"""
        code = self.normalize_code(code)
        prefix = self.get_market_prefix(code)
        return f"{prefix}.{code}"

    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取最新行情 (通过最近一天的日线数据)"""
        try:
            code = self.normalize_code(code)
            full_code = self._get_full_code(code)

            lg = bs.login()

            today = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

            rs = bs.query_history_k_data_plus(
                full_code,
                "date,open,high,low,close,preclose,volume,amount,turn,pctChg",
                start_date=start, end_date=today,
                frequency="d", adjustflag="2",
            )

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            bs.logout()

            if not rows:
                return None

            last = rows[-1]
            prev_close = float(last[5]) if len(last) > 5 and last[4] else 0  # preclose
            cur_close = float(last[4]) if last[4] else 0  # close
            change_pct = float(last[9]) if len(last) > 9 and last[9] else 0
            open_px = float(last[1]) if last[1] else 0
            high_px = float(last[2]) if last[2] else 0
            low_px = float(last[3]) if last[3] else 0
            volume_px = float(last[6]) if last[6] else 0
            amount_px = float(last[7]) if last[7] else 0
            turnover_px = float(last[8]) if len(last) > 8 and last[8] else 0

            # 计算 amplitude: (high - low) / prev_close * 100
            amplitude = ((high_px - low_px) / prev_close * 100) if prev_close else 0.0

            # 计算 position_type
            if change_pct > 5:
                position_type = "high"
            elif change_pct < -3:
                position_type = "low"
            else:
                position_type = "medium"

            return StockQuote(
                code=code,
                name="",  # baostock 不返回名称
                price=cur_close,
                change_pct=change_pct,
                change_amt=cur_close - prev_close if prev_close else 0,
                open=open_px,
                high=high_px,
                low=low_px,
                close=prev_close,
                volume=volume_px,
                amount=amount_px,
                turnover_rate=turnover_px,
                # 扩展字段
                market_cap=0.0,      # baostock 日线不提供市值
                volume_ratio=0.0,    # baostock 日线不提供量比
                position_type=position_type,
                amplitude=amplitude,
                hand_rate=turnover_px,
            )

        except Exception as e:
            raise RuntimeError(f"baostock 行情获取失败: {e}") from e

    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史K线数据"""
        try:
            code = self.normalize_code(code)
            full_code = self._get_full_code(code)

            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")

            lg = bs.login()

            rs = bs.query_history_k_data_plus(
                full_code,
                "date,open,high,low,close,volume,amount,turn",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2",  # 前复权
            )

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            bs.logout()

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"])

            # 类型转换
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            return df.tail(days).reset_index(drop=True)

        except Exception as e:
            try:
                bs.logout()
            except:
                pass
            raise RuntimeError(f"baostock 历史数据获取失败: {e}") from e
