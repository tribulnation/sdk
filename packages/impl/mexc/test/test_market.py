"""Deterministic MEXC market implementation tests."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing_extensions import AsyncIterable
import asyncio

from typed_mexc import MEXC
from typed_mexc.spot.http.market.depth import OrderBook
from typed_mexc.spot.streams.core.proto import (
  PublicAggreDepthsV3Api,
  PublicAggreDepthV3ApiItem,
)
import pytest

from tribulnation.mexc.market.impl.depth import (
  reconstruct_books,
  parse_snapshot,
  parse_update,
)
from tribulnation.mexc.market.impl.mixin import Shared
from tribulnation.mexc import MexcMarket
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl.accounts import Mexc
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Book


def depth_item(price: str, quantity: str) -> PublicAggreDepthV3ApiItem:
  """Build a typed MEXC depth stream item."""
  return PublicAggreDepthV3ApiItem(price=price, quantity=quantity)


def depth_msg(
  from_version: int,
  to_version: int,
  *,
  bids: list[tuple[str, str]] | None = None,
  asks: list[tuple[str, str]] | None = None,
) -> PublicAggreDepthsV3Api:
  """Build a typed MEXC depth stream message."""
  return PublicAggreDepthsV3Api(
    from_version=str(from_version),
    to_version=str(to_version),
    bids=[depth_item(price, qty) for price, qty in bids or []],
    asks=[depth_item(price, qty) for price, qty in asks or []],
  )


def snapshot(
  version: int,
  *,
  bids: list[tuple[str, str]],
  asks: list[tuple[str, str]],
) -> OrderBook:
  """Build a MEXC REST depth snapshot."""
  return {
    'lastUpdateId': version,
    'bids': [[price, qty] for price, qty in bids],
    'asks': [[price, qty] for price, qty in asks],
    'timestamp': datetime.fromtimestamp(0).astimezone(),
  }


class FakeDepthSource:
  """Controllable async source for MEXC depth stream messages."""

  def __init__(self):
    self.queue: asyncio.Queue[PublicAggreDepthsV3Api | None] = asyncio.Queue()
    self.unsubscribe_count = 0

  def __aiter__(self):
    return self

  async def __anext__(self) -> PublicAggreDepthsV3Api:
    msg = await self.queue.get()
    if msg is None:
      raise StopAsyncIteration
    return msg

  async def send(self, msg: PublicAggreDepthsV3Api) -> None:
    """Send one stream message."""
    await self.queue.put(msg)

  async def unsubscribe(self) -> None:
    """Mark the stream as unsubscribed and stop consumers."""
    self.unsubscribe_count += 1
    await self.queue.put(None)


class FakeMarketApi:
  """Fake typed-client market API with queued snapshots."""

  def __init__(self, snapshots: list[OrderBook]):
    self.snapshots = snapshots
    self.calls: list[tuple[str, int | None]] = []

  async def depth(self, *, symbol: str, limit: int | None = None) -> OrderBook:
    """Return the next queued REST depth snapshot."""
    self.calls.append((symbol, limit))
    if len(self.snapshots) > 1:
      return self.snapshots.pop(0)
    return self.snapshots[0]


@dataclass
class FakeHttp:
  """Fake typed-client spot REST namespace."""

  market: FakeMarketApi


@dataclass
class FakeSpot:
  """Fake typed-client spot namespace, shaped like typed-mexc 3.0's `spot.http.market`."""

  http: FakeHttp


@dataclass
class FakeClient:
  """Fake typed MEXC client with optional context tracking."""

  spot: FakeSpot | None = None
  entered: int = 0
  exited: int = 0

  async def __aenter__(self):
    self.entered += 1
    return self

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ):
    self.exited += 1


def depth_subscription(
  client: FakeClient, symbol: str, source: FakeDepthSource
) -> Subscription[Book]:
  """Build the shared book subscription exactly as the mixin does in production:
  reconstruct once upstream, fan out full `Book` snapshots."""

  async def subscribe():
    return reconstruct_books(client, symbol, source), source.unsubscribe  # pyright: ignore[reportArgumentType]

  return Subscription[Book].of(subscribe)


async def next_book(stream: AsyncIterable[Book]) -> Book:
  """Read the next book from a stream."""
  return await asyncio.wait_for(anext(aiter(stream)), timeout=1)


