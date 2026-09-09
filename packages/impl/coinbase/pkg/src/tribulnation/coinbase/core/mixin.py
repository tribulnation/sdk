"""The client every Coinbase SDK surface is built on, and the state they share."""

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypeVar,
)
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import SDK, OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, Trade

from typed_coinbase import Coinbase
from typed_coinbase.app.advanced_trade.http.fees.transaction_summary import (
  FeeTierFeeTier,
)
from typed_coinbase.schemas import Product

from .exc import wrap_exceptions
from .streams import book_stream, user_trades_stream

T = TypeVar('T')

FeeScope = Literal['spot', 'intx']
"""Which fee schedule to read: Advanced Trade spot, or INTX perpetuals."""


def subscription(
  subscribe: Callable[
    [], Awaitable[tuple[AsyncIterable[T], Callable[[], Awaitable[Any]]]]
  ],
) -> Subscription[T]:
  """Build a `Subscription` from a callback returning `(iterable, unsubscribe)`.

  `Subscription.of` does the same, but types its callback's unsubscribe as a bare
  `Awaitable`, which this repo's pyright settings read as an implicit `Any`.
  """

  async def connect() -> 'Subscription.Context[T]':
    iterable, unsubscribe = await subscribe()
    return Subscription.Context(aiter(iterable), unsubscribe)

  return Subscription(connect)


@dataclass(kw_only=True)
class Shared(SDK):
  """Venue-wide state shared by every Coinbase SDK object built from one client.

  One owner of the client, one product/fee cache and one WebSocket subscription per
  channel, however many exchanges and markets are handed out on top of it.
  """

  client: Coinbase
  products: dict[str, Product] = field(default_factory=dict[str, Product])
  fee_tiers: dict[FeeScope, FeeTierFeeTier] = field(
    default_factory=dict[FeeScope, FeeTierFeeTier]
  )
  book_subscriptions: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  user_trades_subscription: 'Subscription[tuple[str, Trade]] | None' = None
  product_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )
  fee_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client

  @wrap_exceptions
  async def load_product(self, product_id: str, /, *, refetch: bool = False) -> Product:
    """Fetch a product's catalogue entry, caching it for later reads.

    Args:
      product_id: Product to fetch, e.g. `BTC-USD`.
      refetch: Fetch even when the product is already cached.
    """
    if not refetch and product_id in self.products:
      return self.products[product_id]
    async with self.product_lock:
      if not refetch and product_id in self.products:
        return self.products[product_id]
      product = await self.client.app.advanced_trade.http.products.get(product_id)
      self.products[product_id] = product
      return product

  @wrap_exceptions
  async def load_fee_tier(
    self, scope: FeeScope, /, *, refetch: bool = False
  ) -> FeeTierFeeTier:
    """Fetch the account's current maker/taker tier, caching it for later reads.

    Args:
      scope: Which fee schedule to read.
      refetch: Fetch even when the tier is already cached.
    """
    if not refetch and scope in self.fee_tiers:
      return self.fee_tiers[scope]
    async with self.fee_lock:
      if not refetch and scope in self.fee_tiers:
        return self.fee_tiers[scope]
      fees = self.client.app.advanced_trade.http.fees
      summary = (
        await fees.transaction_summary(product_type='SPOT')
        if scope == 'spot'
        else await fees.transaction_summary(
          product_type='FUTURE',
          contract_expiry_type='PERPETUAL',
          product_venue='INTX',
        )
      )
      tier = summary.get('fee_tier') or FeeTierFeeTier()
      self.fee_tiers[scope] = tier
      return tier

  def book_subscription(self, product_id: str, /) -> Subscription[Book]:
    """The shared `level2` subscription for one product, created on first use."""
    if product_id not in self.book_subscriptions:
      self.book_subscriptions[product_id] = subscription(
        lambda: book_stream(self.client, product_id)
      )
    return self.book_subscriptions[product_id]

  def user_trades_sub(self) -> 'Subscription[tuple[str, Trade]]':
    """The shared `user` subscription, created on first use.

    One connection covers every product; each market filters the stream itself.
    """
    if self.user_trades_subscription is None:
      self.user_trades_subscription = subscription(
        lambda: user_trades_stream(self.client)
      )
    return self.user_trades_subscription


@dataclass(frozen=True, kw_only=True)
class Mixin(SDK):
  """Base of every Coinbase SDK surface: it borrows `Shared` and calls through it."""

  shared: Shared

  @classmethod
  def new(
    cls,
    key_name: str | None = None,
    private_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Build a Coinbase SDK surface over a fresh client.

    Args:
      key_name: CDP API Key name; read from `COINBASE_API_KEY_NAME` when omitted.
      private_key: CDP API Key private key; read from `COINBASE_PRIVATE_KEY` when
        omitted.
      public: Skip credential resolution, leaving only the unauthenticated routes
        usable.
      validate: Validate responses against their declared schema.
    """
    client = Coinbase.new(
      key_name=key_name, private_key=private_key, public=public, validate=validate
    )
    return cls(shared=Shared(client=client))

  @property
  def client(self) -> Coinbase:
    return self.shared.client

  @property
  def app(self):
    """The Coinbase App (retail) product: v2 accounts plus Advanced Trade."""
    return self.shared.client.app

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.shared

  @SDK.method
  @wrap_exceptions
  async def call_app(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call the Coinbase App API under the SDK exception wrapper.

    Every single-page fetch of a paginated sweep goes through here, so a retry
    replays that one page instead of restarting the sweep.
    """
    return await fn()

  @SDK.method
  @wrap_exceptions
  async def call_exchange(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call the Coinbase Exchange API under the SDK exception wrapper.

    A separate product behind separate credentials, hence a separate shim from
    `call_app`.
    """
    return await fn()

  @SDK.method
  @wrap_exceptions
  async def call_international(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Read one credential-free International Exchange page under SDK middleware."""
    return await fn()

  def subscribe_book(
    self,
    product_id: str,
    /,
    *,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    """Subscribe to a product's order book."""
    return self.shared.book_subscription(product_id).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_user_trades(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to this account's reconstructed fills, across every product."""
    return self.shared.user_trades_sub().subscribe(
      queue_size=queue_size, overflow=overflow
    )
