# hawk-bt — Python Client for Backnest

> **Renaming to `backnest` is planned.** The PyPI package name will change from `hawk-bt` to `backnest` in a future release.

Python client library for [Backnest](https://app.hawk-backtester.com) — agent-native backtesting infrastructure.

Your AI agent (or you) writes a Python strategy locally, connects to the Backnest WASM simulator in the browser via WebSocket, and receives structured, ticket-level analysis results. Strategy code never leaves your machine.

## How it works

```
Your AI Agent / You
    ↕  generates & iterates strategy
hawk-bt (Python, runs locally)
    ↕  WebSocket (binary RPC)
Backnest (browser WASM simulator)
    ↕  structured JSON results
Agent analyzes → next iteration
```

- **Backnest**: Browser-based WASM trading simulator with ticket-level analysis
- **hawk-bt**: Python client for strategy execution and engine communication
- **py_engine_rust** (Rust extension): WebSocket transport and binary codec (required)

## Requirements

- Python >= 3.10
- `hawk-bt-rust-engine` (Rust extension, **required**)
- `numpy >= 1.23`

```bash
pip install hawk-bt
```

## Quick Start

### For AI agents

1. Create a [Backnest account](https://app.hawk-backtester.com/accounts/signup/) (Trial is free)
2. Generate an Agent API key from Settings
3. Hand your agent the [Agent API docs](https://app.hawk-backtester.com/agent-manual/) — it can drive the full workflow autonomously

The agent receives structured JSON with ticket-level MFE/MAE, exit reasons, exposure time series, cost attribution, and more.

### For manual use

```python
import asyncio
from hawk_bt.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from hawk_bt.runtime.loop import run_attached
from hawk_bt.strategy.api import Strategy, Context

class MyStrategy(Strategy):
    async def step(self, ctx: Context) -> None:
        s = ctx.state.statics
        price = s.current_rate

        if price > 100.0 and s.tickets_num == 0:
            await ctx.engine.place_ticket(
                side="buy", units=10,
                sub_limit_pips=5.0, stop_order_pips=3.0,
            )

async def main():
    engine = RustEngineAsyncAdapter(host="127.0.0.1", port=8787)
    await engine.start()
    await engine.wait_connected(timeout=None)

    result = await run_attached(engine, MyStrategy(), gate_policy="eager")
    print(f"Steps: {result.steps}, Final assets: {result.final_assets()}")

asyncio.run(main())
```

## What your agent gets back

A single Backnest API response returns structured JSON with:

- Ticket-level MFE / MAE
- Exit reason per trade
- Long / Short PnL breakdown
- Cost attribution (spread, commission)
- Exposure time series
- Equity curve & drawdown
- Holding period distribution
- Order frequency & regime hints

See [Analysis Results](https://app.hawk-backtester.com/analysis/) for the full schema.

## Strategy API

### Writing a strategy

Subclass `Strategy` and implement `step()`. Called on every simulation step.

```python
class Strategy(ABC):
    @abstractmethod
    async def step(self, ctx: Context) -> None: ...
```

Available via `ctx`:
- `ctx.state.statics` — Current assets, price, and position info
- `ctx.engine` — Engine operations (trade, query)
- `ctx.state.done` — Simulation completion flag
- `ctx.user` — Free-use `dict` for state persistence

### Trade operations

#### Market entry

```python
out = await ctx.engine.place_ticket(
    side="buy",           # "buy" | "sell"
    units=100,            # lot size
    sub_limit_pips=5.0,   # TP (absolute price difference, optional)
    stop_order_pips=3.0,  # SL (absolute price difference, optional)
    trail_pips=2.0,       # trailing stop (optional)
)
```

#### Pending order

```python
out = await ctx.engine.place_token(
    side="sell",
    order="limit",        # "limit" | "stop"
    price=90.0,
    units=80,
    sub_limit_pips=8.0,
    stop_order_pips=25.0,
    trail_pips=None,
    time_limits=240.0,    # expiry in steps (optional)
)
```

#### Close position

```python
events = await ctx.engine.close_step(
    flags=[ticket_flag],  # ticket ID(s)
    actions=[1],          # 1=full close, 2=partial (REDUCE)
    ratios=[0.0],         # ratio for action=2 (0.0–1.0)
)
```

### Market data

```python
statics = await ctx.engine.get_statics()
statics.assets           # account balance
statics.virtual_assets   # balance including unrealized P&L
statics.current_rate     # current price
statics.current_step     # current step
statics.total_steps      # total steps
statics.margin_ratio     # margin ratio
statics.tickets_num      # open ticket count
statics.token_num        # pending order count

tickets = await ctx.engine.get_ticket_list()
```

### Running simulations

#### Attached mode (browser-driven)

```python
result = await run_attached(engine, strategy, gate_policy="eager")
```

#### Backtest mode (Python-driven)

```python
result = await run_backtest(engine, strategy, ohlc5, steps=5000)
```

`ohlc5`: `np.ndarray` shape `(N, 5)` — `[time_ms, open, close, high, low]`

#### BacktestResult

```python
result.steps              # steps executed
result.assets             # np.ndarray — asset history
result.virtual_assets     # np.ndarray — including unrealized P&L
result.price              # np.ndarray — price history
result.final_assets()     # final balance
result.max_drawdown()     # max drawdown (negative)
```

## TP/SL behavior

- TP/SL values are **absolute price differences** (not pips or percentages)
- Buy TP hit: `high >= open_rate + sub_limit_pips`
- Buy SL hit: `low <= open_rate - stop_order_pips`
- When both hit on the same bar: **SL takes priority**
- Close price is set to the bar's close (not the exact TP/SL level)

## Gate policy

Controls intra-step state synchronization:

- **`eager`** (default): Syncs after every operation. Accurate but slower.
- **`step_end`**: Syncs only at step end. Faster but intermediate state may be stale.

```python
gate_policy = await engine.get_gate_policy_hint() or "eager"
```

## Documentation

- [Backnest](https://app.hawk-backtester.com) — Main platform
- [Agent API Manual](https://app.hawk-backtester.com/agent-manual/) — AI agent integration
- [hawk-bt Docs](https://app.hawk-backtester.com/py-engine/) — Detailed library reference
- [Analysis Results](https://app.hawk-backtester.com/analysis/) — Result schema
- [Simulation Model](https://app.hawk-backtester.com/simulation-model/) — Engine internals

## License

[MIT](LICENSE)
