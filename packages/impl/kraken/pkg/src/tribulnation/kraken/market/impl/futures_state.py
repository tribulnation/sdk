"""State the perpetual markets of one Kraken client share: the Futures client, its
account-wide reads and its fan-out feeds."""

from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
from typing_extensions import Awaitable, Callable, TypeVar

from tribulnation.sdk.core import ManagedResource, SharedReads, Subscription
from tribulnation.sdk.market import Book
from tribulnation.kraken.core import Calls, wrap_exceptions

from typed_kraken.futures_trading.client import FuturesEnvironment, KrakenFutures
from typed_kraken.futures_trading.types import (
  AccountsResult,
  LeveragePreferencesResult,
  OpenPositionsResult,
)
from typed_kraken.futures_trading.ws import WsFill

from .perp_streams import fold_futures_books, futures_fills
from .streaming import context

T = TypeVar('T')


@dataclass(kw_only=True)
class FuturesState(Calls):
  """The Futures client of one Kraken account, and what its perpetuals share."""

  client: KrakenFutures
  margin_schedule: str | None = None
  """`marginSchedules` key (e.g. `europa`) whose retail levels set cross-margin leverage;
  `None` reads the instrument's top-level `retailMarginLevels`."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account-wide reads (positions, accounts, leverage), shared per `ttl`."""
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  fills: Subscription[WsFill] | None = None

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    environment: FuturesEnvironment = 'live',
    margin_schedule: str | None = None,
    validate: bool = True,
  ):
    """Build around a fresh Futures client; public without a full key pair.

    Args:
      api_key: Futures API key.
      private_key: Futures API secret.
      environment: `live` or `demo`.
      margin_schedule: See `margin_schedule`.
      validate: Validate responses.
    """
    return cls(
      client=KrakenFutures.new(
        api_key=api_key,
        private_key=private_key,
        environment=environment,
        public=api_key is None or private_key is None,
        validate=validate,
      ),
      margin_schedule=margin_schedule,
    )

  @cached_property
  def resource(self) -> ManagedResource[object]:
    """Own Futures client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  async def read(
    self, key: str, fetch: Callable[[], Awaitable[T]], *, ttl: timedelta | None
  ) -> T:
    """One account-wide request, shared per `ttl` (see `SharedReads`)."""
    return await self.reads.read(key, lambda: self.call_kraken(fetch), ttl=ttl)

  async def accounts(self, *, ttl: timedelta | None) -> AccountsResult:
    """Every account, `flex` (multi-collateral) included."""
    return await self.read('accounts', self.client.trading.accounts, ttl=ttl)

  async def positions(self, *, ttl: timedelta | None) -> OpenPositionsResult:
    """Every open position."""
    return await self.read('positions', self.client.trading.open_positions, ttl=ttl)

  async def leverage_preferences(
    self, *, ttl: timedelta | None
  ) -> LeveragePreferencesResult:
    """The markets set to isolated margin."""
    return await self.read(
      'leverage', self.client.trading.leverage_preferences, ttl=ttl
    )

  def forget_account(self):
    """Drop shared answers a just-sent order may have changed."""
    self.reads.forget('accounts')
    self.reads.forget('positions')

  def book(self, symbol: str) -> Subscription[Book]:
    """The shared book feed of one perpetual, created on first use."""
    if symbol not in self.books:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[Book]:
        stream = await self.client.streams.book(symbol)
        return context(fold_futures_books(stream, symbol), stream.unsubscribe)

      self.books[symbol] = Subscription(subscribe)
    return self.books[symbol]

  def fills_feed(self) -> Subscription[WsFill]:
    """The shared own-fills feed of every perpetual, created on first use.

    Fills before the subscription (the feed's snapshot) are skipped; each market
    filters the rest by its symbol.
    """
    if self.fills is None:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[WsFill]:
        stream = await self.client.streams.fills()
        return context(futures_fills(stream), stream.unsubscribe)

      self.fills = Subscription(subscribe)
    return self.fills
