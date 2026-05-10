"""
Tushare Pro 数据源 (Priority 3)
支持免费档 + 2000积分档的所有接口
免费档可用: daily, stock_basic, adj_factor, hsgt_top10
2000积分档: daily_basic(pe/pb/换手率), moneyflow, top_list, limit_list 等
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from .base import BaseFetcher, StockQuote
from config import Config

try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False


class TushareFetcher(BaseFetcher):
    """Tushare Pro 数据源 - 兼容免费档和2000积分档"""

    @property
    def name(self) -> str:
        return "tushack"

    @property
    def priority(self) -> int:
        return 3  # 低于baostock(2)，高于akshare(4)

    def __init__(self):
        if not HAS_TUSHARE:
            raise ImportError("tushare 未安装，请运行: pip install tushare")
        config = Config.get()
        self._token = config.TUSHARE_TOKEN
        if not self._token:
            raise ValueError("TUSHARE_TOKEN 未配置，请检查 .env 文件")
        self._pro = None
        self._connect()

    def _connect(self):
        """建立Tushare连接"""
        self._pro = ts.pro_api(self._token)

    def _ts_code(self, code: str) -> str:
        """将6位代码转换为Tushare格式 (000001.SZ)"""
        code = self.normalize_code(code)
        if code.startswith(("6", "5", "9")):
            return f"{code}.SH"
        elif code.startswith(("0", "3")):
            return f"{code}.SZ"
        elif code.startswith(("4", "8")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    def _code_from_ts(self, ts_code: str) -> str:
        """从Tushare代码提取6位代码"""
        return ts_code.split(".")[0]

    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取实时行情 - 免费档可用"""
        try:
            ts_code = self._ts_code(code)
            today = datetime.now().strftime("%Y%m%d")

            # 日线数据作为实时行情（包含open/high/low/close/vol/amount）
            df = self._pro.daily(
                ts_code=ts_code,
                start_date=(datetime.now() - timedelta(days=5)).strftime("%Y%m%d"),
                end_date=today
            )
            if df is None or df.empty:
                return None

            row = df.iloc[-1]
            prev_close = float(row.get("pre_close", row.get("close", 0)))
            close = float(row["close"])
            change_pct = float(row["pct_chg"]) if "pct_chg" in row.columns else 0.0

            return StockQuote(
                code=self.normalize_code(code),
                name="",  # daily不返回name，用stock_basic单独查
                price=close,
                change_pct=change_pct,
                change_amt=close - prev_close if prev_close else 0,
                open=float(row["open"]) if pd.notna(row.get("open")) else 0,
                high=float(row["high"]) if pd.notna(row.get("high")) else 0,
                low=float(row["low"]) if pd.notna(row.get("low")) else 0,
                close=prev_close,
                volume=float(row["vol"]) * 100 if pd.notna(row.get("vol")) else 0,  # 手→股
                amount=float(row["amount"]) if pd.notna(row.get("amount")) else 0,
            )
        except Exception as e:
            raise RuntimeError(f"Tushare 行情获取失败: {e}") from e

    def get_name(self, code: str) -> str:
        """获取股票名称 - 免费档可用"""
        try:
            ts_code = self._ts_code(code)
            df = self._pro.stock_basic(
                ts_code=ts_code,
                fields="name"
            )
            if df is not None and not df.empty:
                return df.iloc[0].get("name", "")
            return ""
        except Exception:
            return ""

    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史K线 - 免费档可用 (前复权)"""
        try:
            ts_code = self._ts_code(code)
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

            df = self._pro.daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end
            )
            if df is None or df.empty:
                return None

            df = df.sort_values("trade_date").reset_index(drop=True)
            df.columns = [c.lower() for c in df.columns]

            # 类型转换
            for col in ["open", "high", "low", "close", "vol", "amount"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.rename(columns={"vol": "volume", "pct_chg": "change_pct"})
            df["date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("date").reset_index(drop=True)

            # 复权因子
            adj_df = self._get_adj_factor(ts_code, df["trade_date"].tolist())
            if adj_df is not None and not adj_df.empty:
                df = df.merge(adj_df, on="trade_date", how="left")
                df["adj_factor"] = df["adj_factor"].fillna(1.0)
            else:
                df["adj_factor"] = 1.0

            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            raise RuntimeError(f"Tushare 历史数据获取失败: {e}") from e

    def _get_adj_factor(self, ts_code: str, trade_dates: List[str]) -> Optional[pd.DataFrame]:
        """获取复权因子"""
        try:
            if not trade_dates:
                return None
            start = trade_dates[0]
            end = trade_dates[-1]
            df = self._pro.adj_factor(ts_code=ts_code, start_date=start, end_date=end)
            if df is not None and not df.empty:
                return df[["trade_date", "adj_factor"]]
            return None
        except Exception:
            return None

    # ========== 2000积分档接口 (默认返回None/False，等充值后启用) ==========

    def get_daily_basic(self, code: str, trade_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取每日指标 (pe/pb/换手率/量比/振幅等)
        需要2000积分，当前未解锁时返回None
        """
        try:
            ts_code = self._ts_code(code)
            if trade_date is None:
                trade_date = datetime.now().strftime("%Y%m%d")

            df = self._pro.daily_basic(
                ts_code=ts_code,
                trade_date=trade_date,
                fields="ts_code,trade_date,close,pe,pb,turnover_rate,volume_ratio,rise_fall,amount,circ_mv,total_mv"
            )
            return df if df is not None and not df.empty else None
        except Exception:
            # 权限未解锁时返回None，不抛异常
            return None

    def get_moneyflow(self, code: str, trade_date: str = None) -> Optional[Dict[str, float]]:
        """
        获取个股资金流向
        需要2000积分
        """
        try:
            ts_code = self._ts_code(code)
            if trade_date is None:
                trade_date = datetime.now().strftime("%Y%m%d")

            df = self._pro.moneyflow(ts_code=ts_code, trade_date=trade_date)
            if df is None or df.empty:
                return None

            row = df.iloc[0]
            return {
                "buy_sm_amount": float(row.get("buy_sm_amount", 0)),  # 小单买入
                "buy_md_amount": float(row.get("buy_md_amount", 0)),  # 中单买入
                "buy_lg_amount": float(row.get("buy_lg_amount", 0)),  # 大单买入
                "buy_elg_amount": float(row.get("buy_elg_amount", 0)),  # 超大单买入
                "net_mf_amount": float(row.get("net_mf_amount", 0)),   # 净流入
            }
        except Exception:
            return None

    def get_limit_list(self, trade_date: str = None, limit_type: str = "U") -> Optional[pd.DataFrame]:
        """
        获取涨跌停详情
        需要2000积分
        """
        try:
            if trade_date is None:
                trade_date = datetime.now().strftime("%Y%m%d")

            df = self._pro.limit_list(trade_date=trade_date, limit_type=limit_type)
            return df if df is not None and not df.empty else None
        except Exception:
            return None

    def get_limit_list_d(self, trade_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取涨跌停日统计 (免费档可用)
        """
        try:
            if trade_date is None:
                trade_date = datetime.now().strftime("%Y%m%d")

            df = self._pro.limit_list_d(trade_date=trade_date)
            return df if df is not None and not df.empty else None
        except Exception:
            return None

    def get_top_list(self, trade_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取龙虎榜明细
        需要2000积分
        """
        try:
            if trade_date is None:
                trade_date = datetime.now().strftime("%Y%m%d")

            df = self._pro.top_list(trade_date=trade_date)
            return df if df is not None and not df.empty else None
        except Exception:
            return None

    def get_index_daily(self, index_code: str = "000001.SH", days: int = 60) -> Optional[pd.DataFrame]:
        """
        获取指数日线
        需要2000积分
        """
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

            df = self._pro.index_daily(ts_code=index_code, start_date=start, end_date=end)
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                df["date"] = pd.to_datetime(df["trade_date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df.tail(days).reset_index(drop=True)
            return None
        except Exception:
            return None

    def get_financial_data(self, code: str, fields: str = None) -> Optional[pd.DataFrame]:
        """
        获取财务报表 (income/balancesheet/cashflow)
        需要2000积分
        """
        try:
            ts_code = self._ts_code(code)
            if fields is None:
                fields = "ts_code,ann_date,report_date,type,n_income,revenue,total_profit,operate_profit"

            df = self._pro.income(ts_code=ts_code, fields=fields)
            return df if df is not None and not df.empty else None
        except Exception:
            return None

    def is_2000_enabled(self) -> bool:
        """检测2000积分档是否已解锁"""
        try:
            # 尝试调用需要2000积分的接口
            result = self.get_daily_basic("000001.SZ")
            return result is not None
        except Exception:
            return False
