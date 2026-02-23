from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk import Market as _Market
from mexc_sdk.core import SpotMixin, Settings, StreamManager
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class Spot(SpotMixin, _Market):
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      data=MarketData.of(meta=meta, client=client, settings=settings, streams=streams),
      trade=Trading.of(meta=meta, client=client, settings=settings, streams=streams),
      user=UserData.of(meta=meta, client=client, settings=settings, streams=streams),
    )

  @property
  def venue(self) -> str:
    return 'mexc-spot'

  @property
  def market_id(self) -> str:
    return self.instrument