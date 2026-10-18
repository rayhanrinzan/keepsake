import json
import time
from types import SimpleNamespace as NS

import pytest

from lastseen.brain.llm import ChalkLLM
from lastseen.config import load_config
from tests.test_answer import Fixture, T

TEMPLATE = "Your AirPods are on the desk. You put them there at 3:42 PM."
FACTS = {"item_id": "airpods", "state": "PLACED", "zone": "desk", "uncertain": False}


class Stub:
    """OpenAI-compatible stub: client.chat.completions.create(...)."""

    def __init__(self, content=None, tool_item=None, delay=0.0, raises=None):
        self.content, self.tool_item, self.delay, self.raises = content, tool_item, delay, raises
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        tcs = None
        if self.tool_item is not None:
            tcs = [NS(function=NS(name="get_item_status", arguments=json.dumps({"item_id": self.tool_item})))]
        return NS(choices=[NS(message=NS(content=self.content, tool_calls=tcs))])


def make(stub):
    return ChalkLLM("api.chalk.ai", "k", "env", "m", client=stub)


@pytest.fixture
def items():
    return load_config("config.yaml").items


def test_timeout_falls_back():
    llm = make(Stub(content="Sure thing", delay=5))
    t0 = time.monotonic()
    assert llm.reword(TEMPLATE, FACTS) == TEMPLATE
    assert time.monotonic() - t0 < 3.5
    assert llm.last_ok is False


def test_reword_ok():
    new = "Your AirPods are sitting on the desk, put there at 3:42 PM."
    llm = make(Stub(content=f'  "{new}"  '))
    assert llm.reword(TEMPLATE, FACTS) == new
    assert llm.last_ok is True


def test_reword_dropping_zone_rejected():
    assert make(Stub(content="They're somewhere! 3:42 PM.")).reword(TEMPLATE, FACTS) == TEMPLATE


def test_reword_dropping_time_rejected():
    assert make(Stub(content="Your AirPods are on the desk.")).reword(TEMPLATE, FACTS) == TEMPLATE


def test_reword_dropping_i_think_rejected():
    t = "I think your AirPods are on the desk. You put them there at 3:42 PM."
    assert make(Stub(content="Your AirPods are on the desk at 3:42 PM.")).reword(t, FACTS) == t
    ok = "I think they're on the desk, since 3:42 PM."
    assert make(Stub(content=ok)).reword(t, FACTS) == ok


def test_reword_too_long_rejected():
    long = "Your AirPods are on the desk at 3:42 PM. " * 10
    assert make(Stub(content=long)).reword(TEMPLATE, FACTS) == TEMPLATE


def test_reword_error_returns_template():
    llm = make(Stub(raises=RuntimeError("boom")))
    assert llm.reword(TEMPLATE, FACTS) == TEMPLATE
    assert llm.last_ok is False


def test_payload_has_no_paths(items):
    stub = Stub(content="x", tool_item="airpods")
    llm = make(stub)
    llm.reword(TEMPLATE, {**FACTS, "snapshot_url": "/clips/a.jpg"})
    llm.parse_item("where did my buds go", items)
    blob = json.dumps(stub.calls, default=str)
    assert len(stub.calls) == 2
    for bad in (".jpg", ".mp4", "/clips/", "data:image", "image_url"):
        assert bad not in blob


def test_parse_item_ok_and_unknown(items):
    assert make(Stub(tool_item="airpods")).parse_item("my little pods?", items) == "airpods"
    assert make(Stub(tool_item="spaceship")).parse_item("my little pods?", items) is None
    assert make(Stub(content='{"item_id": "airpods"}')).parse_item("q", items) == "airpods"
    assert make(Stub(content="no idea")).parse_item("q", items) is None
    assert make(Stub(raises=RuntimeError("x"))).parse_item("q", items) is None


def test_parse_item_enum_constrained(items):
    stub = Stub(tool_item="airpods")
    make(stub).parse_item("q", items)
    fn = stub.calls[0]["tools"][0]["function"]
    assert fn["name"] == "get_item_status"
    assert fn["parameters"]["properties"]["item_id"]["enum"] == [i.id for i in items]


