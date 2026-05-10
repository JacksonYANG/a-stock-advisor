"""
数据获取层 - 基类与数据管理器
参考 daily_stock_analysis 的 Strategy Pattern，支持多数据源自动切换
"""

import pandas as pd
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass
from rich.console import Console

console = Console()


@dataclass
class StockQuote:
    """实时行情数据"""
    code: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0    # 涨跌幅(%)
    change_amt: float = 0.0    # 涨跌额
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0        # 成交量(手)
    amount: float = 0.0        # 成交额(元)
    turnover_rate: float = 0.0  # 换手率(%)
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    total_mv: float = 0.0     # 总市值(元)
    circ_mv: float = 0.0       # 流通市值(元)
    # 扩展字段 (用于选股/回测/板块)
    market_cap: float = 0.0     # 总市值(元) - alias
    volume_ratio: float = 0.0   # 量比
    position_type: str = ""     # price position: "high"/"medium"/"low"
    amplitude: float = 0.0      # 振幅(%)
    hand_rate: float = 0.0     # 换手率 alias

    def __post_init__(self):
        if self.market_cap == 0.0:
            self.market_cap = self.total_mv

    def to_dict(self) -> Dict[str, Any]:
        return vars(self)


class BaseFetcher(ABC):
    """数据源基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小优先级越高"""
        ...

    @abstractmethod
    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取实时行情"""
        ...

    @abstractmethod
    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史K线数据

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        ...

    def normalize_code(self, code: str) -> str:
        """标准化股票代码"""
        code = code.strip()
        # 去掉可能的市场前缀
        for prefix in ("sh", "sz", "bj", "SH", "SZ", "BJ"):
            code = code.removeprefix(prefix)
        # 补零
        if code.isdigit():
            code = code.zfill(6)
        return code

    def get_market_prefix(self, code: str) -> str:
        """根据代码判断市场前缀"""
        code = self.normalize_code(code)
        if code.startswith(("6", "5", "9")):
            return "sh"  # 上海
        elif code.startswith(("0", "3")):
            return "sz"  # 深圳
        elif code.startswith(("4", "8")):
            return "bj"  # 北京
        return "sz"


class DataFetcherManager:
    """数据源管理器 - 支持多数据源自动切换"""

    def __init__(self, sources: list[str] = None, use_cache: bool = True):
        self._fetchers: Dict[str, BaseFetcher] = {}
        self._ordered_fetchers: list[BaseFetcher] = []

        # 数据缓存 - 消除冗余的全市场数据下载
        if use_cache:
            from data_provider.cache import DataCache
            self._cache = DataCache()
        else:
            self._cache = None

        if sources:
            self.register_sources(sources)

    def register(self, fetcher: BaseFetcher):
        """注册数据源"""
        self._fetchers[fetcher.name] = fetcher
        self._ordered_fetchers = sorted(
            self._fetchers.values(), key=lambda f: f.priority
        )

    def register_sources(self, source_names: list[str]):
        """根据名称注册数据源"""
        # 真正的延迟导入，避免循环依赖
        from data_provider.efinance_fetcher import EfinanceFetcher
        from data_provider.akshare_fetcher import AkshareFetcher
        from data_provider.baostock_fetcher import BaostockFetcher

        source_map = {
            "efinance": EfinanceFetcher,
            "akshare": AkshareFetcher,
            "baostock": BaostockFetcher,
        }

        for name in source_names:
            name = name.strip().lower()
            if name == "tushare":
                try:
                    from data_provider.tushare_fetcher import TushareFetcher
                    if name not in self._fetchers:
                        fetcher = TushareFetcher()
                        self.register(fetcher)
                        console.print(f"[green]✓ 数据源 {name} 注册成功 (优先级: {fetcher.priority})[/green]")
                except Exception as e:
                    console.print(f"[red]✗ 数据源 {name} 注册失败: {e}[/red]")
                continue
            if name in source_map and name not in self._fetchers:
                try:
                    fetcher = source_map[name]()
                    self.register(fetcher)
                    console.print(f"[green]✓ 数据源 {name} 注册成功 (优先级: {fetcher.priority})[/green]")
                except Exception as e:
                    console.print(f"[red]✗ 数据源 {name} 注册失败: {e}[/red]")

    def get_quote(self, code: str) -> Optional[StockQuote]:
        """获取实时行情，自动切换数据源（带缓存）"""
        # 检查缓存
        if self._cache:
            cached = self._cache.get_quote(code)
            if cached is not None:
                return cached

        # 从数据源获取
        result = self._fetch_from_sources('get_quote', code)

        # 缓存结果
        if result and self._cache:
            self._cache.set_quote(code, result)
        return result

    def get_history(self, code: str, days: int = 120) -> Optional[pd.DataFrame]:
        """获取历史数据，自动切换数据源（带缓存）"""
        cache_key = f"{code}_{days}"
        if self._cache:
            cached = self._cache.get_history(cache_key)
            if cached is not None:
                return cached

        result = self._fetch_from_sources('get_history', code, days)

        if result is not None and not result.empty and self._cache:
            self._cache.set_history(cache_key, result)
        return result

    def _fetch_from_sources(self, method: str, code: str, *args) -> Any:
        """Try each data source in priority order"""
        for fetcher in self._ordered_fetchers:
            try:
                fn = getattr(fetcher, method)
                result = fn(code, *args)
                if method == 'get_quote' and result:
                    return result
                if method == 'get_history' and result is not None and not result.empty:
                    return result
            except Exception as e:
                console.print(f"[yellow]⚠ {fetcher.name} {method} 失败: {e}，尝试下一个数据源[/yellow]")
        return None

    def get_batch_quotes(self, codes: list[str]) -> Dict[str, StockQuote]:
        """批量获取行情"""
        results = {}
        for code in codes:
            quote = self.get_quote(code)
            if quote:
                results[code] = quote
        return results

    def cache_stats(self) -> dict:
        """Return cache statistics"""
        if self._cache:
            return self._cache.stats()
        return {"hits": 0, "misses": 0, "hit_rate": "N/A", "size": 0}

    def cache_cleanup(self):
        """Remove expired cache entries"""
        if self._cache:
            self._cache.cleanup_expired()

    def cache_clear(self):
        """Clear entire cache"""
        if self._cache:
            self._cache.clear()
