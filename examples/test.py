"""
Hawk Auto-Tune: Autonomous Trading Strategy Development Agent
=============================================================
Mean-reversion strategy for TOYOTA daily data (range regime).
Iteratively optimizes parameters via backtest feedback loop.
"""

import time
import requests
import numpy as np
from hawk_bt import Strategy, Context, HawkEngine, configure_logging

# ── Configuration ──
API_BASE = "https://app.hawk-backtester.com/v1"
API_KEY = "hawk_5e364c4d69f34e8aa663f63b9eeca0817f4dc7459b4542f0025f8851e2ddbe73"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
DATASET_ID = 1
WS_HOST = "127.0.0.1"
WS_PORT = 8787
MAX_ITERATIONS = 8

# ── Target Thresholds ──
TARGET_RETURN_OVER_MAX_DD = 2.0
TARGET_WIN_RATE = 0.52
TARGET_TOTAL_RETURN = 0.10

configure_logging(2)


# ── Strategy Definition ──
class MeanReversionStrategy(Strategy):
    """Bollinger Band mean-reversion with RSI filter and ATR-based exits."""

    def __init__(self, bb_period=20, bb_k=2.0, rsi_period=14,
                 rsi_oversold=30, rsi_overbought=70,
                 atr_period=14, tp_atr_mult=2.0, sl_atr_mult=1.0,
                 units=1, cooldown=3):
        self.bb_period = bb_period
        self.bb_k = bb_k
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.tp_atr_mult = tp_atr_mult
        self.sl_atr_mult = sl_atr_mult
        self.units = units
        self.cooldown = cooldown

    def _rsi(self, closes):
        n = self.rsi_period
        if len(closes) < n + 1:
            return None
        deltas = np.diff(closes[-(n + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = gains.mean()
        avg_loss = losses.mean()
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr(self, highs, lows, closes, i):
        n = self.atr_period
        if i < n + 1:
            return None
        trs = []
        for j in range(i - n, i):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - closes[j - 1]),
                abs(lows[j] - closes[j - 1]),
            )
            trs.append(tr)
        return np.mean(trs)

    async def step(self, ctx: Context):
        i = ctx.state.snapshot.step
        c = ctx.state.candles
        warmup = max(self.bb_period, self.rsi_period + 1, self.atr_period + 1)

        if i < warmup:
            return

        closes = c.close[:i + 1]
        price = ctx.state.snapshot.price

        # Bollinger Bands
        window = closes[-self.bb_period:]
        sma = window.mean()
        std = window.std()
        if std == 0:
            return
        upper = sma + self.bb_k * std
        lower = sma - self.bb_k * std
        # RSI
        rsi = self._rsi(closes)
        if rsi is None:
            return

        # ATR for dynamic TP/SL
        atr = self._atr(c.high, c.low, closes, i)
        if atr is None or atr == 0:
            return

        tp = atr * self.tp_atr_mult
        sl = atr * self.sl_atr_mult

        # Cooldown check
        ctx.user.setdefault("last_trade_step", -self.cooldown - 1)
        if i - ctx.user["last_trade_step"] < self.cooldown:
            return

        tickets = ctx.state.snapshot.tickets_num

        # Mean-reversion: buy at lower band + oversold RSI
        if price <= lower and rsi < self.rsi_oversold and tickets == 0:
            await ctx.engine.place_ticket(
                side="buy", units=self.units,
                take_profit=tp, stop_loss=sl,
            )
            ctx.user["last_trade_step"] = i

        # Mean-reversion: sell at upper band + overbought RSI
        elif price >= upper and rsi > self.rsi_overbought and tickets == 0:
            await ctx.engine.place_ticket(
                side="sell", units=self.units,
                take_profit=tp, stop_loss=sl,
            )
            ctx.user["last_trade_step"] = i


# ── Parameter Tuning Logic ──
PARAM_SETS = [
    # Iteration 0: baseline
    dict(bb_period=20, bb_k=2.0, rsi_period=14, rsi_oversold=30,
         rsi_overbought=70, atr_period=14, tp_atr_mult=2.0, sl_atr_mult=1.0,
         units=1, cooldown=3),
    # Iteration 1: wider bands, relaxed RSI
    dict(bb_period=20, bb_k=2.5, rsi_period=14, rsi_oversold=35,
         rsi_overbought=65, atr_period=14, tp_atr_mult=2.5, sl_atr_mult=1.0,
         units=1, cooldown=3),
    # Iteration 2: shorter lookback, tighter entry
    dict(bb_period=14, bb_k=2.0, rsi_period=10, rsi_oversold=25,
         rsi_overbought=75, atr_period=10, tp_atr_mult=2.0, sl_atr_mult=0.8,
         units=1, cooldown=2),
    # Iteration 3: longer lookback, bigger TP
    dict(bb_period=30, bb_k=2.0, rsi_period=14, rsi_oversold=30,
         rsi_overbought=70, atr_period=20, tp_atr_mult=3.0, sl_atr_mult=1.0,
         units=1, cooldown=5),
    # Iteration 4: aggressive entry, tight SL
    dict(bb_period=20, bb_k=1.5, rsi_period=14, rsi_oversold=40,
         rsi_overbought=60, atr_period=14, tp_atr_mult=2.0, sl_atr_mult=0.5,
         units=1, cooldown=2),
    # Iteration 5: wide bands + long RSI
    dict(bb_period=25, bb_k=2.5, rsi_period=21, rsi_oversold=28,
         rsi_overbought=72, atr_period=14, tp_atr_mult=2.5, sl_atr_mult=1.2,
         units=1, cooldown=4),
    # Iteration 6: short fast
    dict(bb_period=10, bb_k=2.0, rsi_period=7, rsi_oversold=25,
         rsi_overbought=75, atr_period=7, tp_atr_mult=1.5, sl_atr_mult=0.8,
         units=1, cooldown=1),
    # Iteration 7: balanced
    dict(bb_period=20, bb_k=2.2, rsi_period=14, rsi_oversold=32,
         rsi_overbought=68, atr_period=14, tp_atr_mult=2.2, sl_atr_mult=0.9,
         units=1, cooldown=3),
]


def adapt_params(iteration, prev_results, prev_params):
    """Dynamically adjust parameters based on previous backtest results.
    Falls back to PARAM_SETS if within range, otherwise generates new params."""
    if iteration < len(PARAM_SETS) and prev_results is None:
        return PARAM_SETS[iteration]

    if prev_results is None:
        return PARAM_SETS[min(iteration, len(PARAM_SETS) - 1)]

    outcome = prev_results.get("outcome", {})
    attribution = prev_results.get("attribution", {})
    action = prev_results.get("action", {})
    p = dict(prev_params)

    total_return = outcome.get("totalReturn", 0)
    max_dd = abs(outcome.get("maxDrawdown", -1))
    win_rate = attribution.get("winRate", 0)
    profit_factor = attribution.get("profitFactor", 0)
    total_orders = action.get("totalOrders", 0)

    note_parts = []

    # Too few trades → relax entry conditions
    if total_orders < 50:
        p["bb_k"] = max(1.2, p["bb_k"] - 0.3)
        p["rsi_oversold"] = min(45, p["rsi_oversold"] + 5)
        p["rsi_overbought"] = max(55, p["rsi_overbought"] - 5)
        p["cooldown"] = max(1, p["cooldown"] - 1)
        note_parts.append("relaxed entries (too few trades)")

    # Too many trades → tighten entry conditions
    elif total_orders > 500:
        p["bb_k"] = min(3.0, p["bb_k"] + 0.2)
        p["rsi_oversold"] = max(20, p["rsi_oversold"] - 3)
        p["rsi_overbought"] = min(80, p["rsi_overbought"] + 3)
        p["cooldown"] = min(10, p["cooldown"] + 1)
        note_parts.append("tightened entries (too many trades)")

    # Poor win rate → widen TP, tighten SL
    if win_rate < 0.45:
        p["tp_atr_mult"] = min(4.0, p["tp_atr_mult"] + 0.3)
        p["sl_atr_mult"] = max(0.3, p["sl_atr_mult"] - 0.2)
        note_parts.append(f"adjusted TP/SL for winRate={win_rate:.2f}")

    # Good win rate but low return → increase TP
    elif win_rate > 0.55 and total_return < TARGET_TOTAL_RETURN:
        p["tp_atr_mult"] = min(4.0, p["tp_atr_mult"] + 0.5)
        note_parts.append("increased TP to capture more profit")

    # High drawdown → tighter SL
    if max_dd > 0.20:
        p["sl_atr_mult"] = max(0.3, p["sl_atr_mult"] - 0.15)
        note_parts.append(f"tightened SL for maxDD={max_dd:.2%}")

    # Low profit factor → adjust bands
    if profit_factor < 1.2 and profit_factor > 0:
        p["bb_period"] = min(40, p["bb_period"] + 3)
        note_parts.append(f"longer BB period for profitFactor={profit_factor:.2f}")

    return p, "; ".join(note_parts) if note_parts else "minor tuning"


# ── Backtest Runner ──
def run_single_backtest(params, iteration, strategy_note):
    """Run one backtest iteration and return analysis results."""

    result_holder = {}

    def on_result(result):
        result_holder["done"] = True
        result_holder["final_balance"] = result.final_balance()
        result_holder["max_drawdown"] = result.max_drawdown()
        result_holder["total_orders"] = result.total_orders

    engine = HawkEngine(
        host=WS_HOST,
        port=WS_PORT,
        on_result=on_result,
        single_run=True,
    )
    strategy = MeanReversionStrategy(**params)

    # Start engine in background thread
    engine_thread = engine.start_background(strategy)
    engine.wait_ready()
    print(f"  [Engine] WS server ready on {WS_HOST}:{WS_PORT}")

    # Register backtest session
    payload = {
        "dataset_id": DATASET_ID,
        "iteration": iteration,
        "strategy_note": strategy_note,
        "ws_url": f"ws://{WS_HOST}:{WS_PORT}",
        "config": {
            "leverage": 0,
            "initial_assets": 10000.0,
        },
    }
    resp = requests.post(f"{API_BASE}/backtests", json=payload, headers=HEADERS)
    resp.raise_for_status()
    session = resp.json()
    session_id = session["session_id"]
    print(f"  [API] Session registered: {session_id} (status: {session.get('status')})")

    # Wait for simulation to complete
    print("  [Engine] Waiting for browser simulation...")
    engine_thread.join(timeout=300)

    if not result_holder.get("done"):
        print("  [WARN] Engine thread did not complete within timeout")
        return session_id, None

    print(f"  [Engine] Done — balance={result_holder['final_balance']:.2f}, "
          f"DD={result_holder['max_drawdown']:.4f}, orders={result_holder['total_orders']}")

    # Fetch detailed analysis from API
    time.sleep(3)  # Brief wait for browser to post analysis
    for attempt in range(10):
        resp = requests.get(f"{API_BASE}/backtests/{session_id}/results", headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("analysis"):
                return session_id, data["analysis"]
        print(f"  [API] Waiting for analysis... (attempt {attempt + 1})")
        time.sleep(5)

    print("  [WARN] Could not retrieve analysis from API")
    return session_id, None


def print_analysis(analysis):
    """Pretty-print key metrics from analysis."""
    o = analysis.get("outcome", {})
    a = analysis.get("attribution", {})
    act = analysis.get("action", {})

    print(f"    totalReturn:     {o.get('totalReturn', 0):>10.4f}  "
          f"({o.get('totalReturn', 0) * 100:.2f}%)")
    print(f"    maxDrawdown:     {o.get('maxDrawdown', 0):>10.4f}")
    print(f"    returnOverMaxDD: {o.get('returnOverMaxDD', 0):>10.4f}")
    print(f"    vsBuyHold:       {o.get('vsBuyHold', 0):>10.4f}")
    print(f"    profitFactor:    {a.get('profitFactor', 0):>10.4f}")
    print(f"    winRate:         {a.get('winRate', 0):>10.4f}  "
          f"(W:{a.get('winCount', 0)} / L:{a.get('lossCount', 0)})")
    print(f"    totalOrders:     {act.get('totalOrders', 0):>10d}")
    print(f"    medianHold:      {act.get('medianHoldingTime', 0):>10.0f} ms")


def meets_targets(analysis):
    """Check if analysis meets target thresholds."""
    if analysis is None:
        return False
    o = analysis.get("outcome", {})
    a = analysis.get("attribution", {})
    return (
        o.get("returnOverMaxDD", 0) >= TARGET_RETURN_OVER_MAX_DD
        and a.get("winRate", 0) >= TARGET_WIN_RATE
        and o.get("totalReturn", 0) >= TARGET_TOTAL_RETURN
    )


def save_result(session_id, iteration, params):
    """Save successful backtest result."""
    payload = {
        "title": f"AutoTune v{iteration} — MeanReversion BB+RSI+ATR",
        "memo": f"Params: {params}",
        "strategy_name": "MeanReversionStrategy",
    }
    resp = requests.post(
        f"{API_BASE}/backtests/{session_id}/save",
        json=payload, headers=HEADERS,
    )
    resp.raise_for_status()
    result_id = resp.json().get("result_id")
    print(f"\n  [SAVED] result_id={result_id}")
    return result_id


# ── Main Loop ──
def main():
    print("=" * 60)
    print("  Hawk Auto-Tune: Mean-Reversion Strategy Optimizer")
    print(f"  Dataset: TOYOTA 1D ({DATASET_ID}), Regime: range")
    print(f"  Targets: returnOverMaxDD≥{TARGET_RETURN_OVER_MAX_DD}, "
          f"winRate≥{TARGET_WIN_RATE}, totalReturn≥{TARGET_TOTAL_RETURN}")
    print("=" * 60)

    best_session_id = None
    best_score = -float("inf")
    best_params = None
    best_analysis = None
    prev_analysis = None
    prev_params = None

    for iteration in range(MAX_ITERATIONS):
        print(f"\n{'─' * 60}")
        print(f"  Iteration {iteration}")
        print(f"{'─' * 60}")

        # Select parameters
        if iteration < len(PARAM_SETS) and prev_analysis is None:
            params = PARAM_SETS[iteration]
            note = f"iter{iteration}: preset params — {params}"
        else:
            result = adapt_params(iteration, prev_analysis, prev_params or PARAM_SETS[0])
            if isinstance(result, tuple):
                params, adapt_note = result
            else:
                params, adapt_note = result, "preset"
            note = f"iter{iteration}: {adapt_note} — {params}"

        print(f"  Params: {params}")
        print(f"  Note: {note}")

        # Run backtest
        session_id, analysis = run_single_backtest(params, iteration, note)

        if analysis is None:
            print("  [SKIP] No analysis returned, continuing...")
            prev_params = params
            continue

        print("\n  Results:")
        print_analysis(analysis)

        # Score: returnOverMaxDD (primary), with winRate bonus
        o = analysis.get("outcome", {})
        a = analysis.get("attribution", {})
        score = o.get("returnOverMaxDD", 0) + a.get("winRate", 0) * 0.5

        if score > best_score:
            best_score = score
            best_session_id = session_id
            best_params = params
            best_analysis = analysis
            print(f"  ★ New best! score={score:.4f}")

        # Check targets
        if meets_targets(analysis):
            print(f"\n  ✓ TARGETS MET at iteration {iteration}!")
            save_result(session_id, iteration, params)
            break

        prev_analysis = analysis
        prev_params = params
    else:
        # Loop exhausted — save best result anyway
        print(f"\n{'─' * 60}")
        print(f"  Max iterations reached. Best score={best_score:.4f}")
        if best_session_id and best_analysis:
            print("  Saving best result...")
            print_analysis(best_analysis)
            save_result(best_session_id, MAX_ITERATIONS - 1, best_params)

    print("\n" + "=" * 60)
    print("  Auto-Tune Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
