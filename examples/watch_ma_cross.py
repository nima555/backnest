"""Moving-average cross with tunable parameters.

    pip install -U hawk-bt
    hawk-bt run examples/watch_ma_cross.py

Open https://app.hawk-backtester.com/simulator/graph?source=python, pick a dataset
and click "Connect to Local Strategy". The Param attributes below appear as
sliders; moving one re-runs the backtest, and saving this file re-runs it too,
with a diff against the previous run.
"""

from hawk_bt import Context, Param, Strategy


class MaCross(Strategy):
    fast = Param(10, min=3, max=50, step=1, label="Fast MA")
    slow = Param(50, min=10, max=200, step=5, label="Slow MA")
    take_profit_pct = Param(1.0, min=0.0, max=5.0, step=0.1, label="Take profit %")
    stop_loss_pct = Param(0.5, min=0.0, max=5.0, step=0.1, label="Stop loss %")
    long_only = Param(False, label="Long only")

    async def step(self, ctx: Context) -> None:
        snap = ctx.state.snapshot
        i = int(snap.step or 0)
        candles = ctx.state.candles
        if candles is None or i < self.slow + 2:
            return
        close = candles.close[:i]
        fast, slow = close[-self.fast:].mean(), close[-self.slow:].mean()
        prev_fast, prev_slow = close[-self.fast - 1:-1].mean(), close[-self.slow - 1:-1].mean()
        if prev_fast <= prev_slow and fast > slow:
            side = "buy"
        elif prev_fast >= prev_slow and fast < slow:
            side = "sell"
        else:
            return
        if self.long_only and side == "sell":
            return
        if snap.tickets_num > 0:
            tickets = await ctx.engine.get_ticket_list()
            ids = [int(t[0]) for t in tickets]
            await ctx.engine.close_positions(position_ids=ids, actions=[2] * len(ids), ratios=[1.0] * len(ids))
        price = float(close[-1])
        await ctx.engine.place_ticket(
            side=side,
            units=int(snap.equity / price),
            take_profit=price * self.take_profit_pct / 100 if self.take_profit_pct > 0 else None,
            stop_loss=price * self.stop_loss_pct / 100 if self.stop_loss_pct > 0 else None,
        )
