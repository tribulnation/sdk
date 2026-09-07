"""The base every Bybit surface is built on: one shared client, one retriable call shim."""

from typing_extensions import (
  Any,
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass, field

from tribulnation.sdk.core import SDK
from typed_bybit import Bybit
from typed_bybit.account.wallet_balance import AccountBalance, Coin
from typed_bybit.core.http import Region
from typed_bybit.position.list import Position

from .exc import wrap_exceptions
from .settings import Settings
from .util import SETTLE_COINS

T = TypeVar('T')


@dataclass(kw_only=True, frozen=True)
class Mixin(SDK):
  """Owns the `Bybit` client and the shim every request goes through."""

  client: Bybit
  settings: Settings = field(default_factory=Settings)

  @property
  def validate(self) -> bool:
    """Whether responses are validated against the client's declared schemas."""
    return self.settings.get('validate', True)

  @classmethod
  @wrap_exceptions
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = False,
    region: Region = 'global',
    testnet: bool = False,
    settings: Settings = {},
  ):
    """Build a surface over a fresh Bybit client.

    Args:
      api_key: Bybit API key; read from the environment when omitted.
      api_secret: Bybit API secret; read from the environment when omitted.
      public: Build a credential-free client, restricted to public endpoints.
      region: Bybit legal entity to target. Each region is a separate account with
        separate keys and its own environment variables (`BYBIT_API_KEY` for
        `'global'`, `BYBIT_EU_API_KEY` for `'eu'`, and so on), and they do not list
        the same products -- `'eu'` carries no derivatives at all.
      testnet: Target the region's testnet host instead of mainnet.
      settings: Client-level settings.
    """
    client = Bybit.new(
      api_key=api_key,
      api_secret=api_secret,
      public=public,
      region=region,
      testnet=testnet,
      validate=settings.get('validate', True),
    )
    return cls(client=client, settings=settings)

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    # The client's REST transport and its nine sockets all connect lazily, so taking
    # ownership here costs nothing until a surface actually calls something.
    yield from super().resources()
    yield self.client

  @SDK.method
  @wrap_exceptions
  async def call_bybit(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Bybit under the SDK exception wrapper.

    Every individual request -- and, crucially, every individual *page* of a paged
    sweep -- goes through here, so retry middleware binds to the one request that
    failed instead of to the whole sweep.
    """
    return await fn()

  @SDK.method
  async def unified_balance(self) -> AccountBalance | None:
    """Fetch the Unified Trading Account's balance and margin state.

    Bybit's unified account is a single pool -- there are no separate spot, margin
    and futures wallets to enumerate -- so this is the one bucket every balance,
    collateral and snapshot reading comes out of.
    """
    wallet = await self.call_bybit(
      lambda: self.client.account.wallet_balance('UNIFIED', validate=self.validate)
    )
    return wallet['list'][0] if wallet['list'] else None

  @SDK.method
  async def coin_balance(self, coin: str) -> Coin | None:
    """Fetch one coin's row in the Unified Trading Account, if it has one."""
    wallet = await self.call_bybit(
      lambda: self.client.account.wallet_balance(
        'UNIFIED', coin=coin, validate=self.validate
      )
    )
    rows = wallet['list'][0]['coin'] if wallet['list'] else []
    return next((c for c in rows if c['coin'] == coin), None)

  @SDK.method
  async def linear_positions(self) -> list[Position]:
    """Fetch every open linear position, across both settlement coins.

    Rows for a flat symbol are dropped: Bybit returns them with an empty `side` and
    an empty string in place of every number.
    """
    out: list[Position] = []
    for settle_coin in SETTLE_COINS:
      cursor: str | None = None
      while True:
        page = await self.call_bybit(
          lambda: self.client.position.list(
            'linear', settle_coin=settle_coin, cursor=cursor, validate=self.validate
          )
        )
        out.extend(p for p in page['list'] if p['side'])
        cursor = page.get('nextPageCursor')
        if not cursor:
          break
    return out
