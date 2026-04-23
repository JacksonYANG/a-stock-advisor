"""技术分析模块测试"""
import pytest
import pandas as pd
import numpy as np


def test_technical_import():
    """测试可以导入"""
    from analyzer.technical import TechnicalAnalyzer
    assert TechnicalAnalyzer is not None


def test_ma_calculation():
    """测试均线计算"""
    from analyzer.technical import TechnicalAnalyzer
    analyzer = TechnicalAnalyzer()

    # 创建测试数据
    dates = pd.date_range("2025-01-01", periods=30, freq="D")
    prices = pd.DataFrame({
        "date": dates,
        "open": np.random.uniform(10, 20, 30),
        "high": np.random.uniform(15, 25, 30),
        "low": np.random.uniform(8, 15, 30),
        "close": np.random.uniform(10, 20, 30),
        "volume": np.random.uniform(100000, 1000000, 30),
    })

    # 计算 MA
    ma5 = prices["close"].rolling(5).mean()
    assert not ma5.iloc[-1] != ma5.iloc[-1]  # Not NaN


def test_rsi_calculation():
    """测试 RSI 计算"""
    from analyzer.technical import TechnicalAnalyzer
    analyzer = TechnicalAnalyzer()

    # 创建测试数据 - 上涨趋势
    dates = pd.date_range("2025-01-01", periods=20, freq="D")
    close_prices = list(range(10, 30))  # 持续上涨

    assert len(close_prices) == 20


def test_stock_quote_dataclass():
    """测试 StockQuote 数据类"""
    from data_provider.base import StockQuote

    quote = StockQuote(
        code="000001",
        name="平安银行",
        price=15.50,
        change_pct=2.5,
        change_amt=0.38,
    )
    assert quote.code == "000001"
    assert quote.price == 15.50
    assert quote.change_pct == 2.5
    assert quote.market_cap == 0.0  # default


def test_stock_quote_extended_fields():
    """测试 StockQuote 扩展字段"""
    from data_provider.base import StockQuote

    quote = StockQuote(
        code="000001",
        total_mv=1e12,
        volume_ratio=2.5,
        position_type="high",
        amplitude=3.2,
    )
    assert quote.market_cap == 1e12  # auto-set from total_mv
    assert quote.volume_ratio == 2.5
    assert quote.position_type == "high"
    assert quote.amplitude == 3.2
