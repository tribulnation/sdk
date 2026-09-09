"""Shared state and mixins behind Kraken's Spot market surface.

`typed_kraken` wraps Kraken Spot only -- Kraken Futures is a separate product on its
own host with its own credentials, and the client has no namespace for it -- so `spot`
is the venue's only exchange here and there is no `PerpMarket`.

One pair has three spellings across the client: the `AssetPairs` key (`XXBTZUSD`), the
`altname` every REST `pair=` argument and account row uses (`XBTUSD`), and the
WebSocket v2 `symbol` (`BTC/USD`). The altname is the market id; the other two are
looked up from the catalogue loaded here.
"""

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  TypedDict,
  TypeVar,
)
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import asyncio

from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book
from tribulnation.kraken.core import Calls, wrap_exceptions

from typed_kraken import Kraken
from typed_kraken.spot.account.balance_ex import ExtendedBalance
from typed_kraken.spot.market_data.asset_pairs import AssetPair
from typed_kraken.streams.private.executions import ExecutionTradeEvent

from .depth import BookDepth, fold_books

T = TypeVar('T')

BALANCE_TTL = timedelta(seconds=1)
"""How long a fetched balance list is reused before another call is made.

Kraken meters private REST calls with a per-account counter that decays at a fraction
of a point per second, and `position`, `collateral` and `available_notional` each need
the same `BalanceEx` answer, so a caller sweeping a handful of markets coalesces those
calls rather than spending three counter points per market.
"""


class PairInfo(TypedDict):
  """One market's catalogue rows, in every spelling the client needs."""

  key: str
  """The `AssetPairs` key, which `Ticker` and `Depth` key their answers by (`XXBTZUSD`)."""
  symbol: str
  """The WebSocket v2 symbol (`BTC/USD`)."""
  info: AssetPair


class Meta(TypedDict):
  """What a `SpotMarket` is constructed around."""

  pair: PairInfo


def context(
  stream: AsyncIterable[T], unsubscribe: Callable[[], Awaitable[Any]]
) -> Subscription.Context[T]:
  """Wrap a typed-client stream as the `(iterator, unsubscribe)` pair a
  `Subscription` fans out from.

  Iteration is wrapped too, not just the subscribe call: a socket that drops
  mid-stream raises from the `async for`, and that has to reach subscribers as a
  `tribulnation.sdk.core` error like every other failure.
  """

  @wrap_exceptions
  async def iterate() -> AsyncIterator[T]:
    async for item in stream:
      yield item

  return Subscription.Context(iterate(), unsubscribe)


def join_pairs(
  internal: dict[str, AssetPair], display: dict[str, AssetPair]
) -> dict[str, PairInfo]:
  """Key the catalogue by altname, pairing each row with its WebSocket v2 symbol.

  `AssetPairs` answers under internal keys by default and under display keys with
  `assetVersion=1`; the display key *is* the WebSocket v2 symbol, and `altname` is
  carried unchanged on both, so the two listings join exactly (1446 of 1446, checked
  live).

  Args:
    internal: The default `AssetPairs` listing.
    display: The `assetVersion=1` listing.
  """
  symbols = {
    altname: symbol
    for symbol, info in display.items()
    if (altname := info.get('altname'))
  }
  out: dict[str, PairInfo] = {}
  for key, info in internal.items():
    altname = info.get('altname')
    if altname is None or (symbol := symbols.get(altname)) is None:
      continue
    out[altname] = {'key': key, 'symbol': symbol, 'info': info}
  return out


