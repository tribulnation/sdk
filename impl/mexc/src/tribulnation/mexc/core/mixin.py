from typing_extensions import AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio

from mexc import MEXC
from mexc.futures.market.contract_info import ContractSpec, ContractSpecListItem
from mexc.spot.market.exchange_info import SymbolInfo
from mexc.spot.streams.core.proto import PrivateDealsV3Api as SpotTrade
from mexc.futures.streams.user.my_trades import Deal as PerpTrade
from .util import StreamManager

SpotInfo = SymbolInfo
PerpInfo = ContractSpec | ContractSpecListItem

class Settings(TypedDict, total=False):
  validate: bool
  recvWindow: int

@dataclass
class Cache:
  spot_markets: dict[str, SpotInfo] = field(default_factory=dict)
  perp_markets: dict[str, PerpInfo] = field(default_factory=dict)

@dataclass(kw_only=True, frozen=True)
class Mixin:
  client: MEXC
  settings: Settings = field(default_factory=Settings)
  streams: dict[str, StreamManager]
  cache: Cache = field(default_factory=Cache)

  @property
  def validate(self) -> bool:
    return self.settings.get('validate', True)

  @property
  def recvWindow(self) -> int | None:
    return self.settings.get('recvWindow', None)

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    settings: Settings = {},
  ):
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=settings.get('validate', True))
    return cls(client=client, settings=settings, streams={})

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(*[stream.close() for stream in self.streams.values()])
    await self.client.__aexit__(exc_type, exc_value, traceback)

  async def cached_spot_market(self, instrument: str, *, refetch: bool = False) -> SpotInfo:
    if refetch or instrument not in self.cache.spot_markets:
      info = await self.client.spot.market.exchange_info()
      self.cache.spot_markets = {
        market['symbol']: market
        for market in info['symbols']
        if 'symbol' in market
      }
    return self.cache.spot_markets[instrument]

  async def cached_perp_market(self, instrument: str, *, refetch: bool = False) -> PerpInfo:
    if refetch or instrument not in self.cache.perp_markets:
      info = await self.client.futures.market.contract_info(symbol=instrument)
      data = info.get('data')
      if data is None:
        raise ValueError(f'MEXC contract info response did not include data for {instrument}')
      if isinstance(data, list):
        self.cache.perp_markets.update({
          market['symbol']: market
          for market in data
          if 'symbol' in market
        })
      else:
        self.cache.perp_markets[instrument] = data
    return self.cache.perp_markets[instrument]
