"""Logging configuration for backnest."""
import logging


def configure(verbosity: int = 2) -> None:
    """Configure backnest logging verbosity.

    Args:
        verbosity: 1 = quiet (WARNING only), 2 = normal (INFO), 3 = verbose (DEBUG).
    """
    level = {1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}.get(
        verbosity, logging.INFO
    )
    root = logging.getLogger("backnest")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
