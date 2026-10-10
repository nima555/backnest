"""``hawk-bt`` command line.

    hawk-bt run my_strategy.py            # serve the strategy, re-run on save
    hawk-bt run my_strategy.py --no-watch # serve without file watching
    hawk-bt run my_strategy.py --open     # also open the Backnest app in a browser
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import itertools
import logging
import os
import sys
import webbrowser
from typing import Callable, Optional

from hawk_bt.hawk_engine import HawkEngine
from hawk_bt.logging import configure as configure_logging
from hawk_bt.strategy.api import Strategy

APP_URL = "https://app.hawk-backtester.com/simulator/graph?source=python"
_counter = itertools.count()


def _load_module(path: str):
    name = f"_hawk_bt_user_strategy_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    directory = os.path.dirname(os.path.abspath(path))
    if directory not in sys.path:
        sys.path.insert(0, directory)
    # Compile from source on every load: the .pyc cache has 1-second mtime resolution
    # and would hand back stale code when the file is saved twice in quick succession.
    with open(path, "rb") as fh:
        code = compile(fh.read(), path, "exec")
    exec(code, module.__dict__)
    return module


def _find_strategy(module, class_name: Optional[str]) -> type:
    candidates = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, Strategy)
        and obj is not Strategy
        and obj.__module__ == module.__name__
        and not inspect.isabstract(obj)
    ]
    if class_name:
        for c in candidates:
            if c.__name__ == class_name:
                return c
        raise SystemExit(f"class {class_name!r} not found; found: {[c.__name__ for c in candidates]}")
    if len(candidates) != 1:
        names = [c.__name__ for c in candidates]
        raise SystemExit(
            f"expected exactly one Strategy subclass in the file, found {names}; use --class NAME"
        )
    return candidates[0]


def make_factory(path: str, class_name: Optional[str]) -> Callable[[], Strategy]:
    """Return a factory that re-imports ``path`` on every call (picks up edits)."""

    def factory() -> Strategy:
        cls = _find_strategy(_load_module(path), class_name)
        return cls()

    return factory


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="hawk-bt", description="Run a Backnest strategy locally.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="serve a strategy file to the Backnest app")
    run.add_argument("file", help="Python file containing one Strategy subclass")
    run.add_argument("--class", dest="class_name", help="Strategy class to use when the file has several")
    run.add_argument("--port", type=int, default=8787)
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--no-watch", action="store_true", help="do not re-run when the file is saved")
    run.add_argument("--open", action="store_true", help="open the Backnest app in a browser")
    run.add_argument("-v", "--verbose", action="count", default=2)
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        parser.error(f"{args.file} does not exist")

    factory = make_factory(path, args.class_name)
    factory()  # fail fast on import errors before opening the port
    watch = None if args.no_watch else path
    log = logging.getLogger("hawk_bt")
    log.info("Serving %s on ws://%s:%d%s", os.path.basename(path), args.host, args.port,
             "" if args.no_watch else " (re-runs on save)")
    log.info("Open the app, pick a dataset, choose 'Your Python strategy' and click Connect: %s", APP_URL)
    if args.open:
        webbrowser.open(APP_URL)
    try:
        HawkEngine(host=args.host, port=args.port, watch=watch).start(factory)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
