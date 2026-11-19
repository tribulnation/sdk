"""EVEDEX client ownership, request middleware, venue constants and cached instruments."""

from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
import asyncio
import re

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  Mapping,
  TypeVar,
  cast,
)
from typed_evedex import BadRequest as ClientBadRequest, Evedex
from typed_evedex.core import order_id
from typed_evedex.exchange.market.instruments import InstrumentInfo
from typed_evedex.schemas import Instrument
from typed_evedex.streams.account.fills import OrderFillUpdate
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  AuthError,
  BadRequest,
  ManagedResource,
  SharedReads,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book

T = TypeVar('T')
VenueId = Literal['evedex']
"""EVEDEX's venue ID: the production exchange (evedex.com)."""

wrap_exceptions = exception_wrapper()

COLLATERAL = 'usdt'
"""The one collateral coin, as the venue writes it: margin, PnL, trading fees and
funding all settle in it."""
FUNDING_SETTLEMENT = timedelta(hours=1)
"""EVEDEX settles funding every hour, each settlement a pro-rated share of the rate it
computes every `fundingRateInterval` hours (8 on every instrument, 2026-11-19)."""
DEFAULT_LEVERAGE = 1
"""The leverage the venue applies on an instrument the account never set one on."""
FILLS = 'fills'
"""The key of the account's fills upstream in `Shared.fills`."""
ORDER_ID = re.compile(r'^\d{5}:[0-9a-f]{26}$')
"""A v2 order id, `DDDDD:<26 hex>`: days since 2025-07-24, then random hex."""


def random_client_order_id() -> str:
  """A fresh order id the venue accepts as the order's own id (`DDDDD:<26 hex>`)."""
  return order_id()


def listed(instrument: InstrumentInfo | Instrument) -> bool:
  """Whether an instrument is listed: visible to every account (`visibility: all`).

  Delisted instruments (`LDOUSD`, `WIFUSD`, ...) are `visibility: none`, `trading: none`.
  """
  return instrument['visibility'] == 'all'


def tradable(instrument: InstrumentInfo) -> bool:
  """Whether an instrument takes orders from any account through the API now."""
  return (
    instrument['trading'] in ('all', 'schedule')
    and instrument['marketState'] == 'OPEN'
    and instrument['matcherState'] == 'active'
  )


def venue_label(exc: BadRequest) -> str | None:
  """The venue's error `label` behind a translated `BadRequest`, if it sent one
  (`mark_price_limit_exceeded_error`, `order_not_found_error`, ...)."""
  cause = exc.__cause__
  if isinstance(cause, ClientBadRequest) and len(cause.args) >= 2:
    payload: object = cause.args[1]
    if isinstance(payload, dict):
      label = cast(dict[str, object], payload).get('label')
      if isinstance(label, str):
        return label


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client for one account; cache instruments and share reads and streams."""

  client: Evedex
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  instruments: dict[str, InstrumentInfo] = field(
    default_factory=dict[str, InstrumentInfo]
  )
  """Every instrument, delisted ones included, by `name`."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  """One shared upstream book per instrument, on the client's one connection."""
  fills: dict[str, Subscription[OrderFillUpdate]] = field(
    default_factory=dict[str, Subscription[OrderFillUpdate]]
  )
  """The account's one `orderFills` upstream (every instrument), under `FILLS`, once
  opened."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account reads shared between markets and concurrent callers."""

  @classmethod
  def new(
    cls,
    *,
    private_key: str | None = None,
    api_key: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client for one account from explicit credentials.

    With neither key the client is public. `typed-evedex` fills an unset key from
    `EVEDEX_PRIVATE_KEY`/`EVEDEX_API_KEY` when the other one is given.

    Args:
      private_key: The wallet's private key: every read, orders and private channels.
      api_key: An API key: every REST account read, without the wallet.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    if private_key or api_key:
      client = Evedex.new(
        env='prod', private_key=private_key, api_key=api_key, validate=validate
      )
    else:
      client = Evedex.new(env='prod', public=True, validate=validate)
    return cls(client=client, account_id=account_id)

  @property
  def venue_id(self) -> VenueId:
    """The venue ID."""
    return 'evedex'

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

  def require_account(self):
    """Check the client can read the account, before an account read.

    Raises:
      AuthError: The client is public.
    """
    if self.client.credentials is None:
      raise AuthError(
        'EVEDEX account reads need an `api_key` or the wallet `private_key`'
      )

  def require_wallet(self):
    """Check the client holds the wallet key, before an order or a private stream.

    Raises:
      AuthError: The client has no wallet key (public, or an API key alone).
    """
    credentials = self.client.credentials
    if credentials is None or credentials.account is None:
      raise AuthError(
        'EVEDEX orders and private streams are signed by the wallet: configure the '
        '`private_key` (an API key only reads)'
      )

  async def load_instruments(
    self, *, refetch: bool = False
  ) -> Mapping[str, InstrumentInfo]:
    """Every instrument, from one request, cached until `refetch`."""
    async with self.lock:
      if refetch or not self.instruments:
        rows = await self.call(self.client.exchange.market.instruments)
        # Without `fields` the venue sends full records; the declared return is the
        # union of every `fields` shape (typed-client-issues.md).
        self.instruments.clear()
        self.instruments.update(
          (r['name'], r) for r in cast(list[InstrumentInfo], rows)
        )
    return self.instruments

  async def instrument(self, name: str, *, refetch: bool = False) -> InstrumentInfo:
    """One instrument's cached record, delisted ones included.

    Raises:
      ValueError: The venue has no instrument of that name.
    """
    rows = await self.load_instruments(refetch=refetch)
    row = rows.get(name)
    if row is None:
      raise ValueError(f'Unknown EVEDEX instrument: {name!r}')
    return row
