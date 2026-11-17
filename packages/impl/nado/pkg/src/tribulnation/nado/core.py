"""Nado client ownership, request middleware, cached symbols and venue constants."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
  TypedDict,
  TypeVar,
)
from typed_nado import Nado
from typed_nado.core.auth import DEFAULT_SUBACCOUNT, subaccount_bytes32
from typed_nado.schemas import Symbol
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  SharedReads,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Trade

T = TypeVar('T')
VenueId = Literal['nado', 'nado_testnet']
"""Nado's venue IDs: mainnet (Ink), and testnet (Ink Sepolia) as a separate venue."""
Network = Literal['mainnet', 'testnet']
"""The Nado deployments the SDK connects to."""
ProductType = Literal['spot', 'perp']
"""What a product trades: a spot asset against USDT0, or a perpetual."""
wrap_exceptions = exception_wrapper()


class Settings(TypedDict, total=False):
  """Nado settings, under `settings['nado']`."""

  spot_leverage: bool
  """Let a spot order borrow against the account's margin (the venue's
  `spot_leverage`). Spot orders never borrow without it; perpetual orders ignore it."""
  reduce_only: bool
  """Only ever reduce the position (the appendix's reduce-only bit): an order that would
  open or grow one is refused, or cut to what closes it."""


X18 = Decimal(10) ** 18
"""Every Nado price, size, balance and rate is an integer times 1e18."""
QUOTE_PRODUCT = 0
"""Product 0 is USDT0, the quote of every market and the settlement asset of every
perpetual."""
QUOTE_ASSET = 'USDT0'
"""The asset id of product 0."""
GTC_EXPIRATION = datetime(2100, 1, 1, tzinfo=timezone.utc)
"""The expiration `LIMIT` and `POST_ONLY` orders are signed with: Nado has no
good-till-cancel flag, an order rests until its `expiration`, and mainnet accepted this
one (2026-11-17)."""
CLIENT_ORDER_IDS = 2**63
"""Client order ids are drawn below this: the venue's `id` is an integer echoed on
order queries and fill events, and a signed 64-bit range is safe for every consumer."""


def x18(value: int | str) -> Decimal:
  """A venue x18 integer as a decimal."""
  return Decimal(int(value)) / X18


def to_x18(value: Decimal) -> int:
  """A decimal as the venue's x18 integer.

  Raises:
    ValueError: The value has more than 18 decimals.
  """
  raw = value * X18
  if raw != raw.to_integral_value():
    raise ValueError(f'{value} has more than 18 decimals')
  return int(raw)


def random_client_order_id() -> str:
  """A fresh client order id: a decimal integer below `2^63`."""
  return str(secrets.randbelow(CLIENT_ORDER_IDS))


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client; cache the symbols; share reads and stream fan-outs."""

  client: Nado
  venue_id: VenueId = 'nado'
  """The deployment this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  owner: str | None = None
  """The wallet owning the subaccount, when one is configured."""
  sender: str | None = None
  """The subaccount every account read is for (`bytes32` hex), when one is configured."""
  symbols: dict[str, Symbol] = field(default_factory=dict[str, Symbol])
  """Every spot and perpetual product by symbol, untradable ones included."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[int, Subscription[Book]] = field(
    default_factory=dict[int, Subscription[Book]]
  )
  """One shared order book upstream per product."""
  fills: dict[int, Subscription[Trade]] = field(
    default_factory=dict[int, Subscription[Trade]]
  )
  """One shared fills upstream per product."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account reads shared between markets and concurrent callers (`subaccount_info`)."""

  @classmethod
  def new(
    cls,
    *,
    network: Network = 'mainnet',
    private_key: str | None = None,
    address: str | None = None,
    subaccount: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client from explicit credentials; the environment is never read.

    Args:
      network: Nado deployment.
      private_key: Signing key: the subaccount owner's, or its linked signer's. Needed
        only to place and cancel orders.
      address: Owner wallet of the subaccount; defaults to the key's own address.
        Without a key, an address alone serves every account read (Nado's reads are
        public).
      subaccount: Subaccount name; `default` (the one the app creates) when omitted.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    if private_key is not None:
      client = Nado.new(
        network=network,
        private_key=private_key,
        address=address,
        subaccount=subaccount or DEFAULT_SUBACCOUNT,
        validate=validate,
      )
      credentials = client.credentials
      if credentials is None:
        raise AuthError('typed-nado resolved no credentials for the private key')
      owner, sender = credentials.owner, credentials.sender
    else:
      client = Nado.new(network=network, public=True, validate=validate)
      owner = address or None
      sender = (
        subaccount_bytes32(owner, subaccount or DEFAULT_SUBACCOUNT) if owner else None
      )
    return cls(
      client=client,
      venue_id='nado' if network == 'mainnet' else 'nado_testnet',
      account_id=account_id,
      owner=owner,
      sender=sender,
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

  def require_sender(self) -> str:
    """The subaccount account reads are for, before any request.

    Raises:
      AuthError: Neither a key nor an address was configured.
    """
    if self.sender is None:
      raise AuthError(
        'Nado account reads need the subaccount: configure an `address` (or a '
        '`private_key`)'
      )
    return self.sender

  def require_signer(self) -> str:
    """The signing subaccount, before any order or cancel is signed.

    Raises:
      AuthError: The client has no key to sign with.
    """
    if self.client.credentials is None:
      raise AuthError(
        'Nado orders are signed: configure the `private_key` (an address alone only reads)'
      )
    return self.client.credentials.sender

  async def load_symbols(self, *, refetch: bool = False) -> dict[str, Symbol]:
    """Cache every spot and perpetual product, untradable ones included, from one
    request."""
    async with self.lock:
      if refetch or not self.symbols:
        rows = await self.call(self.client.gateway.symbols)
        self.symbols.clear()
        self.symbols.update(rows['symbols'])
    return self.symbols

  async def listed(self, type: ProductType) -> list[str]:
    """The symbols of every product of one type, untradable ones included."""
    symbols = await self.load_symbols()
    return [name for name, s in symbols.items() if s['type'] == type]

  async def symbol(
    self, name: str, *, type: ProductType | None = None, refetch: bool = False
  ) -> Symbol:
    """One product by symbol, of `type` when given.

    Raises:
      ValueError: Nado lists no product of that symbol (and type).
    """
    symbols = await self.load_symbols(refetch=refetch)
    s = symbols.get(name)
    if s is not None and type in (None, s['type']):
      return s
    label = 'product' if type is None else f'{type} product'
    raise ValueError(f'Unknown Nado {label}: {name!r}')

  async def symbol_of(self, product_id: int) -> str | None:
    """The symbol of a product id, `None` for one Nado no longer lists."""
    symbols = await self.load_symbols()
    for name, s in symbols.items():
      if s['product_id'] == product_id:
        return name

  async def asset_of(self, product_id: int) -> str | None:
    """The asset id of a spot product: `USDT0` for product 0, else its symbol."""
    if product_id == QUOTE_PRODUCT:
      return QUOTE_ASSET
    return await self.symbol_of(product_id)
