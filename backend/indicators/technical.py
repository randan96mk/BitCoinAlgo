import numpy as np
import pandas as pd


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).where((high - prev_high) > (prev_low - low), 0.0)
    plus_dm = plus_dm.where(plus_dm > 0, 0.0)

    minus_dm = (prev_low - low).where((prev_low - low) > (high - prev_high), 0.0)
    minus_dm = minus_dm.where(minus_dm > 0, 0.0)

    atr_val = atr(high, low, close, length)

    plus_di = 100 * (plus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr_val)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr_val)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.inf)) * 100
    return dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
