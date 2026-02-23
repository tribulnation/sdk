from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk import PerpMarket as _PerpMarket
from mexc_sdk.core import PerpMixin, Settings, StreamManager
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True, kw_only=True)
class Futures(PerpMixin, _PerpMarket):
  data: MarketData
  trade: Trading
  user: UserData

  @property
  def venue(self) -> str:
    return 'mexc'

  @property
  def market_id(self) -> str:
    return self.instrument

  @classmethod
  def of(cls, meta: PerpMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      data=MarketData.of(meta=meta, client=client, settings=settings, streams=streams),
      trade=Trading.of(meta=meta, client=client, settings=settings, streams=streams),
      user=UserData.of(meta=meta, client=client, settings=settings, streams=streams),
    )
