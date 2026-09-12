"""Shared state for the Bitget market surface: instrument catalogues and live streams.

Bitget's public market data is one API whatever the account's mode, so the venue, its
four exchanges and every market are built off the same client and share one cache of
catalogues, one set of order book subscriptions and one account-mode detection.
"""

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  Mapping,
  TypeVar,
)
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import SDK, OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, Fees
from typed_bitget import Bitget
from typed_bitget.classic.mix.market.contracts import MixContract
from typed_bitget.classic.spot.symbols import SpotSymbol
from typed_bitget.classic_streams.fill import MixFill1, SpotFill
from typed_bitget.classic_streams.orderbook import OrderBookPush
from typed_bitget.uta_streams.fill import FillUpdate

from tribulnation.bitget.core import SdkMixin, wrap_exceptions
from .parse import PERP, PerpProduct, Product, parse_book

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


async def merged_books(pushes: AsyncIterable[OrderBookPush]) -> AsyncIterator[Book]:
  """Fold Bitget's `books` channel pushes into whole books.

  The channel pushes one full `snapshot` on subscribe (500 levels a side, confirmed
  live) and then `update`s carrying only the changed levels, a zero size meaning the
  level was removed -- `Book.update`'s exact contract. Each yielded book is a copy, so
  a book already handed to a subscriber is never mutated by a later push.
  """
  book = Book()
  async for push in pushes:
    for levels in push['data']:
      delta = parse_book(levels['bids'], levels['asks'])
      if push['action'] == 'snapshot':
        book = delta
      else:
        book.update(delta)
      yield book.copy()


async def flatten(pushes: AsyncIterable[Mapping[str, Any]], key: str):
  """Split batched stream pushes into their individual `data` rows."""
  async for push in pushes:
    for row in push[key]:
      yield row


@dataclass
class Cache:
  """Catalogues and subscriptions shared by every market built off one client."""

  spot: dict[str, SpotSymbol] = field(default_factory=dict[str, SpotSymbol])
  perp: dict[PerpProduct, dict[str, MixContract]] = field(
    default_factory=dict[PerpProduct, dict[str, MixContract]]
  )
  depth: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  classic_fills: dict[str, 'Subscription[SpotFill | MixFill1]'] = field(
    default_factory=dict[str, 'Subscription[SpotFill | MixFill1]']
  )
  uta_fills: Subscription[FillUpdate] | None = None
  spot_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
  perp_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass(kw_only=True, frozen=True)
