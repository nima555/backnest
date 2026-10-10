from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, Protocol, runtime_checkable

import numpy as np

from hawk_bt.runtime.engine_api import Snapshot


@dataclass
class Candles:
    """OHLC candle data for the full simulation period.

    All fields are numpy float64 arrays of length N (number of bars).
    """
    time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @staticmethod
    def from_matrix(m: np.ndarray) -> "Candles":
        """Parse WASM layout: cols = [time, open, close, high, low].

        The WASM engine uses row 0 as the initial ``last_rate`` and starts
        the simulation from row 1.  We drop row 0 so that
        ``candles.close[step] == snapshot.price`` at each step.
        """
        d = m[1:]  # drop the look-back bar consumed by WASM
        return Candles(
            time=d[:, 0],
            open=d[:, 1],
            high=d[:, 3],
            low=d[:, 4],
            close=d[:, 2],
        )


@runtime_checkable
class EngineProtocol(Protocol):
    """Engine interface used by Strategy.

    Implementations must keep ``state.snapshot`` up-to-date at all times.
    """

    async def get_snapshot(self, timeout: float = 10.0) -> Snapshot: ...
    async def step_next(self, timeout: float = 10.0) -> None: ...
    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray: ...
    async def init_candles(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None: ...
    async def refresh(self, timeout: float = 10.0) -> Snapshot: ...
    async def fetch_events(self, timeout: float = 10.0) -> np.ndarray: ...
    async def end_session(self, timeout: float = 10.0) -> np.ndarray: ...


@dataclass
class SessionState:
    """Mutable session state updated by the backtest loop every step.

    Users should read ``snapshot`` for the latest engine state.
    """
    snapshot: Snapshot
    candles: Candles | None = None
    tickets: Any | None = None
    events: np.ndarray | None = None
    done: bool = False
    exit_code: int | None = None


@dataclass
class Context:
    """Context passed to Strategy.step() on every simulation step.

    Attributes:
        engine:  Engine handle for placing orders, querying state, etc.
        state:   Live session state (``state.snapshot`` is the single source of truth).
        user:    Persistent dict for user-defined data (indicators, logs, counters, etc.).
    """
    engine: EngineProtocol
    state: SessionState
    user: Dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    """Base class for user-defined trading strategies.

    Subclass and implement :meth:`step`.  The method is called once per
    simulation bar — read state from ``ctx.state.snapshot`` and issue
    orders via ``ctx.engine``.
    """

    @abstractmethod
    async def step(self, ctx: Context) -> None:
        raise NotImplementedError

    async def on_start(self, ctx: Context) -> None:
        """Called once at the start of every run. Reset per-run state here."""
        return None

    # -- tunable parameters (see hawk_bt.strategy.params.Param) -------------
    @classmethod
    def param_schema(cls) -> list:
        """JSON-able description of the strategy's ``Param`` attributes."""
        from hawk_bt.strategy.params import param_schema

        return param_schema(cls)

    def set_params(self, values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply parameter values (validated and clamped); returns effective values."""
        from hawk_bt.strategy.params import apply_params

        return apply_params(self, values)

    @property
    def strategy_name(self) -> str:
        return type(self).__name__
