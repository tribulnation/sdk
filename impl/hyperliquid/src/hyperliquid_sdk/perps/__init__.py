from typing_extensions import Literal as _Literal
import asyncio as _asyncio
from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarket
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid.info.perps.perp_meta_and_asset_ctxs import PerpMeta
from hyperliquid.info.spot.spot_meta import SpotMetaResponse
from hyperliquid_sdk.core import Mixin as _Mixin, TradingSettings
from hyperliquid_sdk.perps.core import Meta, PerpMixin
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class PerpMarket(PerpMixin, PerpMarket):
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

  @property
  def venue(self) -> str:
    return 'hyperliquid'

  @property
  def market_id(self) -> str:
    return f'{self.asset_name}/{self.collateral_name}'

def find_perp(name: str, perp_meta: PerpMeta):
  finds: list[int] = []
  for idx, asset in enumerate(perp_meta['universe']):
    if asset['name'] == name:
      finds.append(idx)
  if not finds:
    raise ValueError(f'Perp {name} not found')
  if len(finds) > 1:
    raise ValueError(f'Multiple perps found named "{name}"')
  return finds[0]

def match_perp(name: str, perp_meta: PerpMeta):
  for idx, asset in enumerate(perp_meta['universe']):
    if name in asset['name']:
      yield idx

@_dataclass(frozen=True, kw_only=True)
class Perp(_Mixin):
  spot_meta: SpotMetaResponse
  perp_meta: PerpMeta

  def perp(
    self, asset_idx: int, *,
    settings: TradingSettings | None = None,
    index_price: _Literal['oracle', 'mark'] = 'mark',
  ):
    meta = PerpMarket.meta_of(asset_idx, perp_meta=self.perp_meta, spot_meta=self.spot_meta, settings=settings, index_price=index_price)
    return PerpMarket.of(address=self.address, client=self.client, validate=self.validate, meta=meta)

  def find(self, name: str, *, settings: TradingSettings | None = None, index_price: _Literal['oracle', 'mark'] = 'mark'):
    idx = find_perp(name, self.perp_meta)
    return self.perp(idx, settings=settings, index_price=index_price)

  def match(self, name: str, *, settings: TradingSettings | None = None, index_price: _Literal['oracle', 'mark'] = 'mark'):
    for idx in match_perp(name, self.perp_meta):
      yield self.perp(idx, settings=settings, index_price=index_price)

  @classmethod
  async def fetch(cls, *, address: str, client: _Hyperliquid, validate: bool = True):
    spot_meta, (perp_meta, _) = await _asyncio.gather(
      client.info.spot_meta(),
      client.info.perp_meta_and_asset_ctxs(),
    )
    return cls(
      address=address, client=client, validate=validate,
      spot_meta=spot_meta, perp_meta=perp_meta,
    )