"""Shared streams retain subscribers and release native sockets and account leases."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any, AsyncIterator
import pytest
from typed_core import NetworkError as ClientNetworkError
from typed_aster.futures.listen_key import ListenKey as FuturesListenKey
from typed_aster.futures.user_stream.events import Events as FuturesEvents
from typed_aster.spot.listen_key import ListenKey as SpotListenKey
from typed_aster.spot.user_stream.events import Events as SpotEvents
from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Scope
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.aster.market.streams import parse_fill, with_renewal
from tribulnation.sdk import NetworkError
from tribulnation.sdk.core import MissingData


def market(venue: AsterMarket, scope: Scope, symbol: str) -> SpotMarket | PerpMarket:
  """A market sharing the venue's owner, without catalogue requests."""
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=venue.shared, symbol=symbol)


def fill(scope: Scope, symbol: str, side: str) -> dict[str, Any]:
  """A native last-fill event also carries a different cumulative order quantity."""
  row = dict(
    s=symbol,
    S=side,
    x='TRADE',
    l=Decimal(2),
    L=Decimal(3),
    z=Decimal(10),
    t=42,
    T=datetime.now(timezone.utc),
    m=False,
    n=Decimal('.01'),
    N='USDT',
  )
  return (
    dict(e='ORDER_TRADE_UPDATE', o=row)
    if scope == 'perp'
    else dict(e='executionReport', **row)
  )


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_shared_fills_and_last_subscriber_cleanup(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """One account socket serves symbols independently until its last subscriber leaves."""
  keys = FuturesListenKey if scope == 'perp' else SpotListenKey
  events = FuturesEvents if scope == 'perp' else SpotEvents
  start = AsyncMock(return_value={'listenKey': 'test-lease'})
  close = AsyncMock()
  monkeypatch.setattr(keys, 'start', start)
  monkeypatch.setattr(keys, 'close', close)
  queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
  opened = closed = 0

  async def rows() -> AsyncIterator[dict[str, Any]]:
    """Wait for externally supplied native account events."""
    while True:
      yield await queue.get()

  @asynccontextmanager
  async def stream(*args: Any):
    """Track the actual context lifetime separately from subscriber lifetimes."""
    nonlocal opened, closed
    opened += 1
    try:
      yield rows()
    finally:
      closed += 1

  monkeypatch.setattr(events, 'events', stream)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    btc, eth = (market(venue, scope, symbol) for symbol in ('BTCUSDT', 'ETHUSDT'))
    async with eth.trades_stream() as remaining:
      async with btc.trades_stream() as first:
        await queue.put(fill(scope, 'ETHUSDT', 'SELL'))
        await queue.put(fill(scope, 'BTCUSDT', 'BUY'))
        async with asyncio.timeout(2):
          buy = await anext(aiter(first))
          sell = await anext(aiter(remaining))
        assert buy.qty == 2 and sell.qty == -2
        assert buy.fee is not None and buy.fee.amount == Decimal('.01')
      close.assert_not_awaited()
      await queue.put(fill(scope, 'ETHUSDT', 'BUY'))
      async with asyncio.timeout(2):
        assert (await anext(aiter(remaining))).qty == 2
      assert opened == 1 and start.await_count == 1
    close.assert_awaited_once()
    assert closed == 1


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_failed_socket_acquisition_releases_key(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """A lease acquired before a WebSocket failure is rolled back and translated."""
  keys = FuturesListenKey if scope == 'perp' else SpotListenKey
  events = FuturesEvents if scope == 'perp' else SpotEvents
  monkeypatch.setattr(
    keys, 'start', AsyncMock(return_value={'listenKey': 'test-lease'})
  )
  close = AsyncMock()
  monkeypatch.setattr(keys, 'close', close)

  @asynccontextmanager
  async def fail(*args: Any):
    """Fail while acquiring the native WebSocket, before returning its iterator."""
    raise ClientNetworkError('offline')
    yield

  monkeypatch.setattr(events, 'events', fail)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    with pytest.raises(NetworkError):
      async with market(venue, scope, 'BTCUSDT').trades_stream():
        pytest.fail('failed acquisition must not enter the subscriber body')
  close.assert_awaited_once()


async def test_failed_renewal_interrupts_idle_stream():
  """An idle WebSocket cannot hide a failed renewal or leave an anext task running."""
  reading = asyncio.Event()
  released = asyncio.Event()

  async def idle() -> AsyncIterator[int]:
    """Record cancellation of the pending native receive."""
    try:
      reading.set()
      await asyncio.Future()
      yield 1
    finally:
      released.set()

  async def renew():
    """Fail after the native receive has begun."""
    await reading.wait()
    raise NetworkError('lease renewal failed')

  renewal = asyncio.create_task(renew())
  with pytest.raises(NetworkError, match='lease renewal failed'):
    async with asyncio.timeout(2):
      await anext(with_renewal(idle(), renewal))
  assert released.is_set() and renewal.done()


def test_incomplete_fee_is_not_silently_dropped():
  """The adapter cannot report a fee without its native asset and amount together."""
  row: Any = fill('spot', 'BTCUSDT', 'BUY')
  del row['N']
  with pytest.raises(MissingData, match='commission'):
    parse_fill(row)
