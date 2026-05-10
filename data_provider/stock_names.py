"""
Stock name mapping and resolution module for A-share stocks.

Provides a local lookup table for stock code -> name resolution,
with fallback to quote/hist data sources when available.
"""

# Complete mapping of stock code (6-digit string) -> Chinese name
STOCK_NAME_MAP: dict[str, str] = {
    # === User's 21 watch list stocks ===
    # --- Original 15 ---
    "601138": "工业富联",
    "600276": "恒瑞医药",
    "002714": "牧原股份",
    "000776": "广发证券",
    "600196": "复星医药",
    "603105": "芯能科技",
    "002297": "博云新材",
    "002580": "圣阳股份",
    "600143": "金发科技",
    "002271": "东方雨虹",
    "600872": "中炬高新",
    "002428": "云南锗业",
    "002201": "九鼎新材",
    "300857": "协创数据",
    "002361": "神剑股份",
    # --- New 6 (2026-05-07 added) ---
    "301246": "宏源药业",
    "002842": "翔鹭钨业",
    "002192": "融捷股份",
    "000066": "中国长城",
    "603778": "国晟科技",
    "601778": "晶科科技",

    # === Common A-share blue chips / popular stocks ===
    "600519": "贵州茅台",
    "000001": "平安银行",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "601318": "中国平安",
    "600036": "招商银行",
    "000858": "五粮液",
    "600900": "长江电力",
    "601012": "隆基绿能",
    "300059": "东方财富",
    "002475": "立讯精密",
    "600809": "山西汾酒",
    "000333": "美的集团",
    "002714": "牧原股份",
    "600031": "三一重工",
    "601888": "中国中免",
    "300274": "阳光电源",
    "002415": "海康威视",
    "600887": "伊利股份",
    "601166": "兴业银行",
    "600030": "中信证券",
    "000002": "万科A",
    "600276": "恒瑞医药",
    "002352": "顺丰控股",
    "300760": "迈瑞医疗",
    "601398": "工商银行",
    "600000": "浦发银行",
    "601288": "农业银行",
    "600016": "民生银行",
    "601939": "建设银行",
    "600028": "中国石化",
    "601857": "中国石油",
    "600585": "海螺水泥",
    "000568": "泸州老窖",
    "002304": "洋河股份",
    "601688": "华泰证券",
    "600050": "中国联通",
    "600104": "上汽集团",
    "601668": "中国建筑",
    "600048": "保利发展",
}


def get_stock_name(code: str) -> str:
    """Return the stock name for a given code, or empty string if not found.

    Args:
        code: Stock code, e.g. '601138', '601138.SH', '138', etc.
              Will be stripped and zero-padded to 6 digits.

    Returns:
        Stock name (Chinese) or empty string if not in the mapping.
    """
    normalized = _normalize_code(code)
    return STOCK_NAME_MAP.get(normalized, "")


def resolve_stock_name(code: str, quote=None, hist=None) -> str:
    """Resolve a stock name from multiple sources with fallback chain.

    Resolution order:
        1. quote.name — if a quote object with a non-empty .name attr is provided
        2. STOCK_NAME_MAP — local lookup table
        3. hist DataFrame — try to extract name from column metadata
        4. Fallback — return the code itself

    Args:
        code: Stock code string.
        quote: Optional quote object with a .name attribute.
        hist: Optional pandas DataFrame with stock history data.

    Returns:
        Resolved stock name string (never empty).
    """
    normalized = _normalize_code(code)

    # 1. Try quote.name
    if quote is not None:
        name = getattr(quote, "name", None)
        if name and isinstance(name, str) and name.strip():
            return name.strip()

    # 2. Try local map
    mapped = STOCK_NAME_MAP.get(normalized, "")
    if mapped:
        return mapped

    # 3. Try to extract from hist DataFrame
    if hist is not None:
        name = _extract_name_from_hist(hist, normalized)
        if name:
            return name

    # 4. Fallback to code
    return normalized


def prefetch_names(codes: list) -> dict:
    """Batch-resolve stock names for a list of codes.

    Args:
        codes: List of stock code strings.

    Returns:
        Dict mapping code (normalized 6-digit string) -> resolved name.
    """
    result = {}
    for code in codes:
        normalized = _normalize_code(code)
        name = STOCK_NAME_MAP.get(normalized, "")
        result[normalized] = name
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_code(code: str) -> str:
    """Normalize a stock code to a 6-digit zero-padded string.

    Handles inputs like '601138', 'sh601138', '601138.SH', 'SH.601138', '138', etc.
    """
    if not isinstance(code, str):
        code = str(code)
    s = code.strip()
    # Strip exchange suffixes: .SH, .SZ, .BJ, .SS
    for suffix in (".SH", ".SZ", ".BJ", ".SS", ".sh", ".sz", ".bj", ".ss"):
        if s.upper().endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Strip exchange prefixes: sh, sz, bj
    if "." in s:
        # Handle "sh.601138" format
        parts = s.split(".")
        s = parts[-1]
    for prefix in ("sh", "sz", "bj", "SH", "SZ", "BJ"):
        if s.lower().startswith(prefix) and len(s) > len(prefix):
            s = s[len(prefix):]
            break
    # Zero-pad to 6 digits
    s = s.zfill(6)
    return s


def _extract_name_from_hist(hist, code: str) -> str:
    """Try to extract stock name from a DataFrame's metadata or columns."""
    try:
        # Some data sources store name in attrs
        name = getattr(hist, "attrs", {}).get("name", "")
        if name and isinstance(name, str):
            return name.strip()
        # Try _metadata
        if hasattr(hist, "_metadata"):
            name = hist._metadata.get("name", "")  # type: ignore[attr-defined]
            if name and isinstance(name, str):
                return name.strip()
    except Exception:
        pass
    return ""
