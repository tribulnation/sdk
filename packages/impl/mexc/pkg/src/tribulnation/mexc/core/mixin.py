from functools import cached_property
from typing_extensions import (
  Any,
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypedDict,
  TypeVar,
)
from dataclasses import dataclass, field

from tribulnation.sdk.core import ManagedResource
from tribulnation.sdk import SDK

from typed_mexc import MEXC
from typed_mexc.schemas import ContractSpec
from typed_mexc.spot.http.market.exchange_info import SymbolInfo
from .exc import wrap_exceptions
from .util import StreamManager, closing_streams

T = TypeVar('T')

SpotInfo = SymbolInfo
PerpInfo = ContractSpec


class Settings(TypedDict, total=False):
  validate: bool
  recvWindow: int


@dataclass
class Cache:
  spot_markets: dict[str, SpotInfo] = field(default_factory=dict[str, SpotInfo])
  perp_markets: dict[str, PerpInfo] = field(default_factory=dict[str, PerpInfo])


@dataclass(kw_only=True, frozen=True)
class Mixin(SDK):
  client: MEXC
  settings: Settings = field(default_factory=Settings)
  streams: dict[str, StreamManager[Any]]
  cache: Cache = field(default_factory=Cache)

  @SDK.method
  @wrap_exceptions
  async def call_mexc(self, fetch: Callable[[], Awaitable[T]]) -> T:
    """Retry one report page after translating its transport exception."""
    return await fetch()

  @property
  def validate(self) -> bool:
    return self.settings.get('validate', True)

  @property
  def recvWindow(self) -> int | None:
    return self.settings.get('recvWindow', None)

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    settings: Settings = {},
  ):
    client = MEXC.new(
      api_key=api_key, api_secret=api_secret, validate=settings.get('validate', True)
    )
    return cls(client=client, settings=settings, streams={})

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def resources(self) -> Iterable[AsyncContextManager[Any]]:
    yield from super().resources()
    yield self.client_resource
    # Streams are opened lazily during the block, so they cannot be named up front.
    # Reverse-order exit closes them before the client, as the old `__aexit__` did.
    yield ManagedResource(
      resource=closing_streams(self.streams),
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  async def cached_spot_market(
    self, instrument: str, *, refetch: bool = False
  ) -> SpotInfo:
    if refetch or instrument not in self.cache.spot_markets:
      info = await self.client.spot.http.market.exchange_info()
      self.cache.spot_markets = {
        market['symbol']: market for market in info['symbols'] if 'symbol' in market
      }
    return self.cache.spot_markets[instrument]

  async def cached_perp_market(
    self, instrument: str, *, refetch: bool = False
  ) -> PerpInfo:
    if refetch or instrument not in self.cache.perp_markets:
      info = await self.client.futures.http.market.contract_info(symbol=instrument)
      data = info.get('data')
      if data is None:
        raise ValueError(
          f'MEXC contract info response did not include data for {instrument}'
        )
      if isinstance(data, list):
        self.cache.perp_markets.update(
          {market['symbol']: market for market in data if 'symbol' in market}
        )
      else:
        self.cache.perp_markets[instrument] = data
    return self.cache.perp_markets[instrument]
