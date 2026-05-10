"""
交易日历工具
判断是否为交易日、获取交易日列表
"""

from datetime import datetime, date, timedelta
from typing import List, Optional

try:
    import exchange_calendars as ec
    HAS_EC = True
except ImportError:
    HAS_EC = False


def is_trading_day(target_date: Optional[date] = None) -> bool:
    """判断是否为A股交易日"""
    if target_date is None:
        target_date = date.today()

    if HAS_EC:
        try:
            cal = ec.get_calendar("XSHG")
            return cal.is_session(pd_timestamp(target_date))
        except Exception:
            pass

    # 简易判断: 周一~周五 (不含节假日)
    return target_date.weekday() < 5


def pd_timestamp(d: date):
    """date -> pandas Timestamp"""
    import pandas as pd
    return pd.Timestamp(d)


def get_trading_days(start: date, end: date) -> List[date]:
    """获取交易日列表"""
    if HAS_EC:
        try:
            cal = ec.get_calendar("XSHG")
            sessions = cal.sessions_in_range(
                pd_timestamp(start), pd_timestamp(end)
            )
            return [ts.date() for ts in sessions]
        except Exception:
            pass

    # 简易返回
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def get_last_trading_day(target_date: Optional[date] = None) -> date:
    """获取最近的交易日"""
    if target_date is None:
        target_date = date.today()

    current = target_date
    for _ in range(10):  # 最多往回找10天
        if is_trading_day(current):
            return current
        current -= timedelta(days=1)

    return target_date
