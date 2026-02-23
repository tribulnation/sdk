from typing_extensions import Literal as _Literal
import asyncio as _asyncio
from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarket as _PerpMarket
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid.info.perps.perp_meta_and_asset_ctxs import PerpMeta
from hyperliquid.info.spot.spot_meta import SpotMetaResponse
from hyperliquid_sdk.core import Mixin as _Mixin, Settings, StreamManager
from hyperliquid_sdk.perps.core import Meta, PerpMixin
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class PerpMarket(PerpMixin, _PerpMarket):
  Data = MarketData
  Trade = Trading
  User = UserData
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def of(cls, other: 'PerpMixin'):
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
    settings: Settings = {},
    index_price: _Literal['oracle', 'mark'] = 'mark',
  ):
    meta = PerpMarket.meta_of(asset_idx, perp_meta=self.perp_meta, spot_meta=self.spot_meta, index_price=index_price)
    mixin = PerpMixin(address=self.address, client=self.client, settings=settings, streams=self.streams, meta=meta)
    return PerpMarket.of(mixin)

  def find(self, name: str, *, settings: Settings = {}, index_price: _Literal['oracle', 'mark'] = 'mark'):
    idx = find_perp(name, self.perp_meta)
    return self.perp(idx, settings=settings, index_price=index_price)

  def match(self, name: str, *, settings: Settings = {}, index_price: _Literal['oracle', 'mark'] = 'mark'):
    for idx in match_perp(name, self.perp_meta):
      yield self.perp(idx, settings=settings, index_price=index_price)

  @classmethod
  async def fetch(
    cls, *, address: str, client: _Hyperliquid, dex: str | None = None,
    settings: Settings = {},
    streams: dict[str, StreamManager] = {},
  ):
    spot_meta, (perp_meta, _) = await _asyncio.gather(
      client.info.spot_meta(),
      client.info.perp_meta_and_asset_ctxs(dex),
    )
    return cls(
      address=address, client=client, settings=settings, streams=streams,
      spot_meta=spot_meta, perp_meta=perp_meta,
    )