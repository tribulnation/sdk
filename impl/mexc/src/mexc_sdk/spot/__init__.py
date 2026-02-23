from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk import Market as _Market
from mexc_sdk.core import SpotMixin, Settings
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class Spot(SpotMixin, _Market):
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}):
    return cls(
      meta=meta, client=client, settings=settings,
      data=MarketData.of(meta=meta, client=client, settings=settings),
      trade=Trading.of(meta=meta, client=client, settings=settings),
      user=UserData.of(meta=meta, client=client, settings=settings),
    )

  @property
  def venue(self) -> str:
    return 'mexc-spot'

  @property
  def market_id(self) -> str:
    return self.instrument