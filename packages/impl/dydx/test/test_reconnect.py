"""Indexer channels across dropped connections: reconnection, backfill, and racing."""

from datetime import datetime, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, cast
import asyncio
import logging

import pytest
from typed_core.exceptions import NetworkError as TypedNetworkError
from typed_dydx.indexer.schemas import Fill, PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts

from tribulnation.dydx.market.exchange import Exchange
from tribulnation.dydx.market.impl import dedup, parent_feed, reconnect
from tribulnation.dydx.market.impl.dedup import FillDedup, FillRace
from tribulnation.dydx.market.impl.mixin import MarketMixin, Shared
from tribulnation.dydx.market.impl.orders import (
  indexer_order_id,
  indexer_subaccount_id,
  serialize_id,
)
from tribulnation.dydx.market.impl.parent_feed import ParentFills
from tribulnation.dydx.market.impl.socket_fills import (
  FrameParser,
  SocketItem,
  frame_adapter,
)
from tribulnation.dydx.market.impl.trades import indexer_key, trades_stream
from tribulnation.sdk.core import BadRequest, NetworkError, Subscription

ADDRESS = 'dydx1039f5sxkl0t39vxcsnmlu62ly22typdap0zkyn'
BLOCK_TIME = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
MARKET = cast(
  PerpetualMarket,
  {
    'ticker': 'BTC-USD',
    'clobPairId': 0,
    'atomicResolution': -10,
    'quantumConversionExponent': -9,
    'stepBaseQuantums': 1_000_000,
    'subticksPerTick': 100_000,
  },
)


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch: pytest.MonkeyPatch):
  """Reconnect at once, and give up after half a second."""
  monkeypatch.setattr(reconnect, 'RECONNECT_MIN', 0.01)
  monkeypatch.setattr(reconnect, 'RECONNECT_MAX', 0.05)
  monkeypatch.setattr(reconnect, 'GIVE_UP_AFTER', 0.5)


def proto_id(client_id: int) -> clob.OrderId:
  """A short-term BTC-USD order id of `ADDRESS`'s subaccount 0."""
  return clob.OrderId(
    client_id=client_id,
    order_flags=0,
    clob_pair_id=0,
    subaccount_id=subaccounts.SubaccountId(owner=ADDRESS, number=0),
  )


def pushed(id: str, height: int, *, client_id: int = 1) -> dict[str, Any]:
  """A fill as the parent subaccounts channel pushes it."""
  return {
    'id': id,
    'ticker': 'BTC-USD',
    'side': 'BUY',
    'price': Decimal('60000'),
    'size': Decimal('0.001'),
    'createdAt': BLOCK_TIME,
    'createdAtHeight': height,
    'liquidity': 'MAKER',
    'type': 'LIMIT',
    'orderId': indexer_order_id(proto_id(client_id)),
    'subaccountId': indexer_subaccount_id(ADDRESS, 0),
    'clobPairId': 0,
  }


def rest_fill(id: str, height: int, *, client_id: int = 1) -> Fill:
  """The same fill as REST serves it."""
  return {
    'id': id,
    'side': 'BUY',
    'liquidity': 'MAKER',
    'type': 'LIMIT',
    'market': 'BTC-USD',
    'marketType': 'PERPETUAL',
    'price': Decimal('60000'),
    'size': Decimal('0.001'),
    'fee': Decimal('0.01'),
    'affiliateRevShare': Decimal(0),
    'createdAt': BLOCK_TIME,
    'createdAtHeight': height,
    'orderId': indexer_order_id(proto_id(client_id)),
    'subaccountNumber': 0,
  }


def rest_order(order_id: str) -> dict[str, Any]:
  """The REST order behind `rest_fill`'s `orderId` (client id 1)."""
  return {
    'id': order_id,
    'subaccountId': indexer_subaccount_id(ADDRESS, 0),
    'subaccountNumber': 0,
    'clientId': '1',
    'clobPairId': '0',
    'orderFlags': '0',
  }


class FakeStream:
  """An indexer channel subscription: a reply, scripted items, then a drop or idling."""

  def __init__(self, reply: Any, items: list[Any], *, drop: bool):
    self.reply = reply
    self.items = items
    self.drop = drop
    self.unsubscribed = False

  async def __aiter__(self) -> AsyncIterator[Any]:
    for item in self.items:
      await asyncio.sleep(0)
      yield item
    if self.drop:
      raise TypedNetworkError('Error receiving message')
    await asyncio.Event().wait()

  async def unsubscribe(self):
    """Release the channel."""
    self.unsubscribed = True


