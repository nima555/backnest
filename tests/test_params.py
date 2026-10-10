import asyncio
import json
import textwrap

import pytest

from hawk_bt import Param, Strategy
from hawk_bt.cli import make_factory
from hawk_bt.runtime.browser_rpc import FN_SESSION_HELLO, session_hello


class MaCross(Strategy):
    fast = Param(10, min=3, max=50, step=1, label="Fast")
    slow = Param(50, min=10, max=200, step=5)
    stop = Param(0.5, min=0.0, max=3.0, step=0.1)
    shorts = Param(True)
    mode = Param("close", choices=["close", "hl2"])

    async def step(self, ctx):
        return None


def test_defaults_and_schema():
    s = MaCross()
    assert (s.fast, s.slow, s.stop, s.shorts, s.mode) == (10, 50, 0.5, True, "close")
    schema = {p["name"]: p for p in MaCross.param_schema()}
    assert list(schema) == ["fast", "slow", "stop", "shorts", "mode"]
    assert schema["fast"] == {"name": "fast", "type": "int", "default": 10, "min": 3, "max": 50, "step": 1, "label": "Fast"}
    assert schema["stop"]["type"] == "float"
    assert schema["shorts"]["type"] == "bool"
    assert schema["mode"]["choices"] == ["close", "hl2"]
    json.dumps(schema)  # must be JSON-able


def test_set_params_coerces_clamps_and_ignores_unknown():
    s = MaCross()
    applied = s.set_params({"fast": "25.6", "slow": 9999, "stop": "nan", "shorts": "false", "mode": "hl2", "nope": 1})
    assert applied == {"fast": 26, "slow": 200, "stop": 0.5, "shorts": False, "mode": "hl2"}
    s.set_params({"mode": "bogus"})
    assert s.mode == "close"
    other = MaCross()
    assert other.fast == 10  # values are per instance


class FakeAdapter:
    supports_raw_calls = True

    def __init__(self, reply=None, fail=False):
        self.calls = []
        self.reply = reply or {}
        self.fail = fail

    async def call_json(self, fn_id, payload, timeout=5.0):
        self.calls.append((fn_id, payload))
        if self.fail:
            raise RuntimeError("unsupported fn")
        return self.reply


def test_session_hello_sends_schema_and_applies_browser_values():
    adapter = FakeAdapter(reply={"params": {"fast": 12, "slow": 60}})
    s = MaCross()
    applied = asyncio.run(session_hello(adapter, s, source="ma.py", watching=True, version="0.2.0"))
    fn_id, payload = adapter.calls[0]
    assert fn_id == FN_SESSION_HELLO
    assert payload["strategy_name"] == "MaCross"
    assert payload["watching"] is True and payload["source"] == "ma.py"
    assert [p["name"] for p in payload["params"]] == ["fast", "slow", "stop", "shorts", "mode"]
    assert applied["fast"] == 12 and s.slow == 60


def test_session_hello_falls_back_when_browser_is_old():
    s = MaCross()
    assert asyncio.run(session_hello(FakeAdapter(fail=True), s, source=None, watching=False, version="x")) == {}
    assert s.fast == 10


def test_cli_factory_reimports_file(tmp_path):
    src = tmp_path / "strat.py"
    body = textwrap.dedent('''
        from hawk_bt import Strategy, Param
        class Mine(Strategy):
            n = Param({n})
            async def step(self, ctx):
                return None
    ''')
    src.write_text(body.format(n=5))
    factory = make_factory(str(src), None)
    assert factory().n == 5
    src.write_text(body.format(n=7))
    assert factory().n == 7


def test_cli_factory_requires_unambiguous_class(tmp_path):
    src = tmp_path / "two.py"
    src.write_text(textwrap.dedent('''
        from hawk_bt import Strategy
        class A(Strategy):
            async def step(self, ctx): return None
        class B(Strategy):
            async def step(self, ctx): return None
    '''))
    with pytest.raises(SystemExit):
        make_factory(str(src), None)()
    assert type(make_factory(str(src), "B")()).__name__ == "B"
