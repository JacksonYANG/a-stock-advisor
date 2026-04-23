#!/usr/bin/env python3
"""
交易日志模块
记录每笔交易的理由、情绪、复盘笔记
"""

from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass

from sqlalchemy import Column, String, Text, DateTime, Integer, Float, create_engine
from data_provider.storage import Base, Database


class TradeJournal(Base):
    """交易日志"""
    __tablename__ = "trade_journals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    name = Column(String(50), default="")
    action = Column(String(10), nullable=False)  # 买入/卖出/观望
    price = Column(Float, default=0)
    shares = Column(Integer, default=0)
    # 交易理由
    reason = Column(Text, default="")         # 交易理由
    emotion = Column(String(20), default="")   # 情绪: 自信/犹豫/恐惧/贪婪
    strategy = Column(String(50), default="")  # 使用的策略
    market_view = Column(String(50), default="")  # 当时的市场看法
    # 复盘
    review = Column(Text, default="")           # 复盘笔记
    profit_loss = Column(Float, default=0)       # 实际盈亏
    lesson = Column(Text, default="")            # 经验教训
    # 时间
    created_at = Column(DateTime, default=datetime.now)
    reviewed_at = Column(DateTime, default=None)


def save_journal(db: Database, code: str, action: str, reason: str = "",
                 price: float = 0, shares: int = 0, emotion: str = "",
                 strategy: str = "", market_view: str = ""):
    """保存交易日志"""
    session = db.get_session()
    try:
        journal = TradeJournal(
            code=code.zfill(6),
            action=action,
            reason=reason,
            price=price,
            shares=shares,
            emotion=emotion,
            strategy=strategy,
            market_view=market_view,
        )
        session.add(journal)
        session.commit()
    finally:
        session.close()


def get_journals(db: Database, code: str = "", limit: int = 50) -> List[TradeJournal]:
    """获取交易日志"""
    session = db.get_session()
    try:
        query = session.query(TradeJournal)
        if code:
            query = query.filter(TradeJournal.code == code.zfill(6))
        return query.order_by(TradeJournal.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def add_review(db: Database, journal_id: int, review: str, profit_loss: float = 0, lesson: str = ""):
    """添加复盘"""
    session = db.get_session()
    try:
        journal = session.query(TradeJournal).filter(TradeJournal.id == journal_id).first()
        if journal:
            journal.review = review
            journal.profit_loss = profit_loss
            journal.lesson = lesson
            journal.reviewed_at = datetime.now()
            session.commit()
    finally:
        session.close()
