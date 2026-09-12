"""Client, caches and error helpers shared by every Binance market object."""

from typing_extensions import (
  Any,
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import SDK, exception_wrapper

from typed_binance import Binance
from typed_binance.spot.http.market.exchange_info import SpotSymbol
from typed_binance.usdm_futures.http.market.exchange_info import ExchangeSymbol

wrap_exceptions = exception_wrapper()

T = TypeVar('T')


@dataclass(kw_only=True)
class Shared:
  """Binance client and caches shared by every market/exchange/venue instance."""

  client: Binance
  validate: bool = True

  spot_symbols: dict[str, SpotSymbol] | None = None
  """Cached spot `exchangeInfo` symbols, keyed by symbol. See `load_spot_symbols`."""

  spot_symbols_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )

  perp_symbols: dict[str, ExchangeSymbol] | None = None
  perp_symbols_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )

  @wrap_exceptions
  async def load_perp_symbols(
    self, *, refetch: bool = False
  ) -> dict[str, ExchangeSymbol]:
    """Share a public USD-M metadata snapshot across all market rule reads."""
    if not refetch and self.perp_symbols is not None:
      return self.perp_symbols
    async with self.perp_symbols_lock:
      if not refetch and self.perp_symbols is not None:
        return self.perp_symbols
      info = await self.client.usdm_futures.http.market.exchange_info()
      self.perp_symbols = {row['symbol']: row for row in info['symbols']}
      return self.perp_symbols

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Create a `Shared` backed by a new Binance client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      public: Construct a credential-free client.
      validate: Validate responses against the typed client's schemas.
    """
    client = Binance.new(
      api_key=api_key, secret_key=secret_key, public=public, validate=validate
    )
    return cls(client=client, validate=validate)

  @wrap_exceptions
  async def load_spot_symbols(self, *, refetch: bool = False) -> dict[str, SpotSymbol]:
    """Fetch (and cache) spot `exchangeInfo`, keyed by symbol.

    Args:
      refetch: If `True`, fetch even if a cached copy exists.
    """
    if not refetch and self.spot_symbols is not None:
      return self.spot_symbols
    async with self.spot_symbols_lock:
      if not refetch and self.spot_symbols is not None:
        return self.spot_symbols
      info = await self.client.spot.http.market.exchange_info()
      self.spot_symbols = {s['symbol']: s for s in info['symbols']}
      return self.spot_symbols


@dataclass(frozen=True)
class SharedMixin(SDK):
  """Borrows the venue-wide `Shared` state every market object is built from."""

  shared: Shared

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Create a market object backed by a new Binance client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      public: Construct a credential-free client.
      validate: Validate responses against the typed client's schemas.
    """
    return cls(
      shared=Shared.new(
        api_key=api_key, secret_key=secret_key, public=public, validate=validate
      )
    )

  @property
  def client(self) -> Binance:
    """The shared `typed_binance` client."""
    return self.shared.client

  @SDK.method
  @wrap_exceptions
  async def call_binance(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Binance under the SDK exception wrapper.

    One request per call, so a sweep's retries and tracing span apply per page rather
    than restarting the whole sweep.
    """
    return await fn()

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    yield from super().resources()
    yield self.client


def not_implemented(name: str, id: str) -> NotImplementedError:
  """Build a `NotImplementedError` for a method not yet implemented for Binance.

  Only endpoints verified against a live account are implemented; the rest raise
  until verified, rather than shipping an untested request/response mapping.
  """
  return NotImplementedError(
    f'{name} is not implemented yet for this market [{id}] -- it was never executed '
    'against a live account, so it is intentionally left unimplemented rather than '
    'shipped unverified.'
  )


def futures_permission_error(name: str, id: str) -> NotImplementedError:
  """Build a `NotImplementedError` for a USD-M Futures private endpoint.

  Binance restricts USD-M Futures trading for EEA accounts (MiCA); the credentials
  this was tested against returned 401 (`Invalid API-key, IP, or permissions`) for
  every private futures endpoint, so they are left unimplemented rather than shipped
  unverified. The request/response mapping mirrors the (verified) spot equivalent, but
  hasn't been run against a live account with USD-M Futures access.
  """
  return NotImplementedError(
    f'{name} is not implemented for this market [{id}] -- requires Binance USD-M '
    'Futures account access, which the tested credentials do not have (every private '
    'futures endpoint returned 401 when tested).'
  )
