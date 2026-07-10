"""
Main trading engine — runs the strategy loop continuously.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.config import Config
from backend.database.models import Signal, get_session, init_db
from backend.exchange.data_feed import DataFeed
from backend.strategy.cardwell_rsi import CardwellRSIStrategy, SignalResult
from backend.telegram.notifier import TelegramNotifier

logger = logging.getLogger("engine")


def utcnow_naive() -> datetime:
    """Naive UTC datetime — matches how SQLite stores DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt) -> datetime:
    """Normalize any datetime (aware, naive, pandas Timestamp) to naive UTC."""
    if dt is None:
        return utcnow_naive()
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "4h": 14400,
}


class TradingEngine:
    def __init__(self):
        self.config = Config()
        self.strategy = CardwellRSIStrategy(self.config)
        self.feed = DataFeed(self.config)
        self.notifier = TelegramNotifier(self.config)
        self.engine = init_db()
        self._running = False
        self._last_signal_time: Optional[datetime] = None
        self._last_signal: Optional[SignalResult] = None
        self._current_price: float = 0.0
        self._status = "stopped"

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_signal(self) -> Optional[SignalResult]:
        return self._last_signal

    @property
    def current_price(self) -> float:
        return self._current_price

    async def start(self):
        self._running = True
        self._status = "connecting"

        connected = await self.feed.connect()
        if not connected:
            self._status = "disconnected"
            logger.error("Could not connect to any exchange")
            return

        self._status = "running"
        logger.info("Trading engine started")

        tf = self.config.get("strategy.timeframe", "3m")
        interval = TIMEFRAME_SECONDS.get(tf, 180)

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Engine tick error: {e}")
                self._status = "error"
                await asyncio.sleep(5)
                if not self.feed.is_connected:
                    self._status = "reconnecting"
                    await self.feed.connect()
                    if self.feed.is_connected:
                        self._status = "running"
                continue

            # Align next tick to just after the next bar close so signals
            # fire within seconds of the candle completing (like TradingView),
            # not up to a full interval late.
            import time as _time
            now = _time.time()
            sleep_s = interval - (now % interval) + 3
            await asyncio.sleep(sleep_s)

    async def _tick(self):
        df = await self.feed.fetch_candles()
        htf_df = None
        if self.config.get("strategy.use_htf", True):
            try:
                htf_df = await self.feed.fetch_htf_candles()
            except Exception:
                pass

        self._current_price = df["close"].iloc[-1]
        result = self.strategy.evaluate(df, htf_df)

        # Check exits on open positions
        await self._check_exits()

        if result.signal_type:
            if self._is_duplicate(result):
                return
            self._last_signal = result
            self._last_signal_time = datetime.now(timezone.utc)
            await self._record_signal(result)
            await self._send_alert(result)
            logger.info(f"Signal: {result.signal_type} @ {result.entry_price}")

    def _is_duplicate(self, result: SignalResult) -> bool:
        if self._last_signal is None:
            return False
        if (self._last_signal.signal_type == result.signal_type
                and self._last_signal.entry_price == result.entry_price):
            return True
        return False

    async def _record_signal(self, result: SignalResult):
        session = get_session(self.engine)
        try:
            bar_time = to_naive_utc(result.timestamp)
            signal = Signal(
                timestamp=bar_time,
                symbol=self.config.get("exchange.symbol", "BTC/USDT"),
                timeframe=self.config.get("strategy.timeframe", "3m"),
                direction=result.signal_type,
                signal_type="entry",
                entry_price=result.entry_price,
                stop_loss=result.stop_loss,
                take_profit_1=result.tp1,
                take_profit_2=result.tp2,
                take_profit_3=result.tp3,
                rsi_value=result.rsi_value,
                adx_value=result.adx_value,
                atr_value=result.atr_value,
                trend_ma=result.trend_ma_value,
                regime=result.regime,
                signal_score=result.signal_score,
                entry_time=bar_time,
                is_closed=False,
            )
            session.add(signal)
            session.commit()
        finally:
            session.close()

    async def _check_exits(self):
        session = get_session(self.engine)
        try:
            open_signals = session.query(Signal).filter(
                Signal.is_closed == False
            ).all()

            for sig in open_signals:
                exit_reason = self.strategy.check_exit(sig, self._current_price)
                if exit_reason:
                    now = utcnow_naive()
                    sig.exit_price = self._current_price
                    sig.exit_time = now
                    sig.exit_reason = exit_reason
                    sig.is_closed = True

                    if sig.direction == "long":
                        sig.pnl = self._current_price - sig.entry_price
                    else:
                        sig.pnl = sig.entry_price - self._current_price

                    sig.pnl_pct = (sig.pnl / sig.entry_price) * 100 if sig.entry_price else 0
                    sig.is_winner = sig.pnl > 0

                    if sig.entry_time:
                        sig.duration_minutes = int((now - sig.entry_time).total_seconds() / 60)

                    session.commit()

                    msg = self.notifier.format_exit_signal(
                        sig.direction, sig.symbol, sig.entry_price,
                        self._current_price, sig.pnl, sig.pnl_pct, exit_reason
                    )
                    await self.notifier.send_message(msg)
                    logger.info(f"Exit: {sig.direction} {exit_reason} PnL={sig.pnl:.2f}")
        finally:
            session.close()

    async def _send_alert(self, result: SignalResult):
        symbol = self.config.get("exchange.symbol", "BTC/USDT")
        tf = self.config.get("strategy.timeframe", "3m")
        msg = self.notifier.format_entry_signal(
            result.signal_type, symbol, tf,
            result.entry_price, result.stop_loss,
            result.tp1, result.tp2, result.tp3,
            result.signal_score, result.regime,
            result.rsi_value, result.adx_value,
        )
        await self.notifier.send_message(msg)

    async def stop(self):
        self._running = False
        self._status = "stopped"
        await self.feed.close()
        logger.info("Trading engine stopped")