class FakeIndexer:
  """Scripted channel subscriptions, in order, and REST fills."""

  def __init__(self, streams: list[FakeStream | Exception], fills: list[Fill] = []):
    self.streams = streams
    self.opened: list[FakeStream] = []
    self.fills = fills
    self.fill_requests: list[dict[str, Any]] = []

  async def subscribe(self, *args: Any, **kwargs: Any) -> FakeStream:
    """The next scripted subscription, or its failure."""
    next = self.streams.pop(0)
    if isinstance(next, Exception):
      raise next
    self.opened.append(next)
    return next

  async def get_parent_fills(self, **kwargs: Any) -> dict[str, Any]:
    """REST fills at or below `created_before_or_at_height`, newest first; like the
    indexer, refuses `market_type` without `market`."""
    self.fill_requests.append(kwargs)
    if kwargs.get('market_type') is not None and kwargs.get('market') is None:
      raise BadRequest(400, 'market must be provided if marketType is provided')
    until = kwargs['created_before_or_at_height']
    page = [f for f in self.fills if f['createdAtHeight'] <= until]
    page.sort(key=lambda f: -f['createdAtHeight'])
    return {'fills': page[: kwargs['limit']]}

  async def get_order(self, order_id: str) -> dict[str, Any]:
    """The REST order."""
    return rest_order(order_id)


def shared_with(indexer: FakeIndexer, **kwargs: Any) -> Shared:
  """A client whose indexer is `indexer`."""
  shared = Exchange.new(address=ADDRESS, public=True, **kwargs).shared
  shared.perpetual_markets = {'BTC-USD': MARKET}
  streams = cast(Any, shared.client.indexer.streams)
  data = cast(Any, shared.client.indexer.data)
  streams.parent_subaccounts = indexer.subscribe
  streams.orders = indexer.subscribe
  data.get_parent_fills = indexer.get_parent_fills
  data.get_order = indexer.get_order
  return shared


async def take(stream: AsyncIterator[Any], n: int) -> list[Any]:
  """The first `n` items, failing rather than hanging."""
  return [await asyncio.wait_for(anext(stream), 2) for _ in range(n)]


# ── reconnecting ────────────────────────────────────────────────────────────


async def test_a_dropped_channel_reopens_and_subscribers_see_no_end(
  caplog: pytest.LogCaptureFixture,
):
  """After a drop the channel is released, reopened, and items go on."""
  calls: list[bool] = []
  streams = [FakeStream(None, [1, 2], drop=True), FakeStream(None, [3], drop=False)]

  async def open(reopen: bool) -> reconnect.Opened[Any]:
    """The next stream; a typed drop is translated like the venue's channels."""
    calls.append(reopen)
    stream = streams[len(calls) - 1]

    async def items():
      """Translate the typed drop."""
      try:
        async for item in stream:
          yield item
      except TypedNetworkError as e:
        raise NetworkError(*e.args) from e

    return items(), stream.unsubscribe

  subscription = Subscription[Any].of(reconnect.reconnecting('test', open))
  async with subscription.subscribe() as inbox:
    assert await take(aiter(inbox), 3) == [1, 2, 3]
  assert calls == [False, True]
  assert streams[0].unsubscribed and streams[1].unsubscribed
  assert 'dYdX indexer test dropped' in caplog.text
  assert 'dYdX indexer test reconnected' in caplog.text


async def test_a_channel_down_too_long_ends_its_subscribers():
  """Reconnects failing for `GIVE_UP_AFTER` seconds raise the last error."""
  attempts = 0

  async def open(reopen: bool) -> reconnect.Opened[Any]:
    """The first open succeeds and drops; every reopen fails."""
    nonlocal attempts
    attempts += 1
    if reopen:
      raise NetworkError('indexer unreachable')

    async def items():
      """Drop at once."""
      raise NetworkError('Error receiving message')
      yield

    async def noop():
      """Nothing to release."""

    return items(), noop

  subscription = Subscription[Any].of(reconnect.reconnecting('test', open))
  async with subscription.subscribe() as inbox:
    with pytest.raises(NetworkError, match='indexer unreachable'):
      await asyncio.wait_for(anext(aiter(inbox)), 3)
  assert attempts > 2


