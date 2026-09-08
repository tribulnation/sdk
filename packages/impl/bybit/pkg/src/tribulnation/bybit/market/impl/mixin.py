"""Shared state for the Bybit market surface: instrument catalogues and live streams.

Bybit v5 is one API discriminated by `category`, not a spot client next to a futures
client, so spot and linear markets are built off the same `Bybit` instance and share
one cache of catalogues and one set of stream subscriptions.
"""

from typing_extensions import (
  Any,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Literal,
  Mapping,
  TypeVar,
)
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book
from typed_bybit.linear.orderbook import LinearOrderbookUpdate
from typed_bybit.market.instruments import ContractInstrument, SpotInstrument
from typed_bybit.private.execution import ExecutionUpdate
from typed_bybit.spot.orderbook import OrderbookUpdate

from tribulnation.bybit.core import Mixin, wrap_exceptions
from .parse import Category, parse_book

Depth = Literal[1, 50, 200]
"""Order book depths every category this package covers supports."""

DEFAULT_DEPTH: Depth = 50
"""Depth the shared order book subscription runs at."""

INSTRUMENTS_PAGE = 1000
"""Rows per `market.instruments_paged` page; Bybit's documented maximum."""

T = TypeVar('T')


def open_subscription(
  subscribe: Callable[
    [], Awaitable[tuple[AsyncIterable[T], Callable[[], Awaitable[Any]]]]
  ],
) -> Subscription[T]:
  """Build a fan-out `Subscription` from a subscribe callback.

  `Subscription.of` declares that callback's unsubscribe half as a bare `Awaitable`,
  which reads as an implicit `Any` under this repo's type settings. Spelling the
  callback type out here keeps that to one suppressed line rather than one per
  subscription.
  """
  return Subscription.of(subscribe)  # type: ignore


async def merged_books(
  updates: AsyncIterable['OrderbookUpdate | LinearOrderbookUpdate'],
) -> AsyncIterator[Book]:
  """Fold Bybit's snapshot-then-deltas order book pushes into whole books.

  Bybit pushes one full snapshot on subscribe and then only the changed levels, with
  a zero size meaning the level was removed -- `Book.update`'s exact contract. A
  re-snapshot mid-subscription is recognised by the push's own `type`, which the
  client's core forwards from the frame onto the payload. It is declared
  `NotRequired` only because the spec's replay gate cannot see a field the transport
  merges in; a push arriving without one falls back to Bybit's documented `u == 1`
  marker.

  Each yielded book is a copy, so a book already handed to a subscriber is never
  mutated by a later push.
  """
  book = Book()
  async for update in updates:
    delta = parse_book(update['b'], update['a'])
    kind = update.get('type')
    snapshot = kind == 'snapshot' if kind is not None else update['u'] == 1
    if snapshot:
      book = delta
    else:
      book.update(delta)
    yield book.copy()


async def flatten_executions(
  pushes: AsyncIterable[list[ExecutionUpdate]],
) -> AsyncIterator[ExecutionUpdate]:
  """Split Bybit's batched execution pushes into individual fills."""
  async for push in pushes:
    for execution in push:
      yield execution


@dataclass
class Cache:
  """Catalogues and subscriptions shared by every market built off one client."""

  spot: dict[str, SpotInstrument] = field(default_factory=dict[str, SpotInstrument])
  perp: dict[str, ContractInstrument] = field(
    default_factory=dict[str, ContractInstrument]
  )
  depth: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  executions: Subscription[ExecutionUpdate] | None = None
  spot_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
  perp_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass(kw_only=True, frozen=True)
