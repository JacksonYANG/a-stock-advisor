#!/usr/bin/env python3
"""
行业分类数据获取模块（公共模块）
被 sector.py 和 sector_flow.py 共用
"""

import baostock as bs
from typing import Dict


_industry_cache: Dict[str, str] = {}
_logged_in = False


def _login():
    global _logged_in
    if not _logged_in:
        bs.login()
        _logged_in = True


def _logout():
    global _logged_in
    if _logged_in:
        bs.logout()
        _logged_in = False


def get_stock_industry(code: str) -> str:
    """获取个股所属行业（带缓存）"""
    if code in _industry_cache:
        return _industry_cache[code]

    code = code.strip().zfill(6)
    if code.startswith(("6", "5", "9")):
        bs_code = f"sh.{code}"
    elif code.startswith(("0", "3")):
        bs_code = f"sz.{code}"
    elif code.startswith(("4", "8")):
        bs_code = f"bj.{code}"
    else:
        bs_code = f"sz.{code}"

    _login()
    try:
        rs = bs.query_stock_industry(bs_code)
        while rs.next():
            industry = rs.get_row_data()[2] or ""
            _industry_cache[code] = industry
            return industry
    finally:
        _logout()

    return ""


def clear_cache():
    """清除行业缓存"""
    global _industry_cache
    _industry_cache = {}
