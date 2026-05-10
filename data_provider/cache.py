"""
数据缓存层 - 消除冗余的全市场数据下载

核心问题: efinance/akshare 的 get_quote() 每次调用都下载全市场 5000+ 只股票数据。
缓存策略:
  - 实时行情 TTL = 30 秒 (交易时间内数据频繁变化)
  - 历史数据 TTL = 3600 秒 (日内历史数据不变)
  - 线程安全 (支持监控场景)
  - 纯内存缓存 (无需持久化)
"""

import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """缓存条目"""
    data: Any
    timestamp: float  # time.time()
    ttl: float        # seconds


class DataCache:
    """Thread-safe in-memory cache for stock data"""

    def __init__(self, default_ttl_quote: float = 30, default_ttl_history: float = 3600):
        """
        Args:
            default_ttl_quote: TTL for real-time quotes (30 seconds)
            default_ttl_history: TTL for historical data (1 hour)
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._default_ttl_quote = default_ttl_quote
        self._default_ttl_history = default_ttl_history
        self._hits = 0
        self._misses = 0

    def _get(self, key: str) -> Optional[Any]:
        """Internal get with TTL check"""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.timestamp > entry.ttl:
            # Expired - remove it
            del self._cache[key]
            return None
        return entry.data

    def _set(self, key: str, data: Any, ttl: float):
        """Internal set"""
        self._cache[key] = CacheEntry(data=data, timestamp=time.time(), ttl=ttl)

    def get_quote(self, code: str) -> Optional[Any]:
        """Get cached quote if still fresh"""
        key = f"quote:{code}"
        with self._lock:
            result = self._get(key)
            if result is not None:
                self._hits += 1
                return result
            self._misses += 1
            return None

    def set_quote(self, code: str, quote: Any, ttl: float = None):
        """Cache a quote"""
        key = f"quote:{code}"
        with self._lock:
            self._set(key, quote, ttl if ttl is not None else self._default_ttl_quote)

    def get_history(self, code: str) -> Optional[Any]:
        """Get cached history if still fresh"""
        key = f"history:{code}"
        with self._lock:
            result = self._get(key)
            if result is not None:
                self._hits += 1
                return result
            self._misses += 1
            return None

    def set_history(self, code: str, df: Any, ttl: float = None):
        """Cache historical data"""
        key = f"history:{code}"
        with self._lock:
            self._set(key, df, ttl if ttl is not None else self._default_ttl_history)

    def invalidate(self, code: str):
        """Remove all cached data for a stock"""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.endswith(f":{code}")]
            for k in keys_to_remove:
                del self._cache[k]

    def clear(self):
        """Clear entire cache"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def cleanup_expired(self):
        """Remove all expired entries to free memory"""
        with self._lock:
            now = time.time()
            expired = [
                k for k, v in self._cache.items()
                if now - v.timestamp > v.ttl
            ]
            for k in expired:
                del self._cache[k]

    def stats(self) -> dict:
        """Return cache hit/miss statistics"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "size": len(self._cache),
            }