async def test_other_errors_are_not_retried():
  """Only connection errors reconnect; anything else ends the channel."""
  calls = 0

  async def open(reopen: bool) -> reconnect.Opened[Any]:
    """A channel whose items are broken."""
    nonlocal calls
    calls += 1

    async def items():
      """Fail with a bug."""
      raise ValueError('bad message')
      yield

    async def noop():
      """Nothing to release."""

    return items(), noop

  subscription = Subscription[Any].of(reconnect.reconnecting('test', open))
  async with subscription.subscribe() as inbox:
    with pytest.raises(ValueError):
      await asyncio.wait_for(anext(aiter(inbox)), 2)
  assert calls == 1


async def test_a_rejected_reopen_is_not_retried():
  """A reopen the venue rejects (a bad request) ends the channel at once."""
  calls = 0

  async def open(reopen: bool) -> reconnect.Opened[Any]:
    """Drop, then reject the reopen."""
    nonlocal calls
    calls += 1
    if reopen:
      raise BadRequest(400, 'bad query')

    async def items():
      """Drop at once."""
      raise NetworkError('Error receiving message')
      yield

    async def noop():
      """Nothing to release."""

    return items(), noop

  subscription = Subscription[Any].of(reconnect.reconnecting('test', open))
  async with subscription.subscribe() as inbox:
    with pytest.raises(BadRequest):
      await asyncio.wait_for(anext(aiter(inbox)), 2)
  assert calls == 2


# ── Parent subaccounts feed ─────────────────────────────────────────────────


def test_parent_fills_drop_repeats_and_forget_old_heights(
  monkeypatch: pytest.MonkeyPatch,
):
  """A fill id is delivered once; ids are kept `SEEN_HEIGHTS` blocks."""
  monkeypatch.setattr(parent_feed, 'SEEN_HEIGHTS', 5)
  position = ParentFills()
  msg: Any = {'blockHeight': 10, 'fills': [pushed('a', 10), pushed('b', 10)]}
  assert [f['id'] for f in position.admit(msg).get('fills') or []] == ['a', 'b']
  again: Any = {'blockHeight': 11, 'fills': [pushed('b', 10), pushed('c', 11)]}
  assert [f['id'] for f in position.admit(again).get('fills') or []] == ['c']
  assert position.height == 11
  position.reached(20)
  assert position.seen == {}


async def test_parent_feed_backfills_the_gap_from_rest(
  caplog: pytest.LogCaptureFixture,
):
  """On reconnection the fills between the last height seen and the new subscription's
  height come from REST, marked `backfill`, then live fills go on, without repeats."""
  indexer = FakeIndexer(
    [
      FakeStream(
        {'blockHeight': 9}, [{'blockHeight': 10, 'fills': [pushed('a', 10)]}], drop=True
      ),
      FakeStream(
        {'blockHeight': 15},
        [{'blockHeight': 16, 'fills': [pushed('d', 15), pushed('e', 16)]}],
        drop=False,
      ),
    ],
    fills=[
      rest_fill('old', 9),
      rest_fill('a', 10),
      rest_fill('b', 12),
      rest_fill('d', 15),
      rest_fill('later', 17),
    ],
  )
  shared = shared_with(indexer)
  async with shared.parent_account_subscription(0).subscribe() as inbox:
    first, gap, live = await take(aiter(inbox), 3)
  assert [f['id'] for f in first['fills']] == ['a']
  assert gap['backfill'] is True
  assert [f['id'] for f in gap['fills']] == ['b', 'd']
  assert gap['fills'][0]['subaccountId'] == indexer_subaccount_id(ADDRESS, 0)
  assert gap['fills'][0]['clobPairId'] == 0
  assert [o['id'] for o in gap['orders']] == [indexer_order_id(proto_id(1))]
  assert [f['id'] for f in live['fills']] == ['e']  # 'd' came with the gap
  assert indexer.fill_requests[0]['created_before_or_at_height'] == 15
  assert indexer.opened[0].unsubscribed
  assert '2 fills backfilled from REST' in caplog.text


