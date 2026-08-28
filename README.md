# BitCoinAlgo — BTC Trading Alerts

A **100% free, self-hosted Bitcoin trading-alert platform**. It ports the
*Cardwell Range Analyze [MarkitTick]* Pine Script strategy to Python,
continuously monitors **BTC/USDT** using free exchange APIs, detects entries /
exits / stop-losses / take-profits, and surfaces everything through a live
trading terminal, Telegram alerts, and a searchable signal history.

No paid data feeds, no brokerage keys, no cloud bills — it runs entirely on
your own machine.

> ⚠️ **Alerts only.** This tool does **not** place orders or execute trades. It
> is for signal generation, analysis, and education. Nothing here is financial
> advice.

---

## Features

- 📈 **Live trading terminal** — full-screen candlestick chart (TradingView
  lightweight-charts) with SMA20/SMA50, volume, a synced RSI sub-chart, and
  entry/SL/TP levels drawn directly on the chart.
- 🎯 **Signal detection** — a faithful Python port of the Cardwell RSI Range
  strategy (see [How the Trading Logic Works](#how-the-trading-logic-works)).
- 🔔 **Alerts** — on-screen toast pop-ups with sound for buy/sell/exit events,
  plus optional formatted **Telegram** messages.
- 🛡️ **Trade management** — automatic ATR-based stop-loss and three take-profit
  targets, with open positions monitored every tick.
- 🗄️ **History & analytics** — every signal stored in SQLite; win rate, profit
  factor, drawdown, equity curve, and per-direction stats.
- ⚙️ **Configurable** — timeframe, strategy parameters, exchange, and Telegram
  credentials editable from the Settings page.
- 🚀 **One-command start** — `./start.sh` handles the virtualenv, dependencies,
  and opens the dashboard for you.

---

## Getting Started

### Requirements

- **macOS or Linux**
- **Python 3.10 or newer**

> **macOS note:** the system `python3` is often **3.9**, which is too old.
> Install a newer Python side-by-side (this does **not** touch the system one):
> ```bash
> brew install python@3.12
> ```
> `start.sh` automatically detects and uses the newest available Python
> (`python3.14` → `python3.13` → `python3.12` → …), so you don't need to change
> anything after installing it.

### Quick start (recommended)

```bash
git clone https://github.com/randan96mk/BitCoinAlgo.git
cd BitCoinAlgo
./start.sh
```

`start.sh` will:

1. Find a suitable Python and create a `.venv` (recreating it if an old one is
   found).
2. Install all dependencies from `requirements.txt`.
3. Create the `logs/` and `database/` folders.
4. Start the server and open **http://localhost:8000** in your browser once it
   is ready.

Press **Ctrl+C** to stop.

### Manual start (fallback)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python run.py
```

Then open **http://localhost:8000**.

### Enabling Telegram alerts (optional)

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its **bot
   token**.
2. Get your **chat ID** (e.g. via [@userinfobot](https://t.me/userinfobot)).
3. Open the **Settings** page in the dashboard, paste the token and chat ID,
   tick **Enable Telegram Alerts**, and save.

Until then, alerts still appear on-screen — Telegram is purely additive.

---

## How the Trading Logic Works

The strategy is based on **Andrew Cardwell's RSI Range theory**: RSI does not
just signal overbought/oversold — the *range* it oscillates in tells you the
market regime.

- In an **uptrend**, RSI tends to stay in a **bull range** (default **40–80**),
  bouncing off ~40 as support.
- In a **downtrend**, RSI tends to stay in a **bear range** (default **20–60**),
  rejecting from ~60 as resistance.

The platform combines this with a trend filter and confirmation logic to
decide when a real regime shift has occurred.

### 1. Regime detection

Each closed candle is classified:

| Regime | Condition |
|--------|-----------|
| **Bullish** | price above **SMA(50)** *and* RSI within the bull range (40–80) |
| **Bearish** | price below **SMA(50)** *and* RSI within the bear range (20–60) |
| **Neutral** | anything else |

To avoid whipsaws, a regime must hold for **`confirm_bars`** consecutive
candles (default **2**) before it is considered confirmed.

### 2. Entry signals

A signal fires only on a **fresh transition** into a confirmed regime — not on
every bar that happens to be bullish/bearish. That is, the previous bar's
confirmed regime was *not* bullish and the current one *is* → **BUY** (and the
mirror case for **SELL**).

Two optional filters must also pass:

- **HTF confirmation** (`use_htf`, default on) — the higher-timeframe trend
  (default **4H**) must agree with the signal direction.
- **Chop filter** (`use_adx_filter`, default on) — **ADX ≥ 20** (default), so
  signals are suppressed in low-momentum, choppy conditions.

### 3. Trade levels

When a signal fires, levels are derived from **ATR(14)**:

- **Entry** = previous bar's close (matches the Pine Script's `close[1]`).
- **Stop-loss** = entry ∓ `1.5 × ATR`
- **TP1 / TP2 / TP3** = entry ± `1.0 / 2.0 / 3.0 × ATR`

(∓ / ± flip depending on long vs short.)

### 4. Exit handling

Every open position is checked on each tick against the current price:

- Price hits the **stop-loss** → closed as a loss.
- Price reaches **TP3 / TP2 / TP1** → closed at the highest target reached.

The closed trade's PnL, PnL %, duration, and win/loss result are recorded and
fed into the analytics.

### 5. Signal score

Each signal gets a **confidence score (50–100%)** so you can gauge quality at a
glance:

- Base **50**
- **+15** if the trend aligns with the signal
- **+15** if RSI is inside the expected range
- **+10** if ADX ≥ 25, **+10** more if ADX ≥ 35

### Default parameters

All of these are editable in **Settings** (persisted to `config/user.json`):

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `timeframe` | `3m` | Candle timeframe the engine trades |
| `rsi_length` | `14` | RSI lookback |
| `trend_ma_length` | `50` | SMA length for the trend filter |
| `bull_range_low` / `bull_range_high` | `40` / `80` | RSI bull range |
| `bear_range_low` / `bear_range_high` | `20` / `60` | RSI bear range |
| `confirm_bars` | `2` | Bars a regime must hold before confirming |
| `use_htf` / `htf_timeframe` | `true` / `240` (4H) | Higher-timeframe confirmation |
| `use_adx_filter` / `adx_min_strength` | `true` / `20` | Chop filter |
| `atr_length` | `14` | ATR lookback for trade levels |
| `sl_atr_mult` | `1.5` | Stop-loss distance (× ATR) |
| `tp1/2/3_atr_mult` | `1.0 / 2.0 / 3.0` | Take-profit distances (× ATR) |

The engine replays the full candle history on every evaluation, so regime state
is rebuilt from scratch each cycle — signals stay consistent even across server
restarts.

---

## Project Structure

```
BitCoinAlgo/
├── start.sh                 # One-command launcher
├── run.py                   # Server entry point
├── requirements.txt
├── config/
│   └── default.json         # Default configuration (user.json overrides it)
├── Cardwell Range Analyze [MarkitTick].pine   # Original Pine Script
└── backend/
    ├── main.py              # FastAPI app + page routes
    ├── config.py            # Config loader (default + user merge)
    ├── strategy/
    │   └── cardwell_rsi.py  # The strategy port
    ├── indicators/
    │   └── technical.py     # RSI, SMA, ATR, ADX (Wilder's RMA, Pine-accurate)
    ├── exchange/
    │   └── data_feed.py     # Binance / Bybit REST data feed (httpx)
    ├── services/
    │   └── trading_engine.py  # Continuous strategy loop
    ├── api/
    │   └── routes.py        # /api endpoints (status, signals, chart, analytics)
    ├── database/
    │   └── models.py        # SQLAlchemy models (SQLite)
    ├── telegram/
    │   └── notifier.py      # Telegram message formatting/sending
    └── templates/           # Dashboard, history, analytics, settings pages
```

---

## Data & Accuracy Notes

- Market data comes from the **public Binance API**, with automatic fallback to
  **Bybit** — no API keys required.
- Indicators use **Wilder's RMA smoothing** to match TradingView's `ta.rsi` /
  `ta.atr` / `ta.dmi` outputs as closely as possible.
- If you compare against TradingView, use the **`BINANCE:BTCUSDT`** symbol — the
  generic `CRYPTO:BTCUSD` index aggregates multiple exchanges and will show
  slightly different prices and RSI values.

---

## Disclaimer

This software is provided for **educational and informational purposes only**.
It does not execute trades and is not financial advice. Trading cryptocurrency
carries significant risk. Use at your own risk.
