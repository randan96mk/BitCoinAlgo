from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Boolean, Text,
    create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    timeframe = Column(String(10))
    direction = Column(String(10))  # long / short
    signal_type = Column(String(20))  # entry / exit / stop_loss / take_profit / reversal
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    take_profit_3 = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    is_winner = Column(Boolean, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    entry_time = Column(DateTime, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    rsi_value = Column(Float, nullable=True)
    adx_value = Column(Float, nullable=True)
    atr_value = Column(Float, nullable=True)
    trend_ma = Column(Float, nullable=True)
    regime = Column(String(10), nullable=True)  # bullish / bearish / neutral
    signal_score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    is_closed = Column(Boolean, default=False)
    telegram_sent = Column(Boolean, default=False)


class Candle(Base):
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, index=True)
    symbol = Column(String(20))
    timeframe = Column(String(10))
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class AppLog(Base):
    __tablename__ = "app_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(10))
    category = Column(String(30))
    message = Column(Text)


def get_engine(db_path: str = "database/trading.db"):
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(db_path: str = "database/trading.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