async def test_a_failed_backfill_retries_the_reconnection():
  """A gap REST could not fill is not skipped: the reconnection is retried."""
  indexer = FakeIndexer(
    [
      FakeStream({'blockHeight': 9}, [{'blockHeight': 10, 'fills': []}], drop=True),
      FakeStream({'blockHeight': 12}, [], drop=False),
      FakeStream({'blockHeight': 13}, [], drop=False),
    ],
    fills=[rest_fill('b', 12)],
  )
  failures = [NetworkError('REST down')]
  get_parent_fills = indexer.get_parent_fills

  async def flaky(**kwargs: Any):
    """Fail once."""
    if failures:
      raise failures.pop()
    return await get_parent_fills(**kwargs)

  shared = shared_with(indexer)
  cast(Any, shared.client.indexer.data).get_parent_fills = flaky
  async with shared.parent_account_subscription(0).subscribe() as inbox:
    _, gap = await take(aiter(inbox), 2)
  assert [f['id'] for f in gap['fills']] == ['b']
  assert indexer.opened[1].unsubscribed  # released when its backfill failed


async def test_indexer_trades_stream_survives_a_drop():
  """An `'indexer'` trades stream sees the gap's fills, with order ids, and no end."""
  indexer = FakeIndexer(
    [
      FakeStream(
        {'blockHeight': 9}, [{'blockHeight': 10, 'fills': [pushed('a', 10)]}], drop=True
      ),
      FakeStream({'blockHeight': 12}, [], drop=False),
    ],
    fills=[rest_fill('b', 12)],
  )
  market = MarketMixin(shared=shared_with(indexer), perpetual_market=MARKET)
  async with trades_stream(market) as stream:
    a, b = await take(aiter(stream), 2)
  assert (a.id, b.id) == ('a', 'b')
  assert b.order_id == serialize_id(proto_id(1))


async def test_depth_reopens_with_the_new_snapshot():
  """After a drop, the book restarts from the new subscription's snapshot."""

  def level(price: str, size: str) -> dict[str, Decimal]:
    """A REST book level."""
    return {'price': Decimal(price), 'size': Decimal(size)}

  indexer = FakeIndexer(
    [
      FakeStream(
        {'asks': [level('60000', '1')], 'bids': []},
        [{'asks': [(Decimal('60000'), Decimal('2'))]}],
        drop=True,
      ),
      FakeStream({'asks': [level('60001', '3')], 'bids': []}, [], drop=False),
    ]
  )
  shared = shared_with(indexer)
  async with shared.depth_subscription('BTC-USD').subscribe(queue_size=10) as inbox:
    updated = (await take(aiter(inbox), 1))[0]
    assert updated.asks[0].qty == Decimal('2')
    snapshot = (await take(aiter(inbox), 1))[0]
  assert [(e.price, e.qty) for e in snapshot.asks] == [(Decimal('60001'), Decimal('3'))]


# ── 'fastest' ───────────────────────────────────────────────────────────────


def socket_fill(height: int) -> SocketItem:
  """The fill daemon's copy of `pushed(..., height)`: our maker buy of 0.001 BTC."""
  order: dict[str, Any] = {
    'owner': ADDRESS,
    'number': 0,
    'client_id': 1,
    'order_flags': 0,
    'clob_pair_id': 0,
  }
  frame = frame_adapter.validate_python(
    {
      'tag': 'fill',
      'level': 'committed',
      'height': height,
      'round': 0,
      'index': 0,
      'op': 0,
      'kind': 'match',
      'clob_pair_id': 0,
      'quantums': 10_000_000,
      'subticks': 6_000_000_000,
      'taker_side': 'SELL',
      'taker': {**order, 'owner': 'dydx1other', 'client_id': 9},
      'maker': order,
      'quote_quantums': None,
      'liquidated': None,
      'offsetting': None,
      'is_final_settlement': False,
      'backfill': False,
    }
  )
  [item] = FrameParser(ADDRESS, 0).parse(frame)
  return item


def socket_source(shared: Shared, items: AsyncIterator[SocketItem]):
  """Make `items` the client's fill socket feed."""

  async def noop():
    """Nothing to release."""

  async def subscribe():
    """The scripted feed."""
    return items, noop

  shared.socket_subscription = Subscription.of(subscribe)


