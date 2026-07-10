"""
API routes for the trading platform.
"""
from datetime import datetime, timedelta
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
        "timestamp": s.timestamp.isoformat() if s.timestamp else None,
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
