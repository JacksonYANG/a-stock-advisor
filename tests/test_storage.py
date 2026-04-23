"""数据库存储模块测试"""
import pytest
import os
from pathlib import Path


@pytest.fixture
def db():
    """创建测试数据库"""
    from data_provider.storage import Database
    test_db_path = "test_stocks.db"
    db = Database(test_db_path)
    yield db
    # 清理
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


def test_database_creation(db):
    """测试数据库可以创建"""
    assert db is not None


def test_save_and_get_position(db):
    """测试保存和获取持仓"""
    db.save_position("000001", "平安银行", 100, 15.50)
    positions = db.get_positions()
    assert len(positions) >= 1
    pos = positions[0]
    assert pos.code == "000001"
    assert pos.name == "平安银行"
    assert pos.shares == 100
    assert pos.avg_cost == 15.50


def test_remove_position(db):
    """测试删除持仓"""
    db.save_position("000001", "平安银行", 100, 15.50)
    db.remove_position("000001")
    positions = db.get_positions()
    assert all(p.code != "000001" for p in positions)


def test_save_and_get_trade(db):
    """测试保存和获取交易记录"""
    db.save_trade("000001", "平安银行", "买入", 100, 15.50, 1550.0, 5.0, "ma_cross", 15.50)
    trades = db.get_trades(code="000001")
    assert len(trades) >= 1
    trade = trades[0]
    assert trade.code == "000001"
    assert trade.trade_type == "买入"
    assert trade.shares == 100


def test_stock_pool(db):
    """测试股票池"""
    db.save_stock_pool("测试池", "000001", "测试")
    pools = db.get_stock_pools()
    assert "测试池" in pools

    stocks = db.get_pool_stocks("测试池")
    assert len(stocks) >= 1
    assert stocks[0].code == "000001"

    db.remove_pool_stock("测试池", "000001")
    stocks = db.get_pool_stocks("测试池")
    assert len(stocks) == 0


def test_delete_pool(db):
    """测试删除股票池"""
    db.save_stock_pool("删除测试", "000001")
    db.delete_pool("删除测试")
    pools = db.get_stock_pools()
    assert "删除测试" not in pools