@dataclass(kw_only=True)
class Shared(Calls):
  """State shared by every market of one Kraken client."""

  client: Kraken
  balance_ttl: timedelta = BALANCE_TTL
  pairs: dict[str, PairInfo] | None = None
  balances: dict[str, ExtendedBalance] | None = None
  balances_at: datetime | None = None
  depth_subscriptions: dict[tuple[str, BookDepth], Subscription[Book]] = field(
    default_factory=dict[tuple[str, BookDepth], Subscription[Book]]
  )
  executions: Subscription[ExecutionTradeEvent] | None = None
  pairs_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
  balances_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Build the shared state around a fresh Kraken client."""
    return cls(
      client=Kraken.new(
        api_key=api_key, private_key=private_key, public=public, validate=validate
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client

  async def load_pairs(self, *, refetch: bool = False) -> dict[str, PairInfo]:
    """Fetch and memoise the whole pair catalogue, keyed by altname.

    Args:
      refetch: Refetch even when the catalogue is already cached.
    """
    if not refetch and self.pairs is not None:
      return self.pairs
    async with self.pairs_lock:
      if not refetch and self.pairs is not None:
        return self.pairs
      internal, display = await asyncio.gather(
        self.call_kraken(self.client.spot.market_data.asset_pairs),
        self.call_kraken(
          lambda: self.client.spot.market_data.asset_pairs(asset_version=1)
        ),
      )
      self.pairs = join_pairs(internal, display)
      return self.pairs

  async def load_balances(self, *, refetch: bool = False) -> dict[str, ExtendedBalance]:
    """Fetch every asset's extended balance, keyed by internal asset id.

    Reuses a result younger than `balance_ttl` rather than refetching -- see that
    constant for the rate limit this exists to stay under.

    Args:
      refetch: Refetch even when a fresh result is cached.
    """
    async with self.balances_lock:
      now = datetime.now(timezone.utc)
      fresh = (
        self.balances is not None
        and self.balances_at is not None
        and now - self.balances_at < self.balance_ttl
      )
      if self.balances is None or refetch or not fresh:
        self.balances = dict(
          await self.call_kraken(self.client.spot.account.balance_ex)
        )
        self.balances_at = now
      return self.balances

  def depth_subscription(self, symbol: str, depth: BookDepth) -> Subscription[Book]:
    """The shared order-book subscription for one symbol and depth, created on
    first use."""
    if (symbol, depth) not in self.depth_subscriptions:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[Book]:
        stream = await self.client.streams.market_data.book(
          symbol=[symbol], depth=depth
        )
        return context(fold_books(stream), stream.unsubscribe)

      self.depth_subscriptions[(symbol, depth)] = Subscription(subscribe)
    return self.depth_subscriptions[(symbol, depth)]

  def executions_subscription(self) -> Subscription[ExecutionTradeEvent]:
    """The shared own-fills subscription, created on first use.

    `executions` is one account-wide channel carrying both order-status transitions
    and fills; only the fills (`exec_type == 'trade'`) are fanned out, and each
    market filters them by its own symbol.
    """
    if self.executions is None:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[ExecutionTradeEvent]:
        stream = await self.client.streams.private.executions(snap_trades=False)

        async def fills() -> AsyncIterator[ExecutionTradeEvent]:
          async for message in stream:
            for event in message['data']:
              if event['exec_type'] == 'trade':
                yield event

        return context(fills(), stream.unsubscribe)

      self.executions = Subscription(subscribe)
    return self.executions


@dataclass(frozen=True, kw_only=True)
class SharedMixin(Calls):
  """Base for every Kraken market object, holding the state they share."""

  shared: Shared

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Build a market surface around a fresh Kraken client.

    Args:
      api_key: Kraken API key; read from `KRAKEN_API_KEY` when omitted.
      private_key: Kraken private key; read from `KRAKEN_PRIVATE_KEY` when omitted.
      public: Build a credential-free client. Market data works without
        credentials; balances, orders and the private channels do not.
      validate: Validate responses.
    """
    return cls(
      shared=Shared.new(api_key, private_key, public=public, validate=validate)
    )

  @property
  def client(self) -> Kraken:
    return self.shared.client

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.shared


@dataclass(frozen=True, kw_only=True)
class ExchangeMixin(SharedMixin):
  """Base for the exchange-level surface."""


@dataclass(frozen=True, kw_only=True)
class MarketMixin(ExchangeMixin):
  """Base for one market's surface."""

  meta: Meta

  @property
  def info(self) -> AssetPair:
    return self.meta['pair']['info']

  @property
  def altname(self) -> str:
    """The REST pair name every `pair=` argument and account row uses (`XBTUSD`)."""
    altname = self.info.get('altname')
    if altname is None:
      raise ValueError('Kraken pair metadata is missing its altname')
    return altname

  @property
  def ws_symbol(self) -> str:
    """The WebSocket v2 symbol (`BTC/USD`)."""
    return self.meta['pair']['symbol']

  @property
  def base(self) -> str:
    """The base asset's internal id (`XXBT`)."""
    return self.info.get('base', '')

  @property
  def quote(self) -> str:
    """The quote asset's internal id (`ZUSD`)."""
    return self.info.get('quote', '')

  def subscribe_depth(
    self,
    depth: BookDepth,
    *,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    """Subscribe to this market's shared order-book stream at one of Kraken's depths."""
    return self.shared.depth_subscription(self.ws_symbol, depth).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_fills(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to the account-wide fills stream."""
    return self.shared.executions_subscription().subscribe(
      queue_size=queue_size, overflow=overflow
    )
