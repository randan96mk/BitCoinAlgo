"""
Free market data feed using CCXT (Binance → Bybit → Coinbase fallback).
Uses synchronous ccxt in a thread pool to avoid aiohttp segfaults on Python 3.14.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import ccxt
import pandas as pd

from backend.config import Config

logger = logging.getLogger("exchange")

EXCHANGE_PRIORITY = ["binance", "bybit", "coinbase"]

TIMEFRAME_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
    "240": "4h",
}

_pool = ThreadPoolExecutor(max_workers=2)


class DataFeed:
    def __init__(self, config: Optional[Config] = None):
        cfg = config or Config()
        self.exchange_name = cfg.get("exchange.name", "binance")
        self.symbol = cfg.get("exchange.symbol", "BTC/USDT")
        self.timeframe = cfg.get("strategy.timeframe", "3m")
        self.htf_timeframe = cfg.get("strategy.htf_timeframe", "240")
        self._exchange: Optional[ccxt.Exchange] = None
        self._connected = False

    async def connect(self) -> bool:
        exchanges_to_try = [self.exchange_name] + [
            e for e in EXCHANGE_PRIORITY if e != self.exchange_name
        ]
        loop = asyncio.get_event_loop()
        for name in exchanges_to_try:
            try:
                exchange_class = getattr(ccxt, name)
                ex = exchange_class({"enableRateLimit": True})
                await loop.run_in_executor(_pool, ex.load_markets)
                self._exchange = ex
                self._connected = True
                self.exchange_name = name
                logger.info(f"Connected to {name}")
                return True
            except Exception as e:
                logger.warning(f"Failed to connect to {name}: {e}")
        self._connected = False
        return False

    async def fetch_candles(self, timeframe: Optional[str] = None,
                            limit: int = 200) -> pd.DataFrame:
        if not self._connected or not self._exchange:
            raise ConnectionError("Not connected to any exchange")

        tf = TIMEFRAME_MAP.get(timeframe or self.timeframe, timeframe or self.timeframe)
        loop = asyncio.get_event_loop()
        ohlcv = await loop.run_in_executor(
            _pool, lambda: self._exchange.fetch_ohlcv(self.symbol, tf, limit=limit)
        )
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def fetch_htf_candles(self, limit: int = 200) -> pd.DataFrame:
        return await self.fetch_candles(self.htf_timeframe, limit)

    async def get_current_price(self) -> float:
        if not self._connected or not self._exchange:
            raise ConnectionError("Not connected")
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(
            _pool, lambda: self._exchange.fetch_ticker(self.symbol)
        )
        return ticker["last"]

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self):
        self._exchange = None
        self._connected = False
