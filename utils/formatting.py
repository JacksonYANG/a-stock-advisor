"""
格式化工具
"""

from typing import Optional


def format_number(value: float, decimals: int = 2) -> str:
    """格式化数字"""
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


def format_percent(value: float) -> str:
    """格式化百分比"""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def format_volume(vol: float) -> str:
    """格式化成交量"""
    if vol is None or vol == 0:
        return "0"
    if abs(vol) >= 1e8:
        return f"{vol/1e8:.2f}亿"
    elif abs(vol) >= 1e4:
        return f"{vol/1e4:.2f}万"
    else:
        return f"{vol:.0f}"


def format_amount(amt: float) -> str:
    """格式化金额"""
    if amt is None or amt == 0:
        return "0"
    if abs(amt) >= 1e12:
        return f"{amt/1e12:.2f}万亿"
    elif abs(amt) >= 1e8:
        return f"{amt/1e8:.2f}亿"
    elif abs(amt) >= 1e4:
        return f"{amt/1e4:.2f}万"
    else:
        return f"{amt:.2f}"


def format_market_value(mv: float) -> str:
    """格式化市值"""
    if mv is None or mv == 0:
        return "N/A"
    if abs(mv) >= 1e12:
        return f"{mv/1e12:.2f}万亿"
    elif abs(mv) >= 1e8:
        return f"{mv/1e8:.2f}亿"
    else:
        return f"{mv:.0f}"


def get_market_name(code: str) -> str:
    """根据股票代码判断市场"""
    code = code.strip().zfill(6)
    if code.startswith("6"):
        return "沪市"
    elif code.startswith("0") or code.startswith("3"):
        return "深市"
    elif code.startswith("4") or code.startswith("8"):
        return "北交所"
    else:
        return "未知"


def colorize_change(change: float) -> str:
    """给涨跌加上颜色标记 (用于 Rich 输出)"""
    if change > 0:
        return f"[red]{change:+.2f}%[/red]"
    elif change < 0:
        return f"[green]{change:+.2f}%[/green]"
    else:
        return f"[dim]{change:+.2f}%[/dim]"
