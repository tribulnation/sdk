"""dYdX order expiry from the cached chain tip: freshness, fallback, caps and lifecycle."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing_extensions import Any, cast
import asyncio
import logging
import time

import pytest
from typed_dydx.node.constants import SHORT_BLOCK_WINDOW, STATEFUL_ORDER_TIME_WINDOW
from typed_dydx.node.orders.types import OrderParams

from tribulnation.dydx.market.impl import chain_tip as chain_tip_module
from tribulnation.dydx.market.impl.chain_tip import (
  ChainTip,
  Tip,
  long_term_max_age,
  short_term_max_age,
)
from tribulnation.dydx.market.impl.mixin import MarketMixin, Settings, Shared
from tribulnation.dydx.market.impl.orders import (
  MAX_LONG_TERM_GTBT,
  MAX_SHORT_TERM_GTB,
  with_expiry,
)

BLOCK_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
LIVE_HEIGHT = 1_000
"""The height every live `get_latest_block` returns."""


class FakeChain:
  """A chain whose live block and `/status` are scripted, counting the calls."""

  def __init__(self, *, status_height: int = 900, catching_up: bool = False):
    self.live_calls = 0
    self.status_calls = 0
    self.status_height = status_height
    self.catching_up = catching_up
    self.status_error: Exception | None = None
    self.tendermint = SimpleNamespace(get_latest_block=self.get_latest_block)
    self.comet = SimpleNamespace(status=self.status)

  async def get_latest_block(self) -> Any:
    """A live block at `LIVE_HEIGHT`."""
    self.live_calls += 1
    header = SimpleNamespace(height=LIVE_HEIGHT, time=BLOCK_TIME)
    return SimpleNamespace(block=SimpleNamespace(header=header))

  async def status(self) -> Any:
    """The scripted `/status`, or the scripted failure."""
    self.status_calls += 1
    if self.status_error is not None:
      raise self.status_error
    return {
      'sync_info': {
        'latest_block_height': self.status_height,
        'latest_block_time': BLOCK_TIME,
        'catching_up': self.catching_up,
      }
    }


def tip_of(chain: FakeChain, **kwargs: Any) -> ChainTip:
  """A `ChainTip` over the fake chain, read just now."""
  tip = ChainTip(chain=cast(Any, chain), **kwargs)
  tip.last_read = time.monotonic()
  return tip


def cached(height: int, *, age: float) -> Tip:
  """A tip seen `age` seconds ago."""
  return Tip(
    height=height,
    time=BLOCK_TIME - timedelta(seconds=age),
    observed=time.monotonic() - age,
  )


def market(tip: ChainTip) -> MarketMixin:
  """Just enough of a market for `with_expiry`."""
  return cast(MarketMixin, SimpleNamespace(shared=SimpleNamespace(chain_tip=tip)))


SHORT = cast(
  OrderParams,
  {'side': 'BUY', 'price': 1, 'size': 1, 'flags': 'SHORT_TERM'},
)
LONG = cast(
  OrderParams,
  {'side': 'BUY', 'price': 1, 'size': 1, 'flags': 'LONG_TERM'},
)


async def expire(tip: ChainTip, params: OrderParams, settings: Settings) -> Any:
  """The params `with_expiry` builds, stopping the poll it starts."""
  try:
    return await with_expiry(market(tip), params, settings)
  finally:
    await tip.stop()


async def test_fresh_tip_is_used_without_a_network_call():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.1)

  params = await expire(tip, SHORT, {'short_term_gtb': 5})

  assert params['good_til_block'] == 505
  assert chain.live_calls == 0


async def test_stale_tip_falls_back_to_a_live_read_and_refreshes_the_cache():
  chain = FakeChain()
  tip = tip_of(chain, max_age=2.0, poll_interval=60)
  tip.tip = cached(500, age=2.5)

  params = await expire(tip, SHORT, {'short_term_gtb': 18})

  assert params['good_til_block'] == LIVE_HEIGHT + 18
  assert chain.live_calls == 1
  assert tip.tip is not None and tip.tip.height == LIVE_HEIGHT
  assert tip.tip.age() < 1


async def test_no_tip_reads_live():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)

  params = await expire(tip, SHORT, {'short_term_gtb': 5})

  assert params['good_til_block'] == LIVE_HEIGHT + 5
  assert chain.live_calls == 1


async def test_tip_is_never_extrapolated():
  """A tip 1.5 s old (two or three blocks on mainnet) still yields its own height."""
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=1.5)

  params = await expire(tip, SHORT, {'short_term_gtb': 18})

  assert params['good_til_block'] == 518
  assert chain.live_calls == 0


def test_heights_never_go_backwards():
  tip = tip_of(FakeChain())
  tip.observe(cached(500, age=0.5))
  tip.observe(cached(499, age=0.0))
  assert tip.tip is not None and tip.tip.height == 500
  tip.observe(cached(500, age=0.0))
  assert tip.tip.age() < 0.1


async def test_short_delta_needs_a_fresher_tip():
  """With 2 blocks of life, a tip half a second old may already be a block behind."""
  assert short_term_max_age(2) < 0.5
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.5)

  params = await expire(tip, SHORT, {'short_term_gtb': 2})

  assert params['good_til_block'] == LIVE_HEIGHT + 2
  assert chain.live_calls == 1


async def test_delta_of_one_always_reads_live():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.0)

  await expire(tip, SHORT, {'short_term_gtb': 1})

  assert chain.live_calls == 1


@pytest.mark.parametrize(
  'settings', [{}, {'short_term_gtb': 20}, {'short_term_gtb': 50}]
)
async def test_short_term_gtb_stays_within_the_window(settings: Settings):
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.1)

  params = await expire(tip, SHORT, settings)

  assert params['good_til_block'] == 500 + MAX_SHORT_TERM_GTB
  assert MAX_SHORT_TERM_GTB < SHORT_BLOCK_WINDOW


async def test_long_term_uses_the_cached_block_time():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.5)
  assert tip.tip is not None

  params = await expire(tip, LONG, {'long_term_gtbt': 3600})

  assert params['good_til_block_time'] == int(tip.tip.time.timestamp()) + 3600
  assert chain.live_calls == 0


async def test_long_term_default_stays_within_the_window():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.tip = cached(500, age=0.5)
  assert tip.tip is not None

  params = await expire(tip, LONG, {})

  expected = int(tip.tip.time.timestamp()) + MAX_LONG_TERM_GTBT
  assert params['good_til_block_time'] == expected
  assert MAX_LONG_TERM_GTBT < STATEFUL_ORDER_TIME_WINDOW
  assert long_term_max_age(2) == 1.0


async def test_background_poll_fills_the_cache():
  chain = FakeChain(status_height=700)
  tip = tip_of(chain, poll_interval=0.01)
  tip.start()
  try:
    for _ in range(100):
      if tip.tip is not None:
        break
      await asyncio.sleep(0.01)
    latest = await tip.latest(max_age=1)
  finally:
    await tip.stop()

  assert latest.height == 700
  assert chain.live_calls == 0


async def test_catching_up_node_is_not_cached():
  chain = FakeChain(catching_up=True)
  tip = tip_of(chain, poll_interval=0.01)
  tip.start()
  try:
    while chain.status_calls < 3:
      await asyncio.sleep(0.01)
  finally:
    await tip.stop()

  assert tip.tip is None


async def test_poll_failures_fall_back_to_live_and_recover(
  monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
  monkeypatch.setattr(chain_tip_module, 'POLL_BACKOFF_MAX', 0.02)
  chain = FakeChain(status_height=1_200)
  chain.status_error = ConnectionError('node down')
  tip = tip_of(chain, poll_interval=0.01)
  caplog.set_level(logging.WARNING)
  try:
    params: Any = await with_expiry(market(tip), SHORT, {'short_term_gtb': 5})
    while chain.status_calls < 4:
      await asyncio.sleep(0.01)
    assert tip.task is not None and not tip.task.done()
    assert params['good_til_block'] == LIVE_HEIGHT + 5
    assert len([r for r in caplog.records if 'poll failed' in r.message]) == 1

    chain.status_error = None
    for _ in range(100):
      if tip.tip is not None and tip.tip.height == 1_200:
        break
      await asyncio.sleep(0.01)
    params = await with_expiry(market(tip), SHORT, {'short_term_gtb': 5})
  finally:
    await tip.stop()

  assert params['good_til_block'] == 1_205
  assert chain.live_calls == 1


async def test_dead_poll_is_restarted():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=60)
  tip.start()
  first = tip.task
  assert first is not None
  first.cancel()
  await asyncio.wait([first])

  tip.start()
  try:
    assert tip.task is not None and tip.task is not first
    assert not tip.task.done()
  finally:
    await tip.stop()


async def test_idle_poll_stops_and_the_next_order_restarts_it():
  chain = FakeChain()
  tip = tip_of(chain, poll_interval=0.01, idle_after=0.05)
  tip.start()
  first = tip.task
  assert first is not None
  await asyncio.wait_for(asyncio.wait([first]), timeout=1)
  assert not first.cancelled() and first.exception() is None
  calls = chain.status_calls

  try:
    await tip.latest(max_age=1)
    assert tip.task is not first and tip.task is not None
    await asyncio.sleep(0.03)
    assert chain.status_calls > calls
  finally:
    await tip.stop()


async def test_exit_cancels_the_poll():
  chain = FakeChain()
  async with tip_of(chain, poll_interval=60) as tip:
    tip.start()
    task = tip.task
  assert task is not None and task.cancelled()
  assert tip.task is None


def test_shared_prefers_the_full_node():
  public = SimpleNamespace(chain='public')
  full_node = cast(Any, 'full node')
  with_node = Shared(client=cast(Any, public), address=None, full_node=full_node)
  without = Shared(client=cast(Any, public), address=None, block_max_age=1.0)

  assert with_node.chain_tip.chain == 'full node'
  assert without.chain_tip.chain == 'public'
  assert without.chain_tip.max_age == 1.0
  assert with_node.chain_tip in list(with_node.resources())
