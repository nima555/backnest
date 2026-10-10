"""Python -> browser calls layered on ``call_raw`` (hawk-bt-rust-engine >= 0.1.3).

FN_SESSION_HELLO (103)
    Sent before every run: strategy name, parameter schema and watch state.
    The browser replies with the parameter values currently set by its sliders.
FN_RERUN_REQUEST (104)
    Sent after a run when the watched source file changed; the browser
    reconnects and starts a fresh run.

Browsers that predate these ids answer with an error; callers treat that as
"feature unavailable" and fall back to defaults.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

FN_SESSION_HELLO = 103
FN_RERUN_REQUEST = 104


async def session_hello(adapter, strategy, *, source: Optional[str], watching: bool, version: str) -> Dict[str, Any]:
    """Announce the strategy and receive parameter values. Returns the applied values."""
    payload = {
        "strategy_name": getattr(strategy, "strategy_name", type(strategy).__name__),
        "params": strategy.param_schema() if hasattr(strategy, "param_schema") else [],
        "source": source,
        "watching": watching,
        "library_version": version,
    }
    if not getattr(adapter, "supports_raw_calls", False):
        return {}
    try:
        reply = await adapter.call_json(FN_SESSION_HELLO, payload, timeout=5.0)
    except Exception as e:  # older web app: no hello support
        logger.debug("session hello unsupported: %s", e)
        return {}
    values = reply.get("params") if isinstance(reply, dict) else None
    if hasattr(strategy, "set_params"):
        applied = strategy.set_params(values if isinstance(values, dict) else {})
        if applied:
            logger.info("Params: %s", ", ".join(f"{k}={v}" for k, v in applied.items()))
        return applied
    return {}


async def request_rerun(adapter, *, reason: str, source: Optional[str]) -> bool:
    if not getattr(adapter, "supports_raw_calls", False):
        return False
    try:
        await adapter.call_json(FN_RERUN_REQUEST, {"reason": reason, "source": source}, timeout=5.0)
        return True
    except Exception as e:
        logger.debug("rerun request failed: %s", e)
        return False


__all__ = ["FN_SESSION_HELLO", "FN_RERUN_REQUEST", "session_hello", "request_rerun"]