class VenueMixin(Mixin):
  """Everything the venue, its exchanges and its markets all need."""

  cache: Cache = field(default_factory=Cache)

  async def spot_instruments(
    self, *, refetch: bool = False
  ) -> Mapping[str, SpotInstrument]:
    """Fetch every spot instrument, keyed by symbol.

    Args:
      refetch: Refresh the catalogue even when one is already cached.
    """
    if self.cache.spot and not refetch:
      return self.cache.spot
    async with self.cache.spot_lock:
      if self.cache.spot and not refetch:
        return self.cache.spot
      # Spot is the one category `market.instruments` serves unpaged: its result
      # carries no `nextPageCursor` at all, unlike the contract shape below.
      info = await self.call_bybit(
        lambda: self.client.market.instruments('spot', validate=self.validate)
      )
      assert info['category'] == 'spot'
      self.cache.spot = {i['symbol']: i for i in info['list']}
      return self.cache.spot

  async def perp_instruments(
    self, *, refetch: bool = False
  ) -> Mapping[str, ContractInstrument]:
    """Fetch every linear *perpetual* contract, keyed by symbol.

    Bybit's `linear` category also carries 40-odd dated futures (`LinearFutures`),
    which are dropped here: they settle on a delivery date and pay no funding, so
    nothing about `PerpMarket` describes them.

    Args:
      refetch: Refresh the catalogue even when one is already cached.
    """
    if self.cache.perp and not refetch:
      return self.cache.perp
    async with self.cache.perp_lock:
      if self.cache.perp and not refetch:
        return self.cache.perp
      paging = self.client.market.instruments_paged(
        'linear', limit=INSTRUMENTS_PAGE, validate=self.validate
      )
      instruments: dict[str, ContractInstrument] = {}
      # The pager's item type is the same undiscriminated three-way union the unpaged
      # call returns; `contractType` is required on the contract shape and absent from
      # the other two, which is what narrows a row to it.
      async for rows in paging.via(self.call_bybit):
        instruments.update(
          {
            i['symbol']: i
            for i in rows
            if 'contractType' in i and i['contractType'] == 'LinearPerpetual'
          }
        )
      self.cache.perp = instruments
      return self.cache.perp

  def depth_subscription(
    self, category: Category, symbol: str, *, depth: Depth = DEFAULT_DEPTH
  ) -> Subscription[Book]:
    """Get (or open) the shared order book subscription for one symbol."""
    key = f'{category}.{depth}.{symbol}'
    subscription = self.cache.depth.get(key)
    if subscription is None:

      @wrap_exceptions
      async def subscribe():
        manager = (
          self.client.spot.orderbook(depth, symbol=symbol, validate=self.validate)
          if category == 'spot'
          else self.client.linear.orderbook(
            depth, symbol=symbol, validate=self.validate
          )
        )
        stream = await manager
        # Fold to whole books once here, not per consumer: subscribers then buffer
        # snapshots rather than a growing backlog of deltas they'd have to replay.
        return merged_books(stream.stream), stream.unsubscribe

      subscription = open_subscription(subscribe)
      self.cache.depth[key] = subscription
    return subscription

  def execution_subscription(self) -> Subscription[ExecutionUpdate]:
    """Get (or open) the account-wide fill subscription.

    Bybit's private `execution` channel carries every category on one connection, so
    there is exactly one of these per client and each market filters it down.
    """
    if self.cache.executions is None:

      @wrap_exceptions
      async def subscribe():
        stream = await self.client.private.execution(validate=self.validate)
        return flatten_executions(stream.stream), stream.unsubscribe

      self.cache.executions = open_subscription(subscribe)
    return self.cache.executions


@dataclass(kw_only=True, frozen=True)
class MarketMixin(VenueMixin):
  """One market: a `category` plus the symbol addressed within it."""

  symbol: str

  @property
  def category(self) -> Category:
    """The Bybit v5 product category this market is addressed under."""
    raise NotImplementedError

  def subscribe_depth(
    self, *, queue_size: int = 1, overflow: OverflowPolicy = 'latest'
  ):
    """Subscribe to this market's shared order book stream."""
    return self.depth_subscription(self.category, self.symbol).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_executions(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to the account-wide fill stream."""
    return self.execution_subscription().subscribe(
      queue_size=queue_size, overflow=overflow
    )
