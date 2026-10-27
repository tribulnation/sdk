"""GRVT client ownership, request middleware, cached instruments and venue constants."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from functools import cached_property
import asyncio
import secrets

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypeVar,
)
from typed_grvt import Grvt
from typed_grvt.schemas import InstrumentDisplay
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  SharedReads,
  AuthError,
  ManagedResource,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Trade

T = TypeVar('T')
VenueId = Literal['grvt', 'grvt_testnet']
"""GRVT's venue IDs: mainnet, and testnet as a separate venue."""
Environment = Literal['prod', 'testnet']
"""The GRVT deployments the SDK connects to."""
wrap_exceptions = exception_wrapper()

PERCENT = Decimal(100)
"""Funding rates are sent in percentage points."""
FEE_UNIT = Decimal('1e-6')
"""`ClientTier` fee rates are integers in millionths of notional (GRVT's "centibeeps"):
tier 1's `450` is the 0.045% taker rate of the published schedule, and testnet taker
fills at that tier are charged exactly notional x 450e-6."""
ORDER_TTL = timedelta(days=29)
"""Lifetime of every order signature, and so the expiry of `LIMIT` and `POST_ONLY`
orders: GRVT has no good-till-cancel and caps a signature at 30 days, so orders are
signed one day short of the cap, which clock skew cannot push past it."""
CLIENT_ORDER_IDS = (2**63, 2**64)
"""The client order ids GRVT reserves for API clients, `[2^63, 2^64)`; its UI generates
them below `2^63`."""
NANOSECOND_SLACK = timedelta(microseconds=1)
"""Added to an inclusive upper time bound before sending it: the venue compares
nanoseconds while datetimes hold microseconds, so a row's own (truncated) time would
exclude the row itself. Rows past the caller's bound are dropped locally."""


def random_client_order_id() -> str:
  """A fresh client order id in the range GRVT reserves for API clients."""
  low, high = CLIENT_ORDER_IDS
  return str(low + secrets.randbelow(high - low))


def upper_bound(end: datetime) -> datetime:
  """The venue bound that selects every row at or before `end`."""
  return end + NANOSECOND_SLACK


def percent(value: Decimal) -> Decimal:
  """A venue percentage as a fraction."""
  return value / PERCENT


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client; cache the perpetuals; share reads and stream fan-outs."""

  client: Grvt
  venue_id: VenueId = 'grvt'
  """The deployment this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  instruments: dict[str, InstrumentDisplay] = field(
    default_factory=dict[str, InstrumentDisplay]
  )
  """Every perpetual by instrument name, delisted ones included."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  """One shared order book upstream per instrument."""
  fills: dict[str, Subscription[Trade]] = field(
    default_factory=dict[str, Subscription[Trade]]
  )
  """One shared fills upstream per instrument."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account reads shared between instruments and concurrent callers (`leverage()`)."""

  @classmethod
  def new(
    cls,
    *,
    env: Environment = 'prod',
    api_key: str | None = None,
    private_key: str | None = None,
    trading_account_id: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client from explicit credentials; the environment is never read.

    Args:
      env: GRVT deployment.
      api_key: API key, for every account read. Without it the client is public:
        market data only.
      private_key: The API key's EIP-712 signer key, needed only to place orders.
      trading_account_id: Trading sub-account the account reads and orders use;
        defaults to the one the API key is scoped to. Ignored without an API key.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.

    Raises:
      ValueError: A private key is given without its API key.
    """
    if api_key is None:
      if private_key is not None:
        raise ValueError('A GRVT private key signs for an API key: pass `api_key` too')
      client = Grvt.new(env=env, public=True, validate=validate)
    else:
      client = Grvt.new(
        env=env,
        api_key=api_key,
        private_key=private_key,
        trading_account_id=trading_account_id,
        validate=validate,
        signature_ttl=ORDER_TTL,
      )
    return cls(
      client=client,
      venue_id='grvt' if env == 'prod' else 'grvt_testnet',
      account_id=account_id,
    )

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own the client with the SDK's exception translation on entry and exit."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The client root owns every transport."""
    yield self.client_resource

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate one request, or one page: the unit SDK retries apply to."""
    return await fn()

  def require_session(self):
    """Check the client can read the account, before any request.

    Raises:
      AuthError: The client has no API key.
    """
    if self.client.session is None:
      raise AuthError('GRVT account reads need an API key (`api_key`)')

  def require_signer(self):
    """Check the client can sign orders, before any request.

    Raises:
      AuthError: The client has no API key, or no private key to sign with.
    """
    self.require_session()
    if self.client.trading_client.signer is None:
      raise AuthError(
        "GRVT orders are signed: configure the API key's `private_key`; "
        'an API key alone only reads'
      )

  async def load_instruments(
    self, *, refetch: bool = False
  ) -> dict[str, InstrumentDisplay]:
    """Cache every perpetual, delisted ones included, from one request."""
    async with self.lock:
      if refetch or not self.instruments:
        rows = await self.call(
          lambda: self.client.market.all_instruments(kinds=['PERPETUAL'])
        )
        self.instruments.clear()
        self.instruments.update((i['instrument'], i) for i in rows)
    return self.instruments

  async def instrument(self, name: str, *, refetch: bool = False) -> InstrumentDisplay:
    """One perpetual's instrument.

    Raises:
      ValueError: GRVT lists no perpetual of that name.
    """
    instruments = await self.load_instruments(refetch=refetch)
    if name not in instruments:
      raise ValueError(f'Unknown GRVT perpetual: {name!r}')
    return instruments[name]
