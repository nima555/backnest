from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Callable, Optional, Union

from hawk_bt.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from hawk_bt.runtime.loop import run_attached, BacktestResult
from hawk_bt.runtime.browser_rpc import request_rerun, session_hello
from hawk_bt.strategy.api import Strategy

try:  # pragma: no cover - metadata lookup
    from importlib.metadata import version as _pkg_version

    _VERSION = _pkg_version("hawk-bt")
except Exception:  # pragma: no cover
    _VERSION = "dev"

StrategyFactory = Callable[[], Strategy]

logger = logging.getLogger(__name__)


class HawkEngine:
    """High-level entry point for running strategies against the browser engine.

    Manages the full WebSocket lifecycle: connect, wait ready, negotiate
    sync policy, run strategy, report results, wait disconnect, reconnect.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8787,
        *,
        on_result: Optional[Callable[[BacktestResult], None]] = None,
        single_run: bool = False,
        watch: Optional[Union[str, os.PathLike]] = None,
    ):
        """
        Args:
            watch: Path of the strategy source file. When set (and the strategy is
                given as a factory, e.g. via ``hawk-bt run --watch``), saving the file
                reloads the strategy and asks the browser to re-run automatically.
        """
        self._host = host
        self._port = port
        self._on_result = on_result
        self._single_run = single_run
        self._watch = os.fspath(watch) if watch else None

    def start(self, strategy: Union[Strategy, StrategyFactory]) -> None:
        """Run the strategy in a blocking connect-run-disconnect loop.

        Waits for browser connections, runs the strategy, prints results,
        then waits for disconnect before accepting the next connection.

        When ``single_run=True`` (Agent Mode), exits after one simulation
        instead of looping forever.
        """
        asyncio.run(self._run_loop(strategy))

    def start_background(self, strategy: Strategy) -> threading.Thread:
        """Start the engine in a background thread (non-blocking).

        Returns the thread so callers can ``join()`` after submitting
        the backtest session via the API.  The engine will already be
        listening on ``ws://{host}:{port}`` by the time the
        ``ready`` event fires.

        Usage::

            engine = HawkEngine(single_run=True)
            thread = engine.start_background(my_strategy)
            engine.wait_ready()          # blocks until WS server is up
            requests.post(...)           # now safe to create session
            thread.join()                # wait for simulation to finish
        """
        self._bg_ready = threading.Event()
        t = threading.Thread(
            target=self._start_bg_target,
            args=(strategy,),
            daemon=True,
        )
        t.start()
        return t

    def wait_ready(self, timeout: float = 30.0) -> bool:
        """Block until the background engine's WS server is listening.

        Returns ``True`` if ready, ``False`` on timeout.
        """
        ev = getattr(self, "_bg_ready", None)
        if ev is None:
            raise RuntimeError("wait_ready() requires start_background()")
        return ev.wait(timeout=timeout)

    def _start_bg_target(self, strategy: Strategy) -> None:
        asyncio.run(self._run_loop(strategy))

    # -- watch mode -------------------------------------------------------------
    def _mtime(self) -> Optional[float]:
        try:
            return os.stat(self._watch).st_mtime if self._watch else None
        except OSError:
            return None

    def _reload(self, factory: Optional[StrategyFactory], current: Strategy) -> Strategy:
        if factory is None:
            return current
        try:
            fresh = factory()
            logger.info("Reloaded %s from %s", type(fresh).__name__, self._watch)
            return fresh
        except Exception as e:
            logger.error("Reload failed, keeping the previous version: %s", e)
            return current

    async def _wait_disconnect_or_change(self, adapter, mtime: Optional[float]) -> bool:
        """Wait for the browser to disconnect. Returns True if the watched file changed first."""
        while True:
            try:
                await adapter.get_snapshot_raw(timeout=1.0)
            except Exception:
                return False
            if self._watch and self._mtime() != mtime:
                return True
            await asyncio.sleep(0.4)

    async def _run_loop(self, strategy_or_factory: Union[Strategy, StrategyFactory]) -> None:
        factory: Optional[StrategyFactory] = None
        if isinstance(strategy_or_factory, Strategy):
            strategy = strategy_or_factory
        else:
            factory = strategy_or_factory
            strategy = factory()
        source = os.path.basename(self._watch) if self._watch else None
        mtime = self._mtime()

        adapter = RustEngineAsyncAdapter(
            host=self._host, port=self._port, start_seq=1
        )
        await adapter.start()
        logger.info("Listening on ws://%s:%d", self._host, self._port)

        # Signal background thread that WS server is up
        bg_ready = getattr(self, "_bg_ready", None)
        if bg_ready is not None:
            bg_ready.set()

        while True:
            logger.info("Waiting for browser connection...")
            await adapter.wait_connected(timeout=None)
            logger.info("Browser connected")

            try:
                ready = await adapter.wait_ready(timeout=60.0)
                if not ready:
                    logger.warning("WASM init timed out, waiting for disconnect")
                    await adapter.wait_for_disconnect()
                    continue

                gate_policy = (
                    await adapter.get_sync_policy(timeout=5.0) or "eager"
                )
                logger.info("Sync policy: %s", gate_policy)

                if self._watch and self._mtime() != mtime:
                    strategy = self._reload(factory, strategy)
                    mtime = self._mtime()
                await session_hello(
                    adapter,
                    strategy,
                    source=source,
                    watching=bool(self._watch and factory),
                    version=_VERSION,
                )

                t0 = time.perf_counter()
                result = await run_attached(
                    adapter,
                    strategy,
                    gate_policy=gate_policy,
                    progress=True,
                )
                elapsed = time.perf_counter() - t0

                self._report(result, elapsed, gate_policy)

                if self._on_result:
                    self._on_result(result)

                # End session if simulation stopped early with margin remaining
                try:
                    snap = await adapter.get_snapshot(timeout=5.0)
                    if (
                        snap.total_steps
                        and snap.step < snap.total_steps
                        and snap.margin_level > 1.0
                    ):
                        await adapter.end_session(timeout=5.0)
                except Exception:
                    pass

            except Exception as e:
                logger.error("Simulation error: %s", e)
                if self._single_run:
                    logger.info("Single-run mode: exiting after error")
                    break

            if self._single_run:
                logger.info("Single-run mode: exiting after one simulation")
                break

            if self._watch and factory is not None:
                changed = await self._wait_disconnect_or_change(adapter, mtime)
                if changed:
                    strategy = self._reload(factory, strategy)
                    mtime = self._mtime()
                    logger.info("Source changed: asking the browser to re-run")
                    await request_rerun(adapter, reason="file_changed", source=source)
                    await adapter.wait_for_disconnect(verbose=False)
            else:
                await adapter.wait_for_disconnect()

    @staticmethod
    def _report(result: BacktestResult, elapsed: float, policy: str) -> None:
        logger.info(
            "Simulation complete: %d steps in %.3fs (sync=%s)",
            result.steps,
            elapsed,
            policy,
        )
        logger.info("  Final balance: %.2f", result.final_balance())
        logger.info("  Max drawdown:  %.4f", result.max_drawdown())
        logger.info("  Balance tail:  %s", result.balance[-3:])
