"""
数据持久化模块
使用 SQLite 存储历史数据和分析结果
"""

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from config import Config

Base = declarative_base()


class StockDaily(Base):
    """日线K线数据"""
    __tablename__ = "stock_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    date = Column(DateTime, index=True, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    amount = Column(Float)
    turnover_rate = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now)


class AnalysisRecord(Base):
    """分析结果记录"""
    __tablename__ = "analysis_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    name = Column(String(20))
    analysis_date = Column(DateTime, default=datetime.now, index=True)

    # 行情快照
    price = Column(Float)
    change_pct = Column(Float)

    # 技术指标
    trend_status = Column(String(20))
    macd_status = Column(String(20))
    rsi_status = Column(String(20))
    rsi6 = Column(Float)
    rsi12 = Column(Float)
    rsi24 = Column(Float)

    # 均线
    ma5 = Column(Float)
    ma10 = Column(Float)
    ma20 = Column(Float)
    ma60 = Column(Float)

    # 评分
    buy_score = Column(Integer)
    operation = Column(String(20))
    operation_reason = Column(Text)

    # AI分析 (JSON)
    ai_summary = Column(Text)
    ai_entry_price = Column(Float)
    ai_stop_loss = Column(Float)
    ai_target_price = Column(Float)
    ai_risk_level = Column(String(10))

    # 完整数据
    full_result = Column(JSON)

    created_at = Column(DateTime, default=datetime.now)


class WatchListItem(Base):
    """自选股"""
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(20))
    added_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, default="")


class Position(Base):
    """持仓记录"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    name = Column(String(20))
    shares = Column(Float, nullable=False)        # 持股数量
    avg_cost = Column(Float, nullable=False)       # 平均成本
    current_price = Column(Float, default=0)      # 当前价
    market_value = Column(Float, default=0)       # 市值
    floating_pnl = Column(Float, default=0)       # 浮动盈亏
    floating_pnl_pct = Column(Float, default=0)  # 浮动盈亏比例 %
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    opened_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, default="")


class Trade(Base):
    """交易记录"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True, nullable=False)
    name = Column(String(20))
    trade_type = Column(String(10), nullable=False)   # buy / sell
    shares = Column(Float, nullable=False)            # 成交数量
    price = Column(Float, nullable=False)           # 成交价格
    amount = Column(Float, nullable=False)           # 成交金额
    commission = Column(Float, default=0)             # 手续费
    trade_date = Column(DateTime, default=datetime.now, index=True)
    strategy = Column(String(50), default="")        # 策略来源
    signal_price = Column(Float, default=0)         # 信号时价格
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


class Database:
    """数据库管理"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            config = Config.get()
            db_path = str(config.DATA_DIR / "a_stock_advisor.db")

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def get_session(self):
        return self.Session()

    def save_analysis(self, result_dict: dict):
        """保存分析结果"""
        session = self.get_session()
        try:
            record = AnalysisRecord(
                code=result_dict.get("code", ""),
                name=result_dict.get("name", ""),
                price=result_dict.get("current_price", 0),
                change_pct=result_dict.get("change_pct", 0),
                trend_status=result_dict.get("trend_status", ""),
                macd_status=result_dict.get("macd_status", ""),
                rsi_status=result_dict.get("rsi_status", ""),
                rsi6=result_dict.get("rsi6", 0),
                rsi12=result_dict.get("rsi12", 0),
                rsi24=result_dict.get("rsi24", 0),
                ma5=result_dict.get("ma5", 0),
                ma10=result_dict.get("ma10", 0),
                ma60=result_dict.get("ma60", 0),
                buy_score=result_dict.get("buy_score", 50),
                operation=result_dict.get("operation", ""),
                operation_reason=result_dict.get("operation_reason", ""),
                full_result=result_dict,
            )
            session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_recent_analyses(self, code: str, limit: int = 10) -> List[AnalysisRecord]:
        """获取最近的分析记录"""
        session = self.get_session()
        try:
            return session.query(AnalysisRecord).filter(
                AnalysisRecord.code == code
            ).order_by(
                AnalysisRecord.analysis_date.desc()
            ).limit(limit).all()
        finally:
            session.close()

    def save_daily_data(self, code: str, df):
        """保存日线数据"""
        import pandas as pd
        session = self.get_session()
        try:
            for _, row in df.iterrows():
                existing = session.query(StockDaily).filter(
                    StockDaily.code == code,
                    StockDaily.date == pd.to_datetime(row.get("date")),
                ).first()

                if existing:
                    existing.open = row.get("open", 0)
                    existing.high = row.get("high", 0)
                    existing.low = row.get("low", 0)
                    existing.close = row.get("close", 0)
                    existing.volume = row.get("volume", 0)
                    existing.amount = row.get("amount", 0)
                else:
                    record = StockDaily(
                        code=code,
                        date=pd.to_datetime(row.get("date")),
                        open=row.get("open", 0),
                        high=row.get("high", 0),
                        low=row.get("low", 0),
                        close=row.get("close", 0),
                        volume=row.get("volume", 0),
                        amount=row.get("amount", 0),
                    )
                    session.add(record)

            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_position(self, code: str, name: str, shares: float, avg_cost: float, notes: str = ""):
        """保存或更新持仓"""
        session = self.get_session()
        try:
            existing = session.query(Position).filter(Position.code == code).first()
            if existing:
                existing.shares = shares
                existing.avg_cost = avg_cost
                existing.updated_at = datetime.now()
                existing.notes = notes
            else:
                pos = Position(code=code, name=name, shares=shares, avg_cost=avg_cost, notes=notes)
                session.add(pos)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_positions(self) -> List:
        """获取所有持仓"""
        session = self.get_session()
        try:
            return session.query(Position).all()
        finally:
            session.close()

    def update_position_price(self, code: str, current_price: float):
        """更新持仓当前价格和盈亏"""
        session = self.get_session()
        try:
            pos = session.query(Position).filter(Position.code == code).first()
            if pos:
                pos.current_price = current_price
                pos.market_value = pos.shares * current_price
                pos.floating_pnl = (current_price - pos.avg_cost) * pos.shares
                pos.floating_pnl_pct = (current_price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost > 0 else 0
                pos.updated_at = datetime.now()
                session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def remove_position(self, code: str):
        """清仓（删除持仓）"""
        session = self.get_session()
        try:
            pos = session.query(Position).filter(Position.code == code).first()
            if pos:
                session.delete(pos)
                session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_trade(self, code: str, name: str, trade_type: str, shares: float,
                   price: float, amount: float, commission: float = 0,
                   strategy: str = "", signal_price: float = 0, notes: str = ""):
        """保存交易记录"""
        session = self.get_session()
        try:
            trade = Trade(
                code=code, name=name, trade_type=trade_type,
                shares=shares, price=price, amount=amount,
                commission=commission, strategy=strategy,
                signal_price=signal_price, notes=notes,
            )
            session.add(trade)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_trades(self, code: Optional[str] = None, limit: int = 50) -> List:
        """获取交易记录"""
        session = self.get_session()
        try:
            q = session.query(Trade)
            if code:
                q = q.filter(Trade.code == code)
            return q.order_by(Trade.trade_date.desc()).limit(limit).all()
        finally:
            session.close()