async def test_fastest_races_on_while_the_indexer_reconnects():
  """The socket keeps delivering while the indexer is down, the stream does not end,
  and the indexer's backfilled copy is dropped without counting as a lead."""
  indexer_back = asyncio.Event()
  delivered = asyncio.Event()
  indexer = FakeIndexer(
    [
      FakeStream({'blockHeight': 9}, [], drop=True),
      NetworkError('still down'),
      FakeStream({'blockHeight': 12}, [], drop=False),
    ],
    fills=[rest_fill('late-11', 11)],
  )
  subscribe = indexer.subscribe

  async def gated(*args: Any, **kwargs: Any):
    """Keep the indexer down until the socket delivered."""
    if indexer.opened:
      await indexer_back.wait()
    return await subscribe(*args, **kwargs)

  async def socket_items() -> AsyncIterator[SocketItem]:
    """Height 11's fill, while the indexer is down."""
    yield socket_fill(11)
    delivered.set()
    await asyncio.Event().wait()

  shared = shared_with(indexer, fill_socket='/unused.sock')
  cast(Any, shared.client.indexer.streams).parent_subaccounts = gated
  socket_source(shared, socket_items())
  market = MarketMixin(shared=shared, perpetual_market=MARKET)
  async with trades_stream(
    market, settings={'dydx': {'trades_source': 'fastest'}}
  ) as stream:
    it = aiter(stream)
    [trade] = await take(it, 1)
    await delivered.wait()
    indexer_back.set()
    with pytest.raises(TimeoutError):
      await asyncio.wait_for(anext(it), 0.3)  # no end, and no repeat of height 11
  assert cast(dict[str, Any], trade.details)['source'] == 'socket'
  assert indexer.fill_requests  # the gap was backfilled
  race = shared.fill_race
  assert race is not None and race.wins == {'socket': 1} and race.summary() == []


async def test_two_streams_of_a_market_log_each_fill_once(
  caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
  """Two `'fastest'` streams of one market record and log each fill once, and the
  client logs one summary per interval, not one per stream."""
  caplog.set_level(logging.INFO, logger='tribulnation.dydx')
  monkeypatch.setattr(dedup, 'RACE_LOG_INTERVAL', 0.1)
  socket_done = asyncio.Event()

  async def indexer_items() -> AsyncIterator[Any]:
    """The indexer's copy, after the socket's."""
    await socket_done.wait()
    yield {'blockHeight': 10, 'fills': [pushed('x', 10)]}
    await asyncio.Event().wait()

  async def socket_items() -> AsyncIterator[SocketItem]:
    """The socket's copy."""
    yield socket_fill(10)
    await asyncio.Event().wait()

  async def noop():
    """Nothing to release."""

  async def subscribe_indexer():
    """The fake indexer channel."""
    return indexer_items(), noop

  shared = Exchange.new(address=ADDRESS, public=True, fill_socket='/unused.sock').shared
  shared.parent_subaccount_subscriptions[0] = Subscription.of(subscribe_indexer)
  socket_source(shared, socket_items())
  settings: Any = {'dydx': {'trades_source': 'fastest'}}
  market = MarketMixin(shared=shared, perpetual_market=MARKET)
  async with (
    trades_stream(market, settings=settings) as one,
    trades_stream(market, settings=settings) as two,
  ):
    [a] = await take(aiter(one), 1)
    [b] = await take(aiter(two), 1)
    socket_done.set()
    await asyncio.sleep(0.35)
  race = shared.fill_race
  assert race is not None and race.reporter is None and race.racers == {}
  assert a.id == b.id  # each stream got the fill
  lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
  assert len([m for m in lines if ': socket first, indexer +' in m]) == 1
  assert race.wins == {'socket': 1}
  assert [lead['fills'] for lead in race.summary()] == [1]
  summaries = [m for m in lines if m.startswith('dYdX fill race:')]
  assert 2 <= len(summaries) <= 4  # one per 0.1 s interval


def test_a_late_copy_is_deduplicated_but_not_raced():
  """A backfilled copy (`late`) is dropped like any repeat and records no lead."""
  race = FillRace()
  fills = FillDedup(race=race)
  key = indexer_key(cast(Any, pushed('x', 10)))
  assert fills.admit('socket', key, at=1.0)
  assert not fills.admit('indexer', key, at=30.0, late=True)
  assert race.summary() == [] and race.wins == {'socket': 1}


async def test_racing_hands_recording_over_and_stops_the_reporter():
  """The oldest stream of a market records; the next takes over when it leaves; the
  reporter runs while any stream races."""
  race = FillRace()
  with race.racing(0) as first:
    with race.racing(0) as second:
      assert first() and not second()
      assert race.reporter is not None
    assert first()
    with race.racing(1) as other:
      assert other()
  assert race.reporter is None and race.racers == {}