def test_mexc_depth_parsers() -> None:
  """Parse MEXC REST snapshots and stream deltas into SDK books."""
  version, book = parse_snapshot(
    snapshot(
      10,
      bids=[('99.5', '2'), ('99.0', '1')],
      asks=[('100.5', '3')],
    )
  )
  update = parse_update(
    depth_msg(
      11,
      12,
      bids=[('99.5', '0'), ('99.8', '4')],
      asks=[('100.5', '1')],
    )
  )

  assert version == 10
  assert book.best_bid.price == Decimal('99.5')
  assert book.best_ask.qty == Decimal('3')
  assert update.from_version == 11
  assert update.to_version == 12
  assert update.book.best_bid.price == Decimal('99.8')
  assert update.book.best_ask.qty == Decimal('1')


async def test_mexc_depth_stream_recovers_after_version_gap() -> None:
  """Resynchronize with a fresh snapshot after a MEXC depth version gap."""
  source = FakeDepthSource()
  market_api = FakeMarketApi(
    [
      snapshot(11, bids=[('100', '3')], asks=[('101', '1')]),
      snapshot(14, bids=[('98', '2')], asks=[('103', '5')]),
    ]
  )
  sub = depth_subscription(
    FakeClient(spot=FakeSpot(FakeHttp(market_api))), 'BTCUSDT', source
  )

  async with sub.subscribe(queue_size=1000, overflow='fail') as stream:
    await source.send(depth_msg(11, 11, bids=[('100', '3')]))
    first = await next_book(stream)

    await source.send(depth_msg(13, 13, bids=[('100', '4')]))
    await source.send(depth_msg(14, 14, asks=[('102', '0'), ('103', '5')]))
    second = await next_book(stream)
  assert first.best_bid.price == Decimal('100')
  assert second.best_bid.price == Decimal('98')
  assert second.best_ask.price == Decimal('103')
  assert market_api.calls == [('BTCUSDT', None), ('BTCUSDT', None)]


async def test_mexc_depth_stream_unsubscribe_closes_source() -> None:
  """Tearing down the shared subscription unsubscribes the source exactly once."""
  tasks = asyncio.all_tasks()
  source = FakeDepthSource()
  market_api = FakeMarketApi(
    [
      snapshot(11, bids=[('100', '3')], asks=[('101', '1')]),
    ]
  )
  sub = depth_subscription(
    FakeClient(spot=FakeSpot(FakeHttp(market_api))), 'BTCUSDT', source
  )

  async with sub.subscribe(queue_size=1, overflow='latest') as stream:
    await source.send(depth_msg(11, 11, bids=[('100', '3')]))
    await next_book(stream)

  assert source.unsubscribe_count == 1
  assert not asyncio.all_tasks() - tasks


async def test_mexc_shared_context_owns_the_lazy_client() -> None:
  """The typed client owns lazy transports and must be closed by the SDK."""
  client = FakeClient()
  shared = Shared(client=client)  # pyright: ignore[reportArgumentType]

  async with shared:
    assert client.entered == 1

  assert client.exited == 1


async def test_mexc_real_client_entry_does_not_open_unused_transports():
  """Owning a public client must neither dial sockets nor mint private listen keys."""
  client = MEXC.new(public=True)
  shared = Shared(client=client)
  async with shared:
    assert client.spot_clients.http_client.http._client is None
    assert client.futures_clients.http_client.http._client is None
    assert not client.spot_clients.streams_client.user_client.ctx_future.done()
    assert client.spot_clients.streams_client.market_client._ctx_future is None
  assert client.spot_clients.http_client.http._client is None
  assert client.futures_clients.http_client.http._client is None


async def test_mexc_standalone_root_lookups_do_not_reuse_closed_transports():
  """Repeated factory/child-context usage receives fresh real typed client state."""
  root = MarketSDK(accounts={'test': Mexc(public=True)})
  first = await root.venue('test')
  assert isinstance(first, MexcMarket)
  async with first:
    first_http = await first.client.spot_clients.http_client.http.client
    assert not first_http.is_closed
  assert first_http.is_closed

  second = await root.venue('test')
  assert isinstance(second, MexcMarket)
  assert second is not first
  assert second.client is not first.client
  async with second:
    second_http = await second.client.spot_clients.http_client.http.client
    assert second_http is not first_http
    assert not second_http.is_closed
    assert not second.client.spot_clients.streams_client.user_client.ctx_future.done()
  assert second_http.is_closed