class VenueMixin(SDK):
  """Everything the venue, its exchanges and its markets all need."""

  account: SdkMixin
  """Owns the client and the account-mode detection every account-scoped call keys off."""
  cache: Cache = field(default_factory=Cache)

  @property
  def client(self) -> Bitget:
    return self.account.client

  @property
  def validate(self) -> bool:
    """Whether responses are validated against the client's declared schemas."""
    return self.account.validate

  @classmethod
  def new(
    cls,
    access_key: str | None = None,
    secret_key: str | None = None,
    passphrase: str | None = None,
    *,
    uta: bool | None = None,
    public: bool = False,
    validate: bool = True,
  ):
    """Build a surface over a fresh Bitget client.

    Args:
      access_key: Bitget access key; read from `BITGET_ACCESS_KEY` when omitted.
      secret_key: Bitget secret key; read from `BITGET_SECRET_KEY` when omitted.
      passphrase: Bitget API passphrase; read from `BITGET_PASSPHRASE` when omitted.
      uta: Whether the account is in UTA mode. Auto-detected on the first
        account-scoped call when omitted; public market data never needs it.
      public: Build a credential-free client, restricted to public endpoints.
      validate: Validate responses.
    """
    client = Bitget.new(
      access_key=access_key,
      secret_key=secret_key,
      passphrase=passphrase,
      public=public,
      validate=validate,
    )
    return cls(account=SdkMixin(client=client, uta=uta, validate=validate))

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    yield from super().resources()
    yield self.account

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Bitget under the SDK exception wrapper.

    Every individual request -- and every individual *page* of a paged sweep -- goes
    through here, so retry middleware binds to the one request that failed instead of
    to the whole sweep.
    """
    return await fn()

  @wrap_exceptions
  async def is_uta(self) -> bool:
    """Whether the account is in UTA mode, detecting it on first use.

    Detection calls an authenticated endpoint, so on a credential-free client it
    raises the SDK's `AuthError` rather than answering.
    """
    return await self.account.is_uta()

  async def spot_symbols(self, *, refetch: bool = False) -> Mapping[str, SpotSymbol]:
    """Fetch every spot symbol and its rules, keyed by symbol.

    Args:
      refetch: Refresh the catalogue even when one is already cached.
    """
    if self.cache.spot and not refetch:
      return self.cache.spot
    async with self.cache.spot_lock:
      if self.cache.spot and not refetch:
        return self.cache.spot
      symbols = await self.call(
        lambda: self.client.classic.spot.symbols(validate=self.validate)
      )
      self.cache.spot = {s['symbol']: s for s in symbols}
      return self.cache.spot

  async def perp_contracts(
    self, product: PerpProduct = PERP, *, refetch: bool = False
  ) -> Mapping[str, MixContract]:
    """Fetch one product line's perpetual contracts, keyed by native symbol.

    The product line can also carry dated delivery contracts (`symbolType ==
    'delivery'`); they settle on a date and pay no funding, so nothing about
    `PerpMarket` describes them and they are dropped here.

    Args:
      refetch: Refresh the catalogue even when one is already cached.
    """
    if product in self.cache.perp and not refetch:
      return self.cache.perp[product]
    async with self.cache.perp_lock:
      if product in self.cache.perp and not refetch:
        return self.cache.perp[product]
      contracts = await self.call(
        lambda: self.client.classic.mix.market.contracts(
          product, validate=self.validate
        )
      )
      self.cache.perp[product] = {
        c['symbol']: c for c in contracts if c['symbolType'] == 'perpetual'
      }
      return self.cache.perp[product]

  def depth_subscription(self, product: Product, symbol: str) -> Subscription[Book]:
    """Get (or open) the shared full-depth order book subscription for one symbol.

    Public channels are served by the Classic v2 socket in either account mode.
    """
    key = f'{product}.{symbol}'
    subscription = self.cache.depth.get(key)
    if subscription is None:

      @wrap_exceptions
      async def subscribe():
        stream = await self.client.classic_streams.orderbook(
          product, inst_id=symbol, depth='', validate=self.validate
        )
        # Fold to whole books once here, not per consumer: subscribers then buffer
        # snapshots rather than a growing backlog of deltas they'd have to replay.
        return merged_books(stream.stream), stream.unsubscribe

      subscription = open_subscription(subscribe)
      self.cache.depth[key] = subscription
    return subscription

  def classic_fill_subscription(
    self, product: Product, symbol: str
  ) -> 'Subscription[SpotFill | MixFill1]':
    """Get (or open) a Classic-mode account's fill subscription for one symbol.

    Classic v2 splits its private `fill` channel by product line and symbol, so there
    is one subscription per market.
    """
    key = f'{product}.{symbol}'
    subscription = self.cache.classic_fills.get(key)
    if subscription is None:

      @wrap_exceptions
      async def subscribe():
        stream = await self.client.classic_streams.fill(
          product, inst_id=symbol, validate=self.validate
        )
        return flatten(stream.stream, 'data'), stream.unsubscribe

      subscription = open_subscription(subscribe)
      self.cache.classic_fills[key] = subscription
    return subscription

  def uta_fill_subscription(self) -> Subscription[FillUpdate]:
    """Get (or open) a UTA-mode account's fill subscription.

    UTA v3's private `fill` channel carries every product line on one connection, so
    there is exactly one of these per client and each market filters it down.
    """
    if self.cache.uta_fills is None:

      @wrap_exceptions
      async def subscribe():
        stream = await self.client.uta_streams.fill('UTA', validate=self.validate)
        return flatten(stream.stream, 'data'), stream.unsubscribe

      self.cache.uta_fills = open_subscription(subscribe)
    return self.cache.uta_fills


@dataclass(kw_only=True, frozen=True)
class MarketMixin(VenueMixin):
  """One market: a product line plus the symbol addressed within it."""

  symbol: str

  def require_account_surface(self):
    """Keep newly added public products out of unqualified account-data adapters."""
    if self.product not in ('SPOT', PERP):
      raise NotImplementedError(
        'Bitget USDC and coin futures support public market data only.'
      )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read this account's symbol-specific rates, in its actual account mode.

    Each endpoint returns applicable rates, not the public contract's base tier.
    Rates are fetched on every call; no optional fee-token discount is applied here.
    """
    self.require_account_surface()
    if await self.is_uta():
      rates = await self.call(
        lambda: self.client.uta.account.fee_rate(
          self.product,
          symbol=self.symbol,
          validate=self.validate,
        )
      )
    else:
      rates = await self.call(
        lambda: self.client.classic.common.trade_rate(
          self.symbol,
          business_type='spot' if self.product == 'SPOT' else 'mix',
          validate=self.validate,
        )
      )
    return Fees.symmetric(maker=rates['makerFeeRate'], taker=rates['takerFeeRate'])

  @property
  def product(self) -> Product:
    """The Bitget product line this market is addressed under."""
    raise NotImplementedError

  def subscribe_depth(
    self, *, queue_size: int = 1, overflow: OverflowPolicy = 'latest'
  ):
    """Subscribe to this market's shared order book stream."""
    return self.depth_subscription(self.product, self.symbol).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_classic_fills(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to this market's Classic-mode fill stream."""
    self.require_account_surface()
    return self.classic_fill_subscription(self.product, self.symbol).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_uta_fills(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to the account-wide UTA-mode fill stream."""
    self.require_account_surface()
    return self.uta_fill_subscription().subscribe(
      queue_size=queue_size, overflow=overflow
    )
