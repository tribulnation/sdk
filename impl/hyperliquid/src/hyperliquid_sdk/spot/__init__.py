from dataclasses import dataclass as _dataclass

from trading_sdk.market import Market
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.core import Mixin as _Mixin, Settings, StreamManager
from .core import SpotMixin, find_spot, match_spot, SpotMetaResponse
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class SpotMarket(SpotMixin, Market):
  Data = MarketData
  Trade = Trading
  User = UserData
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def of(cls, other: 'SpotMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      data=MarketData.of(other),
      trade=Trading.of(other),
      user=UserData.of(other),
    )

  @property
  def venue(self) -> str:
    return 'hyperliquid'

  @property
  def market_id(self) -> str:
    return f'{self.base_name}/{self.quote_name}'

@_dataclass(frozen=True, kw_only=True)
class Spot(_Mixin):
  spot_meta: SpotMetaResponse

  def spot(self, asset_idx: int, *, settings: Settings = {}):
    meta = SpotMarket.meta_of(asset_idx, spot_meta=self.spot_meta)
    mixin = SpotMixin(address=self.address, client=self.client, settings=settings, streams=self.streams, meta=meta)
    return SpotMarket.of(mixin)

  def find(self, base: str, quote: str, *, settings: Settings = {}):
    idx = find_spot(base, quote, self.spot_meta)
    return self.spot(idx, settings=settings)

  def match(self, base: str, quote: str, *, settings: Settings = {}):
    for idx in match_spot(base, quote, self.spot_meta):
      yield self.spot(idx, settings=settings)

  @classmethod
  async def fetch(cls, *, address: str, client: _Hyperliquid, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      address=address, client=client, settings=settings, streams=streams,
      spot_meta=await client.info.spot_meta(),
    )