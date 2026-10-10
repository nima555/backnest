"""Declarative strategy parameters.

Declare tunable values as class attributes; the browser renders them as
sliders and sends the chosen values back before every run::

    class MaCross(Strategy):
        fast = Param(10, min=3, max=50, step=1, label="Fast MA")
        slow = Param(50, min=10, max=200, step=5)

        async def step(self, ctx):
            ... self.fast ...  # an int, clamped to [min, max]
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence


class Param:
    """A tunable strategy parameter (int, float, bool or one of ``choices``)."""

    def __init__(
        self,
        default: Any,
        *,
        min: Optional[float] = None,  # noqa: A002 - mirrors slider vocabulary
        max: Optional[float] = None,  # noqa: A002
        step: Optional[float] = None,
        choices: Optional[Sequence[Any]] = None,
        label: Optional[str] = None,
        doc: Optional[str] = None,
    ) -> None:
        if choices is not None and default not in choices:
            raise ValueError(f"default {default!r} is not one of choices {list(choices)!r}")
        if min is not None and max is not None and min > max:
            raise ValueError("min must be <= max")
        self.default = default
        self.min = min
        self.max = max
        self.step = step
        self.choices = list(choices) if choices is not None else None
        self.label = label
        self.doc = doc
        self.name = ""

    # -- descriptor protocol -------------------------------------------------
    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: Optional[type] = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self._slot, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        obj.__dict__[self._slot] = self.coerce(value)

    @property
    def _slot(self) -> str:
        return f"_param_{self.name}"

    # -- helpers ---------------------------------------------------------------
    @property
    def kind(self) -> str:
        if self.choices is not None:
            return "choice"
        if isinstance(self.default, bool):
            return "bool"
        if isinstance(self.default, int):
            return "int"
        return "float"

    def coerce(self, value: Any) -> Any:
        """Convert a browser-supplied value to this parameter's type and range."""
        kind = self.kind
        if kind == "choice":
            for c in self.choices or []:
                if c == value or str(c) == str(value):
                    return c
            return self.default
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        try:
            num = float(value)
        except (TypeError, ValueError):
            return self.default
        if num != num:  # NaN
            return self.default
        if self.min is not None:
            num = max(float(self.min), num)
        if self.max is not None:
            num = min(float(self.max), num)
        return int(round(num)) if kind == "int" else num

    def schema(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "type": self.kind, "default": self.default}
        for key in ("min", "max", "step", "choices", "label", "doc"):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        if self.kind in ("int", "float") and "step" not in out:
            out["step"] = 1 if self.kind == "int" else None
            if out["step"] is None:
                del out["step"]
        return out

    def __repr__(self) -> str:
        return f"Param({self.default!r}, name={self.name!r})"


def iter_params(cls: type) -> Iterable[Param]:
    """Yield the Param descriptors of ``cls`` in declaration order (base classes first)."""
    seen = set()
    for klass in reversed(cls.__mro__):
        for name, attr in vars(klass).items():
            if isinstance(attr, Param) and name not in seen:
                seen.add(name)
                yield attr


def param_schema(cls: type) -> List[Dict[str, Any]]:
    return [p.schema() for p in iter_params(cls)]


def apply_params(obj: Any, values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Set known parameters on ``obj`` from ``values``; unknown keys are ignored.

    Returns the full set of effective values after the update.
    """
    params = {p.name: p for p in iter_params(type(obj))}
    for name, value in (values or {}).items():
        if name in params:
            setattr(obj, name, value)
    return {name: getattr(obj, name) for name in params}


__all__ = ["Param", "iter_params", "param_schema", "apply_params"]
