"""
API routes for the trading platform.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import func, desc

from backend.config import Config
from backend.database.models import Signal, get_session, get_engine

router = APIRouter(prefix="/api")


def _get_db():
    return get_session(get_engine())


@router.get("/status")
async def get_status():
    from backend.main import engine_instance
    return {
        "status": engine_instance.status if engine_instance else "stopped",
        "exchange": Config().get("exchange.name"),
        "symbol": Config().get("exchange.symbol"),
        "timeframe": Config().get("strategy.timeframe"),
        "current_price": engine_instance.current_price if engine_instance else 0,
        "last_signal": _signal_to_dict(engine_instance.last_signal) if engine_instance and engine_instance.last_signal else None,
    }


@router.get("/signals")
async def get_signals(
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    direction: Optional[str] = Query(None),
    is_closed: Optional[bool] = Query(None),
):
    session = _get_db()
    try:
        q = session.query(Signal).order_by(desc(Signal.timestamp))
        if direction:
            q = q.filter(Signal.direction == direction)
        if is_closed is not None:
            q = q.filter(Signal.is_closed == is_closed)
        total = q.count()
        signals = q.offset(offset).limit(limit).all()
        return {"total": total, "signals": [_signal_row(s) for s in signals]}
    finally:
        session.close()


@router.get("/analytics")
async def get_analytics():
    session = _get_db()
    try:
        closed = session.query(Signal).filter(Signal.is_closed == True).all()
        if not closed:
            return _empty_analytics()

        total = len(closed)
        winners = [s for s in closed if s.is_winner]
        losers = [s for s in closed if not s.is_winner]
        profits = [s.pnl for s in closed if s.pnl and s.pnl > 0]
        losses = [s.pnl for s in closed if s.pnl and s.pnl < 0]

        total_profit = sum(profits) if profits else 0
        total_loss = abs(sum(losses)) if losses else 0
        net_profit = total_profit - total_loss

        return {
            "total_signals": total,
            "win_rate": len(winners) / total * 100 if total else 0,
            "loss_rate": len(losers) / total * 100 if total else 0,
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "net_profit": round(net_profit, 2),
            "avg_profit": round(sum(profits) / len(profits), 2) if profits else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown": round(_calc_drawdown(closed), 2),
            "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else 0,
            "avg_duration_min": round(sum(s.duration_minutes or 0 for s in closed) / total, 1),
            "long_trades": len([s for s in closed if s.direction == "long"]),
            "short_trades": len([s for s in closed if s.direction == "short"]),
            "long_win_rate": _win_rate([s for s in closed if s.direction == "long"]),
            "short_win_rate": _win_rate([s for s in closed if s.direction == "short"]),
            "equity_curve": _equity_curve(closed),
            "monthly_pnl": _monthly_pnl(closed),
            "daily_pnl": _daily_pnl(closed),
        }
    finally:
        session.close()


@router.get("/chart/candles")
async def get_chart_candles(timeframe: Optional[str] = Query(None), limit: int = Query(200)):
    from backend.main import engine_instance
    if not engine_instance or not engine_instance.feed.is_connected:
        return {"candles": [], "sma50": [], "sma20": [], "rsi": [], "volumes": []}

    tf = timeframe or Config().get("strategy.timeframe", "3m")
    try:
        df = await engine_instance.feed.fetch_candles(tf, limit)
    except Exception:
        return {"candles": [], "sma50": [], "sma20": [], "rsi": [], "volumes": []}

    from backend.indicators.technical import sma as calc_sma, rsi as calc_rsi

    close = df["close"]
    sma20 = calc_sma(close, 20)
    sma50 = calc_sma(close, 50)
    rsi_vals = calc_rsi(close, 14)

    candles = []
    sma20_data = []
    sma50_data = []
    rsi_data = []
    vol_data = []

    for i, row in df.iterrows():
        t = int(row["timestamp"].timestamp())
        candles.append({"time": t, "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"]})
        vol_data.append({"time": t, "value": row["volume"], "color": "rgba(38,166,154,0.4)" if row["close"] >= row["open"] else "rgba(239,83,80,0.4)"})
        if not _isnan(sma20.iloc[i]):
            sma20_data.append({"time": t, "value": round(sma20.iloc[i], 2)})
        if not _isnan(sma50.iloc[i]):
            sma50_data.append({"time": t, "value": round(sma50.iloc[i], 2)})
        if not _isnan(rsi_vals.iloc[i]):
            rsi_data.append({"time": t, "value": round(rsi_vals.iloc[i], 2)})

    # Candle timestamps for snapping markers onto real bars
    candle_times = [c["time"] for c in candles]
    tf_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}.get(tf, 180)

    def snap_to_candle(epoch: int) -> Optional[int]:
        """Snap a timestamp to the candle bar that contains it.
        Returns None if the signal is outside the loaded candle window."""
        if not candle_times:
            return None
        if epoch < candle_times[0] or epoch > candle_times[-1] + tf_seconds:
            return None
        best = min(candle_times, key=lambda ct: abs(ct - epoch))
        return best

    session = _get_db()
    try:
        signals = session.query(Signal).order_by(desc(Signal.timestamp)).limit(50).all()
        markers = []
        for s in signals:
            if s.entry_time:
                t = snap_to_candle(_epoch_utc(s.entry_time))
                if t is not None:
                    if s.direction == "long":
                        markers.append({"time": t, "position": "belowBar", "color": "#2196f3", "shape": "arrowUp", "text": f"BUY {s.entry_price:.0f}"})
                    else:
                        markers.append({"time": t, "position": "aboveBar", "color": "#ff9800", "shape": "arrowDown", "text": f"SELL {s.entry_price:.0f}"})
            if s.exit_time and s.is_closed:
                t = snap_to_candle(_epoch_utc(s.exit_time))
                if t is not None:
                    color = "#26a69a" if s.is_winner else "#ef5350"
                    markers.append({"time": t, "position": "belowBar" if s.direction == "short" else "aboveBar", "color": color, "shape": "circle", "text": f"EXIT {s.exit_price:.0f}"})

        trade_levels = []
        open_trades = session.query(Signal).filter(Signal.is_closed == False).all()
        for s in open_trades:
            trade_levels.append({
                "entry": s.entry_price, "sl": s.stop_loss,
                "tp1": s.take_profit_1, "tp2": s.take_profit_2, "tp3": s.take_profit_3,
                "direction": s.direction,
            })
    finally:
        session.close()

    return {
        "candles": candles, "sma20": sma20_data, "sma50": sma50_data,
        "rsi": rsi_data, "volumes": vol_data,
        "markers": sorted(markers, key=lambda x: x["time"]),
        "trade_levels": trade_levels,
    }


def _isnan(v) -> bool:
    try:
        import math
        return math.isnan(v)
    except (TypeError, ValueError):
        return True


def _epoch_utc(dt: datetime) -> int:
    """Convert a DB datetime (stored as naive UTC) to a UTC epoch.
    Plain .timestamp() would wrongly interpret naive datetimes as local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """ISO string with explicit UTC offset so JS Date() parses it correctly."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/config")
async def get_config():
    return Config().all()


@router.post("/config")
async def update_config(data: dict):
    cfg = Config()
    for key, val in data.items():
        cfg.set(key, val)
    return {"status": "ok"}


def _signal_to_dict(sig) -> dict:
    if not sig:
        return {}
    return {
        "type": sig.signal_type,
        "entry": sig.entry_price,
        "sl": sig.stop_loss,
        "tp1": sig.tp1,
        "tp2": sig.tp2,
        "tp3": sig.tp3,
        "score": sig.signal_score,
        "regime": sig.regime,
    }


def _signal_row(s: Signal) -> dict:
    return {
        "id": s.id,
        "timestamp": _iso_utc(s.timestamp),
        "direction": s.direction,
        "signal_type": s.signal_type,
        "entry_price": s.entry_price,
        "exit_price": s.exit_price,
        "stop_loss": s.stop_loss,
        "tp1": s.take_profit_1,
        "tp2": s.take_profit_2,
        "tp3": s.take_profit_3,
        "pnl": s.pnl,
        "pnl_pct": s.pnl_pct,
        "is_winner": s.is_winner,
        "exit_reason": s.exit_reason,
        "duration_min": s.duration_minutes,
        "regime": s.regime,
        "score": s.signal_score,
        "is_closed": s.is_closed,
    }


def _calc_drawdown(signals) -> float:
    equity = 0
    peak = 0
    max_dd = 0
    for s in sorted(signals, key=lambda x: x.exit_time or x.timestamp):
        equity += s.pnl or 0
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _win_rate(signals) -> float:
    if not signals:
        return 0
    return len([s for s in signals if s.is_winner]) / len(signals) * 100


def _equity_curve(signals) -> list:
    equity = 0
    curve = []
    for s in sorted(signals, key=lambda x: x.exit_time or x.timestamp):
        equity += s.pnl or 0
        curve.append({
            "time": (s.exit_time or s.timestamp).isoformat(),
            "equity": round(equity, 2),
        })
    return curve


def _monthly_pnl(signals) -> list:
    months = {}
    for s in signals:
        key = (s.exit_time or s.timestamp).strftime("%Y-%m")
        months[key] = months.get(key, 0) + (s.pnl or 0)
    return [{"month": k, "pnl": round(v, 2)} for k, v in sorted(months.items())]


def _daily_pnl(signals) -> list:
    days = {}
    for s in signals:
        key = (s.exit_time or s.timestamp).strftime("%Y-%m-%d")
        days[key] = days.get(key, 0) + (s.pnl or 0)
    return [{"day": k, "pnl": round(v, 2)} for k, v in sorted(days.items())[-30:]]


def _empty_analytics() -> dict:
    return {
        "total_signals": 0, "win_rate": 0, "loss_rate": 0,
        "total_profit": 0, "total_loss": 0, "net_profit": 0,
        "avg_profit": 0, "avg_loss": 0, "max_drawdown": 0,
        "profit_factor": 0, "avg_duration_min": 0,
        "long_trades": 0, "short_trades": 0,
        "long_win_rate": 0, "short_win_rate": 0,
        "equity_curve": [], "monthly_pnl": [], "daily_pnl": [],
    }
