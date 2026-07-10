"""
Cardwell Range Analyze — Python port of the Pine Script strategy.
Mirrors the exact logic from Cardwell Range Analyze [MarkitTick].pine
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from backend.indicators.technical import rsi, sma, atr, adx
from backend.config import Config


@dataclass
class SignalResult:
    signal_type: Optional[str] = None  # "long" / "short" / None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    rsi_value: float = 0.0
    adx_value: float = 0.0
    atr_value: float = 0.0
    trend_ma_value: float = 0.0
    regime: str = "neutral"
    signal_score: float = 0.0
    timestamp: Optional[datetime] = None


class CardwellRSIStrategy:
    def __init__(self, config: Optional[Config] = None):
        cfg = config or Config()
        self.rsi_len = cfg.get("strategy.rsi_length", 14)
        self.trend_ma_len = cfg.get("strategy.trend_ma_length", 50)
        self.bull_lo = cfg.get("strategy.bull_range_low", 40)
        self.bull_hi = cfg.get("strategy.bull_range_high", 80)
        self.bear_lo = cfg.get("strategy.bear_range_low", 20)
        self.bear_hi = cfg.get("strategy.bear_range_high", 60)
        self.confirm_bars = cfg.get("strategy.confirm_bars", 2)
        self.use_htf = cfg.get("strategy.use_htf", True)
        self.use_adx = cfg.get("strategy.use_adx_filter", True)
        self.adx_len = cfg.get("strategy.adx_length", 14)
        self.adx_min = cfg.get("strategy.adx_min_strength", 20)
        self.atr_len = cfg.get("strategy.atr_length", 14)
        self.sl_mult = cfg.get("strategy.sl_atr_mult", 1.5)
        self.tp1_mult = cfg.get("strategy.tp1_atr_mult", 1.0)
        self.tp2_mult = cfg.get("strategy.tp2_atr_mult", 2.0)
        self.tp3_mult = cfg.get("strategy.tp3_atr_mult", 3.0)
        # Per-bar state — only updated when a NEW bar is seen
        self._bull_confirm_count = 0
        self._bear_confirm_count = 0
        self._prev_regime = 0
        self._last_bar_time = None

    def evaluate(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> SignalResult:
        """
        Evaluate strategy on OHLCV DataFrame.
        df must have columns: open, high, low, close, volume, timestamp
        Returns SignalResult for the latest confirmed bar.

        Pine Script equivalence:
          - df[-1] = current forming bar (unconfirmed)
          - df[-2] = idx = last confirmed bar = Pine's "current bar" at barstate.isconfirmed
          - df[-3] = idx-1 = Pine's [1] reference (close[1] for entry)
        """
        min_bars = max(self.rsi_len, self.trend_ma_len, self.atr_len, self.adx_len) + 5
        if len(df) < min_bars:
            return SignalResult()

        close = df["close"]
        high = df["high"]
        low = df["low"]

        rsi_val = rsi(close, self.rsi_len)
        trend_ma = sma(close, self.trend_ma_len)
        atr_val = atr(high, low, close, self.atr_len)
        adx_val = adx(high, low, close, self.adx_len)

        # idx = last confirmed bar (Pine's "current bar" when barstate.isconfirmed)
        idx = len(df) - 2

        cur_rsi = rsi_val.iloc[idx]
        cur_trend_ma = trend_ma.iloc[idx]
        cur_close = close.iloc[idx]
        cur_atr = atr_val.iloc[idx]
        cur_adx = adx_val.iloc[idx]

        is_uptrend = cur_close > cur_trend_ma
        is_downtrend = cur_close < cur_trend_ma

        in_bull_range = self.bull_lo <= cur_rsi <= self.bull_hi
        in_bear_range = self.bear_lo <= cur_rsi <= self.bear_hi

        bull_regime_raw = is_uptrend and in_bull_range
        bear_regime_raw = is_downtrend and in_bear_range

        # Always return current indicator values
        result = SignalResult(
            rsi_value=round(float(cur_rsi), 2),
            adx_value=round(float(cur_adx), 2),
            atr_value=round(float(cur_atr), 2),
            trend_ma_value=round(float(cur_trend_ma), 2),
            regime="bullish" if bull_regime_raw else ("bearish" if bear_regime_raw else "neutral"),
            timestamp=df["timestamp"].iloc[idx] if "timestamp" in df.columns else None,
        )

        # Only evaluate signal logic on NEW bars (matches Pine's once-per-bar execution)
        bar_time = df["timestamp"].iloc[idx] if "timestamp" in df.columns else idx
        if bar_time == self._last_bar_time:
            return result
        self._last_bar_time = bar_time

        # Confirm counters — increment once per bar (matches Pine: bullConfirmCount := bullRegimeRaw ? bullConfirmCount + 1 : 0)
        if bull_regime_raw:
            self._bull_confirm_count += 1
        else:
            self._bull_confirm_count = 0

        if bear_regime_raw:
            self._bear_confirm_count += 1
        else:
            self._bear_confirm_count = 0

        bull_regime = bull_regime_raw and self._bull_confirm_count >= self.confirm_bars
        bear_regime = bear_regime_raw and self._bear_confirm_count >= self.confirm_bars

        regime_state = 1 if bull_regime else (-1 if bear_regime else 0)

        # Update regime label with confirmed state
        result.regime = "bullish" if bull_regime else ("bearish" if bear_regime else "neutral")

        # HTF confirmation (matches Pine: request.security with [1] lookback)
        htf_bull_ok = True
        htf_bear_ok = True
        if self.use_htf and htf_df is not None and len(htf_df) > self.trend_ma_len + 2:
            htf_close = htf_df["close"]
            htf_ma = sma(htf_close, self.trend_ma_len)
            htf_idx = len(htf_df) - 2
            htf_bull_ok = htf_close.iloc[htf_idx] > htf_ma.iloc[htf_idx]
            htf_bear_ok = htf_close.iloc[htf_idx] < htf_ma.iloc[htf_idx]

        # ADX chop filter (matches Pine: chopOk = not i_useAdx or adxVal >= i_adxMin)
        chop_ok = True
        if self.use_adx:
            chop_ok = cur_adx >= self.adx_min

        # Signal detection — transition into regime (matches Pine: regimeState == 1 and prevRegimeState != 1)
        long_signal = regime_state == 1 and self._prev_regime != 1 and htf_bull_ok and chop_ok
        short_signal = regime_state == -1 and self._prev_regime != -1 and htf_bear_ok and chop_ok

        # Update prev regime AFTER signal check (Pine: prevRegimeState = regimeState[1])
        self._prev_regime = regime_state

        if long_signal:
            # Pine: entryPrice = close[1] — previous bar's close
            entry = close.iloc[idx - 1]
            result.signal_type = "long"
            result.entry_price = entry
            result.stop_loss = entry - cur_atr * self.sl_mult
            result.tp1 = entry + cur_atr * self.tp1_mult
            result.tp2 = entry + cur_atr * self.tp2_mult
            result.tp3 = entry + cur_atr * self.tp3_mult
            result.signal_score = self._calc_score(cur_rsi, cur_adx, is_uptrend, in_bull_range)
        elif short_signal:
            entry = close.iloc[idx - 1]
            result.signal_type = "short"
            result.entry_price = entry
            result.stop_loss = entry + cur_atr * self.sl_mult
            result.tp1 = entry - cur_atr * self.tp1_mult
            result.tp2 = entry - cur_atr * self.tp2_mult
            result.tp3 = entry - cur_atr * self.tp3_mult
            result.signal_score = self._calc_score(cur_rsi, cur_adx, is_downtrend, in_bear_range)

        return result

    def _calc_score(self, rsi_val: float, adx_val: float,
                    trend_aligned: bool, range_ok: bool) -> float:
        score = 50.0
        if trend_aligned:
            score += 15
        if range_ok:
            score += 15
        if adx_val >= 25:
            score += 10
        if adx_val >= 35:
            score += 10
        return min(score, 100.0)

    def check_exit(self, signal: "Signal", current_price: float) -> Optional[str]:
        """Check if an open position should be closed."""
        if signal.direction == "long":
            if current_price <= signal.stop_loss:
                return "stop_loss"
            if signal.take_profit_3 and current_price >= signal.take_profit_3:
                return "take_profit_3"
            if signal.take_profit_2 and current_price >= signal.take_profit_2:
                return "take_profit_2"
            if signal.take_profit_1 and current_price >= signal.take_profit_1:
                return "take_profit_1"
        elif signal.direction == "short":
            if current_price >= signal.stop_loss:
                return "stop_loss"
            if signal.take_profit_3 and current_price <= signal.take_profit_3:
                return "take_profit_3"
            if signal.take_profit_2 and current_price <= signal.take_profit_2:
                return "take_profit_2"
            if signal.take_profit_1 and current_price <= signal.take_profit_1:
                return "take_profit_1"
        return None
