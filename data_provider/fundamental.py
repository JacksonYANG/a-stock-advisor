#!/usr/bin/env python3
"""
基本面数据获取模块
基于 baostock 获取财务报表数据

注意: baostock 不提供直接的 PE/PB 数据，使用 query_profit_data 的 ROE/净利率/毛利率/epsTTM
估值指标需要配合市值数据计算，或使用 Tushare 的 daily_basic 接口
"""

import baostock as bs
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FinancialData:
    """财务数据结构"""
    code: str = ""
    name: str = ""
    trade_date: str = ""

    # 估值指标 (从 query_profit_data + 市值计算)
    pe: float = 0.0      # 市盈率 (手动计算)
    pb: float = 0.0      # 市净率 (手动计算)

    # 每股指标
    eps: float = 0.0     # 每股收益 (TTM)
    bps: float = 0.0     # 每股净资产

    # 财务质量
    roe: float = 0.0     # 净资产收益率 %
    roa: float = 0.0     # 总资产收益率 %
    gross_margin: float = 0.0    # 毛利率 %
    net_margin: float = 0.0      # 净利率 %

    # 成长指标
    revenue_growth: float = 0.0   # 营收增长率 %
    profit_growth: float = 0.0    # 净利润增长率 %


class FundamentalFetcher:
    """基本面数据获取器"""

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

    def _normalize_code(self, code: str) -> str:
        """转换代码格式: 000001 -> sz.000001"""
        code = code.strip().zfill(6)
        if code.startswith(("6", "5", "9")):
            return f"sh.{code}"
        elif code.startswith(("0", "3")):
            return f"sz.{code}"
        elif code.startswith(("4", "8")):
            return f"bj.{code}"
        return f"sz.{code}"

    def _get_stock_name(self, bs_code: str) -> str:
        """获取股票名称"""
        try:
            rs = bs.query_stock_basic(bs_code)
            while rs.next():
                return rs.get_row_data()[1]
        except:
            pass
        return ""

    def get_financial_data(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[FinancialData]:
        """
        获取个股基本面数据（综合）

        baostock 提供的财务数据:
        - query_profit_data: roeAvg, npMargin, gpMargin, epsTTM, totalShare, liqaShare
        - query_dupont_data: dupontROE, dupontAssetStoEquity (杠杆), dupontAssetTurn (周转)
        - query_growth_data: YOYNI (净利润增速), YOYEquity, YOYAsset

        Args:
            code: 6位股票代码
            year: 年份 (默认去年)
            quarter: 季度 1-4 (默认4)
        """
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            data = FinancialData(code=code)
            data.name = self._get_stock_name(bs_code)

            # 1. 盈利能力 (query_profit_data)
            try:
                rs = bs.query_profit_data(bs_code, year=str(year), quarter=str(quarter))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    row = rows[0]
                    # fields: code, pubDate, statDate, roeAvg, npMargin, gpMargin, netProfit, epsTTM, MBRevenue, totalShare, liqaShare
                    data.roe = float(row[3] or 0) * 100  # roeAvg
                    data.net_margin = float(row[4] or 0) * 100  # npMargin
                    data.gross_margin = float(row[5] or 0) * 100 if row[5] else 0.0
                    data.eps = float(row[7] or 0)  # epsTTM
                    # 每股净资产 = 总股本市值 / 股本数 (间接)
                    total_share = float(row[9] or 0)  # 总股本
                    liqa_share = float(row[10] or 0)  # 流通股本
            except Exception as e:
                pass

            # 2. 杜邦分析 (query_dupont_data) - 获取更精确的 ROE
            try:
                rs = bs.query_dupont_data(bs_code, year=str(year), quarter=str(quarter))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    row = rows[0]
                    # fields: code, pubDate, statDate, dupontROE, dupontAssetStoEquity, dupontAssetTurn, dupontPnitoni, dupontNitogr, dupontTaxBurden, dupontIntburden, dupontEbittogr
                    if row[3]:  # dupontROE
                        data.roe = float(row[3]) * 100
                    data.roa = float(row[6] or 0) * 100 if row[6] else 0.0  # dupontPnitoni
            except:
                pass

            # 3. 成长能力 (query_growth_data)
            try:
                rs = bs.query_growth_data(bs_code, year=str(year), quarter=str(quarter))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    row = rows[0]
                    # fields: code, pubDate, statDate, YOYEquity, YOYAsset, YOYNI, YOYEPSBasic, YOYPNI
                    data.profit_growth = float(row[5] or 0) * 100 if row[5] else 0.0
                    data.revenue_growth = float(row[1] or 0) * 100 if row[1] else 0.0
            except:
                pass

            return data

        finally:
            self._logout()

    def get_profit_data(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """获取个股盈利能力数据"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_profit_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            return pd.DataFrame(rows, columns=rs.fields)
        finally:
            self._logout()

    def get_dupont_data(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """获取杜邦分析数据"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_dupont_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            return pd.DataFrame(rows, columns=rs.fields)
        finally:
            self._logout()

    def get_growth_data(self, code: str, year: Optional[int] = None, quarter: Optional[int] = None) -> Optional[pd.DataFrame]:
        """获取成长能力数据"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            if year is None:
                year = datetime.now().year - 1
            if quarter is None:
                quarter = 4

            rs = bs.query_growth_data(bs_code, year=str(year), quarter=str(quarter))
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            return pd.DataFrame(rows, columns=rs.fields)
        finally:
            self._logout()

    def get_industry(self, code: str) -> str:
        """获取所属行业"""
        self._login()
        try:
            bs_code = self._normalize_code(code)
            rs = bs.query_stock_industry(bs_code)
            while rs.next():
                # fields: code, code_name, industry, ipoDate, outDate
                return rs.get_row_data()[2] or ""
        finally:
            self._logout()
        return ""

    def screen_stocks(
        self,
        roe_min: Optional[float] = None,
        profit_growth_min: Optional[float] = None,
        net_margin_min: Optional[float] = None,
        gross_margin_min: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        财务筛选器

        通过遍历所有股票进行筛选（baostock 没有批量财务筛选接口）
        注意: 这个方法较慢，因为需要遍历查询所有股票
        """
        results = []

        self._login()
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            all_stocks = []
            while rs.next():
                all_stocks.append(rs.get_row_data())
        finally:
            self._logout()

        count = 0
        for stock in all_stocks:
            if count >= limit:
                break

            try:
                bs_code = stock[0]
                code = bs_code.split(".")[1]

                # 跳过不交易的股票
                if len(stock) > 2 and stock[2] == "":
                    continue

                # 获取财务数据
                data = self.get_financial_data(code)
                if not data:
                    continue

                # 应用筛选条件
                if roe_min is not None and data.roe < roe_min:
                    continue
                if profit_growth_min is not None and data.profit_growth < profit_growth_min:
                    continue
                if net_margin_min is not None and data.net_margin < net_margin_min:
                    continue
                if gross_margin_min is not None and data.gross_margin < gross_margin_min:
                    continue

                results.append({
                    "code": code,
                    "name": data.name,
                    "industry": self.get_industry(code),
                    "roe": data.roe,
                    "net_margin": data.net_margin,
                    "gross_margin": data.gross_margin,
                    "profit_growth": data.profit_growth,
                    "revenue_growth": data.revenue_growth,
                    "eps": data.eps,
                })
                count += 1

            except Exception:
                continue

        return results


_fetcher = None


def get_fundamental_fetcher() -> FundamentalFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = FundamentalFetcher()
    return _fetcher
