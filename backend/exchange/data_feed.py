"""
Free market data feed using direct REST API calls via httpx.
No ccxt — avoids C extension segfaults on Python 3.14.
"""
import asyncio
import logging
from typing import Optional

import httpx
import pandas as pd

from backend.config import Config

logger = logging.getLogger("exchange")

EXCHANGE_APIS = {
    "binance": {
        "base": "https://api.binance.com",
        "klines": "/api/v3/klines",
        "ticker": "/api/v3/ticker/price",
        "symbol_fmt": lambda s: s.replace("/", ""),
    },
    "bybit": {
        "base": "https://api.bybit.com",
        "klines": "/v5/market/kline",
        "ticker": "/v5/market/tickers",
        "symbol_fmt": lambda s: s.replace("/", ""),
    },
}

TIMEFRAME_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
    "240": "4h",
}

BYBIT_TF_MAP = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15",
    "30m": "30", "1h": "60", "4h": "240", "1d": "D",
}


class DataFeed:
    def __init__(self, config: Optional[Config] = None):
        cfg = config or Config()
        self.exchange_name = cfg.get("exchange.name", "binance")
        self.symbol = cfg.get("exchange.symbol", "BTC/USDT")
        self.timeframe = cfg.get("strategy.timeframe", "3m")
        self.htf_timeframe = cfg.get("strategy.htf_timeframe", "240")
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._api_config = None

    async def connect(self) -> bool:
        exchanges_to_try = [self.exchange_name] + [
            e for e in EXCHANGE_APIS if e != self.exchange_name
        ]
        for name in exchanges_to_try:
            if name not in EXCHANGE_APIS:
                continue
            try:
                api = EXCHANGE_APIS[name]
                client = httpx.AsyncClient(base_url=api["base"], timeout=15)
                resp = await client.get(api["ticker"], params={
                    "symbol": api["symbol_fmt"](self.symbol)
                } if name == "binance" else {
                    "category": "linear", "symbol": api["symbol_fmt"](self.symbol)
                })
                resp.raise_for_status()
                self._client = client
                self._api_config = api
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
        if not self._connected or not self._client:
            raise ConnectionError("Not connected to any exchange")

        tf = TIMEFRAME_MAP.get(timeframe or self.timeframe, timeframe or self.timeframe)
        symbol = self._api_config["symbol_fmt"](self.symbol)

        if self.exchange_name == "binance":
            resp = await self._client.get(self._api_config["klines"], params={
                "symbol": symbol, "interval": tf, "limit": limit
            })
            resp.raise_for_status()
            raw = resp.json()
            rows = []
            for r in raw:
                rows.append({
                    "timestamp": int(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                })
            df = pd.DataFrame(rows)

        elif self.exchange_name == "bybit":
            bybit_tf = BYBIT_TF_MAP.get(tf, "3")
            resp = await self._client.get(self._api_config["klines"], params={
                "category": "linear", "symbol": symbol,
                "interval": bybit_tf, "limit": limit
            })
            resp.raise_for_status()
            raw = resp.json()["result"]["list"]
            rows = []
            for r in raw:
                rows.append({
                    "timestamp": int(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                })
            df = pd.DataFrame(rows)
            df = df.iloc[::-1].reset_index(drop=True)

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def fetch_htf_candles(self, limit: int = 200) -> pd.DataFrame:
        return await self.fetch_candles(self.htf_timeframe, limit)

    async def get_current_price(self) -> float:
        if not self._connected or not self._client:
            raise ConnectionError("Not connected")
        symbol = self._api_config["symbol_fmt"](self.symbol)

        if self.exchange_name == "binance":
            resp = await self._client.get(self._api_config["ticker"], params={"symbol": symbol})
            resp.raise_for_status()
            return float(resp.json()["price"])
        elif self.exchange_name == "bybit":
            resp = await self._client.get(self._api_config["ticker"], params={
                "category": "linear", "symbol": symbol
            })
            resp.raise_for_status()
            return float(resp.json()["result"]["list"][0]["lastPrice"])
        return 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self):
        if self._client:
            await self._client.aclose()
        self._connected = False
