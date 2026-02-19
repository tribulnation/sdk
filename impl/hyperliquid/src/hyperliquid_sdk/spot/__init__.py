from dataclasses import dataclass as _dataclass

from trading_sdk.market import Market
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.core import Mixin as _Mixin, TradingSettings
from .core import Meta, SpotMixin, find_spot, match_spot, SpotMetaResponse
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
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      data=MarketData.of(address=address, client=client, validate=validate, meta=meta),
      trade=Trading.of(address=address, client=client, validate=validate, meta=meta),
      user=UserData.of(address=address, client=client, validate=validate, meta=meta),
    )

@_dataclass(frozen=True, kw_only=True)
class Spot(_Mixin):
  spot_meta: SpotMetaResponse

  def spot(self, asset_idx: int, *, settings: TradingSettings | None = None):
    meta = SpotMarket.meta_of(asset_idx, spot_meta=self.spot_meta, settings=settings)
    return SpotMarket.of(address=self.address, client=self.client, validate=self.validate, meta=meta)

  def find(self, base: str, quote: str, *, settings: TradingSettings | None = None):
    idx = find_spot(base, quote, self.spot_meta)
    return self.spot(idx, settings=settings)

  def match(self, base: str, quote: str, *, settings: TradingSettings | None = None):
    for idx in match_spot(base, quote, self.spot_meta):
      yield self.spot(idx, settings=settings)

  @classmethod
  async def fetch(cls, *, address: str, client: _Hyperliquid, validate: bool = True):
    return cls(
      address=address, client=client, validate=validate,
      spot_meta=await client.info.spot_meta(),
    )