def test_from_env_none_without_credentials(monkeypatch, tmp_path):
    for k in ("CHALK_ROUTER_KEY", "CHALK_API_HOST", "CHALK_ENV_ID", "CHALK_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert ChalkLLM.from_env(dotenv_path=tmp_path / "nope.env") is None
    monkeypatch.setenv("CHALK_ROUTER_KEY", "k")
    assert ChalkLLM.from_env(dotenv_path=tmp_path / "nope.env") is None  # no host
    monkeypatch.setenv("CHALK_API_HOST", "api.chalk.ai")
    assert ChalkLLM.from_env(dotenv_path=tmp_path / "nope.env") is None  # no model
    monkeypatch.setenv("CHALK_MODEL", "openai/x")
    llm = ChalkLLM.from_env(dotenv_path=tmp_path / "nope.env")
    assert llm is not None and llm.model == "openai/x"


def test_from_env_reads_dotenv(monkeypatch, tmp_path):
    for k in ("CHALK_ROUTER_KEY", "CHALK_API_HOST", "CHALK_ENV_ID", "CHALK_MODEL"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / ".env"
    p.write_text("CHALK_ROUTER_KEY=abc\nCHALK_API_HOST=h.example\nCHALK_MODEL=m1\n")
    llm = ChalkLLM.from_env(dotenv_path=p)
    assert llm is not None and llm.host == "h.example"
    monkeypatch.delenv("CHALK_ROUTER_KEY", raising=False)
    monkeypatch.delenv("CHALK_API_HOST", raising=False)
    monkeypatch.delenv("CHALK_MODEL", raising=False)


def test_disabled_flag_skips_llm(tmp_path):
    stub = Stub(content="x", tool_item="airpods")
    fx = Fixture(tmp_path, llm=make(stub))
    fx.cfg.features.chalk_llm = False
    fx.row(); fx.ev("PLACED", T(15, 42))
    fx.eng.ask("where are my airpods", "dashboard")
    fx.eng.ask("blorp frobnicate", "dashboard")
    assert stub.calls == []


def test_on_status_callback():
    seen = []
    llm = make(Stub(content="Your AirPods are on the desk at 3:42 PM."))
    llm.on_status = seen.append
    llm.reword(TEMPLATE, FACTS)
    assert seen == ["ok"]


@pytest.mark.parametrize("bad", [
    "Your AirPods are on the desk, put there at 13:42 PM.",
    "Your AirPods are on the desk, put there at 23:42 PM.",
    "Your AirPods are on the desktop, put there at 3:42 PM.",
    "Your AirPods are not on the desk, put there at 3:42 PM.",
    "Your AirPods aren't on the desk since 3:42 PM.",
    "Your AirPods are on the desk since 3:42 PM, around 4:00 PM.",
    "Your AirPods are on the desk since 3:42 PM, around 4 PM.",
])
def test_fact_guard_bypasses_rejected(bad):
    assert make(Stub(content=bad)).reword(TEMPLATE, FACTS) == TEMPLATE


# ---------------------------------------------------------------- one latency budget per ask
def _timed_ask(tmp_path, stub, question, source):
    f = Fixture(tmp_path, llm=make(stub))
    f.row(); f.ev("PLACED", T(15, 42))
    t0 = time.monotonic()
    r = f.eng.ask(question, source)
    return r, time.monotonic() - t0


def test_voice_reword_budget_is_one_second(tmp_path):
    stub = Stub(content="Your AirPods are on the desk, since 3:42 PM.", delay=3)
    r, dt = _timed_ask(tmp_path, stub, "where are my airpods", "voice")
    assert dt < 1.3 and r["text"].startswith("Your AirPods are on the desk.")


def test_parse_plus_reword_share_one_deadline(tmp_path):
    stub = Stub(content="Your AirPods are on the desk, since 3:42 PM.", tool_item="airpods", delay=1.5)
    r, dt = _timed_ask(tmp_path, stub, "whereabouts of the little earbud thing", "dashboard")
    assert r["item_id"] == "airpods" and len(stub.calls) == 2
    assert dt < 2.8                                   # 1.5 s parse + reword cut at the 2.5 s deadline


def test_explicit_timeout_overrides_default():
    llm = make(Stub(content="Sure thing", delay=3))
    t0 = time.monotonic()
    assert llm.reword(TEMPLATE, FACTS, timeout_s=0.3) == TEMPLATE
    assert time.monotonic() - t0 < 0.8
