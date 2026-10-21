"""margin.trade client ownership, cached metadata, shared streams and the request seam."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property
import asyncio
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  NamedTuple,
  TypeVar,
)
from typed_margin_trade import MarginTrade, Wallet
from typed_margin_trade.schemas import (
  Fill,
  L2Book,
  OrderDetail,
  PerpAssetCtx,
  PerpUniverseItem,
  SpotPair,
  SpotToken,
)
from typed_margin_trade.info.frontend_open_orders import FrontendOpenOrder
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  OverflowPolicy,
  SDK,
  SkippingView,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, OrderState, Trade

T = TypeVar('T')
U = TypeVar('U')
VenueId = Literal['margin-trade', 'margin-trade-testnet']
wrap_exceptions = exception_wrapper()

MAX_SIGNIFICANT_FIGURES = 5
"""Prices carry at most five significant figures; integer prices always pass
(Hyperliquid's tick rule, which margin.trade inherits)."""
PERP_PRICE_DECIMALS = 6
"""Perpetual prices carry at most `6 - szDecimals` decimals."""
SPOT_PRICE_DECIMALS = 8
"""Spot prices carry at most `8 - szDecimals` decimals."""
SPOT_ASSET_OFFSET = 10000
"""Order actions address spot pair `i` as asset `10000 + i`."""
FUNDING_INTERVAL = timedelta(hours=1)
"""Funding settles every hour, on the hour."""
PERP_ASSET = 'USDC'
"""The perpetual wallet's collateral, as transfer history and `perpBalance` name it."""
PERP_FEE_ASSET = 'USD'
"""The `feeToken` perpetual fills are charged in."""


def round_price(price: Decimal, *, max_decimals: int) -> Decimal:
  """
  Round a price to the venue's precision, in positional form.

  Args:
    price: The requested price.
    max_decimals: `6 - szDecimals` on perpetuals, `8 - szDecimals` on spot.
  """
  if price == price.to_integral_value():
    return Decimal(f'{price.to_integral_value():f}')
  places = min(MAX_SIGNIFICANT_FIGURES - 1 - price.adjusted(), max_decimals)
  rounded = price.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
  return Decimal(f'{rounded.normalize():f}')


def tick_size(sz_decimals: int, *, max_decimals: int) -> Decimal:
  """The finest price step: `10^-min(5, max_decimals - szDecimals)`."""
  return Decimal(10) ** -min(MAX_SIGNIFICANT_FIGURES, max_decimals - sz_decimals)


def parse_book(raw: L2Book, levels: int | None = None) -> Book:
  """An `l2Book` snapshot; an empty book arrives as `levels: []`."""
  sides = raw['levels']
  bids, asks = (sides[0], sides[1]) if sides else ([], [])
  book = Book(
    bids=[Book.Entry(price=level['px'], qty=level['sz']) for level in bids],
    asks=[Book.Entry(price=level['px'], qty=level['sz']) for level in asks],
    time=raw['time'],
  )
  return book.limit(levels) if levels else book


def parse_trade(fill: Fill) -> Trade:
  """A fill, signed by side; `isTaker` decides the role (`crossed` can disagree)."""
  sign = 1 if fill['side'] == 'B' else -1
  return Trade(
    id=str(fill['tid']),
    order_id=str(fill['oid']),
    price=fill['px'],
    qty=sign * fill['sz'],
    time=fill['time'],
    maker=not fill['isTaker'],
    fee=Trade.Fee(amount=fill['fee'], asset=fill['feeToken']),
    details=fill,
  )


def order_state(order: OrderDetail | FrontendOpenOrder, *, active: bool) -> OrderState:
  """An order with signed quantities; the filled part is `origSz - sz`."""
  sign = 1 if order['side'] == 'B' else -1
  return OrderState(
    id=str(order['oid']),
    price=order['limitPx'] or Decimal(0),
    qty=sign * order['origSz'],
    filled_qty=sign * (order['origSz'] - order['sz']),
    active=active,
    details=order,
  )


class Pair(NamedTuple):
  """A spot pair with its base and quote tokens."""

  pair: SpotPair
  base: SpotToken
  quote: SpotToken


def new_client(
  *, address: str | None, private_key: str | None, mainnet: bool, validate: bool
) -> MarginTrade:
  """
  Build a client signing as the master key or as an approved agent of `address`.

  Args:
    address: Master account address; derived from the key when omitted.
    private_key: The master's key or an approved agent's; `None` builds a public client.
    mainnet: Use mainnet when true, testnet when false.
    validate: Validate responses.
  """
  if private_key is None:
    return MarginTrade.new(public=True, mainnet=mainnet, validate=validate)
  wallet = Wallet.parse(private_key)
  vault = address if address is not None and address != wallet.address else None
  return MarginTrade.new(wallet, vault=vault, mainnet=mainnet, validate=validate)


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client, its market metadata and the account's shared streams."""

  client: MarginTrade
  mainnet: bool
  maybe_address: str | None = None
  """The account read and traded: the master address."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  perps: dict[str, PerpUniverseItem] = field(
    default_factory=dict[str, PerpUniverseItem]
  )
  pairs: dict[str, Pair] = field(default_factory=dict[str, Pair])
  leverages: dict[str, Decimal] = field(default_factory=dict[str, Decimal])
  """The account's leverage per perpetual, filled by `leverage()`."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  """One `l2Book` upstream per coin."""
  fills: dict[str, Subscription[Trade]] = field(
    default_factory=dict[str, Subscription[Trade]]
  )
  """One `userFills` upstream per coin: the venue pushes fills only per coin."""

  @property
  def venue_id(self) -> VenueId:
    """The network-specific venue ID."""
    return 'margin-trade' if self.mainnet else 'margin-trade-testnet'

  @property
  def address(self) -> str:
    """The account address, required by every account read."""
    if self.maybe_address is None:
      raise AuthError('margin.trade account reads need an `address` or a private key')
    return self.maybe_address

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own the client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The client root owns both transports."""
    yield self.client_resource

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate and retry one request or one paginator page."""
    return await fn()

  async def perp_universe(
    self, *, refetch: bool = False
  ) -> dict[str, PerpUniverseItem]:
    """Cache the perpetual universe by name."""
    async with self.lock:
      if refetch or not self.perps:
        meta = await self.call(self.client.info.meta)
        self.perps.clear()
        self.perps.update((item['name'], item) for item in meta['universe'])
    return self.perps

  async def spot_pairs(self, *, refetch: bool = False) -> dict[str, Pair]:
    """Cache the spot pairs by name, with their tokens."""
    async with self.lock:
      if refetch or not self.pairs:
        meta = await self.call(self.client.info.spot_meta)
        tokens = {t['index']: t for t in meta['tokens']}
        self.pairs.clear()
        self.pairs.update(
          (p['name'], Pair(p, tokens[p['tokens'][0]], tokens[p['tokens'][1]]))
          for p in meta['universe']
        )
    return self.pairs

  async def contexts(self) -> dict[str, tuple[PerpUniverseItem, PerpAssetCtx]]:
    """Every perpetual with its live context, joined by asset `index`.

    The venue does not list the contexts in universe order.
    """
    meta, ctxs = await self.call(self.client.info.meta_and_asset_ctxs)
    by_index = {ctx['index']: ctx for ctx in ctxs}
    return {
      item['name']: (item, by_index[item['index']])
      for item in meta['universe']
      if item['index'] in by_index
    }

  @asynccontextmanager
  async def stream(
    self,
    subscriptions: dict[str, Subscription[T]],
    key: str,
    connect: Callable[[], Awaitable[Subscription.Context[T]]],
    *,
    select: Callable[[T], U],
    queue_size: int,
    overflow: OverflowPolicy,
  ) -> AsyncIterator[AsyncIterable[U]]:
    """Subscribe to one shared upstream, mapping each item for this subscriber.

    The upstream opens with its first subscriber and closes with its last.
    """
    if key not in subscriptions:
      subscriptions[key] = Subscription(connect)
    async with subscriptions[key].subscribe(
      queue_size=queue_size, overflow=overflow
    ) as upstream:

      async def selected() -> AsyncIterator[U]:
        """This subscriber's view of each shared item."""
        async for item in upstream:
          yield select(item)

      yield SkippingView(selected(), upstream)

  async def connect_book(self, coin: str) -> Subscription.Context[Book]:
    """Open the `l2Book` upstream of one coin; every push is a full snapshot."""
    stream = await self.call(lambda: self.client.streams.l2_book(coin).connect())

    @wrap_exceptions
    async def books() -> AsyncIterator[Book]:
      """Parse each snapshot, translating a dropped socket."""
      async for raw in stream:
        yield parse_book(raw)

    return Subscription.Context(books(), stream.unsubscribe)

  async def connect_fills(self, coin: str) -> Subscription.Context[Trade]:
    """Open the account's `userFills` upstream of one coin."""
    stream = await self.call(
      lambda: self.client.streams.user_fills(user=self.address, coin=coin).connect()
    )

    @wrap_exceptions
    async def trades() -> AsyncIterator[Trade]:
      """Each pushed fill; a snapshot push would repeat history, so it is skipped."""
      async for push in stream:
        if not push.get('isSnapshot'):
          for fill in push['fills']:
            yield parse_trade(fill)

    return Subscription.Context(trades(), stream.unsubscribe)


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange, market and report objects."""

  shared: Shared

  @classmethod
  def new(
    cls,
    *,
    address: str | None = None,
    private_key: str | None = None,
    mainnet: bool = True,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """
    Create a surface over a new client.

    Args:
      address: Master account address (base58). Alone, it serves the account's reads;
        derived from `private_key` when omitted.
      private_key: The master's key, or an approved agent's (with `address` set to the
        master); any format `typed_margin_trade.Wallet.parse` accepts. Needed for trading.
      mainnet: Use mainnet when true, testnet when false.
      validate: Validate responses against the typed client's schemas.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    client = new_client(
      address=address, private_key=private_key, mainnet=mainnet, validate=validate
    )
    return cls(
      shared=Shared(
        client=client,
        mainnet=mainnet,
        maybe_address=address or client.account,
        account_id=account_id,
      )
    )

  @property
  def client(self) -> MarginTrade:
    """The shared typed client."""
    return self.shared.client

  @property
  def venue_id(self) -> VenueId:
    """The network-specific venue ID."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared
