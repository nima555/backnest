"""backnest -- Python backtesting engine for the Hawk trading simulator."""

from backnest.runtime.engine_api import Snapshot, Engine, EXIT_MARGIN_CALL, EXIT_COMPLETE
from backnest.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from backnest.runtime.loop import run_backtest, run_attached, BacktestResult
from backnest.strategy.api import Strategy, Context, SessionState, EngineProtocol, Candles
from backnest.logging import configure as configure_logging
from backnest.hawk_engine import HawkEngine

__all__ = [
    "HawkEngine",
    "Snapshot",
    "Engine",
    "EngineProtocol",
    "RustEngineAsyncAdapter",
    "run_backtest",
    "run_attached",
    "BacktestResult",
    "Strategy",
    "Context",
    "SessionState",
    "Candles",
    "EXIT_MARGIN_CALL",
    "EXIT_COMPLETE",
    "configure_logging",
]
